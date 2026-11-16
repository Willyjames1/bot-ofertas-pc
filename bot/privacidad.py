"""Que nada sensible llegue a los logs (los de GitHub Actions son públicos en un repo público).

Tacha el token de Telegram, los chat_id y cualquier URL de la API de Telegram de TODO lo que
se escribe con logging, incluidos los tracebacks, y también de los errores no capturados."""
from __future__ import annotations

import logging
import os
import re
import sys
import traceback

RE_API_TELEGRAM = re.compile(r"https?://api\.telegram\.org/\S*", re.I)
RE_TOKEN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")  # forma de cualquier token de bot
VARIABLES_SECRETAS = ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID_YO", "TELEGRAM_CHAT_ID_HERMANO")


def tachar(texto: str) -> str:
    if not texto:
        return texto
    texto = RE_API_TELEGRAM.sub("[API de Telegram]", texto)
    texto = RE_TOKEN.sub("[token]", texto)
    for var in VARIABLES_SECRETAS:
        valor = os.getenv(var, "").strip()
        if len(valor) >= 4:
            texto = texto.replace(valor, f"[{var.lower()}]")
    return texto


class FormatoSeguro(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return tachar(super().format(record))


def _excepthook(tipo, valor, tb):
    sys.stderr.write(tachar("".join(traceback.format_exception(tipo, valor, tb))))


def configurar_logs(verbose: bool = False):
    h = logging.StreamHandler()
    h.setFormatter(FormatoSeguro("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S"))
    raiz = logging.getLogger()
    raiz.handlers[:] = [h]
    raiz.setLevel(logging.DEBUG if verbose else logging.INFO)
    # httpx/httpcore loguean cada pedido con la URL completa (la de Telegram lleva el token): apagados
    for nombre in ("httpx", "httpcore", "hpack", "urllib3"):
        logging.getLogger(nombre).setLevel(logging.WARNING)
    sys.excepthook = _excepthook
