"""Cuotas y promociones bancarias de las tiendas argentinas, y cuánto valen "de contado".

De dónde sale cada cosa:
  - Las cuotas de un producto: de su ficha en la tienda (solo de las 5 más baratas de cada cosa que
    seguís, ver fichas.py). Cada tienda las escribe a su manera; acá hay un lector general que entiende
    "12 cuotas sin interés de $226.700", "3 x $371.470,67 Sin interés", "12 Pagos $205.863 (PTF: $2.470.367)"
    y la tabla de Mexx ("Cuotas Interés 3 Sin interés 6 20.00% …" sobre el precio de lista).
  - Las promos bancarias: una vez por día, de la página de promociones de cada tienda grande (Compra
    Gamer las publica en un JSON; Maximus y Mexx, en texto). Valen para todos los productos de la tienda
    y se aplican sobre el precio de lista. Los banners que son solo imagen no se pueden leer.

Valor de contado: lo que valen hoy las cuotas, descontadas a una tasa mensual (por defecto la de plazo
fijo: la mediana de la TNA para clientes de los bancos, de argentinadatos.com, dividida por 12). La
primera cuota se paga al mes (con el resumen de la tarjeta).

El precio real más barato es el menor entre la transferencia y el valor de contado de las cuotas: eso
usan el veredicto y la comparación con Australia."""
from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .cotizaciones import ars

log = logging.getLogger("bot.cuotas")

URL_TASAS = "https://api.argentinadatos.com/v1/finanzas/tasas/plazoFijo"
TASA_RESPALDO_MENSUAL = 0.017     # ~20% TNA: si no se puede bajar la de plazo fijo
CUOTAS_VALIDAS = {2, 3, 4, 5, 6, 9, 10, 12, 14, 15, 18, 20, 24, 30, 36}


@dataclass
class Plan:
    cuotas: int
    valor: float            # cada cuota
    sin_interes: bool
    medio: str | None = None  # "MODO", "ICBC Mastercard", "Mercado Pago"…; None = la tarjeta que sea
    fuente: str = "ficha"     # "ficha" (la página del producto) | "promo" (promoción de la tienda)

    @property
    def total(self) -> float:
        return self.cuotas * self.valor

    def a_lista(self) -> list:
        return [self.cuotas, round(self.valor, 2), int(self.sin_interes), self.medio, self.fuente]

    @classmethod
    def de_lista(cls, x: list) -> "Plan":
        return cls(int(x[0]), float(x[1]), bool(x[2]), x[3] if len(x) > 3 else None,
                   x[4] if len(x) > 4 else "ficha")


def valor_contado(valor_cuota: float, cuotas: int, tasa_mensual: float) -> float:
    """Valor presente de 'cuotas' pagos mensuales (el primero al mes)."""
    if tasa_mensual <= 0:
        return valor_cuota * cuotas
    return valor_cuota * (1 - (1 + tasa_mensual) ** -cuotas) / tasa_mensual


# ------------------------------------------------------------------ tasa

def tasa_mensual(db, cfg: dict, cliente=None, ahora: datetime | None = None) -> tuple[float, str]:
    """(tasa mensual, de dónde sale). config.yaml → cuotas.tasa_mensual_pct: un número, o
    "plazo_fijo" (por defecto: se baja una vez por día)."""
    c = (cfg.get("cuotas") or {})
    fija = c.get("tasa_mensual_pct", "plazo_fijo")
    if isinstance(fija, (int, float)):
        return float(fija) / 100, f"{fija:g}% mensual (config.yaml)"
    ahora = ahora or datetime.now(timezone.utc)
    guardada = json.loads(db.get("tasa_plazo_fijo", "{}") or "{}")
    vieja = not guardada or ahora - datetime.fromisoformat(guardada["ts"]) > timedelta(hours=20)
    if vieja and cliente is not None:
        try:
            filas = cliente.get(URL_TASAS).json()
            tnas = [float(f["tnaClientes"]) for f in filas if f.get("tnaClientes")]
            if tnas:
                guardada = {"ts": ahora.isoformat(), "tna": statistics.median(tnas), "bancos": len(tnas)}
                db.set("tasa_plazo_fijo", json.dumps(guardada))
        except Exception as e:  # noqa: BLE001
            log.warning("No pude bajar la tasa de plazo fijo: %s", type(e).__name__)
    if guardada.get("tna"):
        tna = guardada["tna"]
        return tna / 12, f"plazo fijo {tna * 100:.1f}% TNA ({tna * 100 / 12:.2f}% mensual)"
    return TASA_RESPALDO_MENSUAL, f"{TASA_RESPALDO_MENSUAL * 100:.1f}% mensual (respaldo: no pude bajar la de plazo fijo)"


