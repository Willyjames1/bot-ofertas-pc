"""Gezatek. Listados con ?page=N y link "Siguiente".

Cada producto trae el "Precio Geza" (efectivo/transferencia) y el precio con Mercado Pago, que
tomamos como precio de lista. robots.txt prohíbe ordenar y filtrar (?orderby=, ?filter=...)."""
from __future__ import annotations

from urllib.parse import urljoin

from ..modelos import Oferta
from ..stock import estado_etiqueta
from .base import Tienda, precio_ar, registrar


@registrar
class Gezatek(Tienda):
    id = "gezatek"
    nombre = "Gezatek"
    pais = "AR"
    moneda = "ARS"
    web = "https://gezatek.com.ar"
    categorias = {
        "placas": ["https://gezatek.com.ar/placas-de-video/"],
        "cpu": ["https://gezatek.com.ar/procesadores/"],
        "ram": ["https://gezatek.com.ar/memorias-ram/memoria-ram-ddr5/"],
        "pcs": ["https://gezatek.com.ar/pc-armadas/"],
    }

    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        return self.parsear(self.cliente.get(url).text, url, categoria)

    def parsear(self, texto: str, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        arbol = self.html(texto)
        ofertas = []
        for d in arbol.css("div[data-nombre]"):
            a = d.css_first("h4 a")
            precio = precio_ar(d.attributes.get("data-precio"))
            if not a or not precio:
                continue
            mp = d.css_first(".precio_mp")
            lista = precio_ar(mp.text()) if mp else None
            est = d.css_first(".et")
            est = est.text(strip=True) if est else ""
            ofertas.append(self.oferta(
                categoria=categoria, titulo=(d.attributes.get("data-nombre") or a.text()).strip(),
                url=a.attributes["href"], precio=precio, tipo_precio="transferencia",
                precio_lista=lista if lista and lista > precio else None,
                stock=estado_etiqueta(est),
                sku=d.attributes.get("data-id"), datos={"estado_stock": est} if est else {}))
        sig = arbol.css_first("a[rel=next]")
        return ofertas, (urljoin(url, sig.attributes["href"]) if sig else None)
