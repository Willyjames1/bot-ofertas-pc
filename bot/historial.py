"""Comparar contra el pasado. En Argentina todo en USD MEP del día (con la inflación, en pesos
cualquier precio "sube"); en Australia, en A$.

De dónde sale el pasado:
  - nuestra base (la tabla precios: cada cambio de cada publicación, desde el 16/11/2026),
  - el gráfico de la ficha de HardGamers de cada publicación (un precio por día, hasta 75 días),
  - el "precio más bajo de los últimos N días" que muestra esa ficha (la referencia de octubre),
  - el dólar MEP de cada día (argentinadatos.com).

Para cada cosa que seguís (compras.py) se arma la serie del MEJOR precio de cada día entre todas las
publicaciones que cumplen, y de ahí: hace 7 días, hace 30 días, el mínimo de 75 días y la mediana de 30
días. Una oferta se compara contra esa mediana (en USD), nunca contra el "precio anterior" de la tienda.

Descuento inflado: si en los 14 días antes del 27/11 una tienda subió el precio en USD y después "lo
bajó", y contra el precio de hace 14 días no está más barato, se marca ⚠️."""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .config import TZ_AR
from .cotizaciones import ars, usd

log = logging.getLogger("bot.historial")
URL_MEP = "https://api.argentinadatos.com/v1/cotizaciones/dolares/bolsa"
DIAS_MEP = 120
MIN_DIAS_MEDIANA = 5          # con menos días de datos no hay mediana de 30 días
INFLADO_SUBA = 0.05           # subió 5% o más en USD…
INFLADO_BAJA = 0.03           # …y después bajó 3% o más, pero no quedó 3% más barato que antes de subir


def dia_ar(ts: str | datetime) -> date:
    d = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    return d.astimezone(TZ_AR).date()


# ------------------------------------------------------------------ dólar MEP de cada día

def actualizar_mep(db, cliente, mep_hoy: float | None, ahora: datetime | None = None):
    """Una vez por día baja el MEP de los últimos 120 días; el de hoy es el de esta corrida."""
    ahora = ahora or datetime.now(timezone.utc)
    hoy = dia_ar(ahora)
    if cliente is not None and db.get("mep_diario_bajado") != str(hoy):
        try:
            desde = str(hoy - timedelta(days=DIAS_MEP))
            filas = [(f["fecha"], float(f["venta"])) for f in cliente.get(URL_MEP).json()
                     if f.get("fecha", "") >= desde and f.get("venta")]
            db.c.executemany("INSERT OR REPLACE INTO mep_diario VALUES(?,?)", filas)
            db.set("mep_diario_bajado", str(hoy))
        except Exception as e:  # noqa: BLE001
            log.warning("No pude bajar el MEP histórico: %s", type(e).__name__)
    if mep_hoy:
        db.c.execute("INSERT OR REPLACE INTO mep_diario VALUES(?,?)", (str(hoy), mep_hoy))
    db._mep = None


def _meps(db) -> list[tuple[str, float]]:
    if getattr(db, "_mep", None) is None:
        filas = db.c.execute("SELECT fecha, mep FROM mep_diario ORDER BY fecha").fetchall()
        if not filas:   # sin la tabla llena (tests, primera corrida): lo que guardaron las corridas
            por_dia: dict[str, float] = {}
            for r in db.c.execute("SELECT ts, mep FROM cotizaciones WHERE mep IS NOT NULL ORDER BY ts"):
                por_dia[str(dia_ar(r["ts"]))] = r["mep"]
            filas = sorted(por_dia.items())
        db._mep = [(f[0], f[1]) for f in filas]
    return db._mep


def mep_en(db, fecha: date | str) -> float | None:
    """El MEP de ese día (o del último día hábil anterior; si es anterior a todo, el primero que hay)."""
    f = str(fecha)
    filas = _meps(db)
    if not filas:
        return None
    antes = [m for d, m in filas if d <= f]
    return antes[-1] if antes else filas[0][1]


# ------------------------------------------------------------------ series

def serie_oferta(filas_precios: list, ultima_vez: str | None, hasta: date) -> dict[date, float]:
    """El precio (con stock) de una publicación en cada día, a partir de sus cambios en la tabla precios.
    Si en un día tuvo varios precios, el más bajo."""
    salida: dict[date, float] = {}
    if not filas_precios:
        return salida
    fin = min(hasta, dia_ar(ultima_vez)) if ultima_vez else hasta
    estado = None          # (precio, stock) vigente al empezar el día
    i = 0
    d = dia_ar(filas_precios[0]["ts"])
    while d <= fin:
        candidatos = []
        if estado and estado[1] != 0 and estado[0]:
            candidatos.append(estado[0])
        while i < len(filas_precios) and dia_ar(filas_precios[i]["ts"]) == d:
            f = filas_precios[i]
            estado = (f["precio"], f["stock"])
            if f["stock"] != 0 and f["precio"]:
                candidatos.append(f["precio"])
            i += 1
        if candidatos:
            salida[d] = min(candidatos)
        d += timedelta(days=1)
    return salida


