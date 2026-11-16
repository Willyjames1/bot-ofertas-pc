"""Katech (WooCommerce). Usamos la API pública de la tienda (/wp-json/wc/store/v1/products),
la misma que usa su web: 100 productos por pedido.

El precio de la API es el "Precio especial EFECTIVO/TRANSFERENCIA". El de lista (tarjeta) y las
cuotas solo aparecen en la ficha de cada producto, así que no los leemos (serían cientos de pedidos)."""
from __future__ import annotations

import html
from urllib.parse import parse_qs, urlencode, urlsplit

from ..modelos import Oferta
from .base import Tienda, registrar

API = "https://katech.com.ar/wp-json/wc/store/v1/products"
POR_PAGINA = 100
SLUGS = {
    "placas": ["placas-de-video"],
    "cpu": ["microprocesadores-am5-procesadores", "microprocesadores-lga-1851-procesadores",
            "microprocesadores-lga-1700"],
    "ram": ["memoria-ram-ddr5"],
}


def url_api(slug: str, pagina: int = 1) -> str:
    return f"{API}?{urlencode({'category': slug, 'per_page': POR_PAGINA, 'page': pagina})}"


@registrar
class Katech(Tienda):
    id = "katech"
    nombre = "Katech"
    pais = "AR"
    moneda = "ARS"
    web = "https://katech.com.ar"
    categorias = {c: [url_api(s) for s in slugs] for c, slugs in SLUGS.items()}

    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        r = self.cliente.get(url)
        total = int(r.headers.get("x-wp-totalpages", "1") or 1)
        return self.parsear(r.json(), categoria), self._siguiente(url, total)

    @staticmethod
    def _siguiente(url: str, total_paginas: int) -> str | None:
        q = parse_qs(urlsplit(url).query)
        pagina = int(q.get("page", ["1"])[0])
        return url_api(q["category"][0], pagina + 1) if pagina < total_paginas else None

    def parsear(self, productos: list[dict], categoria: str) -> list[Oferta]:
        ofertas = []
        for p in productos:
            pr = p.get("prices") or {}
            if not pr.get("price"):
                continue
            div = 10 ** int(pr.get("currency_minor_unit", 0))
            precio = int(pr["price"]) / div
            if precio <= 0:
                continue
            disp = (p.get("stock_availability") or {}).get("text") or ""
            datos = {"estado_stock": disp} if disp else {}
            if categoria == "ram":
                datos["ddr"] = "DDR5"  # la categoría es "memoria-ram-ddr5"
            ofertas.append(self.oferta(
                categoria=categoria, titulo=html.unescape(p["name"]).strip(), url=p["permalink"], precio=precio,
                tipo_precio="transferencia", stock=bool(p.get("is_in_stock")), sku=p.get("sku") or str(p["id"]),
                datos=datos))
        return ofertas
