"""Cliente HTTP "buen vecino": User-Agent normal, pausa entre pedidos al mismo sitio,
respeta robots.txt, reintenta con espera y NO intenta pasar captchas ni protecciones."""
from __future__ import annotations

import logging
import random
import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger("bot.red")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
CABECERAS = {"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
             "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7"}
SENALES_BLOQUEO = ("Just a moment...", "challenges.cloudflare.com", "Human Verification",
                   "awsWafCookieDomainList", "cf-chl-", "Attention Required!", "captcha-delivery")


class Bloqueado(Exception):
    """La tienda pide captcha / desafío anti-bots. No se evade: se marca como caída."""


class ProhibidoPorRobots(Exception):
    pass


class Cliente:
    def __init__(self, pausa: tuple[float, float] = (3.0, 5.0), timeout: float = 25.0,
                 reintentos: int = 3, respetar_robots: bool = True):
        self.pausa = pausa
        self.reintentos = reintentos
        self.respetar_robots = respetar_robots
        self.http = httpx.Client(headers=CABECERAS, timeout=timeout, follow_redirects=True)
        self._ultimo: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self.pedidos = 0

    def cerrar(self):
        self.http.close()

    # -------------------------------------------------------------- robots

    def _robots_para(self, url: str) -> RobotFileParser | None:
        p = urlsplit(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.http.get(base + "/robots.txt")
                if r.status_code == 200 and "text/html" not in r.headers.get("content-type", ""):
                    rp.parse(r.text.splitlines())
                else:
                    rp = None  # sin robots.txt => todo permitido
            except httpx.HTTPError:
                rp = None
            self._robots[base] = rp
        return self._robots[base]

    def permitido(self, url: str) -> bool:
        if not self.respetar_robots:
            return True
        rp = self._robots_para(url)
        return True if rp is None else rp.can_fetch(UA, url)

    # -------------------------------------------------------------- pedidos

    def _esperar_turno(self, host: str, minimo: float = 0.0):
        with self._lock:
            ultimo = self._ultimo.get(host, 0.0)
            espera = ultimo + max(random.uniform(*self.pausa), minimo) - time.monotonic()
            self._ultimo[host] = time.monotonic() + max(espera, 0)
        if espera > 0:
            time.sleep(espera)

    def get(self, url: str, **kw) -> httpx.Response:
        if not self.permitido(url):
            raise ProhibidoPorRobots(url)
        host = urlsplit(url).netloc
        rp = self._robots_para(url) if self.respetar_robots else None
        crawl_delay = float((rp.crawl_delay(UA) if rp else None) or 0)
        ultimo_error: Exception | None = None
        for intento in range(1, self.reintentos + 1):
            self._esperar_turno(host, crawl_delay)
            try:
                r = self.http.get(url, **kw)
                self.pedidos += 1
            except httpx.HTTPError as e:
                ultimo_error = e
                log.warning("Error de red en %s (intento %d): %s", url, intento, e)
                time.sleep(5 * intento)
                continue
            cuerpo = r.text[:6000] if r.headers.get("content-type", "").startswith(("text", "application/xhtml")) else ""
            if r.status_code in (403, 405, 503) and any(s in cuerpo for s in SENALES_BLOQUEO):
                raise Bloqueado(f"{host} pide verificación anti-bots (HTTP {r.status_code})")
            if r.status_code == 429 or r.status_code >= 500:
                espera = int(r.headers.get("retry-after", "0") or 0) or 15 * intento
                log.warning("HTTP %s en %s, espero %ss", r.status_code, url, espera)
                ultimo_error = httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                time.sleep(min(espera, 60))
                continue
            r.raise_for_status()
            return r
        raise ultimo_error or RuntimeError(f"No pude leer {url}")
