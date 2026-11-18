"""Maximus Gaming Hardware. Listados .../maximus.aspx?/CAT=<n>/SCAT=-1/M=-1/OR=1/PAGE=<n>/.

La grilla la dibuja Vue en el navegador, pero el servidor manda dos cosas que alcanzan:
  - el bloque "mxSeoSSR" con cada tarjeta y el precio de efectivo/transferencia,
  - un JSON-LD (schema.org ItemList) con el precio de lista y el stock.
robots.txt solo prohíbe el checkout, el login y las URLs con PASO=."""
from __future__ import annotations

import re

from ..modelos import Oferta
from ..stock import estado_schema
from .base import Tienda, precio_ar, registrar

BASE = "https://www.maximus.com.ar/Productos"
RE_TARJETA = re.compile(
    r'<article class="mxCardProduct">.*?href="([^"]+)".*?class="mxCardProduct__title">([^<]+)</h3>'
    r'<div class="mxCardProduct__prices">(.*?)</div></div></a></article>', re.S)
RE_PRECIO = re.compile(r'class="mxCardProduct__price">\s*([^<]+)<')
RE_ITEM = re.compile(r"/ITEM=(\d+)/")
RE_PAGINA = re.compile(r"/PAGE=(\d+)/?")


def _url(nombre: str, cat: int) -> str:
    return f"{BASE}/{nombre}/maximus.aspx?/CAT={cat}/SCAT=-1/M=-1/OR=1/PAGE=1/"


@registrar
class Maximus(Tienda):
    id = "maximus"
    nombre = "Maximus"
    pais = "AR"
    moneda = "ARS"
    web = "https://www.maximus.com.ar"
    timeout = 40.0
    max_paginas = 12
    categorias = {
        "placas": [_url("Placas-De-Video", 48)],
        "cpu": [_url("Microprocesadores", 52)],
        "ram": [_url("Memorias", 50)],
        "pcs": [_url("Computadoras", 68)],
        "ssd": [_url("Almacenamiento", 53)],
    }

    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        return self.parsear(self.cliente.get(url).text, url, categoria)

    def parsear(self, texto: str, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        lista: dict[str, tuple[float | None, str]] = {}
        for p in self.json_ld(self.html(texto)):
            if p.get("@type") != "Product" or not isinstance(p.get("offers"), dict):
                continue
            m = RE_ITEM.search(p.get("url", ""))
            if m:
                of = p["offers"]
                try:
                    precio = float(of.get("price")) if of.get("price") is not None else None
                except (TypeError, ValueError):
                    precio = None
                lista[m.group(1)] = (precio, str(of.get("availability", "")))
        ssr = texto[texto.find('id="mxSeoSSR"'):] if 'id="mxSeoSSR"' in texto else ""
        ofertas = []
        for href, titulo, precios in RE_TARJETA.findall(ssr):
            m_item = RE_ITEM.search(href)
            m_precio = RE_PRECIO.search(precios)
            contado = precio_ar(m_precio.group(1)) if m_precio else None
            if not (m_item and contado):
                continue
            precio_lista, disp = lista.get(m_item.group(1), (None, ""))
            ofertas.append(self.oferta(
                categoria=categoria, titulo=titulo.strip(), url=href, precio=contado,
                tipo_precio="transferencia",
                precio_lista=precio_lista if precio_lista and precio_lista > contado else None,
                stock=estado_schema(disp),
                sku=m_item.group(1)))
        actual = int(RE_PAGINA.search(url).group(1)) if RE_PAGINA.search(url) else 1
        sig = RE_PAGINA.sub(f"/PAGE={actual + 1}/", url)
        hay_siguiente = f"PAGE={actual + 1}/" in texto.replace("\\/", "/")
        return ofertas, (sig if ofertas and hay_siguiente else None)
