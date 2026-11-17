"""Comparación con el otro país: el producto equivalente, la conversión a dólares y pesos, la
diferencia, la aduana y el veredicto.

Equivalente (mejor precio con stock del otro país, visto en las últimas 48 h):
  placas  mismo chip y misma VRAM, cualquier marca
  cpu     el mismo modelo
  ram     misma capacidad, módulos y velocidad (y CL; si el CL cambia, "aprox.")
  pcs     la misma placa y la misma cantidad de RAM
Si no está el mismo, se usa el más parecido y se marca "aprox."."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from .cotizaciones import FRANQUICIA_USD, ARANCEL, Cotizacion, ars, usd
from .db import DB

BANDERA = {"AU": "🇦🇺", "AR": "🇦🇷"}
OTRO = {"AU": "AR", "AR": "AU"}
HORAS_OTRO_PAIS = 48
CONVIENE_PCT = 10   # más de 10% más barato traído (con aduana) = conviene


def plata(x: float | None, moneda: str) -> str:
    if x is None:
        return "—"
    return ("A$" + f"{x:,.0f}".replace(",", ".")) if moneda == "AUD" else ars(x)


@dataclass
class Equivalente:
    fila: dict
    exacto: bool
    nota: str           # "mismo chip" | "aprox.: CL36 en vez de CL30" ...

    @property
    def datos(self) -> dict:
        return json.loads(self.fila.get("datos") or "{}")


def _num(x) -> int | None:
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _mas_parecido(filas: list[dict], distancia) -> dict | None:
    """El de menor distancia; a igual distancia, el más barato."""
    return min(filas, key=lambda r: (distancia(r), r["precio"])) if filas else None


def equivalente(db: DB, categoria: str, modelo: str, datos: dict, pais_otro: str,
                ahora: datetime | None = None, horas: int = HORAS_OTRO_PAIS) -> Equivalente | None:
    desde = (ahora or datetime.now(timezone.utc)) - timedelta(hours=horas)
    filas = [dict(r) for r in db.vigentes(pais_otro, categoria, desde)]
    for r in filas:
        r["_d"] = json.loads(r.get("datos") or "{}")
    if not filas:
        return None

    if categoria == "placas":
        exactas = [r for r in filas if r["modelo"] == modelo]
        if exactas:
            return Equivalente(exactas[0], True, "mismo chip")
        chip, vram = datos.get("chip"), _num(datos.get("vram"))
        r = _mas_parecido([r for r in filas if r["_d"].get("chip") == chip],
                          lambda r: abs((_num(r["_d"].get("vram")) or 0) - (vram or 0)))
        return Equivalente(r, False, f"aprox.: {r['_d'].get('vram')}GB en vez de {vram}GB") if r else None

    if categoria == "cpu":
        exactas = [r for r in filas if r["modelo"] == modelo]
        if exactas:
            return Equivalente(exactas[0], True, "mismo modelo")
        m = re.search(r"\d{3,5}", modelo)
        if not m:
            return None
        familia = [r for r in filas if re.search(rf"(?<!\d){m.group()}(?!\d)", r["modelo"])
                   and r["_d"].get("marca") == datos.get("marca")]
        r = _mas_parecido(familia, lambda r: 0)
        return Equivalente(r, False, f"aprox.: {r['modelo']} en vez de {modelo}") if r else None

    if categoria == "ram":
        cap, mods = _num(datos.get("capacidad_gb")), _num(datos.get("modulos"))
        vel, cl = _num(datos.get("velocidad")), _num(datos.get("cl"))
        misma_cap = [r for r in filas if _num(r["_d"].get("capacidad_gb")) == cap]
        mismos_mods = [r for r in misma_cap if _num(r["_d"].get("modulos")) == mods]

        def dist(r):
            v, c = _num(r["_d"].get("velocidad")), _num(r["_d"].get("cl"))
            dv = abs((v or 0) - (vel or 0)) if (v and vel) else (0 if v == vel else 10_000)
            dc = abs(c - cl) if (c and cl) else 0  # CL desconocido de un lado: no cuenta
            return (dv, dc)

        r = _mas_parecido(mismos_mods, dist) or _mas_parecido(misma_cap, dist)
        if not r:
            return None
        rv, rc, rm = _num(r["_d"].get("velocidad")), _num(r["_d"].get("cl")), _num(r["_d"].get("modulos"))
        difs = []
        if rm != mods:
            difs.append(f"{rm}x{cap // rm if rm else '?'} en vez de {mods}x{cap // mods if mods else '?'}")
        if rv != vel:
            difs.append(f"{rv or '?'} en vez de {vel or '?'}")
        if rc and cl and rc != cl:
            difs.append(f"CL{rc} en vez de CL{cl}")
        if not difs:
            return Equivalente(r, True, "misma capacidad, módulos y velocidad")
        return Equivalente(r, False, "aprox.: " + ", ".join(difs))

    if categoria == "pcs":
        chip, ram = datos.get("chip"), _num(datos.get("ram_gb"))
        misma_placa = [r for r in filas if r["_d"].get("chip") == chip]
        exactas = [r for r in misma_placa if ram and _num(r["_d"].get("ram_gb")) == ram]
        if exactas:
            return Equivalente(exactas[0], True, "misma placa y RAM")
        r = _mas_parecido(misma_placa, lambda r: abs((_num(r["_d"].get("ram_gb")) or 0) - (ram or 0)))
        if not r:
            return None
        otra = _num(r["_d"].get("ram_gb"))
        nota = f"aprox.: {otra}GB de RAM en vez de {ram}GB" if (ram and otra) else "aprox.: misma placa, RAM sin dato"
        return Equivalente(r, False, nota)
    return None


# ------------------------------------------------------------------ cuentas

@dataclass
class Cuenta:
    au_aud: float
    au_usd: float
    au_ars: float          # convertido, sin aduana
    ar_ars: float
    aduana_ars: float      # 50% sobre lo que pase de USD 500
    au_con_aduana: float

    @property
    def diferencia(self) -> float:      # positivo = más barato en Australia
        return self.ar_ars - self.au_ars

    @property
    def diferencia_pct(self) -> float:  # sobre el más caro de los dos
        return self.diferencia / max(self.ar_ars, self.au_ars) * 100

    @property
    def ahorro_con_aduana(self) -> float:
        return self.ar_ars - self.au_con_aduana

    @property
    def ahorro_con_aduana_pct(self) -> float:  # sobre el precio argentino
        return self.ahorro_con_aduana / self.ar_ars * 100


def cuenta(cot: Cotizacion, precio_aud: float, precio_ars: float) -> Cuenta:
    u = cot.aud_a_usd(precio_aud)
    au_ars = cot.usd_a_ars(u)
    ad = cot.aduana_ars(u)
    return Cuenta(precio_aud, u, au_ars, precio_ars, ad, au_ars + ad)


def veredicto(c: Cuenta) -> str:
    """'conviene' (traído sale más de 10% más barato, con aduana), 'casi igual' (0–10%), 'no conviene'."""
    p = c.ahorro_con_aduana_pct
    if p > CONVIENE_PCT:
        return "conviene"
    if p >= 0:
        return "casi igual"
    return "no conviene"


ICONO_VEREDICTO = {"conviene": "✅", "casi igual": "🟰", "no conviene": "❌"}


def _tienda(fila: dict, nombres: dict) -> str:
    nombre = escape(nombres.get(fila["tienda"], fila["tienda"]))
    return f'<a href="{escape(fila["url"])}">{nombre}</a>'


def lineas_comparacion(db: DB, cot: Cotizacion | None, pais: str, categoria: str, modelo: str,
                       datos: dict, precio: float, nombres: dict, ahora: datetime | None = None) -> list[str]:
    """Las líneas que van debajo del precio: conversión, mejor precio del otro país, diferencia,
    aduana y veredicto."""
    if not cot:
        return ["   (sin cotización: no pude convertir ni comparar)"]
    otro = OTRO[pais]
    lineas = []
    if pais == "AU":
        u = cot.aud_a_usd(precio)
        lineas.append(f"   ≈ {usd(u)} ≈ {ars(cot.usd_a_ars(u))} (MEP {ars(cot.mep)})")
    else:
        lineas.append(f"   ≈ {usd(cot.ars_a_usd(precio))} (MEP {ars(cot.mep)})")
    eq = equivalente(db, categoria, modelo, datos, otro, ahora)
    if not eq:
        lineas.append(f"{BANDERA[otro]} Sin precio para comparar en las tiendas que leo")
    else:
        f = eq.fila
        staticice = " · staticICE, confirmá stock" if eq.datos.get("via") == "staticICE" else ""
        if otro == "AR":
            tipo = f" {f['tipo_precio']}" if f.get("tipo_precio") in ("transferencia", "contado") else ""
            lineas.append(f"{BANDERA['AR']} Mejor precio: {_tienda(f, nombres)} {ars(f['precio'])}{tipo} "
                          f"({escape(eq.nota)})")
            c = cuenta(cot, precio, f["precio"])
        else:
            u = cot.aud_a_usd(f["precio"])
            lineas.append(f"{BANDERA['AU']} Mejor precio: {_tienda(f, nombres)} {plata(f['precio'], 'AUD')} "
                          f"≈ {usd(u)} ≈ {ars(cot.usd_a_ars(u))} ({escape(eq.nota)}{staticice})")
            c = cuenta(cot, f["precio"], precio)
        if c.diferencia >= 0:
            lineas.append(f"💰 Diferencia: ~{ars(c.diferencia)} más barato en 🇦🇺 ({c.diferencia_pct:.0f}%)")
        else:
            lineas.append(f"💰 Diferencia: ~{ars(-c.diferencia)} más barato en 🇦🇷 ({-c.diferencia_pct:.0f}%)")
        regla = f"{ARANCEL * 100:.0f}% sobre lo que pase de USD {FRANQUICIA_USD}"
        if c.aduana_ars <= 0:
            aduana = f"🛃 Aduana: no paga (vale menos de USD {FRANQUICIA_USD})"
        else:
            sentido = "más barato" if c.ahorro_con_aduana >= 0 else "más caro"
            quien = "" if pais == "AU" else " traído de 🇦🇺"
            aduana = (f"🛃 Si se declara en aduana ({regla}): ~{ars(c.au_con_aduana)} → "
                      f"~{ars(abs(c.ahorro_con_aduana))} {sentido}{quien}")
        lineas.append(aduana)
        v = veredicto(c)
        extra = ""
        if pais == "AR":
            extra = {"conviene": " traerlo de 🇦🇺", "casi igual": "", "no conviene": " traerlo: comprá en 🇦🇷"}[v]
        lineas.append(f"{ICONO_VEREDICTO[v]} Veredicto: {v}{extra}")
    if nota := cot.nota_respaldo():
        lineas.append(nota)
    return lineas
