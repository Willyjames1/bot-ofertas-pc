"""Mexx. Con ?all=1 (el botón "Todo" de la web) cada categoría entra en una sola página.

El precio del listado es el "Mejor precio": efectivo, débito, crédito en 1 pago o transferencia."""
from __future__ import annotations

from ..modelos import Oferta
from .base import Tienda, precio_ar, registrar


@registrar
class Mexx(Tienda):
    id = "mexx"
    nombre = "Mexx"
    pais = "AR"
    moneda = "ARS"
    web = "https://www.mexx.com.ar"
    categorias = {
        "placas": ["https://www.mexx.com.ar/productos-rubro/placas-de-video/?all=1"],
        "cpu": ["https://www.mexx.com.ar/productos-rubro/procesadores/?all=1"],
        "ram": ["https://www.mexx.com.ar/productos-rubro/memorias-ram/?all=1"],
    }

    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        return self.parsear(self.cliente.get(url).text, categoria), None

    def parsear(self, texto: str, categoria: str) -> list[Oferta]:
        ofertas = []
        for card in self.html(texto).css("div.productos"):
            a = card.css_first("h4.card-title a")
            p = card.css_first(".price h4 b")
            if not a or not p or not (precio := precio_ar(p.text())):
                continue
            etiqueta = card.css_first(".enstocklistado")
            etiqueta = etiqueta.text(strip=True) if etiqueta else ""
            ofertas.append(self.oferta(
                categoria=categoria, titulo=a.text(strip=True), url=a.attributes["href"], precio=precio,
                tipo_precio="transferencia",
                stock=True if "STOCK" in etiqueta.upper() and "SIN" not in etiqueta.upper() else None,
                datos={"estado_stock": etiqueta} if etiqueta else {}))
        return ofertas
