"""Venex. Listados de 12 productos con ?page=N (robots.txt prohíbe ?sort=, ?limit=, etc.).

El precio del listado es "Precio en un pago: contado efectivo". El título visible viene cortado
con "...", pero el completo está en el dato de analytics de cada tarjeta (enhancedClick)."""
from __future__ import annotations

import html
import json
import re

from ..modelos import Oferta
from .base import Tienda, precio_ar, registrar

RE_CLICK = re.compile(r"enhancedClick\((\{.*?\})\)")


@registrar
class Venex(Tienda):
    id = "venex"
    nombre = "Venex"
    pais = "AR"
    moneda = "ARS"
    web = "https://www.venex.com.ar"
    categorias = {
        "placas": ["https://www.venex.com.ar/componentes-de-pc/placas-de-video"],
        "cpu": ["https://www.venex.com.ar/componentes-de-pc/microprocesadores"],
        "ram": ["https://www.venex.com.ar/componentes-de-pc/memorias-ram/desktop"],
    }
    max_paginas = 25

    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        return self.parsear(self.cliente.get(url).text, categoria)

    def parsear(self, texto: str, categoria: str) -> tuple[list[Oferta], str | None]:
        arbol = self.html(texto)
        ofertas = []
        for caja in arbol.css(".product-box"):
            a = caja.css_first(".product-box-title a")
            p = caja.css_first(".current-price")
            if not a or not p or not (precio := precio_ar(p.text())):
                continue
            titulo = a.text(strip=True)
            if m := RE_CLICK.search(a.attributes.get("onclick") or ""):
                try:
                    titulo = json.loads(html.unescape(m.group(1))).get("name") or titulo
                except json.JSONDecodeError:
                    pass
            pago = caja.css_first(".product-box-payment")
            ofertas.append(self.oferta(
                categoria=categoria, titulo=titulo.strip(), url=a.attributes["href"], precio=precio,
                tipo_precio="contado", stock=None,
                datos={"forma_pago": pago.text(strip=True)} if pago else {}))
        sig = arbol.css_first('a.pageResults[title*="Siguiente "]')
        return ofertas, (sig.attributes.get("href") if sig else None)
