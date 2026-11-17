"""Foros por RSS. Fase 1: solo OzBargain (trae votos, vencimiento y estado en <ozb:...>).
Reddit quedó afuera: cortó el RSS el 13/11/2026 y no da acceso nuevo a su API."""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .modelos import Oferta, Post
from .normalizar import PC_ARMADA, chip_gpu, limpiar, normalizar

log = logging.getLogger("bot.feeds")
NS_OZB = "{https://www.ozbargain.com.au}"
RE_PRECIO = re.compile(r"(?:A?\$|AUD\s?)\s?(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2})?)")
RE_NO_ES_PRECIO_DESPUES = re.compile(
    r"\s*(OFF|CASHBACK|BACK|CREDIT|GIFT|BONUS|VOUCHER|STORE CREDIT|MIN(IMUM)?|SPEND|OR MORE)\b", re.I)
RE_NO_ES_PRECIO_ANTES = re.compile(r"(MIN(IMUM)?|SPEND|OVER|ABOVE|SAVE|UP TO|EXTRA|RRP|WAS)\W*$", re.I)
# Marcas de OzBargain que significan "ya no se puede comprar"
ESTADOS_MUERTOS = {"expired", "outofstock", "soldout", "deleted", "unpublished"}
RE_AGOTADO = re.compile(r"\b(SOLD OUT|OUT OF STOCK|EXPIRED|AGOTADO)\b", re.I)
MAX_DIAS_POST = 7


def precio_en_titulo(titulo: str) -> float | None:
    """Primer monto que parece precio: saltea '$100 off', 'Minimum $999', 'RRP $139', '$0 to Metro'."""
    for m in RE_PRECIO.finditer(titulo):
        if RE_NO_ES_PRECIO_DESPUES.match(titulo, m.end()):
            continue
        if RE_NO_ES_PRECIO_ANTES.search(titulo[max(0, m.start() - 16):m.start()]):
            continue
        v = float(m.group(1).replace(",", ""))
        if v >= 20:
            return v
    return None


def _fecha(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        try:
            return parsedate_to_datetime(texto)
        except (TypeError, ValueError):
            return None


def parsear_ozbargain(xml: str) -> list[Post]:
    raiz = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    posts = []
    for item in raiz.iter("item"):
        titulo = html.unescape(item.findtext("title", "")).strip()
        link = item.findtext("link", "")
        meta = item.find(f"{NS_OZB}meta")
        votos = int(meta.get("votes-pos", 0)) - int(meta.get("votes-neg", 0)) if meta is not None else None
        publicado = _fecha(item.findtext("pubDate", "")) or datetime.now(timezone.utc)
        estados = [m.get("type", "") for m in item.findall(f"{NS_OZB}title-msg")]
        id_ = link.rstrip("/").rsplit("/", 1)[-1]
        posts.append(Post(
            fuente="ozbargain", id=id_, titulo=titulo, url=link, publicado=publicado, votos=votos,
            url_tienda=meta.get("url") if meta is not None else None,
            precio=precio_en_titulo(titulo), moneda="AUD",
            etiquetas=[c.text or "" for c in item.findall("category")],
            expira=_fecha(meta.get("expiry")) if meta is not None else None, estados=estados,
            descripcion=RE_TAGS.sub(" ", html.unescape(item.findtext("description", "") or "")).strip()[:600]))
    return posts


# ------------------------------------------------------------------ códigos de descuento

RE_TAGS = re.compile(r"<[^>]+>")
RE_CODIGO = re.compile(r"\b(?:PROMO\s*CODE|DISCOUNT\s*CODE|COUPON\s*CODE|VOUCHER\s*CODE|COUPON|CODE)\s*[:\-]?\s*"
                       r"[\"'“”‘’]?([A-Z0-9]{4,20})\b")
NO_ES_CODIGO = {"REQUIRED", "NEEDED", "APPLIED", "BELOW", "CHECKOUT", "WORKS", "STACK", "STACKS", "ONLY",
                "EBAY", "WITH", "FROM", "INSIDE", "HERE", "AUTO", "APPLY", "SHOWN", "LISTED", "EXPIRED"}
RE_PCT_OFF = re.compile(r"(?<![\d.])(\d{1,2})\s*%\s*OFF")
RE_TOPE = re.compile(r"(?:MAX(?:IMUM)?|CAPPED AT|CAP(?:PED)?|UP TO)\s*(?:DISCOUNT\s*)?(?:OF\s*)?A?\$\s?(\d[\d,]*)")
RE_MIN_GASTO = re.compile(r"MIN(?:IMUM)?\.?\s*(?:SPEND|PURCHASE|ORDER)?\s*(?:OF\s*)?A?\$\s?(\d[\d,]*)")
# "$2,399 with code", "$2,399 after code": el precio del título YA tiene el código aplicado
RE_YA_APLICADO = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?\s*(?:\([^)]*\)\s*)?(?:DELIVERED\s*)?"
                            r"(?:WITH|AFTER|USING|W/|VIA)\s*(?:THE\s*)?(?:\w+\s*)?(?:CODE|COUPON)")


