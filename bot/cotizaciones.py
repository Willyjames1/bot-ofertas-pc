"""Cotizaciones (MEP y AUD/USD) y el cálculo de "¿conviene traerlo de Australia?"."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import DB
from .red import Cliente

log = logging.getLogger("bot.cotizaciones")
URL_MEP = "https://dolarapi.com/v1/dolares/bolsa"
URL_AUD = "https://api.frankfurter.dev/v1/latest?from=AUD&to=USD"
FRANQUICIA_USD = 500
ARANCEL = 0.5


@dataclass
class Cotizacion:
    mep: float
    aud_usd: float
    ts: datetime


def obtener(db: DB, cliente: Cliente | None = None, max_minutos: int = 60) -> Cotizacion | None:
    ult = db.ultima_cotizacion()
    if ult:
        ts = datetime.fromisoformat(ult["ts"])
        if datetime.now(timezone.utc) - ts < timedelta(minutes=max_minutos):
            return Cotizacion(ult["mep"], ult["aud_usd"], ts)
    cliente = cliente or Cliente(pausa=(0.5, 1.0), respetar_robots=False)
    try:
        mep = float(cliente.get(URL_MEP).json()["venta"])
        aud = float(cliente.get(URL_AUD).json()["rates"]["USD"])
        db.guardar_cotizacion(mep, aud)
        return Cotizacion(mep, aud, datetime.now(timezone.utc))
    except Exception as e:  # noqa: BLE001
        log.warning("No pude actualizar cotizaciones: %s", e)
        if ult:
            return Cotizacion(ult["mep"], ult["aud_usd"], datetime.fromisoformat(ult["ts"]))
        return None


@dataclass
class Conviene:
    costo_ars: float          # lo que cuesta traerlo, ya con el reintegro del TRS
    usd: float                # valor en USD después del TRS (base para aduana)
    aduana_ars: float         # lo que pagarías si te cobran aduana
    mejor_ar: float | None
    ahorro: float | None      # positivo = conviene traerlo
    ahorro_pct: float | None


def calcular(precio_aud: float, cot: Cotizacion, mejor_ar: float | None, aduana: bool = False) -> Conviene:
    sin_gst = precio_aud * (1 - 1 / 11)
    usd = sin_gst * cot.aud_usd
    costo = usd * cot.mep
    aduana_ars = ARANCEL * max(0.0, usd - FRANQUICIA_USD) * cot.mep
    total = costo + (aduana_ars if aduana else 0)
    ahorro = (mejor_ar - total) if mejor_ar else None
    pct = (ahorro / mejor_ar * 100) if mejor_ar else None
    return Conviene(total, usd, aduana_ars, mejor_ar, ahorro, pct)


def ars(x: float) -> str:
    return "$" + f"{x:,.0f}".replace(",", ".")


def texto_conviene(c: Conviene, tienda_ar: str | None, aduana: bool) -> str:
    base = f"✈️ ¿Conviene traerlo? Traído: {ars(c.costo_ars)} (con TRS{', con aduana' if aduana else ''})"
    if c.mejor_ar:
        if c.ahorro >= 0:
            base += f" vs {ars(c.mejor_ar)} en {tienda_ar} → ahorrás {ars(c.ahorro)} ({c.ahorro_pct:.0f}%)"
        else:
            base += f" vs {ars(c.mejor_ar)} en {tienda_ar} → perdés {ars(-c.ahorro)}. Comprá acá"
    else:
        base += " (no hay precio argentino para comparar)"
    if not aduana:
        base += f"\n   Si te cobran aduana: +{ars(c.aduana_ars)}"
    return base
