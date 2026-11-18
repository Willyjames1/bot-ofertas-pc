"""Stock: qué cuenta como "hay", "no hay" y "sin confirmar", en un solo lugar.

  estado_texto("Agotado")            → False     (lo que dicen los listados: etiquetas cortas)
  estado_schema("schema.org/PreOrder") → False
  estado_pagina(html)                → (True/False/None, motivo)   (ficha de producto: solo datos estructurados)
  Verificador().verificar(url)       → mira la ficha en la tienda real (Shopify: /products/<handle>.js)
  EstadoStock(db).de(fila)           → Estado("si" | "no" | "?", motivo)   para exportar, avisar y comparar

En la ficha completa NO se buscan palabras sueltas: una página trae "Sold out" o "In stock" en
banners y productos relacionados (CCPU, por ejemplo), así que solo valen schema.org, la meta
product:availability o la API de Shopify. Si no hay nada de eso, queda "sin confirmar".
"""
from __future__ import annotations

import hashlib
import html as html_mod
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx

from .red import Bloqueado, Cliente, ProhibidoPorRobots

log = logging.getLogger("bot.stock")

# ------------------------------------------------------------------ textos y schema.org

SIN_STOCK = re.compile(
    r"(?<![A-Z0-9])(AGOTAD[OA]S?|SIN STOCK|SIN EXISTENCIAS?|0 UNIDADES|CONSULTAR|CONSULTE|PRE-? ?VENTA|"
    r"SOLD ?OUT|OUT[- ]OF[- ]STOCK|NO LONGER AVAILABLE|DISCONTINUED|DISCONTINUAD[OA]|PRE-? ?ORDERS?|"
    r"BACK-? ?ORDERS?|NO DISPONIBLE|NOT AVAILABLE|UNAVAILABLE|ARRIVING SOON|COMING SOON|PROXIMAMENTE)(?![A-Z0-9])")
CON_STOCK = re.compile(
    r"(?<![A-Z0-9])(EN STOCK|IN STOCK|HAY STOCK|CON STOCK|STOCK DISPONIBLE|DISPONIBLE|AVAILABLE|INSTOCK|IN_STOCK|"
    r"LIMITED STOCK|LOW STOCK|ULTIMAS? UNIDAD(?:ES)?|POCAS UNIDADES|ENTREGA INMEDIATA)(?![A-Z0-9])")
SCHEMA_SI = {"instock", "limitedavailability", "instoreonly", "onlineonly", "in stock", "in_stock", "available"}
SCHEMA_NO = {"outofstock", "soldout", "discontinued", "preorder", "presale", "backorder", "madetoorder",
             "out of stock", "out_of_stock", "oos", "preorder", "pending", "unavailable"}


