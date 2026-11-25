"""Comparación con el otro país: el producto equivalente, la conversión a dólares y pesos, la
diferencia, la aduana y el veredicto.

Equivalente (mejor precio con stock del otro país, visto en las últimas 48 h):
  placas  mismo chip y misma VRAM, cualquier marca
  cpu     el mismo modelo
  ram     misma capacidad, módulos y velocidad (y CL; si el CL cambia, "aprox.")
  ssd     misma capacidad y tipo (NVMe/SATA), y la generación más parecida
  pcs     la misma placa y la misma cantidad de RAM
Si no está el mismo, se usa el más parecido y se marca "aprox.".

Lo que viene de Australia se cuenta "traído": precio + una valija extra (general.valija_extra_aud)
+ aduana declarada. Una PC australiana se compara contra armarla en Argentina por partes."""
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
    """El de menor distancia; a igual distancia, el de stock confirmado y, entre esos, el más barato."""
    return min(filas, key=lambda r: (distancia(r), not r.get("stock_ok", True), r["precio"])) if filas else None


def equivalente(db: DB, categoria: str, modelo: str, datos: dict, pais_otro: str,
                ahora: datetime | None = None, horas: int = HORAS_OTRO_PAIS) -> Equivalente | None:
    desde = (ahora or datetime.now(timezone.utc)) - timedelta(hours=horas)
    filas = [dict(r) for r in db.vigentes(pais_otro, categoria, desde, ahora)]
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

    if categoria == "ssd":
        cap, interfaz, gen = datos.get("capacidad_tb"), datos.get("interfaz"), _num(datos.get("gen"))
        formato = datos.get("formato") or "2280"
        mismos = [r for r in filas if r["_d"].get("capacidad_tb") == cap and r["_d"].get("interfaz") == interfaz
                  and (r["_d"].get("formato") or "2280") == formato
                  and (interfaz == "SATA" or bool(r["_d"].get("gen")) == bool(gen))]
        r = _mas_parecido(mismos, lambda r: abs((_num(r["_d"].get("gen")) or gen or 0) - (gen or 0)))
        if not r:
            return None
        otra = _num(r["_d"].get("gen"))
        if otra and gen and otra != gen:
            return Equivalente(r, False, f"aprox.: Gen{otra} en vez de Gen{gen}")
        return Equivalente(r, True, "misma capacidad y tipo")

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
    au_con_aduana: float   # traído: precio + valija + aduana
    valija_ars: float = 0.0

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


def cuenta(cot: Cotizacion, precio_aud: float, precio_ars: float, valija_aud: float = 0) -> Cuenta:
    """La aduana se calcula sobre el producto; la valija es lo que cobra la aerolínea."""
    u = cot.aud_a_usd(precio_aud)
    au_ars = cot.usd_a_ars(u)
    ad = cot.aduana_ars(u)
    valija = cot.aud_a_ars(valija_aud)
    return Cuenta(precio_aud, u, au_ars, precio_ars, ad, au_ars + ad + valija, valija)


def valija_de(cfg: dict | None) -> float:
    return float(((cfg or {}).get("general") or {}).get("valija_extra_aud") or 0)


# ------------------------------------------------------------------ PCs por partes

@dataclass
class Partes:
    total: float
    detalle: list[str]       # "RTX 5070 Ti $2.244.000 (Compra Gamer)"
    faltan: list[str]        # lo que no se encontró en Argentina


def _mas_barata(db: DB, categoria: str, desde: datetime, cumple) -> dict | None:
    for r in db.vigentes("AR", categoria, desde):   # confirmadas primero, cada grupo por precio
        d = json.loads(r["datos"] or "{}")
        if cumple(r["modelo"], d):
            return dict(r)
    return None


