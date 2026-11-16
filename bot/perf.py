"""Lectura de perf.yaml.

Fase 1: la "oportunidad fuerte" usa SOLO el orden de gamas (lista `gama`), no los números.
Los índices de juegos/DaVinci quedan cargados para /top, el resumen y la web (Fase 2),
cuando estén los datos reales."""
from __future__ import annotations

from functools import lru_cache

import yaml

from .config import RAIZ
from .normalizar import canon


@lru_cache(maxsize=1)
def _crudo() -> dict:
    with open(RAIZ / "perf.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def orden() -> dict[str, dict[str, int]]:
    """{'placas': {'rtx 5070 ti': 21, ...}} posición en la lista de gamas (mayor = mejor)."""
    gama = _crudo().get("gama") or {}
    return {cat: {canon(m): i for i, m in enumerate(lista or [])} for cat, lista in gama.items()}


@lru_cache(maxsize=1)
def indices() -> dict[str, dict[str, dict]]:
    d = _crudo()
    return {cat: {canon(k): v for k, v in (d.get(cat) or {}).items()} for cat in ("placas", "cpu")}


def clave_perf(categoria: str, modelo: str, datos: dict) -> str | None:
    """Nombre del modelo tal como figura en la lista de gamas, o None si no está."""
    tabla = orden().get(categoria, {})
    if categoria == "placas":
        for k in (f"{datos.get('chip')} {datos.get('vram')}GB", str(datos.get("chip"))):
            if canon(k) in tabla:
                return canon(k)
        return None
    return canon(modelo) if canon(modelo) in tabla else None


def indice(categoria: str, clave: str) -> dict | None:
    return indices().get(categoria, {}).get(clave)


def domina(categoria: str, alto: str, bajo: str) -> bool:
    """True si 'alto' está más arriba que 'bajo' en el orden de gamas."""
    tabla = orden().get(categoria, {})
    return alto in tabla and bajo in tabla and tabla[alto] > tabla[bajo]
