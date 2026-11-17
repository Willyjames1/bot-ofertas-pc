"""eBay Australia por la API oficial (Browse API): PCs armadas nuevas, de vendedores ubicados en
Australia, con placa pcs.gpu_min o superior y procesador Ryzen 7/9, Core i7/i9 o Core Ultra 7/9.

Además sigue de cerca a los vendedores de ebay.vendedores_seguidos (HP Official Store): busca
sus OMEN y Victus y, si un modelo desaparece de la búsqueda, lo marca sin stock para avisar cuando
vuelve (lo hace corrida.py con `marcar_faltantes`).

Necesita EBAY_CLIENT_ID y EBAY_CLIENT_SECRET (App ID y Cert ID de developer.ebay.com, keyset
de Production). Sin eso no se lee y no cuenta como tienda caída. Las claves nunca se loguean."""
from __future__ import annotations

import base64
import logging
import os
from urllib.parse import urlsplit, urlunsplit

from .. import alertas, config
from ..modelos import Oferta
from ..normalizar import normalizar
from ..red import Cliente
from .base import Tienda, registrar

log = logging.getLogger("bot.fuentes")
URL_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
URL_BUSQUEDA = "https://api.ebay.com/buy/browse/v1/item_summary/search"
ALCANCE = "https://api.ebay.com/oauth/api_scope"
NUEVO = "1000"   # conditionId de "New"


def _sin_query(url: str) -> str:
    """El link sin el rastreo (?hash=..., &amdata=...): sirve de clave estable del producto."""
    s = urlsplit(url)
    return urlunsplit((s.scheme, s.netloc, s.path, "", ""))


def cpu_alcanza(datos: dict, tier_min: int) -> bool:
    """Ryzen 7/9, Core i7/i9 o Core Ultra 7/9 (tier_min=7)."""
    tier = datos.get("cpu_tier")
    return tier is not None and tier >= tier_min


@registrar
class EBay(Tienda):
    id = "ebay"
    nombre = "eBay AU"
    pais = "AU"
    moneda = "AUD"
    web = "https://www.ebay.com.au"
    pausa = (1.0, 2.0)
    categorias = {"pcs": []}         # se arman con config.yaml → ebay
    marcar_faltantes = ()            # se completa con los vendedores seguidos (tienda "ebay_<usuario>")

    def __init__(self, cliente=None, cfg: dict | None = None, token: str | None = None):
        # API oficial: no es scraping, robots.txt del sitio no aplica a api.ebay.com
        super().__init__(cliente or Cliente(pausa=self.pausa, timeout=30, respetar_robots=False))
        self.cfg = cfg if cfg is not None else config.cargar()
        self.e = self.cfg.get("ebay") or {}
        self.seguidos: dict[str, str] = dict(self.e.get("vendedores_seguidos") or {})
        self.marcar_faltantes = tuple(f"ebay_{u}" for u in self.seguidos)
        self._token = token

    @staticmethod
    def tiendas_seguidas(cfg: dict) -> list[str]:
        """Las "tiendas" (ebay_<usuario>) cuyos productos se marcan sin stock si dejan de aparecer."""
        return [f"ebay_{u.lower()}" for u in ((cfg.get("ebay") or {}).get("vendedores_seguidos") or {})]

    # ------------------------------------------------------------------ API
    def token(self) -> str | None:
        if self._token:
            return self._token
        cid, sec = os.getenv("EBAY_CLIENT_ID", "").strip(), os.getenv("EBAY_CLIENT_SECRET", "").strip()
        if not (cid and sec):
            return None
        auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        try:
            r = self.cliente.http.post(URL_TOKEN, headers={"Authorization": f"Basic {auth}",
                                                          "Content-Type": "application/x-www-form-urlencoded"},
                                       data={"grant_type": "client_credentials", "scope": ALCANCE})
            r.raise_for_status()
            self._token = r.json()["access_token"]
        except Exception as e:  # noqa: BLE001 — nunca loguear la respuesta: podría traer datos de la cuenta
            raise RuntimeError(f"eBay no dio el token de acceso ({type(e).__name__})") from None
        return self._token

    def buscar(self, q: str, vendedor: str | None = None) -> list[dict]:
        filtros = [f"itemLocationCountry:AU", f"conditionIds:{{{NUEVO}}}", "buyingOptions:{FIXED_PRICE}",
                   "deliveryCountry:AU", "priceCurrency:AUD"]
        if vendedor:
            filtros.append(f"sellers:{{{vendedor}}}")
        else:
            filtros.append(f"price:[1000..{int(self.e.get('precio_max_aud', 6000))}]")
        params = {"q": q, "filter": ",".join(filtros), "limit": 100, "sort": "price"}
        if self.e.get("categoria"):
            params["category_ids"] = str(self.e["categoria"])
        r = self.cliente.get(URL_BUSQUEDA, params=params,
                             headers={"Authorization": f"Bearer {self.token()}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_AU",
                                      "Accept": "application/json"})
        return r.json().get("itemSummaries") or []

    # ------------------------------------------------------------------ lectura
    def leer(self, categoria: str) -> list[Oferta]:
        if categoria != "pcs" or not self.e.get("activo", True):
            return []
        if not self.token():
            log.info("eBay: faltan EBAY_CLIENT_ID / EBAY_CLIENT_SECRET, no lo leo")
            return []
        vistas: dict[str, Oferta] = {}
        busquedas = [(q, None) for q in self.e.get("busquedas") or []]
        busquedas += [(m, u) for u in self.seguidos for m in self.e.get("modelos_seguidos") or []]
        for q, vendedor in busquedas:
            for item in self.buscar(q, vendedor):
                o = self.oferta_de(item)
                if o and o.url not in vistas:
                    vistas[o.url] = o
        log.info("ebay/pcs: %d PCs que pasan los filtros", len(vistas))
        return list(vistas.values())

    def leer_pagina(self, url: str, categoria: str):  # no se usa
        return [], None

    def oferta_de(self, item: dict) -> Oferta | None:
        vendedor = ((item.get("seller") or {}).get("username") or "").lower()
        if (item.get("itemLocation") or {}).get("country", "AU") != "AU":
            return None
        if str(item.get("conditionId", NUEVO)) != NUEVO:
            return None
        try:
            precio = float((item.get("price") or {}).get("value"))
        except (TypeError, ValueError):
            return None
        tid = f"ebay_{vendedor}"
        seguido = vendedor in {u.lower() for u in self.seguidos}
        alertas.NOMBRE_TIENDA[tid] = (self.seguidos.get(vendedor) or f"eBay · {vendedor}") + (" (eBay)" if seguido else "")
        o = normalizar(Oferta(
            tienda=tid, pais="AU", moneda="AUD", categoria="pcs", titulo=item.get("title", ""),
            url=_sin_query(item.get("itemWebUrl", "")), precio=precio, tipo_precio="unico", stock=True,
            sku=item.get("legacyItemId") or item.get("itemId"),
            datos={"via": "eBay", "vendedor": vendedor, "seguido": seguido}))
        if o.descartada or not o.modelo:
            return None
        if not alertas.gpu_alcanza(self.cfg.get("pcs") or {}, o.datos):
            return None
        if not cpu_alcanza(o.datos, int(self.e.get("cpu_tier_min", 7))):
            return None
        return o
