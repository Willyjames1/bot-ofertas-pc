"""Mercado Libre Argentina por la API oficial (OAuth2). Solo productos NUEVOS de tiendas oficiales o
de vendedores MercadoLíder (platinum, gold o silver).

Cómo busca (la búsqueda abierta /sites/MLA/search contesta 403 a los servidores de GitHub):
  1. /sites/MLA/domain_discovery/search?q=…  → el "dominio" (ej. MLA-GRAPHICS_CARDS)
  2. /products/search?site_id=MLA&domain_id=…&q=…  → los productos del catálogo
  3. /products/{id}/items  → las publicaciones de cada producto (con precio, vendedor, condición)
  4. /users?ids=…  → la reputación de cada vendedor (MercadoLíder)

Credenciales (GitHub Secrets, nunca en el código ni en los logs):
  ML_CLIENT_ID, ML_CLIENT_SECRET  la app de developers.mercadolibre.com.ar
  ML_REFRESH_TOKEN                el primero, lo da `python -m bot mercadolibre codigo …` (ver README)
  ML_CLAVE                        para cifrar el refresh token que se guarda en la base
El refresh token se usa UNA vez: cada renovación da uno nuevo, que se guarda CIFRADO en la base
(la rama datos es pública). Sin credenciales, o si la API contesta 401/403, no se lee y no cuenta
como tienda caída."""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import quote

from .. import config
from ..modelos import Oferta
from ..red import Cliente
from .base import Tienda, registrar

log = logging.getLogger("bot.fuentes")
API = "https://api.mercadolibre.com"
URL_TOKEN = f"{API}/oauth/token"
URL_AUTORIZAR = "https://auth.mercadolibre.com.ar/authorization"
REDIRECT_POR_DEFECTO = "https://www.mercadolibre.com.ar"
LIDER = {"platinum", "gold", "silver"}
PRODUCTOS_POR_BUSQUEDA = 8
CLAVE_ESTADO = "ml_refresh"          # en la base, cifrado con ML_CLAVE

# lo que se busca por categoría (lo de compras.items; el filtro fino lo hace compras.Item.cumple)
BUSQUEDAS = {
    "placas": ["placa de video rtx 5070 ti"],
    "ram": ["memoria ram ddr5 32gb 2x16 6000"],
    "ssd": ["ssd nvme m.2 2tb gen4", "ssd nvme m.2 2tb gen5"],
    "mothers": ["motherboard b850 wifi am5"],
    "fuentes": ["fuente 850w 80 plus gold atx 3.1"],
    "refrigeracion": ["water cooler aio 360"],
    "gabinetes": ["gabinete mid tower 360"],
}


def _credenciales() -> tuple[str, str]:
    return os.getenv("ML_CLIENT_ID", "").strip(), os.getenv("ML_CLIENT_SECRET", "").strip()


def _fernet():
    clave = os.getenv("ML_CLAVE", "").strip()
    if not clave:
        return None
    from cryptography.fernet import Fernet
    return Fernet(clave.encode())


def cifrar(texto: str) -> str | None:
    f = _fernet()
    return f.encrypt(texto.encode()).decode() if f else None


def descifrar(texto: str) -> str | None:
    f = _fernet()
    if not f or not texto:
        return None
    from cryptography.fernet import InvalidToken
    try:
        return f.decrypt(texto.encode()).decode()
    except InvalidToken:
        return None


def url_autorizar(client_id: str, redirect: str = REDIRECT_POR_DEFECTO) -> str:
    return f"{URL_AUTORIZAR}?response_type=code&client_id={quote(client_id)}&redirect_uri={quote(redirect, safe='')}"


def canjear_codigo(cliente: Cliente, codigo: str, redirect: str = REDIRECT_POR_DEFECTO) -> dict:
    """El código que aparece en la barra de direcciones después de autorizar → access y refresh token."""
    cid, sec = _credenciales()
    r = cliente.http.post(URL_TOKEN, data={"grant_type": "authorization_code", "client_id": cid,
                                           "client_secret": sec, "code": codigo, "redirect_uri": redirect},
                          headers={"accept": "application/json"})
    r.raise_for_status()
    return r.json()


def preparar(db, cliente: Cliente | None = None) -> bool:
    """En el hilo principal, antes de leer las tiendas: renueva el access token con el refresh token
    (el último guardado en la base, o el de ML_REFRESH_TOKEN la primera vez) y guarda el nuevo."""
    MercadoLibre.access_token = None
    cid, sec = _credenciales()
    if not (cid and sec and os.getenv("ML_CLAVE", "").strip()):
        return False
    refresh = descifrar(db.get(CLAVE_ESTADO) or "") or os.getenv("ML_REFRESH_TOKEN", "").strip()
    if not refresh:
        return False
    propio = cliente is None
    cliente = cliente or Cliente(pausa=(0.5, 1.0), respetar_robots=False)
    try:
        r = cliente.http.post(URL_TOKEN, data={"grant_type": "refresh_token", "client_id": cid,
                                               "client_secret": sec, "refresh_token": refresh},
                              headers={"accept": "application/json"})
        if r.status_code != 200:
            log.warning("Mercado Libre: no pude renovar el token (HTTP %s)", r.status_code)
            return False
        j = r.json()
        MercadoLibre.access_token = j["access_token"]
        if j.get("refresh_token"):
            db.set(CLAVE_ESTADO, cifrar(j["refresh_token"]))
            db.commit()
        return True
    except Exception as e:  # noqa: BLE001 — nunca se loguea el token
        log.warning("Mercado Libre: no pude renovar el token (%s)", type(e).__name__)
        return False
    finally:
        if propio:
            cliente.cerrar()


