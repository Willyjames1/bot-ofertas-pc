"""Compra Gamer. La web es una app Angular que baja TODO el catálogo en un solo JSON
(static.compragamer.com/productos, ~1.700 productos) y filtra en el navegador. Hacemos lo mismo:
un único pedido por corrida, que es lo más liviano posible para ellos.

Precios: "precioEspecial" es el de transferencia/depósito; "precioLista" el de tarjeta."""
from __future__ import annotations

import re

from ..modelos import Oferta
from .base import Tienda, registrar

CATALOGO = "https://static.compragamer.com/productos"
# id_subcategoria de static.compragamer.com/categorias_sub
SUBCATEGORIAS = {
    "placas": {6, 62, 116},      # GeForce, Radeon, Intel Arc
    "cpu": {27, 48},             # AMD, Intel (el 103 es "Procesadores Outlet": no)
    "ram": {15},                 # Memorias (las de notebook son la 47)
    "pcs": {30},                 # PC de Escritorio (las gamer se arman en "Armá tu PC": no son productos)
    "mothers": {26, 49},
    "ssd": {81},
    "fuentes": {34},
    "refrigeracion": {36},
    "gabinetes": {7},
    "teclados": {39},
    "mouse": {2},
}


def url_producto(id_producto: int, nombre: str) -> str:
    # igual que la web: nombre con todo lo que no sea letra/número/_ cambiado por "_"
    return f"https://compragamer.com/producto/{re.sub(r'[^A-Za-z0-9_]+', '_', nombre.strip())}_{id_producto}"


@registrar
class CompraGamer(Tienda):
    id = "compragamer"
    nombre = "Compra Gamer"
    pais = "AR"
    moneda = "ARS"
    web = "https://compragamer.com"
    categorias = {c: [CATALOGO] for c in SUBCATEGORIAS}

    def __init__(self, cliente=None):
        super().__init__(cliente)
        self._catalogo: list[dict] | None = None

    def catalogo(self) -> list[dict]:
        if self._catalogo is None:
            self._catalogo = self.cliente.get(CATALOGO).json()
        return self._catalogo

    def leer(self, categoria: str) -> list[Oferta]:
        return self.parsear(self.catalogo(), categoria)

    def parsear(self, productos: list[dict], categoria: str) -> list[Oferta]:
        subs = SUBCATEGORIAS.get(categoria, set())
        ofertas = []
        for p in productos:
            if p.get("id_subcategoria") not in subs or not p.get("precioEspecial"):
                continue
            if p.get("visible_solo_en_ATPC") or p.get("visible_solo_en_combo"):
                continue  # solo se venden dentro de "Armá tu PC" o de un combo
            o = self.oferta(
                categoria=categoria, titulo=p["nombre"].strip(), url=url_producto(p["id_producto"], p["nombre"]),
                precio=float(p["precioEspecial"]), tipo_precio="transferencia",
                precio_lista=float(p["precioLista"]) if p.get("precioLista") else None,
                stock=bool(p.get("vendible")) and (p.get("stock") or 0) > 0,
                sku=str(p["id_producto"]), datos={"estado_stock": p.get("codigo")})
            if p.get("es_outlet"):
                o.descartada = "outlet"
            ofertas.append(o)
        return ofertas