def _limpio(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def estado_texto(texto: str | None) -> bool | None:
    """Etiqueta de un listado ("Sin stock", "Pre-order", "Disponible") → False / True / None."""
    t = _limpio(texto or "")
    if not t.strip():
        return None
    if SIN_STOCK.search(t):
        return False
    if CON_STOCK.search(t):
        return True
    return None


def estado_etiqueta(texto: str | None) -> bool | None:
    """Etiqueta de stock de un listado AR ("Stock: 3", "En stock", "Sin stock", "Consultar"):
    como estado_texto, pero "STOCK" a secas (sin un "sin", "0 unidades", etc.) cuenta como que hay."""
    e = estado_texto(texto)
    if e is None and "STOCK" in _limpio(texto or ""):
        return True
    return e


def estado_schema(valor: str | None) -> bool | None:
    """'https://schema.org/InStock', 'OutOfStock', 'in stock' (meta), 'PreOrder'… → True / False / None."""
    v = (valor or "").strip().rstrip("/").rsplit("/", 1)[-1].lower()
    if not v:
        return None
    if v in SCHEMA_NO or v.replace(" ", "") in SCHEMA_NO:
        return False
    if v in SCHEMA_SI or v.replace(" ", "") in SCHEMA_SI:
        return True
    return estado_texto(v)


# ------------------------------------------------------------------ ficha de producto

RE_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
RE_ITEMPROP = re.compile(r'<[^>]+itemprop=["\']availability["\'][^>]*>', re.I)
RE_ATRIB = re.compile(r'(?:href|content)=["\']([^"\']+)["\']', re.I)
RE_META = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:product|og):availability["\'][^>]*>', re.I)


def _nodos(x):
    if isinstance(x, list):
        for y in x:
            yield from _nodos(y)
    elif isinstance(x, dict):
        yield x
        for k in ("@graph", "mainEntity", "itemListElement"):
            if k in x:
                yield from _nodos(x[k])


def _tipos(n: dict) -> set[str]:
    t = n.get("@type")
    return {str(x) for x in (t if isinstance(t, list) else [t])}


def _disponibilidades(producto: dict) -> list[str]:
    salida = []
    pendientes = [producto.get("offers")] + [v.get("offers") for v in (producto.get("hasVariant") or [])
                                              if isinstance(v, dict)]
    while pendientes:
        of = pendientes.pop()
        if isinstance(of, list):
            pendientes += of
        elif isinstance(of, dict):
            if of.get("availability"):
                salida.append(str(of["availability"]))
            if of.get("offers"):
                pendientes.append(of["offers"])     # AggregateOffer
    return salida


def estado_pagina(texto: str) -> tuple[bool | None, str]:
    """El stock del producto principal de la ficha, solo de datos estructurados."""
    for bloque in RE_LD.findall(texto):
        try:
            datos = json.loads(html_mod.unescape(bloque.strip()), strict=False)
        except ValueError:
            continue
        for n in _nodos(datos):
            if _tipos(n) & {"Product", "ProductGroup", "IndividualProduct"}:
                estados = [estado_schema(a) for a in _disponibilidades(n)]
                if True in estados:
                    return True, "la tienda dice que hay stock"
                if False in estados:
                    return False, "la tienda dice sin stock"
                break       # el primer Product es el de la página; los demás suelen ser relacionados
    if m := RE_ITEMPROP.search(texto):
        if (a := RE_ATRIB.search(m.group(0))) and (e := estado_schema(a.group(1))) is not None:
            return e, "la tienda dice que hay stock" if e else "la tienda dice sin stock"
    if m := RE_META.search(texto):
        c = re.search(r'content=["\']([^"\']+)["\']', m.group(0), re.I)
        if c and (e := estado_schema(c.group(1))) is not None:
            return e, "la tienda dice que hay stock" if e else "la tienda dice sin stock"
    return None, "la página de la tienda no informa stock"


def estado_shopify(datos: dict, variante: str | None) -> bool | None:
    """/products/<handle>.js de Shopify: 'available' de la variante (o del producto)."""
    variantes = datos.get("variants") or []
    if variante:
        for v in variantes:
            if str(v.get("id")) == str(variante):
                return bool(v.get("available"))
    if "available" in datos:
        return bool(datos["available"])
    return any(v.get("available") for v in variantes) if variantes else None


RE_LINK_HG = re.compile(r'href="(https?://[^"]*utm_source=hardgamers[^"]*)"')


def link_tienda_hg(texto: str) -> str | None:
    """En la ficha de HardGamers, el link al producto en la tienda real (no el del logo ni imágenes)."""
    for crudo in RE_LINK_HG.findall(texto):
        url = html_mod.unescape(crudo)
        if "product_detail_logo" in url or re.search(r"\.(png|jpe?g|webp|gif|svg)(\?|$)", url, re.I):
            continue
        return url
    return None


def sin_rastreo(url: str) -> str:
    s = urlsplit(url)
    q = "&".join(p for p in s.query.split("&") if p and not p.startswith(("utm_", "currency=")))
    return urlunsplit((s.scheme, s.netloc, s.path, q, ""))


def clave_url(url: str) -> str:
    """Id corto y estable de un producto (para el botón "❌ Sin stock" de Telegram)."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ verificar en la tienda real

@dataclass
class Verificacion:
    disponible: bool | None
    motivo: str
    destino: str | None = None      # la URL en la tienda real (HardGamers → tienda)


RE_SHOPIFY = re.compile(r"/products/[^/]+/?$")    # /products/<handle> (PCCG usa /products/<id>/<nombre>)


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


class Verificador:
    """Mira el stock en la página de la tienda real. Un pedido por producto (dos si viene de
    HardGamers: su ficha tiene el link a la tienda), con pausas por sitio, robots.txt y sin
    reintentos: si una tienda frena (403, 429, Cloudflare), se la deja de consultar un día."""

    def __init__(self, db=None, cliente: Cliente | None = None, tope_por_host: int = 6, horas_bloqueo: int = 24):
        self.db = db
        self.cli = cliente or Cliente(pausa=(2.0, 3.0), timeout=15, reintentos=1)
        self.tope_por_host = tope_por_host
        self.horas_bloqueo = horas_bloqueo
        self.pedidos_host: dict[str, int] = {}
        self.sin_datos: dict[str, int] = {}
        self.pedidos = 0
        self._lock = threading.Lock()

    def cerrar(self):
        self.cli.cerrar()

    # bloqueos guardados en la base: no volver a molestar a una tienda que frenó
    def bloqueada(self, host: str) -> str | None:
        if not self.db:
            return None
        with self._lock:
            v = self.db.get(f"verif_bloqueo:{host}")
        if not v:
            return None
        hasta, motivo = v.split("|", 1)
        return motivo if datetime.fromisoformat(hasta) > datetime.now(timezone.utc) else None

    def _bloquear(self, host: str, motivo: str):
        if self.db:
            hasta = datetime.now(timezone.utc) + timedelta(hours=self.horas_bloqueo)
            with self._lock:
                self.db.set(f"verif_bloqueo:{host}", f"{hasta.isoformat(timespec='seconds')}|{motivo}")

    def _get(self, url: str) -> httpx.Response | Verificacion:
        host = _host(url)
        if motivo := self.bloqueada(host):
            return Verificacion(None, motivo)
        if self.pedidos_host.get(host, 0) >= self.tope_por_host:
            return Verificacion(None, "sin verificar todavía (tope de pedidos por corrida)")
        with self._lock:
            self.pedidos_host[host] = self.pedidos_host.get(host, 0) + 1
            self.pedidos += 1
        try:
            return self.cli.get(url)
        except Bloqueado as e:
            motivo = "la tienda no deja verificar el stock" + (" (429)" if "429" in str(e) else "")
            self._bloquear(host, motivo)
            return Verificacion(None, motivo)
        except ProhibidoPorRobots:
            return Verificacion(None, "robots.txt de la tienda no deja verificar")
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (404, 410):
                return Verificacion(False, "la página del producto ya no existe")
            if code in (401, 403, 429):
                self._bloquear(host, f"la tienda no deja verificar el stock ({code})")
            return Verificacion(None, f"la tienda contestó {code}")
        except Exception as e:  # noqa: BLE001 — red, certificados, timeouts
            return Verificacion(None, f"no pude abrir la tienda ({type(e).__name__})")

    def verificar(self, url: str) -> Verificacion:
        s = urlsplit(url)
        if _host(url).endswith("hardgamers.com.ar") and s.path.startswith("/product/"):
            r = self._get(url)
            if isinstance(r, Verificacion):
                return r
            destino = link_tienda_hg(r.text)
            if not destino:
                return Verificacion(None, "HardGamers no muestra el link a la tienda")
            v = self.verificar(destino)
            return Verificacion(v.disponible, v.motivo, sin_rastreo(destino))
        if RE_SHOPIFY.search(s.path):      # Shopify (Mwave, JB Hi-Fi…): la API pública del producto
            variante = (parse_qs(s.query).get("variant") or [None])[0]
            r = self._get(urlunsplit((s.scheme, s.netloc, s.path.rstrip("/") + ".js", "", "")))
            if isinstance(r, httpx.Response) and r.text.lstrip().startswith("{"):   # viene como javascript
                try:
                    e = estado_shopify(r.json(), variante)
                except ValueError:
                    e = None
                if e is not None:
                    return Verificacion(e, "la tienda dice que hay stock" if e else "la tienda dice sin stock (Sold out)")
            elif isinstance(r, Verificacion) and r.disponible is False:
                return r
            elif isinstance(r, Verificacion) and self.bloqueada(_host(url)):
                return r
        r = self._get(url)
        if isinstance(r, Verificacion):
            return r
        e, motivo = estado_pagina(r.text)
        if e is None:
            # dos fichas seguidas sin datos de stock: esa tienda no los publica, no la sigo consultando
            host = _host(url)
            with self._lock:
                self.sin_datos[host] = self.sin_datos.get(host, 0) + 1
                cuantas = self.sin_datos[host]
            if cuantas >= 2:
                self._bloquear(host, "la tienda no informa stock en su página")
        return Verificacion(e, motivo)

    def verificar_varios(self, urls: list[str]) -> dict[str, Verificacion]:
        """En paralelo entre tiendas distintas, en serie (con pausas) dentro de cada una."""
        por_host: dict[str, list[str]] = {}
        for u in urls:
            por_host.setdefault(_host(u), []).append(u)
        salida: dict[str, Verificacion] = {}

        def hacer(lista):
            return [(u, self.verificar(u)) for u in lista]

        with ThreadPoolExecutor(max_workers=max(1, min(8, len(por_host)))) as ex:
            for res in ex.map(hacer, por_host.values()):
                salida.update(res)
        return salida


# ------------------------------------------------------------------ estado de cada publicación

@dataclass
class Estado:
    nivel: str           # "si" | "no" | "?"
    motivo: str = ""

    @property
    def confirmado(self) -> bool:
        return self.nivel == "si"


CADA_TURNO = {"placas", "cpu", "ram", "pcs"}     # las de la Fase 1 (las de la Fase 2 se leen cada 6 h)
COMPARADORES = {"staticice":"staticICE no informa stock", "hardgamers": "HardGamers: sin verificar en la tienda"}


def fuente_de(fila) -> str:
    """El adaptador que trajo la publicación: el comparador si vino de uno, si no la tienda."""
    via = (json.loads(fila["datos"] or "{}") if isinstance(fila["datos"], str) else (fila["datos"] or {})).get("via")
    if via == "staticICE":
        return "staticice"
    if via == "HardGamers" or fila["tienda"].startswith("hg_"):
        return "hardgamers"
    if fila["tienda"].startswith("ebay_"):
        return "ebay"
    return fila["tienda"]


def _fecha(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(v)


class EstadoStock:
    """Decide, para cada publicación, si mostrarla como con stock, sin stock o sin confirmar:

      1. la tienda dice que no hay (stock=0)                                   → no
      2. lo marcaste "❌ Sin stock" en Telegram (hasta que la tienda lo vuelva a mostrar)  → no
      3. no apareció en la última pasada de su fuente (por categoría)           → no
      4. la última pasada buena es de hace más de `horas_reciente`              → ?  "no pude leer X hace N h"
      5. se verificó en la tienda real hace menos de `horas_verificacion` (y no cambió el precio) → lo que dijo
      6. vino de un comparador (staticICE, HardGamers) o la tienda no informa stock → ?
      7. si no                                                                  → si
    """

    def __init__(self, db, ahora: datetime | None = None, horas_reciente: float = 8, horas_verificacion: float = 6):
        self.ahora = ahora or datetime.now(timezone.utc)
        self.horas_reciente = horas_reciente
        self.horas_verificacion = horas_verificacion
        self.pasadas = {(r["fuente"], r["categoria"]): _fecha(r["ts"]) for r in db.c.execute("SELECT * FROM pasadas")}
        self.verif = {r["url"]: dict(r) for r in db.c.execute("SELECT * FROM verificaciones")}
        self.ocultos = {r["url"]: dict(r) for r in db.c.execute("SELECT * FROM ocultos WHERE levantado IS NULL")}
        # Respaldo mientras no haya pasadas registradas (bases de antes de esta tabla): la última
        # lectura sin errores de la tienda, solo para las categorías que se leen en cada turno
        self.ultima_ok = {r["tienda"]: _fecha(r["ts"]) for r in db.c.execute(
            "SELECT tienda, MAX(ts) ts FROM corridas_tienda WHERE ok=1 GROUP BY tienda")}

    def _pasada(self, fuente: str, categoria: str) -> tuple[datetime | None, timedelta]:
        """(cuándo fue la última lectura completa, tolerancia). La de corridas_tienda se anota al
        terminar de leer la tienda (no al empezar), así que tiene más margen."""
        if p := self.pasadas.get((fuente, categoria)):
            return p, timedelta(minutes=2)
        if fuente != "hardgamers" and categoria in CADA_TURNO and (p := self.ultima_ok.get(fuente)):
            return p, timedelta(minutes=30)
        return None, timedelta(0)

    def de(self, fila) -> Estado:
        if fila["url"] in self.ocultos:
            return Estado("no", "lo marcaste sin stock")
        return self.base(fila)

    def base(self, fila) -> Estado:
        if fila["stock"] == 0:
            return Estado("no", "la tienda dice sin stock")
        fuente = fuente_de(fila)
        visto = _fecha(fila["ultima_vez"])
        pasada, margen = self._pasada(fuente, fila["categoria"])
        referencia = pasada or visto
        if pasada and visto < pasada - margen:
            return Estado("no", "ya no aparece en la tienda")
        horas = (self.ahora - referencia).total_seconds() / 3600
        if horas > self.horas_reciente:
            from .alertas import NOMBRE_TIENDA      # (acá, para no importar alertas al cargar el módulo)
            nombre = {"staticice": "staticICE", "hardgamers": "HardGamers", "ebay": "eBay"}.get(
                fuente, NOMBRE_TIENDA.get(fuente, fuente))
            return Estado("?", f"no pude leer {nombre} hace {horas:.0f} h")
        if self.verificacion_al_dia(fila):
            v = self.verif[fila["url"]]
            if v["disponible"] == 1:
                return Estado("si", "verificado en la tienda")
            if v["disponible"] == 0:
                return Estado("no", v["motivo"] or "la tienda dice sin stock")
            return Estado("?", v["motivo"] or "no se pudo verificar")
        if fuente in COMPARADORES:
            return Estado("?", COMPARADORES[fuente])
        if fila["stock"] is None:
            return Estado("?", "la tienda no informa stock en el listado")
        return Estado("si")

    def verificacion_al_dia(self, fila) -> bool:
        v = self.verif.get(fila["url"])
        return bool(v) and (self.ahora - _fecha(v["ts"])).total_seconds() / 3600 <= self.horas_verificacion \
            and (v["precio"] is None or abs(v["precio"] - fila["precio"]) < 0.5)

    def necesita_verificar(self, fila) -> bool:
        """¿Vale la pena mirar la tienda real? (comparadores o stock desconocido, sin verificación al día)."""
        if self.verificacion_al_dia(fila):
            return False
        e = self.base(fila)
        return e.nivel == "?" and not e.motivo.startswith("no pude leer") and (
            fuente_de(fila) in COMPARADORES or fila["stock"] is None)


# ------------------------------------------------------------------ "❌ Sin stock" desde Telegram

def sincronizar_ocultos(db, worker_url: str, secreto: str, http: httpx.Client | None = None) -> int:
    """Trae del Worker los "❌ Sin stock" que tocaste ({clave: fecha}) y los guarda en la base
    (clave = sha1 del link). Devuelve cuántos son nuevos."""
    if not worker_url or not secreto:
        return 0
    cli = http or httpx.Client(timeout=15)
    try:
        r = cli.get(f"{worker_url}/ocultos", headers={"Authorization": f"Bearer {secreto}"})
        r.raise_for_status()
        marcas = r.json().get("ocultos") or {}
    finally:
        if http is None:
            cli.close()
    if not marcas:
        return 0
    por_clave = {clave_url(u): u for (u,) in db.c.execute("SELECT url FROM ofertas")}
    nuevos = 0
    for h, ts in marcas.items():
        if (url := por_clave.get(h)) and db.ocultar(url, h, datetime.fromisoformat(ts)):
            nuevos += 1
    return nuevos
