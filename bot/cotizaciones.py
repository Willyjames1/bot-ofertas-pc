"""Cotizaciones: dólar MEP (dolarapi.com) y AUD/USD (frankfurter.app).

Se bajan UNA vez por corrida y se usan para todos los avisos de esa corrida. Cada una se guarda en la
base; si alguna de las dos falla, se usa la última guardada y el aviso lo aclara."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import TZ_AR
from .db import DB
from .red import Cliente

log = logging.getLogger("bot.cotizaciones")
URL_MEP = "https://dolarapi.com/v1/dolares/bolsa"
URL_AUD = "https://api.frankfurter.app/latest?from=AUD&to=USD"
FRANQUICIA_USD = 500   # aduana: lo que pase de USD 500 paga 50%
ARANCEL = 0.5
FUENTE = {"mep": "dolarapi.com", "aud_usd": "frankfurter.app"}


@dataclass
class Cotizacion:
    mep: float                 # pesos por dólar (venta)
    aud_usd: float             # dólares por dólar australiano
    ts: datetime
    respaldo: dict[str, datetime] = field(default_factory=dict)  # cuál vino de la base y de cuándo

    def aud_a_usd(self, aud: float) -> float:
        return aud * self.aud_usd

    def usd_a_ars(self, usd: float) -> float:
        return usd * self.mep

    def aud_a_ars(self, aud: float) -> float:
        return self.usd_a_ars(self.aud_a_usd(aud))

    def ars_a_usd(self, pesos: float) -> float:
        return pesos / self.mep

    def aduana_ars(self, usd: float) -> float:
        return ARANCEL * max(0.0, usd - FRANQUICIA_USD) * self.mep

    def nota_respaldo(self) -> str | None:
        """'⚠️ Cotización guardada: MEP del 16/11 14:00 (dolarapi.com no respondió)'."""
        if not self.respaldo:
            return None
        partes = [f"{'MEP' if k == 'mep' else 'AUD/USD'} del {ts.astimezone(TZ_AR):%d/%m %H:%M} "
                  f"({FUENTE[k]} no respondió)" for k, ts in self.respaldo.items()]
        return "⚠️ Cotización guardada: " + "; ".join(partes)


def _bajar(cliente: Cliente) -> dict[str, float | None]:
    valores: dict[str, float | None] = {"mep": None, "aud_usd": None}
    try:
        valores["mep"] = float(cliente.get(URL_MEP).json()["venta"])
    except Exception as e:  # noqa: BLE001
        log.warning("No pude bajar el MEP de %s: %s", FUENTE["mep"], type(e).__name__)
    try:
        valores["aud_usd"] = float(cliente.get(URL_AUD).json()["rates"]["USD"])
    except Exception as e:  # noqa: BLE001
        log.warning("No pude bajar el AUD/USD de %s: %s", FUENTE["aud_usd"], type(e).__name__)
    return valores


def obtener(db: DB, cliente: Cliente | None = None) -> Cotizacion | None:
    """Baja las dos cotizaciones (una vez por corrida: el que llama la guarda y la reusa)."""
    propio = cliente is None
    cliente = cliente or Cliente(pausa=(0.3, 0.6), respetar_robots=False)
    try:
        valores = _bajar(cliente)
    finally:
        if propio:
            cliente.cerrar()
    ahora = datetime.now(timezone.utc)
    if any(v is not None for v in valores.values()):
        db.guardar_cotizacion(valores["mep"], valores["aud_usd"])
    respaldo: dict[str, datetime] = {}
    for k in ("mep", "aud_usd"):
        if valores[k] is None:
            fila = db.ultima_cotizacion(k)
            if not fila:
                log.warning("Sin %s y sin cotización guardada: no puedo convertir precios", k)
                return None
            valores[k] = fila[k]
            respaldo[k] = datetime.fromisoformat(fila["ts"])
    return Cotizacion(valores["mep"], valores["aud_usd"], ahora, respaldo)


def ars(x: float) -> str:
    return "$" + f"{x:,.0f}".replace(",", ".")


def usd(x: float) -> str:
    return "USD " + f"{x:,.0f}".replace(",", ".")