def suma_partes(db: DB, cfg: dict | None, datos: dict, nombres: dict, ahora: datetime | None = None,
                horas: int = HORAS_OTRO_PAIS) -> Partes:
    """Lo que sale armar en Argentina la misma PC: la placa (mismo chip), el procesador (mismo
    modelo), la RAM DDR5 (misma cantidad), el SSD (misma capacidad, NVMe) y un estimado para
    mother, fuente y gabinete (pcs.resto_estimado_ars)."""
    desde = (ahora or datetime.now(timezone.utc)) - timedelta(hours=horas)
    pedidos = [
        ("placas", datos.get("chip"), lambda m, d: d.get("chip") == datos.get("chip")),
        ("cpu", datos.get("cpu"), lambda m, d: m == datos.get("cpu")),
        ("ram", f"RAM {datos.get('ram_gb')}GB" if datos.get("ram_gb") else None,
         lambda m, d: d.get("capacidad_gb") == datos.get("ram_gb")),
        ("ssd", f"SSD {datos.get('ssd_tb'):g}TB" if datos.get("ssd_tb") else None,
         lambda m, d: d.get("capacidad_tb") == datos.get("ssd_tb") and d.get("interfaz") == "NVMe"),
    ]
    total, detalle, faltan = 0.0, [], []
    for cat, nombre, cumple in pedidos:
        etiqueta = {"placas": "placa", "cpu": "procesador", "ram": "RAM", "ssd": "SSD"}[cat]
        if not nombre:
            faltan.append(f"{etiqueta} (la publicación no lo dice)")
            continue
        r = _mas_barata(db, cat, desde, cumple)
        if not r:
            faltan.append(f"{etiqueta} {nombre} (no lo vi en 🇦🇷)")
            continue
        total += r["precio"]
        detalle.append(f"{escape(nombre)} {ars(r['precio'])} ({escape(nombres.get(r['tienda'], r['tienda']))}"
                       f"{sin_confirmar(r)})")
    resto = float(((cfg or {}).get("pcs") or {}).get("resto_estimado_ars") or 0)
    if resto:
        total += resto
        detalle.append(f"mother + fuente + gabinete ~{ars(resto)} (estimado)")
    return Partes(total, detalle, faltan)


def aviso_davinci(cfg: dict | None, datos: dict) -> str | None:
    """⚠️ si la PC queda corta para editar en DaVinci Resolve (núcleos o disco)."""
    dv = ((cfg or {}).get("pcs") or {}).get("davinci") or {}
    nmin, smin = dv.get("nucleos_min", 12), dv.get("ssd_min_tb", 2)
    faltas = []
    n, ssd = datos.get("nucleos"), datos.get("ssd_tb")
    if n is not None and n < nmin:
        faltas.append(f"el procesador tiene {n} núcleos (menos de {nmin})")
    elif n is None:
        faltas.append("no dice cuántos núcleos tiene el procesador")
    if ssd is not None and ssd < smin:
        faltas.append(f"el SSD es de {ssd:g}TB (menos de {smin}TB)")
    elif ssd is None:
        faltas.append("no dice de cuánto es el SSD")
    return ("⚠️ Para DaVinci: " + " · ".join(faltas)) if faltas else None


def veredicto(c: Cuenta) -> str:
    """'conviene' (traído sale más de 10% más barato, con aduana), 'casi igual' (0–10%), 'no conviene'."""
    p = c.ahorro_con_aduana_pct
    if p > CONVIENE_PCT:
        return "conviene"
    if p >= 0:
        return "casi igual"
    return "no conviene"


ICONO_VEREDICTO = {"conviene": "✅", "casi igual": "🟰", "no conviene": "❌"}


def sin_confirmar(fila: dict) -> str:
    """' · stock sin confirmar' si no se pudo confirmar el stock de esa publicación."""
    return "" if fila.get("stock_ok", True) else " · stock sin confirmar"


def _tienda(fila: dict, nombres: dict) -> str:
    nombre = escape(nombres.get(fila["tienda"], fila["tienda"]))
    return f'<a href="{escape(fila["url"])}">{nombre}</a>'


