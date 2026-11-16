"""Registro de tiendas. Importar un módulo acá lo registra automáticamente."""
from .base import TIENDAS, Tienda, registrar  # noqa: F401

# Las tiendas se importan acá a medida que se suman (una por archivo).
import importlib
import pkgutil

for _m in pkgutil.iter_modules(__path__):
    if _m.name not in ("base",):
        importlib.import_module(f"{__name__}.{_m.name}")