def codigo_descuento(p: Post) -> dict | None:
    """Del título (o, si no está ahí, de la descripción) del post: {'codigo', 'pct', 'tope', 'minimo'}."""
    for texto in (p.titulo, p.descripcion):
        t = (texto or "").upper()
        for m in RE_CODIGO.finditer(t):
            cod = m.group(1)
            if cod in NO_ES_CODIGO or cod.isdigit():
                continue
            todo = f"{(p.titulo or '').upper()} {(p.descripcion or '').upper()}"
            pct = RE_PCT_OFF.search(t) or RE_PCT_OFF.search(todo)
            tope = RE_TOPE.search(todo)
            minimo = RE_MIN_GASTO.search(todo)
            return {"codigo": cod, "pct": int(pct.group(1)) if pct else None,
                    "tope": float(tope.group(1).replace(",", "")) if tope else None,
                    "minimo": float(minimo.group(1).replace(",", "")) if minimo else None}
    return None


def precio_con_codigo(p: Post) -> tuple[float | None, dict | None, bool]:
    """(precio final, código, ¿lo apliqué yo?). Si el título ya muestra el precio con el código
    ("$2,399 with code X") se deja como está; si dice "Extra 20% off with code X" se descuenta."""
    cod = codigo_descuento(p)
    if not p.precio or not cod or not cod.get("pct"):
        return p.precio, cod, False
    if RE_YA_APLICADO.search(p.titulo.upper()):
        return p.precio, cod, False
    descuento = p.precio * cod["pct"] / 100
    if cod.get("tope"):
        descuento = min(descuento, cod["tope"])
    return round(p.precio - descuento, 2), cod, True


def es_codigo_ebay(p: Post, modelos: list) -> bool:
    """Post de un código de eBay (no de un producto): '20% off Selected Sellers with code X @ eBay AU'."""
    de_ebay = "ebay." in (p.url_tienda or "").lower() or "@ EBAY" in p.titulo.upper()
    return de_ebay and not modelos and (cod := codigo_descuento(p)) is not None and cod.get("pct") is not None


def vigente(p: Post, ahora: datetime | None = None, max_dias: int = MAX_DIAS_POST) -> tuple[bool, str | None]:
    """¿Sirve este post para alertas? Descarta expirados, agotados y los de más de 7 días."""
    ahora = ahora or datetime.now(timezone.utc)
    muertos = ESTADOS_MUERTOS.intersection(p.estados)
    if muertos:
        return False, f"marcado {sorted(muertos)[0]}"
    if RE_AGOTADO.search(p.titulo):
        return False, "agotado según el título"
    if p.expira and p.expira <= ahora:
        return False, f"venció el {p.expira:%d/%m/%Y}"
    if ahora - p.publicado > timedelta(days=max_dias):
        return False, f"tiene más de {max_dias} días ({p.publicado:%d/%m/%Y})"
    return True, None


# "Desktop" suelto también aparece en "Desktop Processor" o "Desktop RAM": solo cuenta como PC
# si el título trae una placa de video y no habla de un componente suelto.
RE_COMPONENTE = re.compile(r"\bDESKTOP\s+(PROCESSOR|CPU|RAM|MEMORY|KIT|GRAPHICS|GPU|VIDEO)|"
                           r"\b(GRAPHICS|VIDEO) CARD\b")


def es_pc(titulo: str, palabras: list[str] | None) -> bool:
    t = limpiar(titulo)
    if PC_ARMADA.search(t):
        return True
    for palabra in palabras or []:
        if re.search(r"(?<![A-Z0-9])" + re.escape(limpiar(palabra)) + r"(?![A-Z0-9])", t):
            if " " in palabra.strip() or palabra.strip().lower() == "prebuilt":
                return True  # "gaming PC", "prebuilt": no hay duda
            if chip_gpu(t) and not RE_COMPONENTE.search(t):
                return True
    return False


def modelos_del_post(p: Post, palabras_pc: list[str] | None = None) -> list[Oferta]:
    """Prueba el título con cada parser (placa, CPU, RAM, SSD) y devuelve las coincidencias.
    Si es una PC armada, la devuelve como tal (categoría "pcs") y no como sus componentes."""
    if es_pc(p.titulo, palabras_pc):
        o = normalizar(Oferta(tienda=p.fuente, pais="AU", categoria="pcs", titulo=p.titulo, url=p.url,
                              precio=p.precio or 0, moneda="AUD"))
        return [o] if o.modelo and not o.descartada else []
    salida = []
    for cat in ("placas", "cpu", "ram", "ssd"):
        o = normalizar(Oferta(tienda=p.fuente, pais="AU", categoria=cat, titulo=p.titulo, url=p.url,
                              precio=p.precio or 0, moneda="AUD"))
        if o.modelo and not o.descartada:
            salida.append(o)
    return salida
