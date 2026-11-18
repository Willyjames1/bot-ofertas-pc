"""Resumen diario: un solo mensaje (desde las 12:00 hora argentina, una vez por día) con el mejor
precio de hoy en 🇦🇷 y en 🇦🇺 de cada producto de config.yaml → resumen_diario.productos, pasado a
pesos y con la diferencia entre países."""
from __future__ import annotations

import json
import logging
from datetime import datetime, time, timezone
from html import escape

from .alertas import ICONO, NOMBRE_TIENDA, pasa_filtros, ram_cumple
from .comparar import BANDERA, cuenta, plata, valija_de
from .config import TZ_AR
from .cotizaciones import Cotizacion, ars
from .db import DB
from .normalizar import canon, coincide_ssd, consulta_ssd, limpiar, parsear_chip_config

log = logging.getLogger("bot.resumen")
CLAVE_ESTADO = "resumen_diario"


def _coincide(categoria: str, nombre: str, modelo: str, datos: dict) -> bool:
    if categoria == "placas":
        chip, vram = parsear_chip_config(nombre)
        return chip == datos.get("chip") and (vram is None or vram == datos.get("vram"))
    if categoria == "ram":
        return ram_cumple(nombre, datos)
    if categoria == "pcs":
        return canon(datos.get("chip") or "") == canon(nombre)
    if categoria == "ssd":   # "990 Pro 2TB", "Gen5 2TB", "SN850X 4TB": como /buscar
        q = consulta_ssd(limpiar(f"SSD {nombre}"))
        return q is not None and coincide_ssd(q, datos)
    return canon(modelo) == canon(nombre)


def mejor_de_hoy(db: DB, cfg: dict, categoria: str, nombre: str, pais: str, desde: datetime) -> dict | None:
    """La más barata con stock vista desde 'desde' que cumple tus filtros (sin mirar precio_max)."""
    for r in db.vigentes(pais, categoria, desde):  # confirmadas primero, cada grupo por precio
        datos = json.loads(r["datos"] or "{}")
        if not _coincide(categoria, nombre, r["modelo"], datos):
            continue
        if not pasa_filtros(cfg, categoria, r["modelo"], datos, None, r["moneda"], bool(r["tray"]), bool(r["combo"])):
            continue
        return dict(r)
    return None


def _titulo(categoria: str, nombre: str) -> str:
    if categoria == "ram":
        return f"RAM DDR5 {nombre}"
    if categoria == "pcs":
        return f"PC armada con {nombre}"
    if categoria == "ssd":
        return f"SSD {nombre}"
    return nombre


def _tienda(r: dict) -> str:
    nota = "" if r.get("stock_ok", True) else " (stock sin confirmar)"
    return f'<a href="{escape(r["url"])}">{escape(NOMBRE_TIENDA.get(r["tienda"], r["tienda"]))}</a>{nota}'


def texto(db: DB, cfg: dict, cot: Cotizacion | None, ahora: datetime | None = None) -> str | None:
    rd = cfg.get("resumen_diario") or {}
    productos = rd.get("productos") or {}
    if not productos:
        return None
    ahora = ahora or datetime.now(timezone.utc)
    local = ahora.astimezone(TZ_AR)
    desde = datetime.combine(local.date(), time(0), TZ_AR)
    cab = f"☀️ <b>Resumen del día</b> — {local:%d/%m}"
    if cot:
        aud = f"{cot.aud_usd:.3f}".replace(".", ",")
        cab += f"\nMEP {ars(cot.mep)} · A$1 = USD {aud}"
    bloques = [cab]
    for categoria, nombres in productos.items():
        for nombre in nombres or []:
            ar = mejor_de_hoy(db, cfg, categoria, str(nombre), "AR", desde)
            au = mejor_de_hoy(db, cfg, categoria, str(nombre), "AU", desde)
            icono = ICONO.get(categoria, "•").split(" ")[0]
            lineas = [f"{icono} <b>{escape(_titulo(categoria, str(nombre)))}</b>"]
            lineas.append(f"  {BANDERA['AR']} " + (f"{ars(ar['precio'])} · {_tienda(ar)}" if ar else "sin precio hoy"))
            if au:
                conv = f" ≈ {ars(cot.aud_a_ars(au['precio']))}" if cot else ""
                lineas.append(f"  {BANDERA['AU']} {plata(au['precio'], 'AUD')}{conv} · {_tienda(au)}")
            else:
                lineas.append(f"  {BANDERA['AU']} sin precio hoy")
            if ar and au and cot:
                c = cuenta(cot, au["precio"], ar["precio"], valija_de(cfg))
                if c.diferencia >= 0:
                    dif = f"{c.diferencia_pct:.0f}% más barato en {BANDERA['AU']}"
                else:
                    dif = f"{-c.diferencia_pct:.0f}% más barato en {BANDERA['AR']}"
                if c.aduana_ars > 0 or c.valija_ars > 0:
                    con = c.ahorro_con_aduana_pct
                    que = "con valija y aduana" if c.aduana_ars > 0 and c.valija_ars > 0 else                         ("con valija" if c.valija_ars > 0 else "con aduana")
                    dif += (f" ({que}: {con:.0f}% más barato traído)" if con >= 0
                            else f" ({que}: {-con:.0f}% más caro traído)")
                lineas.append(f"  → {dif}")
            bloques.append("\n".join(lineas))
    if cot and (nota := cot.nota_respaldo()):
        bloques.append(nota)
    return "\n\n".join(bloques)


def toca(db: DB, cfg: dict, ahora: datetime) -> bool:
    """¿Ya es la hora y todavía no se mandó hoy?"""
    rd = cfg.get("resumen_diario") or {}
    if not rd.get("activo", True) or not rd.get("productos"):
        return False
    local = ahora.astimezone(TZ_AR)
    hora = time.fromisoformat(str(rd.get("hora", "12:00")))
    return local.time() >= hora and db.get(CLAVE_ESTADO) != str(local.date())


def marcar_enviado(db: DB, ahora: datetime):
    db.set(CLAVE_ESTADO, str(ahora.astimezone(TZ_AR).date()))