def lineas_comparacion(db: DB, cot: Cotizacion | None, pais: str, categoria: str, modelo: str,
                       datos: dict, precio: float, nombres: dict, ahora: datetime | None = None,
                       cfg: dict | None = None, real_ar=None) -> list[str]:
    """Las líneas que van debajo del precio: conversión, mejor precio del otro país (o, para una
    PC australiana, armarla en Argentina por partes), diferencia, traerlo (valija + aduana) y
    veredicto. real_ar(fila): el precio real de una publicación argentina (la transferencia o las
    cuotas pasadas a contado, lo que sea menor); sin eso se usa el precio publicado."""
    if not cot:
        return ["   (sin cotización: no pude convertir ni comparar)"]
    otro = OTRO[pais]
    lineas = []
    if pais == "AU":
        u = cot.aud_a_usd(precio)
        lineas.append(f"   ≈ {usd(u)} ≈ {ars(cot.usd_a_ars(u))} (MEP {ars(cot.mep)})")
    else:
        lineas.append(f"   ≈ {usd(cot.ars_a_usd(precio))} (MEP {ars(cot.mep)})")
    valija = valija_de(cfg)
    eq = equivalente(db, categoria, modelo, datos, otro, ahora)
    partes = suma_partes(db, cfg, datos, nombres, ahora) if categoria == "pcs" and pais == "AU" else None
    c = None
    if partes and not partes.faltan:
        lineas.append(f"{BANDERA['AR']} Armarla por partes en 🇦🇷: ~{ars(partes.total)}")
        lineas.append("   " + " · ".join(partes.detalle))
        if eq:
            lineas.append(f"   (PC armada parecida en 🇦🇷: {_tienda(eq.fila, nombres)} {ars(eq.fila['precio'])}, "
                          f"{escape(eq.nota)}{sin_confirmar(eq.fila)})")
        c = cuenta(cot, precio, partes.total, valija)
    elif partes:
        lineas.append(f"{BANDERA['AR']} Por partes no se puede comparar: falta " + ", ".join(partes.faltan))
    if c is None and not eq:
        if not partes:
            lineas.append(f"{BANDERA[otro]} Sin precio para comparar en las tiendas que leo")
    elif c is None:
        f = eq.fila
        stock = sin_confirmar(f)
        if otro == "AR":
            tipo = f" {f['tipo_precio']}" if f.get("tipo_precio") in ("transferencia", "contado") else ""
            real = real_ar(f) if real_ar else f["precio"]
            if real and real < f["precio"] - 1:
                tipo += f", {ars(real)} en cuotas a contado"
            lineas.append(f"{BANDERA['AR']} Mejor precio: {_tienda(f, nombres)} {ars(f['precio'])}{tipo} "
                          f"({escape(eq.nota)}{stock})")
            c = cuenta(cot, precio, real or f["precio"], valija)
        else:
            u = cot.aud_a_usd(f["precio"])
            lineas.append(f"{BANDERA['AU']} Mejor precio: {_tienda(f, nombres)} {plata(f['precio'], 'AUD')} "
                          f"≈ {usd(u)} ≈ {ars(cot.usd_a_ars(u))} ({escape(eq.nota)}{stock})")
            c = cuenta(cot, f["precio"], precio, valija)
    if c is not None:
        lineas += lineas_cuenta(c, pais, valija)
    if nota := cot.nota_respaldo():
        lineas.append(nota)
    return lineas


def lineas_cuenta(c: Cuenta, pais: str, valija: float) -> list[str]:
    """Diferencia, traerlo (valija + aduana) y veredicto. El Worker de /buscar arma exactamente
    estas mismas líneas (worker/src/comparar.js; tests/test_worker.py compara las dos)."""
    lineas = []
    if c.diferencia >= 0:
        lineas.append(f"💰 Diferencia: ~{ars(c.diferencia)} más barato en 🇦🇺 ({c.diferencia_pct:.0f}%)")
    else:
        lineas.append(f"💰 Diferencia: ~{ars(-c.diferencia)} más barato en 🇦🇷 ({-c.diferencia_pct:.0f}%)")
    regla = f"{ARANCEL * 100:.0f}% sobre lo que pase de USD {FRANQUICIA_USD}"
    sentido = "más barato" if c.ahorro_con_aduana >= 0 else "más caro"
    quien = "" if pais == "AU" else " traído de 🇦🇺"
    resultado = f"~{ars(c.au_con_aduana)} → ~{ars(abs(c.ahorro_con_aduana))} {sentido}{quien}"
    con_valija = f"valija extra ({plata(valija, 'AUD')})" if valija else ""
    if c.aduana_ars <= 0 and not valija:
        aduana = f"🛃 Aduana: no paga (vale menos de USD {FRANQUICIA_USD})"
    elif c.aduana_ars <= 0:
        aduana = f"🧳 Traído con {con_valija}, sin aduana (vale menos de USD {FRANQUICIA_USD}): {resultado}"
    elif valija:
        aduana = f"🛃 Traído con {con_valija} y aduana declarada ({regla}): {resultado}"
    else:
        aduana = f"🛃 Si se declara en aduana ({regla}): {resultado}"
    lineas.append(aduana)
    v = veredicto(c)
    extra = ""
    if pais == "AR":
        extra = {"conviene": " traerlo de 🇦🇺", "casi igual": "", "no conviene": " traerlo: comprá en 🇦🇷"}[v]
    lineas.append(f"{ICONO_VEREDICTO[v]} Veredicto: {v}{extra}")
    return lineas
