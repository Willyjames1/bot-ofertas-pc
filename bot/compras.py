"""Lo que te falta comprar (config.yaml → compras): cada cosa con su filtro, en qué país se busca,
el objetivo y el umbral de baja. Solo esto suena por bajas de precio; lo de 'comprado' no avisa más.

Lo que puede traer tu hermano de Australia (compras.hermano.trae) se busca en los dos países; el
resto, solo en Argentina. La aduana de lo que traiga se calcula sobre el TOTAL: la franquicia de
USD 500 es una sola por persona (ver canasta_hermano)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import normalizar as N

CERT_ORDEN = {"White": 0, "Bronze": 1, "Silver": 2, "Gold": 3, "Platinum": 4, "Titanium": 5}
UMBRALES_POR_DEFECTO = {"placas": 8, "ram": 10, "ssd": 10, "mothers": 10, "fuentes": 10, "gabinetes": 10,
                        "refrigeracion": 10, "teclados": 15, "mouse": 15, "cpu": 10, "pcs": 10}
ICONO = {"placas": "🎮", "cpu": "🧠", "ram": "💾", "ssd": "💽", "mothers": "🔌", "fuentes": "⚡",
         "refrigeracion": "❄️", "gabinetes": "🗄️", "teclados": "⌨️", "mouse": "🖱️", "pcs": "🖥️"}


def _datos(fila: dict) -> dict:
    d = fila.get("datos")
    return json.loads(d) if isinstance(d, str) else dict(d or {})


@dataclass
class Item:
    nombre: str
    categoria: str
    paises: list[str]
    objetivo: dict = field(default_factory=dict)    # {"AUD": 1440, "USD": 1250} (USD: Argentina, en MEP)
    filtro: dict = field(default_factory=dict)
    umbral: float = 10

    def cumple(self, fila: dict) -> bool:
        """fila: una de la tabla ofertas (o un dict con categoria, modelo, datos, titulo, tray, combo)."""
        if fila.get("categoria") and fila["categoria"] != self.categoria:
            return False
        if fila.get("combo"):
            return False
        d, f, cat = _datos(fila), self.filtro, self.categoria
        titulo = N.limpiar(fila.get("titulo") or "")
        if cat == "placas":
            chip, vram = N.parsear_chip_config(f.get("chip") or self.nombre)
            return d.get("chip") == chip and (vram is None or d.get("vram") == vram)
        if cat == "ram":
            from .alertas import ram_cumple
            if not ram_cumple(str(f.get("ram") or self.nombre), d):
                return False
            cl = d.get("cl")
            if f.get("cl_max") or f.get("cl_min"):
                return cl is not None and (f.get("cl_min") or 0) <= cl <= (f.get("cl_max") or 99)
            return True
        if cat == "ssd":
            s = N.datos_ssd(titulo) if titulo else d
            if isinstance(s, str) or not N.ssd_estandar(s):
                return False
            return (s.get("capacidad_tb") == f.get("capacidad_tb", s.get("capacidad_tb"))
                    and (s.get("gen") or 0) >= f.get("gen_min", 4)
                    and (not f.get("lectura_min") or (s.get("lectura") or 0) >= f["lectura_min"]))
        if cat == "mothers":
            if (ch := f.get("chipsets")) and d.get("chipset") not in ch:
                return False
            if f.get("wifi") and not d.get("wifi"):
                return False
            if (lineas := f.get("lineas")) and not any(N.limpiar(x) in (d.get("linea") or "") or
                                                        N.limpiar(x) in titulo for x in lineas):
                return False
            return d.get("formato") != "ITX"
        if cat == "fuentes":
            if d.get("sfx") or (d.get("watts") or 0) < f.get("watts_min", 0):
                return False
            if (c := f.get("certificacion_min")) and CERT_ORDEN.get(d.get("certificacion") or "", -1) < CERT_ORDEN[c]:
                return False
            return not f.get("atx_min") or (d.get("atx") or 0) >= float(f["atx_min"])
        if cat == "refrigeracion":
            return d.get("tipo") == "AIO" and (not f.get("radiador") or d.get("radiador") == f["radiador"])
        if cat == "gabinetes":
            if d.get("con_fuente") or d.get("formato") in ("mini", "itx"):
                return False
            conocidos = [N.limpiar(x) for x in f.get("modelos_360") or []]
            return bool(d.get("rad360") and d.get("formato") in ("mid", None)) or any(m in titulo for m in conocidos)
        if cat in ("teclados", "mouse", "cpu"):
            modelos = [N.limpiar(x) for x in f.get("modelos") or []]
            return any(m in titulo or m == N.limpiar(fila.get("modelo") or "") for m in modelos)
        return False

    def objetivo_en(self, moneda: str) -> float | None:
        v = self.objetivo.get(moneda)
        return float(v) if v else None


def items(cfg: dict) -> list[Item]:
    c = cfg.get("compras") or {}
    trae = set(((c.get("hermano") or {}).get("trae")) or [])
    umbrales = {**UMBRALES_POR_DEFECTO, **(cfg.get("umbrales_baja") or {})}
    salida = []
    for x in c.get("items") or []:
        x = dict(x)
        nombre, cat = str(x.pop("nombre")), x.pop("categoria")
        paises = x.pop("paises", None) or (["AU", "AR"] if cat in trae else ["AR"])
        objetivo = x.pop("objetivo", None) or {}
        salida.append(Item(nombre, cat, list(paises), objetivo, x, float(umbrales.get(cat, 10))))
    return salida


def item_de(cfg: dict, fila: dict, pais: str | None = None) -> Item | None:
    pais = pais or fila.get("pais")
    for it in items(cfg):
        if (pais is None or pais in it.paises) and it.cumple(fila):
            return it
    return None


def comprado(cfg: dict, categoria: str) -> str | None:
    """Lo que ya compraste de esa categoría (compras.comprado: {cpu: Ryzen 9 9900X}): la categoría no avisa más."""
    return ((cfg.get("compras") or {}).get("comprado") or {}).get(categoria)


def umbral(cfg: dict, categoria: str) -> float:
    return float({**UMBRALES_POR_DEFECTO, **(cfg.get("umbrales_baja") or {})}.get(categoria, 10))


def hermano(cfg: dict) -> dict:
    h = ((cfg.get("compras") or {}).get("hermano")) or {}
    return {"franquicia_usd": float(h.get("franquicia_usd", 500)), "trae": list(h.get("trae") or []),
            "viaje": h.get("viaje")}
