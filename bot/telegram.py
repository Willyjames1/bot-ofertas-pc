"""Envío de mensajes por Telegram (los comandos los responde el Worker, por webhook).
Solo habla con los chat_id autorizados; a cualquier otro lo ignora."""
from __future__ import annotations

import logging
import time

import httpx

from .config import Secretos

log = logging.getLogger("bot.telegram")
LIMITE = 4000


class Telegram:
    def __init__(self, secretos: Secretos, dry_run: bool = False):
        self.s = secretos
        self.dry_run = dry_run or not secretos.token
        if not secretos.token and not dry_run:
            log.warning("No hay TELEGRAM_TOKEN: funciono en modo dry-run")
        self.http = httpx.Client(timeout=20)
        self.enviados: list[dict] = []  # para tests y dry-run

    def _api(self, metodo: str, intentos: int = 3, **datos) -> dict:
        # La URL lleva el token: nunca se loguea ni viaja en un mensaje de error.
        # Los cortes de red suelen ser momentáneos: reintenta con 2 y 4 segundos de pausa.
        for n in range(intentos):
            try:
                r = self.http.post(f"https://api.telegram.org/bot{self.s.token}/{metodo}", json=datos)
                j = r.json()
                break
            except (httpx.TransportError, ValueError) as e:
                if n == intentos - 1:
                    raise RuntimeError(f"Telegram {metodo}: error de red ({type(e).__name__})") from None
                time.sleep(2 * (n + 1))
        if not j.get("ok"):
            raise RuntimeError(f"Telegram {metodo}: {j.get('description')}")
        return j["result"]

    def enviar(self, chat_id: str, texto: str, silencioso: bool = False, botones: list | None = None) -> bool:
        """botones: inline_keyboard de Telegram (van en la última parte del mensaje)."""
        if not chat_id:
            return False
        if chat_id not in self.s.autorizados() and not self.dry_run:
            log.error("chat_id no autorizado, no envío")
            return False
        partes = [texto[i:i + LIMITE] for i in range(0, len(texto), LIMITE)] or [""]
        for n, parte in enumerate(partes):
            extra = {"reply_markup": {"inline_keyboard": botones}} if botones and n == len(partes) - 1 else {}
            self.enviados.append({"chat_id": chat_id, "texto": parte, "silencioso": silencioso, **extra})
            if self.dry_run:
                print(f"\n----- [DRY-RUN] a {'yo' if chat_id == self.s.chat_yo else 'hermano'}"
                      f"{' (silencioso)' if silencioso else ' (SUENA)'} -----\n{parte}\n")
                continue
            try:
                self._api("sendMessage", chat_id=chat_id, text=parte, parse_mode="HTML",
                          disable_web_page_preview=True, disable_notification=silencioso, **extra)
            except Exception as e:  # noqa: BLE001
                log.error("No pude enviar a Telegram: %s", e)
                return False
        return True
