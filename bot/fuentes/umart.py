"""Umart y MSY: son la misma empresa y usan la misma plataforma (mismas rutas y mismo HTML).

Cada listado trae 20 productos por página con precio, stock y "Save $X" (lo que bajó).
Su robots.txt prohíbe ordenar, filtrar y cambiar el tamaño de página (sort=, pagesize=,
brand=, etc.): solo usamos ?page=N, que está permitido."""
from __future__ import annotations

import math
import re
from urllib.parse import urljoin

import httpx

from ..modelos import Oferta
from ..red import Bloqueado
from ..stock import estado_schema, estado_texto
from .base import Tienda, precio_au, registrar

RUTAS = {
    "placas": ["/pc-parts/computer-parts/graphics-cards-gpu-610"],
    "cpu": ["/pc-parts/computer-parts/cpu-processors-611"],
    "ram": ["/pc-parts/computer-parts/memory-ram/ddr5-ram-1085"],
    "mothers": ["/pc-parts/computer-parts/motherboards/amd-am5-1115"],
    "ssd": ["/pc-parts/storage-devices/ssd-hard-drives-580"],
    "fuentes": ["/pc-parts/computer-parts/power-supply-psu-140"],
    "refrigeracion": ["/pc-parts/computer-parts/cooling/cpu-cooling-670"],
}
POR_PAGINA = 20
RE_TOTAL = re.compile(r"([\d,]+)\s*Products", re.I)
RE_PAGINA = re.compile(r"[?&]page=(\d+)")
RE_AHORRO = re.compile(r"Save\s*\$\s*([\d,]+(?:\.\d+)?)", re.I)


class PlataformaUmart(Tienda):
    pais = "AU"
    moneda = "AUD"
    max_paginas = 20
    servidor = "umart-msy"
    pausa = (6.0, 9.0)   # comparten servidor y frenan si se les pide rápido

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if cls.web:
            cls.categorias = {c: [cls.web + r for r in rs] for c, rs in RUTAS.items()}

    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        try:
            texto = self.cliente.get(url).text
        except httpx.HTTPStatusError as e:
            # Cuando reciben muchos pedidos, Umart y MSY contestan "404 Not Found" a TODO
            # (incluso a la portada). Lo tratamos como un freno, no como una página inexistente.
            if e.response.status_code == 404 and "Not Found" in e.response.text[:400]:
                raise Bloqueado(f"{self.nombre} contesta 404 a todo (freno por exceso de pedidos)") from None
            raise
        return self.parsear(texto, url, categoria)

    def parsear(self, texto: str, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        arbol = self.html(texto)
        ofertas: list[Oferta] = []
        for li in arbol.css("li.goods_info"):
            a = li.css_first(".goods_name a")
            p = li.css_first("[itemprop=price]")
            if not a or not p:
                continue
            precio = precio_au(p.attributes.get("content") or p.text())
            if not precio:
                continue
            titulo = (a.attributes.get("title") or a.text()).strip()
            disp = li.css_first("link[itemprop=availability]")
            disp = disp.attributes.get("href", "") if disp else ""
            stock_txt = li.css_first(".goods_stock")
            stock_txt = stock_txt.text(strip=True) if stock_txt else ""
            # lista solo lo publicado: salvo que diga lo contrario (Out of stock, Pre-order, Discontinued…), hay
            stock = estado_schema(disp) is not False and estado_texto(stock_txt) is not False
            ahorro = li.css_first(".discount")
            m = RE_AHORRO.search(ahorro.text()) if ahorro else None
            lista = round(precio + float(m.group(1).replace(",", "")), 2) if m else None
            item = li.css_first(".goods-item")
            ofertas.append(self.oferta(
                categoria=categoria, titulo=titulo, url=urljoin(self.web, a.attributes["href"]),
                precio=precio, precio_lista=lista, stock=stock,
                sku=item.attributes.get("data-id") if item else None,
                datos={"estado_stock": stock_txt} if stock_txt else {}))
        return ofertas, self._siguiente(texto, url)

    @staticmethod
    def _siguiente(texto: str, url: str) -> str | None:
        m = RE_TOTAL.search(texto)
        if not m:
            return None
        paginas = math.ceil(int(m.group(1).replace(",", "")) / POR_PAGINA)
        actual = int(RE_PAGINA.search(url).group(1)) if RE_PAGINA.search(url) else 1
        if actual >= paginas:
            return None
        base = RE_PAGINA.sub("", url).rstrip("?&")
        return f"{base}?page={actual + 1}"


@registrar
class Umart(PlataformaUmart):
    id = "umart"
    nombre = "Umart"
    web = "https://www.umart.com.au"


@registrar
class MSY(PlataformaUmart):
    id = "msy"
    nombre = "MSY"
    web = "https://www.msy.com.au"