def serie_hg(db, url: str) -> dict[date, float]:
    return {date.fromisoformat(r["fecha"]): r["precio"]
            for r in db.c.execute("SELECT fecha, precio FROM hg_historial WHERE url=?", (url,))}


def serie(db, pais: str, categoria: str, cumple: Callable[[dict], bool], hasta: date,
          dias: int = 76) -> dict[date, tuple[float, str]]:
    """El mejor precio de cada día (y de qué publicación) entre las que cumplen, de 'dias' atrás a hoy."""
    clave = (pais, categoria, id(cumple), hasta, dias)
    cache = db.__dict__.setdefault("_series", {})
    if clave in cache:
        return cache[clave]
    desde = hasta - timedelta(days=dias)
    filas = [dict(r) for r in db.c.execute(
        "SELECT id, url, titulo, modelo, datos, tienda, ultima_vez, categoria, pais, tray, combo FROM ofertas "
        "WHERE pais=? AND categoria=? AND sospechoso=0 AND combo=0 AND modelo IS NOT NULL", (pais, categoria))]
    elegidas = [f for f in filas if cumple(f)]
    mejor: dict[date, tuple[float, str]] = {}

    def sumar(d: date, precio: float, url: str):
        if desde <= d <= hasta and precio and (d not in mejor or precio < mejor[d][0]):
            mejor[d] = (precio, url)

    for f in elegidas:
        cambios = db.c.execute("SELECT ts, precio, stock FROM precios WHERE oferta_id=? ORDER BY ts",
                               (f["id"],)).fetchall()
        for d, p in serie_oferta(cambios, f["ultima_vez"], hasta).items():
            sumar(d, p, f["url"])
        for d, p in serie_hg(db, f["url"]).items():
            sumar(d, p, f["url"])
    cache[clave] = mejor
    return mejor


def _en(serie_: dict, d: date, margen: int = 1):
    """El valor de ese día, o del más cercano a ±margen días."""
    for k in [0] + [s * x for x in range(1, margen + 1) for s in (-1, 1)]:
        if (d + timedelta(days=k)) in serie_:
            return d + timedelta(days=k), serie_[d + timedelta(days=k)]
    return None, None


# ------------------------------------------------------------------ referencias

@dataclass
class Punto:
    precio: float
    usd: float | None       # AR: en USD MEP de ese día; AU: None (se compara en A$)
    fecha: date | None = None

    def valor(self) -> float:
        return self.usd if self.usd is not None else self.precio


@dataclass
class Referencias:
    pais: str
    hoy: Punto
    hace7: Punto | None
    hace30: Punto | None
    minimo: Punto | None          # mínimo de 75 días (HardGamers, o nuestro historial)
    minimo_fuente: str            # "HardGamers" | "historial propio desde el 16/11"
    mediana30: float | None       # en USD (AR) o A$ (AU)
    dias_datos: int
    minimo_propio: Punto | None = None   # el de nuestro historial, si es más bajo que el de HardGamers
    desde_propio: date | None = None

    @property
    def piso(self) -> Punto | None:
        """El mínimo más bajo que conocemos (HardGamers o nuestro historial)."""
        ps = [p for p in (self.minimo, self.minimo_propio) if p]
        return min(ps, key=lambda p: p.valor()) if ps else None

    def vs(self, p: Punto | None) -> float | None:
        """% de diferencia de hoy contra ese punto, en USD (AR) o A$ (AU): negativo = más barato hoy."""
        if not p or not p.valor():
            return None
        return (self.hoy.valor() / p.valor() - 1) * 100

    @property
    def bajo_mediana_pct(self) -> float | None:
        if not self.mediana30:
            return None
        return (1 - self.hoy.valor() / self.mediana30) * 100


def _punto(db, pais: str, precio: float, d: date) -> Punto:
    if pais != "AR":
        return Punto(precio, None, d)
    m = mep_en(db, d)
    return Punto(precio, precio / m if m else None, d)


