"""Estructuras de datos comunes a todas las fuentes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

CATEGORIAS = ("placas", "cpu", "ram", "pcs", "mothers", "ssd", "fuentes", "refrigeracion",
              "gabinetes", "monitores")


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Oferta:
    """Un producto tal como lo publica una tienda, en un momento dado."""

    tienda: str            # id corto, ej. "umart"
    pais: str              # "AU" o "AR"
    categoria: str         # una de CATEGORIAS
    titulo: str
    url: str
    precio: float          # AU: con GST. AR: transferencia/contado si existe, si no lista
    moneda: str            # "AUD" o "ARS"
    tipo_precio: str = "lista"        # "transferencia" | "lista" | "unico"
    precio_lista: float | None = None  # AR: precio con tarjeta / de lista
    cuotas: str | None = None          # AR: ej. "6 sin interés de $250.000"
    stock: bool | None = True
    sku: str | None = None
    fecha: datetime = field(default_factory=ahora_utc)
    # Lo completa normalizar.normalizar()
    modelo: str | None = None          # modelo canónico, ej. "RTX 5070 Ti 16GB"
    variante: str | None = None        # ej. "MSI Ventus 3X OC"
    datos: dict = field(default_factory=dict)
    tray: bool = False
    combo: bool = False
    descartada: str | None = None      # motivo si se descarta (usado, notebook, ...)


@dataclass
class Post:
    """Un post de foro (OzBargain, Reddit...)."""

    fuente: str        # "ozbargain" | "reddit"
    id: str
    titulo: str
    url: str
    publicado: datetime
    votos: int | None = None
    url_tienda: str | None = None
    precio: float | None = None
    moneda: str | None = None
    etiquetas: list[str] = field(default_factory=list)
    expira: datetime | None = None                       # OzBargain: fecha de vencimiento del deal
    estados: list[str] = field(default_factory=list)     # OzBargain: expired, outofstock, upcoming...
