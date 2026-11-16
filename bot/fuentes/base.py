"""Interfaz común de las tiendas. Para sumar una tienda: crear un archivo en bot/fuentes/,
heredar de Tienda, completar los atributos y el método leer_pagina(), y decorarla con @registrar."""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from selectolax.lexbor import LexborHTMLParser

from ..modelos import Oferta
from ..red import Cliente

log = logging.getLogger("bot.fuentes")

TIENDAS: dict[str, type["Tienda"]] = {}


def registrar(cls: type["Tienda"]) -> type["Tienda"]:
    TIENDAS[cls.id] = cls
    return cls


class Tienda:
    id: str = ""
    nombre: str = ""
    pais: str = ""            # "AU" | "AR"
    moneda: str = ""          # "AUD" | "ARS"
    web: str = ""
    # categoría -> lista de URLs de listado (página 1)
    categorias: dict[str, list[str]] = {}
    servidor: str = ""        # tiendas con el mismo servidor no se leen en el mismo turno
    max_paginas: int = 15
    pausa: tuple[float, float] = (3.0, 5.0)

    def __init__(self, cliente: Cliente | None = None):
        self.cliente = cliente or Cliente(pausa=self.pausa)

    # Cada tienda implementa esto: recibe la URL de una página y devuelve
    # (ofertas, url_siguiente_o_None).
    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        raise NotImplementedError

    def leer(self, categoria: str) -> list[Oferta]:
        vistas: dict[str, Oferta] = {}
        for url in self.categorias.get(categoria, []):
            pagina = 0
            while url and pagina < self.max_paginas:
                pagina += 1
                ofertas, url = self.leer_pagina(url, categoria)
                nuevas = [o for o in ofertas if o.url not in vistas]
                for o in nuevas:
                    vistas[o.url] = o
                if not nuevas:  # la página no trajo nada nuevo: fin
                    break
        log.info("%s/%s: %d productos", self.id, categoria, len(vistas))
        return list(vistas.values())

    # ------------------------------------------------------------ ayudas

    def oferta(self, **kw) -> Oferta:
        return Oferta(tienda=self.id, pais=self.pais, moneda=self.moneda, **kw)

    @staticmethod
    def html(texto: str) -> LexborHTMLParser:
        return LexborHTMLParser(texto)

    @staticmethod
    def json_ld(arbol: LexborHTMLParser) -> list[dict]:
        """Todos los objetos schema.org de la página, aplanados."""
        salida: list[dict] = []

        def aplanar(x):
            if isinstance(x, list):
                for y in x:
                    aplanar(y)
            elif isinstance(x, dict):
                if "@graph" in x:
                    aplanar(x["@graph"])
                else:
                    salida.append(x)
                    if x.get("@type") == "ItemList":
                        for el in x.get("itemListElement", []):
                            aplanar(el.get("item", el) if isinstance(el, dict) else el)

        for nodo in arbol.css('script[type="application/ld+json"]'):
            try:
                aplanar(json.loads(nodo.text() or "null"))
            except json.JSONDecodeError:
                continue
        return salida


def precio_ar(texto: str | None) -> float | None:
    """'$ 1.234.567,89' -> 1234567.89"""
    if not texto:
        return None
    t = re.sub(r"[^\d,\.]", "", texto)
    if not t:
        return None
    if "," in t and t.rfind(",") > t.rfind("."):
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1 or re.search(r"\.\d{3}$", t):
        t = t.replace(".", "")
    t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def precio_au(texto: str | None) -> float | None:
    """'$1,299.00' -> 1299.0"""
    if not texto:
        return None
    t = re.sub(r"[^\d\.]", "", texto.replace(",", ""))
    try:
        return float(t) if t else None
    except ValueError:
        return None


def primero(iterable: Iterable):
    return next(iter(iterable), None)
