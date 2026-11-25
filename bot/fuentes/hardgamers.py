"""HardGamers: comparador argentino que junta los precios de ~50 tiendas (FullH4rd, SCP Hardstore,
SilverHard, XT-PC, Max Tecno...). Cada producto se guarda con la TIENDA REAL que lo vende, no
como "HardGamers"; las tiendas que ya leemos directo (Venex, Gezatek, Mexx, Maximus, Compra
Gamer, Katech) se saltean para no duplicar precios.

robots.txt permite las páginas de categoría (/search?category=<slug>&page=N), pide 5 s entre
pedidos (Crawl-delay) y prohíbe ordenar y filtrar por precio. Los listados ya vienen de menor a
mayor precio, así que no leemos todas las páginas (placas son 36, RAM 68): con dos búsquedas
binarias encontramos las páginas donde empieza y termina la FRANJA de precios que nos interesa y
leemos solo esas. Además se lee UNA categoría por corrida, rotando (lo maneja corrida.py con
`una_categoria_por_corrida`). El precio que muestra es el de contado/transferencia de cada tienda.

Ojo: Katech y Compra Gamer NO están en HardGamers."""
from __future__ import annotations

import logging
import re
from math import ceil

from ..modelos import Oferta
from ..stock import estado_schema
from .base import TIENDAS, Tienda, registrar

log = logging.getLogger("bot.fuentes")
BASE = "https://www.hardgamers.com.ar"
POR_PAGINA = 54
SLUG = {"placas": "placas-de-video", "cpu": "microprocesadores", "ram": "memorias-ram", "pcs": "pcs-armadas",
        # Fase 2 (se leen cada fase2_cada_horas): lo que te falta comprar y solo se busca en 🇦🇷
        "mothers": "motherboards", "ssd": "almacenamiento", "fuentes": "fuentes", "refrigeracion": "refrigeracion",
        "gabinetes": "gabinetes", "teclados": "teclados", "mouse": "mouse"}
# franja de precios que nos interesa: abajo quedan DDR4, placas de entrada y CPUs viejos; arriba,
# placas que pasan el precio_max y servidores
FRANJA = {"placas": (900_000, 3_500_000), "cpu": (300_000, 2_000_000), "ram": (300_000, 3_000_000),
          "pcs": (3_000_000, 15_000_000), "mothers": (250_000, 1_500_000), "ssd": (150_000, 1_000_000),
          "fuentes": (120_000, 900_000), "refrigeracion": (120_000, 900_000), "gabinetes": (80_000, 900_000),
          "teclados": (40_000, 600_000), "mouse": (25_000, 400_000)}
MAX_PAGINAS_LEIDAS = 30          # tope de seguridad por categoría y corrida
RE_TOTAL = re.compile(r"var total = (\d+);")
RE_ESPACIOS = re.compile(r"\s+")