# ------------------------------------------------------------------ fichas de producto

_N = r"(\d{1,2})"
_P = r"\$\s*([\d.]+(?:,\d{1,2})?)"
RE_CUOTAS_DE = re.compile(_N + r"\s*cuotas?\s*(sin\s*inter[eé]s|fijas|simples)?\s*de\s*" + _P, re.I)
RE_X = re.compile(r"(?<![\d.,])" + _N + r"\s*x\s*" + _P + r"(\s*sin\s*inter[eé]s)?", re.I)
RE_PAGOS = re.compile(_N + r"\s*pagos?\s*" + _P + r"\s*\(\s*PTF:?\s*" + _P, re.I)
RE_TABLA = re.compile(r"Cuotas\s*Inter[eé]s((?:\s*\d{1,2}\s*(?:Sin\s*inter[eé]s|\d+[.,]\d+\s*%))+)", re.I)
RE_FILA_TABLA = re.compile(r"(\d{1,2})\s*(Sin\s*inter[eé]s|(\d+[.,]\d+)\s*%)", re.I)
RE_LISTA = [re.compile(r"Precio\s*de\s*lista:?\s*" + _P, re.I),
            re.compile(_P + r"\s*Precio\s*\d{1,2}\s*cuotas", re.I),       # Mexx: "$1.111.389 Precio 12 cuotas"
            re.compile(r"Sin\s*inter[eé]s\s*" + _P + r"\s*\d{1,2}\s*cuotas", re.I)]  # Gezatek


def _plata(x: str) -> float:
    return float(x.replace(".", "").replace(",", "."))


def lista_de_texto(texto: str) -> float | None:
    for rx in RE_LISTA:
        if m := rx.search(texto):
            return _plata(m.group(1))
    return None


RE_EN_EL_LOCAL = re.compile(r"(?:cuotas|pagos?)\s*en\s*el\s*local.{0,300}", re.I | re.S)


def planes_de_texto(texto: str, lista: float | None = None) -> list[Plan]:
    """Los planes de cuotas que dice el texto de una ficha (sin 1 pago). Un plan cuenta "sin interés"
    si lo dice, o si el total da el precio de lista (±1,5%). Lo que es solo para pagar en el local
    (Katech: "Cuotas en el local … Mercado Pago 3 x … 13% OFF") no cuenta."""
    texto = RE_EN_EL_LOCAL.sub(" ", texto)
    lista = lista or lista_de_texto(texto)
    planes: dict[int, Plan] = {}

    def sumar(n: int, valor: float, dice_sin: bool):
        if n not in CUOTAS_VALIDAS or valor <= 0:
            return
        if lista and n * valor < lista * 0.9:
            return   # da menos que el precio de lista: es de otro producto o de otra cosa (Katech "2 x …")
        sin = dice_sin or bool(lista and abs(n * valor - lista) / lista <= 0.015)
        p = Plan(n, valor, sin)
        if n not in planes or p.total < planes[n].total:
            planes[n] = p

    for m in RE_CUOTAS_DE.finditer(texto):
        sumar(int(m.group(1)), _plata(m.group(3)), bool(m.group(2) and "inter" in m.group(2).lower()))
    for m in RE_X.finditer(texto):
        sumar(int(m.group(1)), _plata(m.group(2)), bool(m.group(3)))
    for m in RE_PAGOS.finditer(texto):
        sumar(int(m.group(1)), _plata(m.group(2)), False)
    if lista and (m := RE_TABLA.search(texto)):      # Mexx: % de recargo sobre el precio de lista
        for f in RE_FILA_TABLA.finditer(m.group(1)):
            n = int(f.group(1))
            recargo = 0.0 if f.group(3) is None else float(f.group(3).replace(",", ".")) / 100
            sumar(n, lista * (1 + recargo) / n, recargo == 0)
    return sorted(planes.values(), key=lambda p: p.cuotas)


def texto_de_html(html: str) -> str:
    from selectolax.lexbor import LexborHTMLParser
    arbol = LexborHTMLParser(html)
    for s in arbol.css("script,style,noscript"):
        s.decompose()
    return " ".join((arbol.body.text() if arbol.body else "").split())


# ------------------------------------------------------------------ promos de las tiendas

