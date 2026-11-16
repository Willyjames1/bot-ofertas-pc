"""staticICE: comparador de precios australiano. Sirve para cubrir las tiendas que no se
dejan leer directo (PC Case Gear y Scorptec piden verificación anti-bots, Centre Com usa AWS WAF)
y muchas más (PLE, JW, I-Tech, Computer Alliance, MegaBuy, Austin, CPL...).

No tiene categorías: se busca por modelo. Las búsquedas salen de config.yaml:
  - placas: cada chip de "placas.chips"
  - cpu:    los Ryzen de perf.yaml (gama.cpu) que cumplen "cpu.nucleos_min"
  - ram:    "DDR5 <capacidad>GB" por cada capacidad de "ram.capacidad_gb"
Ordena de menor a mayor precio y dice el rango de la página siguiente, así que cortamos
apenas se pasa del tope. Cada fila trae el link real a la tienda (va dentro del parámetro
newurl= del redirect; no lo visitamos: robots.txt lo prohíbe y no hace falta).

Las tiendas que ya leemos directo (Umart, MSY...) se saltean para no duplicarlas."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, quote, urlsplit

from .. import alertas, config
from ..modelos import Oferta
from .base import TIENDAS, Tienda, precio_au, registrar

log = logging.getLogger("bot.fuentes")
BASE = "https://www.staticice.com.au/cgi-bin/search.cgi"
POR_PAGINA = 50
PISO = {"placas": 400, "cpu": 150, "ram": 150}   # saltea accesorios baratos (water blocks, cables)
MAX_PAGINAS = {"placas": 3, "cpu": 1, "ram": 2}
UMBRAL_DESFASADA = 0.75                           # ver StaticICE.sin_desfasadas
DIAS_VIEJO = 3                                    # filas sin actualizar hace más de 3 días: no se usan
RE_FILA = re.compile(
    r'<tr valign="top"><td align="left"><a [^>]*href="/cgi-bin/redirect\.cgi\?([^"]+)"[^>]*>\$([\d,\.]+)</a>'
    r'.*?<td valign="bottom">(.*?)<br>.*?<font color="#0080CC">([^<]+)</font>.*?updated: (\d{2}-\d{2}-\d{4})',
    re.S)
RE_PAGINAS = re.compile(r'href="/cgi-bin/search\.cgi\?[^"]*start=(\d+)[^"]*"\s+title="See results \d+ to \d+ '
                        r'\(\$([\d,\.]+) to')
RE_START = re.compile(r"&start=(\d+)")
RE_TAGS = re.compile(r"<[^>]+>")


def _slug(nombre: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", nombre.lower())


def _dominio(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def busquedas(cfg: dict, gama_cpu: list[str]) -> dict[str, list[str]]:
    q: dict[str, list[str]] = {}
    if cfg.get("placas", {}).get("activo", True):
        q["placas"] = list(cfg["placas"].get("chips", []))
    c = cfg.get("cpu", {})
    if c.get("activo", True):
        minimo = c.get("nucleos_min", 0)
        nucleos = {"5": 6, "7": 8, "9": 12}   # Ryzen 5/7/9: núcleos mínimos de cada línea
        terminos = [m.split()[-1] for m in gama_cpu
                    if m.startswith("Ryzen") and nucleos.get(m.split()[1], 0) >= minimo]
        terminos += [m.split()[-1] for m in c.get("objetivos", {})]
        q["cpu"] = list(dict.fromkeys(terminos))
    r = cfg.get("ram", {})
    if r.get("activo", True):
        q["ram"] = [f"DDR5 {gb}GB" for gb in r.get("capacidad_gb", [32, 64])]
    return q


def tope(cfg: dict, categoria: str) -> float | None:
    return (cfg.get(categoria, {}).get("precio_max") or {}).get("AUD")


@registrar
class StaticICE(Tienda):
    id = "staticice"
    nombre = "staticICE"
    pais = "AU"
    moneda = "AUD"
    web = "https://www.staticice.com.au"
    pausa = (4.0, 6.0)
    categorias = {"placas": [], "cpu": [], "ram": []}   # se completan al crear la tienda

    def __init__(self, cliente=None, cfg: dict | None = None, hoy: date | None = None):
        super().__init__(cliente)
        self.cfg = cfg if cfg is not None else config.cargar()
        self.hoy = hoy or date.today()
        from ..perf import _crudo
        gama = (_crudo().get("gama") or {}).get("cpu", [])
        self.categorias = {cat: [self.url(t, cat) for t in terminos]
                           for cat, terminos in busquedas(self.cfg, gama).items()}
        propias = {_dominio(c.web) for k, c in TIENDAS.items() if k != self.id and c.pais == "AU" and c.web}
        self.saltear = propias
        self.nombres: dict[str, str] = {}
        self.desfasadas: dict[str, list[str]] = {}

    def leer(self, categoria: str) -> list[Oferta]:
        return self.sin_desfasadas(super().leer(categoria), categoria)

    def sin_desfasadas(self, ofertas: list[Oferta], categoria: str) -> list[Oferta]:
        """Algunas tiendas le pasan a staticICE precios viejos (en RAM, CPL y Austin figuran a un
        tercio de lo que cobra el resto desde la suba de la memoria). Si la mitad o más de los
        productos de una tienda están por debajo del 75% de lo que cobran las DEMÁS tiendas por el
        mismo modelo, esa tienda no se usa en esta categoría."""
        from statistics import median

        from ..normalizar import normalizar
        por_modelo: dict[str, dict[str, list[float]]] = {}
        for o in ofertas:
            normalizar(o)
            if o.modelo and not o.descartada:
                # RAM: se compara por capacidad y módulos ("DDR5 64GB (2x32)"), sin velocidad ni CL
                clave = o.modelo.split(")")[0] + ")" if categoria == "ram" else o.modelo
                por_modelo.setdefault(clave, {}).setdefault(o.tienda, []).append(o.precio)
        ratios: dict[str, list[float]] = {}
        for modelo, tiendas in por_modelo.items():
            for t, precios in tiendas.items():
                otras = [median(p) for t2, p in tiendas.items() if t2 != t]
                if len(otras) >= 2:   # hace falta comparar contra al menos 2 tiendas más
                    ref = median(otras)
                    ratios.setdefault(t, []).extend(p / ref for p in precios)
        self.desfasadas[categoria] = sorted(
            t for t, r in ratios.items() if len(r) >= 3 and median(r) < UMBRAL_DESFASADA)
        for t in self.desfasadas[categoria]:
            log.warning("staticICE/%s: %s tiene precios muy por debajo del resto (mediana %.0f%%), "
                        "parecen desactualizados: la salteo", categoria, self.nombres.get(t, t),
                        median(ratios[t]) * 100)
        return [o for o in ofertas if o.tienda not in self.desfasadas[categoria]]

    @staticmethod
    def url(termino: str, categoria: str) -> str:
        return f"{BASE}?q={quote(termino.lower())}&price-min={PISO.get(categoria, 0)}&links={POR_PAGINA}&showadres=1"

    def leer_pagina(self, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        return self.parsear(self.cliente.get(url).text, url, categoria)

    def parsear(self, texto: str, url: str, categoria: str) -> tuple[list[Oferta], str | None]:
        termino = parse_qs(urlsplit(url).query).get("q", [""])[0]
        ofertas: list[Oferta] = []
        for qs, precio, titulo, tienda, actualizado in RE_FILA.findall(texto):
            destino = parse_qs(qs.replace("&amp;", "&")).get("newurl", [""])[0]
            # algunos links pasan por un rastreador de afiliados (…?Url=https://tienda…): lo sacamos
            real = parse_qs(urlsplit(destino).query).get("Url") or parse_qs(urlsplit(destino).query).get("url")
            if real and real[0].startswith("http"):
                destino = real[0]
            if not destino or _dominio(destino) in self.saltear:
                continue
            fecha = datetime.strptime(actualizado, "%d-%m-%Y").date()
            if self.hoy - fecha > timedelta(days=DIAS_VIEJO):
                continue
            tienda = tienda.strip()
            tid = _slug(tienda)
            self.nombres[tid] = tienda
            ofertas.append(Oferta(
                tienda=tid, pais="AU", moneda="AUD", categoria=categoria,
                titulo=RE_TAGS.sub("", titulo).strip(), url=destino, precio=precio_au(precio) or 0,
                stock=None, datos={"via": "staticICE", "actualizado": fecha.isoformat(), "busqueda": termino}))
        ofertas = [o for o in ofertas if o.precio]
        alertas.NOMBRE_TIENDA.update(self.nombres)
        # ¿seguimos a la página siguiente? Solo si el rango de precios que anuncia no se pasa del tope.
        actual = int(RE_START.search(url).group(1)) if RE_START.search(url) else 1
        if actual // POR_PAGINA + 1 >= MAX_PAGINAS.get(categoria, 1):
            return ofertas, None
        paginas = {int(s): precio_au(p) or 0 for s, p in RE_PAGINAS.findall(texto)}
        desde = paginas.get(actual + POR_PAGINA)
        limite = tope(self.cfg, categoria)
        if desde is None or (limite is not None and desde > limite):
            return ofertas, None
        return ofertas, f"{RE_START.sub('', url)}&start={actual + POR_PAGINA}"
