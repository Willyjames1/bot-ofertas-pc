"""Comandos de Telegram. En Fase 1 solo los básicos; el resto llega en la Fase 2.
Se leen con getUpdates en cada corrida, así que pueden tardar hasta ~20 min en responder."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from .db import DB


def filtros_texto(cfg: dict) -> str:
    lineas = ["⚙️ <b>Filtros activos</b>"]
    for cat in ("placas", "cpu", "ram", "pcs", "mothers", "ssd", "fuentes", "refrigeracion", "gabinetes", "monitores"):
        c = cfg.get(cat) or {}
        if not c.get("activo"):
            continue
        partes = []
        for k, v in c.items():
            if k in ("activo", "objetivos", "objetivo"):
                continue
            partes.append(f"{k}: {v}")
        lineas.append(f"\n<b>{cat}</b>: " + escape("; ".join(partes)))
        objetivos = dict(c.get("objetivos") or {})
        if c.get("objetivo"):
            objetivos[f"{c.get('gpu_min', '')} o superior".strip()] = c["objetivo"]
        for mod, precios in objetivos.items():
            lineas.append(f"   🎯 {escape(str(mod))}: " + escape(", ".join(f"{m} {p:,}" for m, p in precios.items())))
    return "\n".join(lineas)


def estado_texto(db: DB) -> str:
    desde = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    filas = db.c.execute(
        "SELECT tienda, SUM(ok) ok, COUNT(*) n, MAX(productos) prod, "
        "(SELECT error FROM corridas_tienda c2 WHERE c2.tienda=c.tienda ORDER BY ts DESC LIMIT 1) ult_error "
        "FROM corridas_tienda c WHERE ts>=? GROUP BY tienda ORDER BY tienda", (desde,)).fetchall()
    if not filas:
        return "Todavía no hay corridas registradas en las últimas 24 h."
    lineas = ["📊 <b>Tiendas, últimas 24 h</b>"]
    for f in filas:
        ic = "✅" if f["ok"] == f["n"] else ("⚠️" if f["ok"] else "❌")
        extra = f" — {escape(f['ult_error'] or '')}" if f["ok"] < f["n"] else ""
        lineas.append(f"{ic} {f['tienda']}: {f['ok']}/{f['n']} corridas ok, {f['prod'] or 0} productos{extra}")
    return "\n".join(lineas)


def responder(texto: str, cfg: dict, db: DB) -> str:
    cmd = texto.split()[0].split("@")[0].lower()
    if cmd in ("/start", "/ayuda", "/help"):
        return ("👋 Hola. Te aviso de ofertas de hardware en Argentina y Australia.\n"
                "Comandos: /filtros, /estado.\nEn la Fase 2 llegan /seguir, /dejar, /objetivo, /precio, "
                "/top, /conviene, /aduana, /hermano, /pausa y /silencio.")
    if cmd == "/filtros":
        return filtros_texto(cfg)
    if cmd == "/estado":
        return estado_texto(db)
    return "Ese comando llega en la Fase 2. Por ahora: /filtros y /estado."