@registrar
class MercadoLibre(Tienda):
    id = "mercadolibre"
    nombre = "Mercado Libre"
    pais = "AR"
    moneda = "ARS"
    web = "https://www.mercadolibre.com.ar"
    pausa = (1.0, 2.0)
    categorias = {c: [] for c in BUSQUEDAS}
    access_token: str | None = None      # lo pone preparar() (corrida.py)

    def __init__(self, cliente=None, cfg: dict | None = None):
        # API oficial: robots.txt del sitio no aplica a api.mercadolibre.com
        super().__init__(cliente or Cliente(pausa=self.pausa, timeout=30, respetar_robots=False))
        self.cfg = cfg if cfg is not None else config.cargar()
        self._apagada = False

    def _get(self, ruta: str) -> dict | list | None:
        if self._apagada:
            return None
        self.cliente._esperar_turno("api.mercadolibre.com")    # pausa entre pedidos
        r = self.cliente.http.get(API + ruta, headers={"Authorization": f"Bearer {self.access_token}"})
        if r.status_code in (401, 403):
            log.warning("Mercado Libre contesta %s a %s: no la leo en esta corrida", r.status_code, ruta.split("?")[0])
            self._apagada = True
            return None
        if r.status_code == 429:
            log.warning("Mercado Libre: demasiados pedidos (429), sigo en la próxima corrida")
            self._apagada = True
            return None
        if r.status_code != 200:
            return None
        return r.json()

    def leer(self, categoria: str) -> list[Oferta]:
        if not self.access_token:
            return []
        ofertas: dict[str, Oferta] = {}
        for q in BUSQUEDAS.get(categoria, []):
            for o in self.buscar(q, categoria):
                ofertas.setdefault(o.url, o)
        log.info("%s/%s: %d productos", self.id, categoria, len(ofertas))
        return list(ofertas.values())

    def buscar(self, q: str, categoria: str) -> list[Oferta]:
        dominios = self._get(f"/sites/MLA/domain_discovery/search?limit=1&q={quote(q)}") or []
        if not dominios:
            return []
        dominio = dominios[0].get("domain_id")
        res = self._get(f"/products/search?status=active&site_id=MLA&domain_id={quote(dominio)}&q={quote(q)}"
                        f"&limit={PRODUCTOS_POR_BUSQUEDA}") or {}
        items: list[tuple[dict, dict]] = []
        for p in (res.get("results") or [])[:PRODUCTOS_POR_BUSQUEDA]:
            pub = self._get(f"/products/{p['id']}/items") or {}
            for it in (pub.get("results") or []):
                if it.get("condition") == "new":
                    items.append((p, it))
        vendedores = {str(it.get("seller_id")) for _, it in items if it.get("seller_id") and not it.get("official_store_id")}
        reputacion = self._reputacion(sorted(vendedores))
        salida = []
        for p, it in items:
            oficial = bool(it.get("official_store_id"))
            if not oficial and reputacion.get(str(it.get("seller_id"))) not in LIDER:
                continue
            if o := self.oferta_de(p, it, categoria, oficial):
                salida.append(o)
        return salida

    def _reputacion(self, ids: list[str]) -> dict[str, str | None]:
        rep: dict[str, str | None] = {}
        for i in range(0, len(ids), 20):
            for u in self._get(f"/users?ids={','.join(ids[i:i + 20])}") or []:
                body = u.get("body") or u
                rep[str(body.get("id"))] = ((body.get("seller_reputation") or {}).get("power_seller_status"))
        return rep

    @staticmethod
    def oferta_de(p: dict, it: dict, categoria: str, oficial: bool) -> Oferta | None:
        precio = it.get("price")
        if not precio or it.get("currency_id", "ARS") != "ARS":
            return None
        titulo = p.get("name") or ""
        item_id = it.get("item_id") or it.get("id") or ""
        # el link de la publicación (MLA-123456789); el del producto de catálogo si no hay
        num = re.sub(r"^MLA", "", item_id)
        url = (f"https://articulo.mercadolibre.com.ar/MLA-{num}" if num else
               f"https://www.mercadolibre.com.ar/p/{p.get('id')}")
        return Oferta("mercadolibre", "AR", categoria, titulo, url, float(precio), "ARS", stock=True,
                      precio_lista=float(it["original_price"]) if it.get("original_price") else None,
                      datos={"vendedor": "tienda oficial" if oficial else "MercadoLíder"})

    def leer_pagina(self, url: str, categoria: str):  # no se usa
        return [], None
