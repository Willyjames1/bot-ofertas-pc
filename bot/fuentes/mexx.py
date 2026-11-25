"""Mexx. Con ?all=1 (el botón "Todo" de la web) cada categoría entra en una sola página.

El precio del listado es el "Mejor precio": efectivo, débito, crédito en 1 pago o transferencia.

PCs armadas: el nombre viene cortado ("GP709 Pc Intel Core i9 14900KF - 16Gb - 1Tb - RTX5"), así
que la placa de video se lee de la lista de componentes de la ficha. Solo se abre la ficha de las
que cuestan menos que el objetivo de PCs (las únicas que pueden avisar), y como mucho 8 por corrida."""
from __future__ import annotations

import re

from .. import config
from ..modelos import Oferta
from ..stock import estado_etiqueta
from .base import Tienda, precio_ar, registrar

RE_PLACA = re.compile(r"(Placa De Video .+?)\s*Cant:", re.I)
MAX_FICHAS = 8


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
        "pcs": ["https://www.mexx.com.ar/productos-rubro/gamers/?all=1"],
        "mothers": ["https://www.mexx.com.ar/productos-rubro/motherboards/?all=1"],
        "ssd": ["https://www.mexx.com.ar/productos-rubro/almacenamiento/?all=1"],
        "fuentes": ["https://www.mexx.com.ar/productos-rubro/fuentes-de-poder/?all=1"],
        "gabinetes": ["https://www.mexx.com.ar/productos-rubro/gabinetes/?all=1"],
        "refrigeracion": ["https://www.mexx.com.ar/productos-rubro/refrigeracion/?all=1"],
    }

    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        return self.parsear(self.cliente.get(url).text, categoria), None

    def leer(self, categoria: str) -> list[Oferta]:
        ofertas = super().leer(categoria)
        if categoria == "pcs":
            tope = ((config.cargar().get("pcs") or {}).get("objetivo") or {}).get("ARS")
            candidatas = [o for o in ofertas if o.stock is not False and (not tope or o.precio <= tope)]
            for o in sorted(candidatas, key=lambda x: x.precio)[:MAX_FICHAS]:
                if placa := self.placa_de_ficha(self.cliente.get(o.url).text):
                    o.datos["placa"] = placa
        return ofertas

    def placa_de_ficha(self, texto: str) -> str | None:
        cuerpo = self.html(texto).body
        m = RE_PLACA.search(" ".join(cuerpo.text().split())) if cuerpo else None
        return m.group(1).strip() if m else None

    def parsear(self, texto: str, categoria: str) -> list[Oferta]:
        ofertas = []
        for card in self.html(texto).css("div.card-ecommerce"):
            a = card.css_first("h4.card-title a")
            p = card.css_first(".price h4 b")
            if not a or not p or not (precio := precio_ar(p.text())):
                continue
            etiqueta = card.css_first(".enstocklistado")
            etiqueta = etiqueta.text(strip=True) if etiqueta else ""
            ofertas.append(self.oferta(
                categoria=categoria, titulo=a.text(strip=True).rstrip(" -"), url=a.attributes["href"],
                precio=precio, tipo_precio="transferencia",
                stock=estado_etiqueta(etiqueta),
                datos={"estado_stock": etiqueta} if etiqueta else {}))
        return ofertas
