"""Cliente HTTP "buen vecino": User-Agent normal, pausa entre pedidos al mismo sitio,
respeta robots.txt, reintenta con espera y NO intenta pasar captchas ni protecciones."""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("bot.red")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
CABECERAS = {"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
             "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7"}
SENALES_BLOQUEO = ("Just a moment...", "challenges.cloudflare.com", "Human Verification",
                   "awsWafCookieDomainList", "cf-chl-", "Attention Required!", "captcha-delivery")


class Robots:
    """robots.txt con comodines (* y $), como lo interpretan Google y Bing: gana la regla más
    larga que coincida y, a igual largo, Allow. (El robotparser de Python ignora los comodines,
    y Umart/MSY prohíben justamente /*sort=*, /*brand=*, etc.)"""

    def __init__(self, texto: str, agente: str = "*"):
        grupos: list[tuple[list[str], list[tuple[bool, str]], float | None]] = []
        agentes: list[str] = []
        reglas: list[tuple[bool, str]] = []
        demora: float | None = None
        ultimo_fue_agente = False
        for linea in texto.splitlines():
            linea = linea.split("#", 1)[0].strip()
            if ":" not in linea:
                continue
            campo, valor = (x.strip() for x in linea.split(":", 1))
            campo = campo.lower()
            if campo == "user-agent":
                if not ultimo_fue_agente and agentes:
                    grupos.append((agentes, reglas, demora))
                    agentes, reglas, demora = [], [], None
                agentes.append(valor.lower())
                ultimo_fue_agente = True
                continue
            ultimo_fue_agente = False
            if campo in ("allow", "disallow") and valor:
                reglas.append((campo == "allow", valor))
            elif campo == "crawl-delay":
                try:
                    demora = float(valor)
                except ValueError:
                    pass
        if agentes:
            grupos.append((agentes, reglas, demora))
        elegido = next((g for g in grupos if agente.lower() in g[0]), None) or             next((g for g in grupos if "*" in g[0]), None)
        self.reglas = [(permite, len(patron), self._regex(patron)) for permite, patron in (elegido[1] if elegido else [])]
        self.demora = elegido[2] if elegido else None

    @staticmethod
    def _regex(patron: str) -> re.Pattern:
        fin = patron.endswith("$")
        cuerpo = re.escape(patron.rstrip("$")).replace(r"\*", ".*")
        return re.compile(cuerpo + ("$" if fin else ""))

    def permite(self, url: str) -> bool:
        p = urlsplit(url)
        ruta = (p.path or "/") + (f"?{p.query}" if p.query else "")
        mejor: tuple[int, bool] | None = None
        for permite, largo, rx in self.reglas:
            if rx.match(ruta) and (mejor is None or largo > mejor[0] or (largo == mejor[0] and permite)):
                mejor = (largo, permite)
        return True if mejor is None else mejor[1]


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
        self._robots: dict[str, Robots | None] = {}
        self._lock = threading.Lock()
        self.pedidos = 0

    def cerrar(self):
        self.http.close()

    # -------------------------------------------------------------- robots

    def _robots_para(self, url: str) -> Robots | None:
        p = urlsplit(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            try:
                r = self.http.get(base + "/robots.txt")
                if r.status_code == 200 and "text/html" not in r.headers.get("content-type", ""):
                    rp = Robots(r.text)
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
        return True if rp is None else rp.permite(url)

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
        crawl_delay = float((rp.demora if rp else None) or 0)
        ultimo_error: Exception | None = None
        for intento in range(1, self.reintentos + 1):
            self._esperar_turno(host, crawl_delay)
            try:
                r = self.http.get(url, **kw)
                self.pedidos += 1
            except httpx.HTTPError as e:
                ultimo_error = e
                log.warning("Error de red en %s (intento %d): %s", url, intento, e)
                if intento < self.reintentos:   # en el último intento no tiene sentido esperar
                    time.sleep(5 * intento)
                continue
            cuerpo = r.text[:6000] if r.headers.get("content-type", "").startswith(("text", "application/xhtml")) else ""
            if r.status_code in (403, 405, 503) and any(s in cuerpo for s in SENALES_BLOQUEO):
                raise Bloqueado(f"{host} pide verificación anti-bots (HTTP {r.status_code})")
            if r.status_code == 429 and intento >= 2:
                # ya esperamos lo que pidió y sigue frenando: no insistimos
                raise Bloqueado(f"{host} contesta 429 (demasiados pedidos)")
            if r.status_code == 429 or r.status_code >= 500:
                espera = int(r.headers.get("retry-after", "0") or 0) or 15 * intento
                if intento < self.reintentos:
                    log.warning("HTTP %s en %s, espero %ss", r.status_code, url, espera)
                ultimo_error = httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                if intento < self.reintentos:
                    time.sleep(min(espera, 60))
                continue
            r.raise_for_status()
            return r
        raise ultimo_error or RuntimeError(f"No pude leer {url}")