@dataclass
class Promo:
    tienda: str
    texto: str               # "3, 4, 5 y 6 cuotas sin interés con MODO (tarjetas de todos los bancos)"
    cuotas: int | None       # el máximo de cuotas sin interés (None si es otra cosa: reintegro, % off)
    sin_interes: bool
    medio: str | None
    vence: str | None = None  # "30/11/2026"
    general: bool = True      # vale con tarjetas de todos los bancos (no hace falta ser cliente de uno)

    def vale_para(self, mis_tarjetas: list[str]) -> bool:
        """¿Cuenta para el precio real? Las generales siempre; las de un banco, si tenés esa tarjeta."""
        if self.general:
            return True
        medio = (self.medio or "").lower()
        return any(t.lower() in medio or medio in t.lower() for t in mis_tarjetas if t)

    def vencida(self, hoy) -> bool:
        if not self.vence:
            return False
        try:
            d, m, a = (int(x) for x in self.vence.split("/"))
            return datetime(a + 2000 if a < 100 else a, m, d).date() < hoy
        except ValueError:
            return False

    @property
    def clave(self) -> str:
        return re.sub(r"\W+", " ", f"{self.medio or ''} {self.cuotas or ''} {self.texto}".lower()).strip()[:120]


RE_NUMS = re.compile(r"\d{1,2}")
RE_VENCE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")


def _nombre_medio(x: str) -> str:
    """'banco_ciudad_logo' → 'Banco Ciudad'; 'Comafi UNICO v2' → 'Comafi UNICO'; 'Mercado pago' → 'Mercado Pago'."""
    x = re.sub(r"(?i)[_-]?logo\b|\bv\d\b", " ", x).replace("_", " ")
    x = " ".join(x.split())
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in x.split())


def promos_compragamer(datos: dict, hoy=None) -> list[Promo]:
    """static.compragamer.com/cms/promos/payment_promos.json: título (banco o billetera), cuotas y
    aclaración. Las vencidas no van."""
    hoy = hoy or datetime.now(timezone.utc).date()
    salida = []
    for p in datos.get("promos") or []:
        titulo = (p.get("title") or {})
        medio = _nombre_medio((titulo.get("image") or {}).get("name") or titulo.get("text") or "") or None
        for c in p.get("contents") or []:
            valor = " ".join(v.get("text", "") for v in (c.get("value") or [])).strip()
            sufijo = " ".join(v.get("text", "") for v in (c.get("suffix") or [])).strip()
            prefijo = " ".join(v.get("text", "") for v in (c.get("prefix") or []) if isinstance(v, dict)).strip()
            frase = " ".join(x for x in (prefijo, valor, sufijo) if x)
            es_cuotas = "cuota" in sufijo.lower()
            nums = [int(n) for n in RE_NUMS.findall(valor)] if es_cuotas else []
            sin = es_cuotas and "inter" in sufijo.lower()
            indicacion = ((p.get("indication") or {}).get("text") or "").strip().rstrip(".")
            if re.search(r"(?i)\bdesde$", indicacion):   # "Pagando desde" + el logo de la app: no dice nada
                indicacion = ""
            texto = f"{frase.lower() if es_cuotas else frase}{' con ' + medio if medio else ''}"
            if indicacion:
                texto += f" ({indicacion[0].lower() + indicacion[1:]})"
            vence = RE_VENCE.search(p.get("description") or "")
            general = bool(re.search(r"(?i)todos los bancos|sin tarjeta", indicacion))
            promo = Promo("compragamer", texto, max(nums) if nums else None, sin, medio,
                          vence.group(1) if vence else None, general)
            if vence:
                promo.texto += f", hasta el {vence.group(1)}"
            if not promo.vencida(hoy):
                salida.append(promo)
    return salida


RE_PROMO_TEXTO = re.compile(
    r"(?:(?P<medio>[A-ZÁÉÍÓÚ]\w*(?:\s+[A-ZÁÉÍÓÚ]\w*){0,3})\s*:\s*)?"
    r"(?P<nums>\d{1,2}(?:\s*(?:,|y)\s*\d{1,2})*)\s*cuotas\s*sin\s*inter[eé]s"
    r"(?:\s*(?:con|pagando con)\s+(?P<con>(?:tarjetas?\s+)?[A-ZÁÉÍÓÚ]\w*(?:\s+[A-ZÁÉÍÓÚ]\w*){0,3}))?", re.U)


def promos_de_texto(tienda: str, texto: str) -> list[Promo]:
    """'Mercado Pago: 3 y 6 cuotas sin interés' (Maximus), '12 cuotas sin interés con ICBC Mastercard'…"""
    salida: dict[str, Promo] = {}
    for m in RE_PROMO_TEXTO.finditer(texto):
        nums = [int(n) for n in RE_NUMS.findall(m.group("nums"))]
        nums = [n for n in nums if n in CUOTAS_VALIDAS]
        if not nums:
            continue
        medio = (m.group("medio") or m.group("con") or "").strip() or None
        frase = f"{m.group('nums')} cuotas sin interés" + (f" con {medio}" if medio else "")
        # "Mercado Pago: 3 y 6 cuotas sin interés" (con cualquier tarjeta) es general; "con ICBC Mastercard", no
        general = not medio or bool(re.search(r"(?i)mercado\s*pago|modo|todas las tarjetas|todos los bancos", medio))
        p = Promo(tienda, frase, max(nums), True, medio, None, general)
        salida.setdefault(p.clave, p)
    return list(salida.values())


