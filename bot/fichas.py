"""Fichas de producto: se abren solo las de las 5 publicaciones más baratas de cada cosa que te falta
comprar (compras.py), para no hacer cientos de pedidos. Cada una vale 20 h (12 h en Black Friday).

  - HardGamers: el gráfico de precios (un precio por día, hasta 75 días), el "precio más bajo de los
    últimos N días" y el link a la tienda real. Su robots.txt pide 5 s entre pedidos.
  - La tienda (Mexx, Gezatek, Katech y las que vienen por HardGamers): el precio de lista y las cuotas.
    Compra Gamer y Maximus no hace falta abrirlas: el precio de lista viene en el listado y sus cuotas
    son las de sus promociones (ver promos()). Venex y FullH4rd nos bloquean (403): no se piden.

También las promociones bancarias de cada tienda grande, una vez por día.

Si una tienda agrega o aumenta cuotas sin interés (en la ficha o en una promo), queda un Cambio para
que alertas.py avise aunque el precio no haya bajado."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from . import compras, cuotas as C, historial as H
from .config import TZ_AR

log = logging.getLogger("bot.fichas")
POR_ITEM = 5
HG = "www.hardgamers.com.ar"
# tiendas cuyas fichas sí traen cuotas en el HTML (las demás: promos o nada)
CON_FICHA = {"mexx", "gezatek", "katech"}
SIN_PEDIR = {"compragamer", "maximus", "venex", "hg_venex", "hg_fullh4rd"}
HOSTS_BLOQUEADOS = {"fullh4rd.com.ar", "www.fullh4rd.com.ar", "www.venex.com.ar"}
# páginas de promociones (texto) de las tiendas grandes; Compra Gamer las publica en un JSON
PAGINAS_PROMOS = {
    "compragamer": "https://static.compragamer.com/cms/promos/payment_promos.json",
    "maximus": "https://www.maximus.com.ar/",
    "mexx": "https://www.mexx.com.ar/formas-de-pago/",
    "katech": "https://katech.com.ar/medios-de-pago/",
    "gezatek": "https://gezatek.com.ar/",
}
RE_MINIMO = re.compile(r"Precio m[aá]s bajo de los [uú]ltimos (\d+) d[ií]as:\s*\$\s*([\d.]+)", re.I)
RE_CHART = re.compile(r"var chartConfig = (\{.*?\});\s*\n", re.S)
RE_DESTINO = re.compile(r'<a target="_blank" href="([^"]+)" itemprop="url"')


@dataclass
class Cambio:
    """Una tienda agregó o aumentó cuotas sin interés (o una promo nueva)."""
    fila: dict                     # la publicación (tabla ofertas)
    item: compras.Item
    antes: int                     # cuotas sin interés que tenía (0 = ninguna)
    ahora: C.Plan
    lista_antes: float | None
    lista_ahora: float | None
    fecha_antes: str | None
    promo: str | None = None       # el texto de la promo, si vino de una promo de la tienda


def tienda_de(fila: dict) -> str:
    return fila["tienda"]


# ------------------------------------------------------------------ HardGamers

def parsear_ficha_hg(html: str, hoy: date) -> dict:
    """{'minimo', 'minimo_dias', 'historial': [(fecha, precio)], 'destino'} de una ficha de HardGamers."""
    salida: dict = {"minimo": None, "minimo_dias": None, "historial": [], "destino": None}
    if m := RE_MINIMO.search(html):
        salida["minimo_dias"] = int(m.group(1))
        salida["minimo"] = float(m.group(2).replace(".", ""))
    if m := RE_DESTINO.search(html):
        salida["destino"] = m.group(1).replace("&amp;", "&")
    if m := RE_CHART.search(html):
        try:
            cfg = json.loads(m.group(1))
            etiquetas = cfg["data"]["labels"]
            precios = cfg["data"]["datasets"][0]["data"]
        except (ValueError, KeyError, IndexError):
            etiquetas, precios = [], []
        # "06-11", "07-11"…: sin año. El último es hoy (o ayer); hacia atrás, si el mes "sube", es el año anterior
        anio, mes_ant, puntos = hoy.year, None, []
        for et, p in zip(reversed(etiquetas), reversed(precios)):
            try:
                d, mm = (int(x) for x in et.split("-"))
            except ValueError:
                continue
            if mes_ant is not None and mm > mes_ant:
                anio -= 1
            mes_ant = mm
            try:
                f = date(anio, mm, d)
            except ValueError:
                continue
            if f > hoy:   # el primer dato es de "mañana": todavía es el año pasado
                f = date(anio - 1, mm, d)
                anio -= 1
            if p:
                puntos.append((f, float(p)))
        salida["historial"] = sorted(puntos)
    return salida


# ------------------------------------------------------------------ candidatas

def candidatas(db, cfg: dict, ahora: datetime) -> list[tuple[compras.Item, dict]]:
    """Las 5 más baratas (con stock) de cada cosa que te falta, en Argentina."""
    from .comparar import HORAS_OTRO_PAIS
    desde = ahora - timedelta(hours=HORAS_OTRO_PAIS)
    salida, vistas = [], set()
    for it in compras.items(cfg):
        if "AR" not in it.paises:
            continue
        n = 0
        for r in db.vigentes("AR", it.categoria, desde, ahora):
            if n >= POR_ITEM:
                break
            if not it.cumple(r):
                continue
            n += 1
            if r["url"] not in vistas:
                vistas.add(r["url"])
                salida.append((it, r))
    return salida


def candidatas_hg(db, cfg: dict, ahora: datetime, por_item: int = 3) -> list[tuple[compras.Item, dict]]:
    """Las 3 más baratas de HardGamers de cada cosa que te falta (aunque no estén entre las 5 más
    baratas de todas): de sus fichas sale el "precio más bajo de los últimos 75 días"."""
    from .comparar import HORAS_OTRO_PAIS
    desde = ahora - timedelta(hours=HORAS_OTRO_PAIS)
    salida = []
    for it in compras.items(cfg):
        if "AR" not in it.paises:
            continue
        n = 0
        for r in db.vigentes("AR", it.categoria, desde, ahora):
            if n >= por_item:
                break
            if urlsplit(r["url"]).netloc == HG and it.cumple(r):
                n += 1
                salida.append((it, r))
    return salida


def _vieja(db, url: str, ahora: datetime, horas: float) -> bool:
    fila = db.c.execute("SELECT ts FROM fichas WHERE url=?", (url,)).fetchone()
    return fila is None or ahora - datetime.fromisoformat(fila["ts"]) >= timedelta(hours=horas)


def _guardar(db, url: str, ahora: datetime, **campos) -> dict | None:
    """Guarda la ficha; devuelve la anterior (para ver si cambiaron las cuotas)."""
    vieja = db.c.execute("SELECT * FROM fichas WHERE url=?", (url,)).fetchone()
    vieja = dict(vieja) if vieja else None
    nuevo = {"minimo": None, "minimo_dias": None, "lista": None, "planes": None, "destino": None}
    if vieja:
        nuevo.update({k: vieja[k] for k in nuevo})
    nuevo.update({k: v for k, v in campos.items() if v is not None})
    antes = (vieja or {})
    db.c.execute("INSERT OR REPLACE INTO fichas VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (url, ahora.isoformat(), nuevo["minimo"], nuevo["minimo_dias"], nuevo["lista"], nuevo["planes"],
                  nuevo["destino"],
                  antes.get("lista") if "planes" in campos else antes.get("lista_antes"),
                  antes.get("planes") if "planes" in campos else antes.get("planes_antes"),
                  antes.get("ts") if "planes" in campos else antes.get("ts_antes")))
    return vieja


def _max_sin_interes(planes: list[C.Plan]) -> int:
    return max((p.cuotas for p in planes if p.sin_interes), default=0)


def leer_fichas(db, cfg: dict, ahora: datetime, cli_hg, cli, aj: dict) -> list[Cambio]:
    """Abre las fichas que hacen falta (con tope por corrida) y devuelve los cambios de cuotas."""
    horas = 12 if aj.get("black_friday") else 20
    tope_hg = int((cfg.get("cuotas") or {}).get("fichas_hardgamers_por_corrida", 8))
    tope_tiendas = int((cfg.get("cuotas") or {}).get("fichas_tiendas_por_corrida", 10))
    hoy = H.dia_ar(ahora)
    cambios: list[Cambio] = []
    pedidas_hg = pedidas = 0
    por_host: dict[str, int] = {}
    vistas: set[str] = set()
    for it, r in candidatas(db, cfg, ahora) + candidatas_hg(db, cfg, ahora):
        if r["url"] in vistas:
            continue
        vistas.add(r["url"])
        url, tienda = r["url"], r["tienda"]
        ficha_tienda = None   # (url de la tienda) para leer las cuotas
        if urlsplit(url).netloc == HG:
            if _vieja(db, url, ahora, horas) and pedidas_hg < tope_hg:
                pedidas_hg += 1
                try:
                    f = parsear_ficha_hg(cli_hg.get(url).text, hoy)
                except Exception as e:  # noqa: BLE001
                    log.info("No pude abrir la ficha de HardGamers %s: %s", url, type(e).__name__)
                    continue
                H.guardar_historial_hg(db, url, f["historial"])
                _guardar(db, url, ahora, minimo=f["minimo"], minimo_dias=f["minimo_dias"], destino=f["destino"])
            fila = db.c.execute("SELECT destino FROM fichas WHERE url=?", (url,)).fetchone()
            ficha_tienda = fila["destino"] if fila and fila["destino"] else None
        elif tienda in CON_FICHA:
            ficha_tienda = url
        if not ficha_tienda or tienda in SIN_PEDIR:
            continue
        host = urlsplit(ficha_tienda).netloc
        if host in HOSTS_BLOQUEADOS or por_host.get(host, 0) >= 3 or pedidas >= tope_tiendas:
            continue
        # la ficha de cuotas se guarda con el link de la publicación (el de HardGamers si vino de ahí)
        clave_cuotas = url + "#cuotas" if ficha_tienda != url else url
        if not _vieja(db, clave_cuotas, ahora, horas):
            continue
        pedidas += 1
        por_host[host] = por_host.get(host, 0) + 1
        try:
            texto = C.texto_de_html(cli.get(ficha_tienda).text)
        except Exception as e:  # noqa: BLE001
            log.info("No pude abrir la ficha %s: %s", ficha_tienda, type(e).__name__)
            continue
        lista = C.lista_de_texto(texto) or r.get("precio_lista")
        planes = C.planes_de_texto(texto, lista)
        vieja = _guardar(db, clave_cuotas, ahora, lista=lista, planes=json.dumps([p.a_lista() for p in planes]))
        if vieja and vieja.get("planes") is not None:
            antes = [C.Plan.de_lista(x) for x in json.loads(vieja["planes"])]
            n_antes, n_ahora = _max_sin_interes(antes), _max_sin_interes(planes)
            if n_ahora > n_antes:
                mejor = max((p for p in planes if p.sin_interes), key=lambda p: p.cuotas)
                cambios.append(Cambio(r, it, n_antes, mejor, vieja.get("lista"), lista, vieja.get("ts")))
    log.info("Fichas: %d de HardGamers, %d de tiendas, %d cambios de cuotas", pedidas_hg, pedidas, len(cambios))
    return cambios


def ficha_de(db, url: str) -> tuple[float | None, list[C.Plan]]:
    """(precio de lista, planes) guardados para esa publicación."""
    for clave in (url + "#cuotas", url):
        fila = db.c.execute("SELECT lista, planes FROM fichas WHERE url=?", (clave,)).fetchone()
        if fila and fila["planes"] is not None:
            return fila["lista"], [C.Plan.de_lista(x) for x in json.loads(fila["planes"])]
    return None, []


# ------------------------------------------------------------------ promos de las tiendas

def leer_promos(db, cli, ahora: datetime) -> list[tuple[str, C.Promo]]:
    """Una vez por día. Devuelve las promos NUEVAS (o con más cuotas sin interés) de tiendas que ya
    tenían promos guardadas: la primera vez que se lee una tienda no avisa (sería todo "nuevo")."""
    hoy = str(H.dia_ar(ahora))
    if db.get("promos_leidas") == hoy:
        return []
    nuevas: list[tuple[str, C.Promo]] = []
    for tienda, url in PAGINAS_PROMOS.items():
        try:
            r = cli.get(url)
            lista = (C.promos_compragamer(r.json(), H.dia_ar(ahora)) if tienda == "compragamer"
                     else C.promos_de_texto(tienda, C.texto_de_html(r.text)))
        except Exception as e:  # noqa: BLE001
            log.info("No pude leer las promos de %s: %s", tienda, type(e).__name__)
            continue
        guardadas = {f["clave"]: dict(f) for f in db.c.execute("SELECT * FROM promos WHERE tienda=?", (tienda,))}
        primera = not guardadas and not db.get(f"promos_vistas:{tienda}")
        maximo_antes = max((f["cuotas"] or 0 for f in guardadas.values() if f["sin_interes"] and f["ultima_vez"] >= _ayer(hoy)),
                           default=0)
        vigentes = set()
        for p in lista:
            vigentes.add(p.clave)
            if p.clave in guardadas:
                db.c.execute("UPDATE promos SET ultima_vez=?, texto=?, vence=? WHERE tienda=? AND clave=?",
                             (hoy, p.texto, p.vence, tienda, p.clave))
                continue
            db.c.execute("INSERT INTO promos VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (tienda, p.clave, p.texto, p.cuotas, int(p.sin_interes), p.medio, p.vence,
                          int(p.general), hoy, hoy))
            # avisa: una promo de un banco con cuotas sin interés, o una general con más cuotas que antes
            if not primera and p.sin_interes and p.cuotas and (not p.general or p.cuotas > maximo_antes):
                nuevas.append((tienda, p))
        # las que ya no aparecen quedan con su última fecha (no cuentan más)
        db.set(f"promos_vistas:{tienda}", hoy)
    db.set("promos_leidas", hoy)
    return nuevas


def _ayer(hoy: str) -> str:
    return str(date.fromisoformat(hoy) - timedelta(days=1))


def promos_de(db, tienda: str, ahora: datetime | None = None) -> list[C.Promo]:
    """Las promos vigentes de la tienda (vistas en las últimas 48 h y no vencidas)."""
    hoy = H.dia_ar(ahora or datetime.now(timezone.utc))
    desde = str(hoy - timedelta(days=2))
    tienda = {"hg_fullh4rd": "fullh4rd"}.get(tienda, tienda)
    salida = []
    for f in db.c.execute("SELECT * FROM promos WHERE tienda=? AND ultima_vez>=? ORDER BY cuotas DESC", (tienda, desde)):
        p = C.Promo(f["tienda"], f["texto"], f["cuotas"], bool(f["sin_interes"]), f["medio"], f["vence"],
                    bool(f["general"]))
        if not p.vencida(hoy):
            salida.append(p)
    return salida


def pagos_de(db, cfg: dict, fila: dict, tasa: float, ahora: datetime | None = None) -> C.Pagos:
    """El bloque de precios de una publicación argentina: transferencia, lista, mejor plan y promos."""
    lista, planes = ficha_de(db, fila["url"])
    lista = lista or fila.get("precio_lista")
    promos = promos_de(db, fila["tienda"], ahora)
    mis = list((cfg.get("cuotas") or {}).get("mis_tarjetas") or [])
    return C.pagos(fila["precio"], lista, planes, promos, tasa, mis)
