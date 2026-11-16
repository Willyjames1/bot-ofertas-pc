"""Carga de config.yaml y secretos (.env / GitHub Secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

RAIZ = Path(__file__).resolve().parent.parent
TZ_AR = ZoneInfo("America/Argentina/Salta")
TZ_AU = ZoneInfo("Australia/Sydney")

try:  # .env solo existe en local
    from dotenv import load_dotenv

    load_dotenv(RAIZ / ".env")
except ImportError:  # pragma: no cover
    pass


@dataclass
class Secretos:
    token: str
    chat_yo: str
    chat_hermano: str

    @classmethod
    def desde_entorno(cls) -> "Secretos":
        return cls(
            token=os.getenv("TELEGRAM_TOKEN", "").strip(),
            chat_yo=os.getenv("TELEGRAM_CHAT_ID_YO", "").strip(),
            chat_hermano=os.getenv("TELEGRAM_CHAT_ID_HERMANO", "").strip(),
        )

    def autorizados(self) -> set[str]:
        return {c for c in (self.chat_yo, self.chat_hermano) if c}


def ruta_db() -> Path:
    return RAIZ / os.getenv("BOT_DB", "datos/precios.db")


def cargar(ruta: Path | None = None) -> dict:
    ruta = ruta or RAIZ / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _a_fecha(v) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def es_black_friday(cfg: dict, ahora: datetime | None = None) -> bool:
    bf = cfg.get("black_friday") or {}
    if not bf:
        return False
    hoy = (ahora or datetime.now(TZ_AR)).astimezone(TZ_AR).date()
    return _a_fecha(bf["desde"]) <= hoy <= _a_fecha(bf["hasta"])


def ajustes(cfg: dict, ahora: datetime | None = None) -> dict:
    """Ajustes efectivos: general + frecuencia, pisados por el modo Black Friday si corresponde."""
    g = dict(cfg.get("general") or {})
    fr = dict(cfg.get("frecuencia") or {})
    av = dict(cfg.get("avisos") or {})
    efectivo = {**fr, **g, **av, "black_friday": False}
    if es_black_friday(cfg, ahora):
        bf = cfg["black_friday"]
        for k in ("feeds_cada_min", "tiendas_cada_min", "votos_ozbargain_urgente",
                  "tope_alertas_que_suenan_por_dia"):
            if k in bf:
                efectivo[k] = bf[k]
        efectivo["black_friday"] = True
    efectivo.setdefault("feeds_cada_min", 20)
    efectivo.setdefault("tiendas_cada_min", 20)
    efectivo.setdefault("turnos_tiendas", 2)
    efectivo.setdefault("votos_ozbargain_urgente", 25)
    efectivo.setdefault("tope_alertas_que_suenan_por_dia", 6)
    efectivo.setdefault("re_aviso_baja_pct", 3)
    efectivo.setdefault("sospechoso_vs_mediana_pct", 40)
    efectivo.setdefault("horas_historial_para_minimo", 24)
    efectivo.setdefault("silencio_noche", {"desde": "00:00", "hasta": "08:00"})
    return efectivo