def _clave(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", texto.lower())


@registrar
class HardGamers(Tienda):
    id = "hardgamers"
    nombre = "HardGamers"
    pais = "AR"
    moneda = "ARS"
    web = BASE
    pausa = (5.0, 7.0)    # robots.txt: Crawl-delay 5
    timeout = 40.0
    categorias = {cat: [f"{BASE}/search?category={slug}"] for cat, slug in SLUG.items()}
    una_categoria_por_corrida = True
    tambien: set[str] = set()     # tiendas argentinas caídas: se leen desde HardGamers

    def __init__(self, cliente=None):
        super().__init__(cliente)
        # las tiendas que leemos directo se saltean, salvo las que están caídas o nos bloquearon
        # (corrida.py completa 'tambien': ej. Venex, que contesta 403 desde GitHub Actions)
        self.saltear = {_clave(k) for k, c in TIENDAS.items()
                        if c.pais == "AR" and k != self.id and k not in type(self).tambien}
        self.nombres: dict[str, str] = {}
        self.paginas_leidas = 0
        self._minimo: float | None = None

    # ------------------------------------------------------------------ lectura
    def leer(self, categoria: str) -> list[Oferta]:
        base = self.categorias[categoria][0]
        cache: dict[int, tuple] = {}

        def pagina(n: int):
            """(ofertas, más caro, total, más barato) de la página n."""
            if n not in cache:
                url = base if n == 1 else f"{base}&page={n}"
                ofertas, maximo, total = self.parsear(self.cliente.get(url).text, categoria)
                self.paginas_leidas += 1
                cache[n] = (ofertas, maximo, total, self._minimo)
            return cache[n]

        _, _, total, _ = pagina(1)
        n_pags = max(1, ceil((total or POR_PAGINA) / POR_PAGINA))
        piso, techo = FRANJA.get(categoria, (0, float("inf")))

        def primera(cumple) -> int:   # primera página que cumple (las páginas van de menor a mayor precio)
            lo, hi = 1, n_pags + 1
            while lo < hi:
                mid = (lo + hi) // 2
                if cumple(pagina(mid)):
                    hi = mid
                else:
                    lo = mid + 1
            return lo

        inicio = primera(lambda pg: pg[1] is None or pg[1] >= piso)          # el más caro ya llega al piso
        pasada = primera(lambda pg: pg[3] is not None and pg[3] > techo)     # el más barato ya pasa el techo
        fin = min(pasada - 1, n_pags, inicio + MAX_PAGINAS_LEIDAS - 1)
        vistas: dict[str, Oferta] = {}
        for n in range(inicio, fin + 1):
            for o in pagina(n)[0]:
                if piso * 0.9 <= o.precio <= techo * 1.1:
                    vistas.setdefault(o.url, o)
        lo = inicio
        log.info("hardgamers/%s: páginas %d a %d de %d (%d pedidos), %d productos",
                 categoria, lo, fin, n_pags, len(cache), len(vistas))  # noqa: E501
        from .. import alertas
        alertas.NOMBRE_TIENDA.update(self.nombres)
        return list(vistas.values())

    def leer_pagina(self, url: str, categoria: str):  # no se usa: leer() maneja las páginas
        ofertas, _, _ = self.parsear(self.cliente.get(url).text, categoria)
        return ofertas, None

    # ------------------------------------------------------------------ parseo
    def parsear(self, texto: str, categoria: str) -> tuple[list[Oferta], float | None, int | None]:
        """(ofertas, precio más caro de la grilla ordenada, total de productos de la categoría)."""
        # Lo que viene después de "Ofertas Destacadas" son productos patrocinados de cualquier
        # categoría y sin orden: no se usan.
        corte = texto.find('<div class="Offers">')
        grilla = texto if corte < 0 else texto[:corte]
        arbol = self.html(grilla)
        ofertas: list[Oferta] = []
        maximo: float | None = None
        self._minimo = None
        for art in arbol.css("article.One-Bit-Product"):
            a = art.css_first('a[href^="/product/"]')
            nombre = art.css_first("p.product-name")
            precio = art.css_first('span[itemprop="price"]')
            tienda = art.css_first("p.store")
            if not (a and nombre and precio and tienda):
                continue
            try:
                valor = float(precio.attributes.get("content") or 0)
            except ValueError:
                continue
            if not valor:
                continue
            maximo = max(maximo or 0, valor)
            self._minimo = valor if self._minimo is None else min(self._minimo, valor)
            pid = a.attributes["href"].rsplit("/", 1)[-1]           # "fullh4rd:dvdwfg"
            clave_tienda = _clave(pid.split(":", 1)[0])
            if clave_tienda in self.saltear:
                continue
            cond = art.css_first('link[itemprop="itemCondition"]')
            if cond and "NewCondition" not in (cond.attributes.get("href") or ""):
                continue
            disp = art.css_first('link[itemprop="availability"]')
            disp = (disp.attributes.get("href") or "") if disp else ""
            nombre_tienda = RE_ESPACIOS.sub(" ", tienda.text()).strip()
            tid = f"hg_{clave_tienda}"
            self.nombres[tid] = nombre_tienda
            ofertas.append(Oferta(
                tienda=tid, pais="AR", moneda="ARS", categoria=categoria,
                titulo=RE_ESPACIOS.sub(" ", nombre.text()).strip(), url=f"{BASE}/product/{pid}",
                precio=valor, tipo_precio="contado",
                stock=estado_schema(disp),
                sku=pid, datos={"via": "HardGamers"}))
        m = RE_TOTAL.search(texto)
        return ofertas, maximo, int(m.group(1)) if m else None