def minimo_hg(db, urls: list[str], hasta: date) -> tuple[float, date | None] | None:
    """El "precio más bajo de los últimos N días" de las fichas de HardGamers, y el de sus gráficos."""
    if not urls:
        return None
    marcas = ",".join("?" * len(urls))
    candidatos = []
    for r in db.c.execute(f"SELECT minimo, ts FROM fichas WHERE url IN ({marcas}) AND minimo IS NOT NULL", urls):
        candidatos.append((r["minimo"], None))
    desde = str(hasta - timedelta(days=75))
    for r in db.c.execute(f"SELECT precio, fecha FROM hg_historial WHERE url IN ({marcas}) AND fecha>=?",
                          (*urls, desde)):
        candidatos.append((r["precio"], date.fromisoformat(r["fecha"])))
    if not candidatos:
        return None
    precio = min(c[0] for c in candidatos)
    fecha = next((c[1] for c in candidatos if c[0] == precio and c[1]), None)
    return precio, fecha


def referencias(db, pais: str, categoria: str, cumple: Callable[[dict], bool], precio_hoy: float,
                ahora: datetime | None = None) -> Referencias:
    hoy = dia_ar(ahora or datetime.now(timezone.utc))
    s = serie(db, pais, categoria, cumple, hoy)
    pasado = {d: v for d, v in s.items() if d < hoy}
    r_hoy = _punto(db, pais, precio_hoy, hoy)
    d7, v7 = _en(pasado, hoy - timedelta(days=7))
    d30, v30 = _en(pasado, hoy - timedelta(days=30), 2)
    hace7 = _punto(db, pais, v7[0], d7) if v7 else None
    hace30 = _punto(db, pais, v30[0], d30) if v30 else None
    urls_hg = sorted({u for _, u in s.values() if "hardgamers.com.ar" in u})
    # el mínimo de HardGamers: de las publicaciones de HardGamers que cumplen (no solo las del gráfico)
    if pais == "AR":
        todas = [dict(r) for r in db.c.execute(
            "SELECT url, titulo, modelo, datos, categoria, pais, tray, combo FROM ofertas WHERE pais='AR' AND "
            "categoria=? AND url LIKE 'https://www.hardgamers.com.ar/%' AND sospechoso=0 AND combo=0", (categoria,))]
        urls_hg = sorted(set(urls_hg) | {f["url"] for f in todas if cumple(f)})
    mh = minimo_hg(db, urls_hg, hoy) if pais == "AR" else None
    propio = None
    if pasado:
        d_min = min(pasado, key=lambda d: pasado[d][0])
        propio = _punto(db, pais, pasado[d_min][0], d_min)
    if mh:
        minimo = _punto(db, pais, mh[0], mh[1] or hoy)
        fuente = "HardGamers"
        if propio and propio.valor() >= minimo.valor() * 0.995:
            propio = None   # el de HardGamers ya es el más bajo
    elif propio:
        minimo, propio = propio, None
        fuente = f"historial propio desde el {min(pasado):%d/%m}"
    else:
        minimo, fuente = None, ""
    ultimos = [(d, v[0]) for d, v in pasado.items() if d >= hoy - timedelta(days=30)]
    mediana = None
    if len(ultimos) >= MIN_DIAS_MEDIANA:
        mediana = statistics.median(_punto(db, pais, p, d).valor() for d, p in ultimos)
    return Referencias(pais, r_hoy, hace7, hace30, minimo, fuente, mediana, len(ultimos), propio,
                       min(pasado) if pasado else None)


def _fmt(p: Punto, pais: str) -> str:
    if pais == "AR":
        return f"{ars(p.precio)}" + (f" ({usd(p.usd)})" if p.usd is not None else "")
    return "A$" + f"{p.precio:,.0f}".replace(",", ".")