def planes_de_promos(promos: list[Promo], lista: float | None) -> list[Plan]:
    """Las promos de cuotas sin interés de la tienda, sobre el precio de lista del producto."""
    if not lista:
        return []
    planes = []
    for p in promos:
        if p.cuotas and p.sin_interes:
            planes.append(Plan(p.cuotas, lista / p.cuotas, True, p.medio, "promo"))
    return planes


# ------------------------------------------------------------------ el mejor precio

@dataclass
class Pagos:
    transferencia: float
    lista: float | None
    plan: Plan | None              # el plan de cuotas que menos vale de contado
    contado: float | None          # el valor de contado de ese plan
    promos: list[str]              # textos de las promos bancarias de la tienda

    @property
    def real(self) -> float:
        """El precio real más barato: la transferencia o el valor de contado de las cuotas."""
        return min(self.transferencia, self.contado) if self.contado else self.transferencia

    @property
    def conviene_cuotas(self) -> bool:
        return bool(self.contado and self.contado < self.transferencia)

    def a_lista(self) -> list:
        """Para el JSON de /buscar: [lista, cuotas, valor cuota, sin interés, contado, real]."""
        p = self.plan
        return [round(self.lista) if self.lista else None, p.cuotas if p else None,
                round(p.valor) if p else None, int(p.sin_interes) if p else None,
                round(self.contado) if self.contado else None, round(self.real)]


def mejor_plan(planes: list[Plan], tasa: float) -> tuple[Plan | None, float | None]:
    if not planes:
        return None, None
    p = min(planes, key=lambda x: (valor_contado(x.valor, x.cuotas, tasa), -x.cuotas))
    return p, valor_contado(p.valor, p.cuotas, tasa)


def pagos(transferencia: float, lista: float | None, planes: list[Plan], promos: list[Promo],
          tasa: float, mis_tarjetas: list[str] | None = None) -> Pagos:
    """Para el precio real cuentan las cuotas de la ficha y las promos generales de la tienda (y las de
    un banco, si está en cuotas.mis_tarjetas). Todas las promos se muestran."""
    validas = [p for p in promos if p.vale_para(mis_tarjetas or [])]
    # en cuotas nunca se paga menos que por transferencia: un plan así está mal leído
    todos = [p for p in list(planes) + planes_de_promos(validas, lista) if p.total >= transferencia * 0.97]
    plan, contado = mejor_plan(todos, tasa)
    # primero las que no cuentan (las de bancos: son las que hay que saber que existen), sin repetir
    textos = [p.texto for p in sorted(promos, key=lambda p: (p.general, -(p.cuotas or 0)))]
    return Pagos(transferencia, lista, plan, contado, list(dict.fromkeys(textos)))


def describir_plan(p: Plan) -> str:
    """'12 cuotas sin interés de $226.700' / '9 cuotas de $135.253'."""
    return f"{p.cuotas} cuotas{' sin interés' if p.sin_interes else ''} de {ars(p.valor)}"


def lineas_pagos(pg: Pagos, tipo_precio: str = "transferencia") -> list[str]:
    """El bloque de precios de Argentina:
    💵 Transferencia: $2.348.000
    💳 Lista: $2.720.000 · 12 cuotas sin interés de $226.700 (≈ $2.390.000 contado)
    🏦 Promo: 12 cuotas sin interés con ICBC Mastercard"""
    from html import escape
    nombre = "Transferencia" if tipo_precio == "transferencia" else ("Contado" if tipo_precio == "contado" else "Precio")
    lineas = [f"💵 {nombre}: <b>{ars(pg.transferencia)}</b>"]
    partes = []
    if pg.lista:
        partes.append(f"Lista: {ars(pg.lista)}")
    if pg.plan:
        partes.append(f"{describir_plan(pg.plan)} (≈ {ars(pg.contado)} contado"
                      f"{', conviene más que la transferencia' if pg.conviene_cuotas else ''})")
    if partes:
        lineas.append("💳 " + " · ".join(partes))
    if pg.promos:
        lineas.append("🏦 Promo: " + escape(" · ".join(pg.promos[:3])))
    return lineas