def lineas_referencias(ref: Referencias) -> list[str]:
    """📊 Hoy: $2.348.000 (USD 1.349)
       Hace 7 días: $2.269.000 (USD 1.424)
       Hace 30 días: …
       Mínimo 75 días (HardGamers): $2.581.840
    → En USD está 5% más barato que hace una semana ✅"""
    p = ref.pais
    lineas = [f"📊 Hoy: {_fmt(ref.hoy, p)}"]
    lineas.append(f"   Hace 7 días: {_fmt(ref.hace7, p)}" if ref.hace7 else "   Hace 7 días: sin datos")
    lineas.append(f"   Hace 30 días: {_fmt(ref.hace30, p)}" if ref.hace30 else "   Hace 30 días: sin datos todavía")
    if ref.minimo:
        cuando = f", el {ref.minimo.fecha:%d/%m}" if ref.minimo.fecha and ref.minimo.fecha != dia_ar(datetime.now(timezone.utc)) else ""
        lineas.append(f"   Mínimo 75 días ({ref.minimo_fuente}): {_fmt(ref.minimo, p)}{cuando}")
    if ref.minimo_propio:
        mp = ref.minimo_propio
        lineas.append(f"   Mínimo en otras tiendas (historial propio desde el {ref.desde_propio:%d/%m}): "
                      f"{_fmt(mp, p)}" + (f", el {mp.fecha:%d/%m}" if mp.fecha else ""))
    moneda = "En USD" if p == "AR" else "En A$"
    frases = []
    for nombre, punto in (("hace una semana", ref.hace7), ("hace 30 días", ref.hace30)):
        pct = ref.vs(punto)
        if pct is None:
            continue
        if abs(pct) < 1:
            frases.append(f"igual que {nombre}")
        else:
            frases.append(f"{abs(pct):.0f}% más {'barato' if pct < 0 else 'caro'} que {nombre}")
    if ref.bajo_mediana_pct is not None:
        b = ref.bajo_mediana_pct
        frases.append("igual que la mediana de 30 días" if abs(b) < 1 else
                      f"{abs(b):.0f}% {'abajo' if b > 0 else 'arriba'} de la mediana de 30 días")
    if frases:
        # ✅ si en general está más barato que antes, ⚠️ si está más caro, ➖ si da parejo
        señales = [-(ref.vs(ref.hace7) or 0), -(ref.vs(ref.hace30) or 0), ref.bajo_mediana_pct or 0]
        puntos = sum(1 if s > 1 else -1 if s < -1 else 0 for s in señales)
        lineas.append(f"→ {moneda} está {', '.join(frases)} {'✅' if puntos > 0 else '⚠️' if puntos < 0 else '➖'}")
    return lineas


# ------------------------------------------------------------------ descuento inflado

def inflado(db, fila: dict, ahora: datetime | None = None, anclaje: date | None = None) -> str | None:
    """⚠️ si en los 14 días antes de 'anclaje' (el 27/11) la publicación subió en USD y después "bajó"
    sin quedar más barata que antes de subir. fila = la de la tabla ofertas."""
    ahora = ahora or datetime.now(timezone.utc)
    hoy = dia_ar(ahora)
    anclaje = anclaje or hoy
    base_dia = anclaje - timedelta(days=14)
    cambios = db.c.execute("SELECT ts, precio, stock FROM precios WHERE oferta_id=? ORDER BY ts",
                           (fila["id"],)).fetchall() if fila.get("id") else []
    s = serie_oferta(cambios, fila.get("ultima_vez"), hoy)
    for d, p in serie_hg(db, fila["url"]).items():
        if d not in s or p < s[d]:
            s[d] = p
    if fila.get("precio"):
        s[hoy] = fila["precio"]
    pais = fila.get("pais", "AR")
    antes = [d for d in s if d <= base_dia]
    d_base = max(antes) if antes else (min(s) if s else None)
    if d_base is None or d_base > base_dia + timedelta(days=4) or d_base >= hoy:
        return None
    tramo = {d: _punto(db, pais, p, d) for d, p in s.items() if d_base <= d <= hoy}
    base = tramo[d_base]
    d_pico = max(sorted(tramo), key=lambda d: tramo[d].valor())    # el primer día del pico
    pico, actual = tramo[d_pico], tramo[hoy]
    if d_pico in (d_base, hoy):
        return None
    if not (pico.valor() >= base.valor() * (1 + INFLADO_SUBA) and actual.valor() <= pico.valor() * (1 - INFLADO_BAJA)
            and actual.valor() >= base.valor() * (1 - INFLADO_BAJA)):
        return None
    moneda = (lambda p: usd(p.usd)) if pais == "AR" else (lambda p: "A$" + f"{p.precio:,.0f}".replace(",", "."))
    subio = (pico.valor() / base.valor() - 1) * 100
    bajo = (1 - actual.valor() / pico.valor()) * 100
    contra = (actual.valor() / base.valor() - 1) * 100
    estado = "igual" if abs(contra) < 1 else (f"{contra:.0f}% más caro" if contra > 0 else f"{-contra:.0f}% más barato")
    return (f"⚠️ Descuento inflado: el {d_pico:%d/%m} lo subió a {moneda(pico)} (+{subio:.0f}% desde el "
            f"{d_base:%d/%m}) y ahora lo \"bajó\" {bajo:.0f}% a {moneda(actual)}: contra el {d_base:%d/%m} está {estado}")


def es_inflado(db, fila: dict, ahora: datetime | None = None, anclaje: date | None = None) -> bool:
    return inflado(db, fila, ahora, anclaje) is not None


def guardar_historial_hg(db, url: str, puntos: list[tuple[date, float]]):
    db.c.executemany("INSERT OR REPLACE INTO hg_historial VALUES(?,?,?)",
                     [(url, str(d), p) for d, p in puntos])
    db.__dict__.pop("_series", None)


def datos_de(fila: dict) -> dict:
    d = fila.get("datos")
    return json.loads(d) if isinstance(d, str) else (d or {})
