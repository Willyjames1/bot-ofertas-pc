"""Exporta un JSON chico para el Worker de Cloudflare que responde /buscar desde Telegram.

Va a la rama "datos" junto con precios.db, al final de cada corrida. Tiene que ser chico: el
Worker gratis tiene 10 ms de CPU por pedido, y parsear el JSON es lo que más gasta. Por eso:
  - nada sin stock: solo lo que apareció en la última pasada de su tienda (o comparador), sin combos
    ni sospechosos; si la tienda no se pudo leer hace horas, o el stock no se pudo confirmar en la
    tienda real (staticICE, HardGamers), va igual pero marcado "sin confirmar" (y al final)
  - de cada modelo y país, las POR_MODELO más baratas (el Worker muestra 5)
  - todo en listas, con las tiendas y los modelos en una tabla aparte

También van las cotizaciones, las reglas de la cuenta (aduana, valija), los posts recientes de
OzBargain y los textos de /estado y /filtros ya armados (los arma el mismo código que antes).

  python -m bot exportar [--salida archivo.json]     # a mano, para mirarlo
  python -m bot generar-worker                      # regenera worker/src/normalizador_gen.js
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import comandos, normalizar as N
from .comparar import CONVIENE_PCT, HORAS_OTRO_PAIS, valija_de
from .config import RAIZ
from .cotizaciones import ARANCEL, FRANQUICIA_USD, Cotizacion
from .db import DB

VERSION = 2
POR_MODELO = 16     # lo máximo que deja pedir /buscar (r16)
HORAS_POSTS = 48
MAX_POSTS = 40
CATEGORIAS = ("placas", "cpu", "ram", "ssd", "pcs")
# lo que el Worker necesita de cada modelo para saber si coincide con la búsqueda
CAMPOS = {"placas": ("chip", "vram"), "cpu": ("marca", "nucleos"),
          "ram": ("capacidad_gb", "modulos", "velocidad", "cl"),
          "ssd": ("capacidad_tb", "interfaz", "gen"), "pcs": ("chip", "ram_gb", "ssd_tb", "cpu", "nucleos")}
TIPOS_PRECIO = ("transferencia", "contado")


def ruta_json() -> Path:
    return RAIZ / os.getenv("BOT_JSON", "datos/precios.json")


def _detalle(cat: str, r, d: dict) -> str:
    """Lo que va al lado de la tienda: la marca y línea, o el procesador/RAM/disco de una PC."""
    if cat == "pcs":
        partes = [d.get("cpu"), f"{d['ram_gb']}GB RAM" if d.get("ram_gb") else None,
                  f"{d['ssd_tb']:g}TB SSD" if d.get("ssd_tb") else None]
        partes = [p for p in partes if p]
        return " · ".join(partes) if partes else (r["titulo"] or "")[:60]
    return r["variante"] or ""


def armar(db: DB, cfg: dict, cot: Cotizacion | None, nombres: dict, ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    desde = ahora - timedelta(hours=HORAS_OTRO_PAIS)
    tiendas: list[str] = []
    i_tienda: dict[str, int] = {}
    modelos: list[list] = []
    i_modelo: dict[tuple[str, str], int] = {}
    filas: list[list] = []
    motivos: list[str] = [""]          # [0] = stock confirmado; el resto, por qué no se pudo confirmar
    i_motivo: dict[str, int] = {"": 0}
    for pais in ("AR", "AU"):
        for cat in CATEGORIAS:
            vistos: Counter = Counter()
            for r in db.vigentes(pais, cat, desde, ahora):   # sin las que no tienen stock; confirmadas primero
                if not r["precio"] or vistos[r["modelo"]] >= POR_MODELO:
                    continue
                vistos[r["modelo"]] += 1
                d = json.loads(r["datos"] or "{}")
                clave = (cat, r["modelo"])
                if clave not in i_modelo:
                    i_modelo[clave] = len(modelos)
                    modelos.append([r["modelo"], cat, {k: d[k] for k in CAMPOS[cat] if d.get(k) is not None}])
                if r["tienda"] not in i_tienda:
                    i_tienda[r["tienda"]] = len(tiendas)
                    tiendas.append(nombres.get(r["tienda"], r["tienda"]))
                visto = datetime.fromisoformat(r["ultima_vez"])
                motivo = "" if r["stock_ok"] else (r["stock_motivo"] or "stock sin confirmar")
                if motivo not in i_motivo:
                    i_motivo[motivo] = len(motivos)
                    motivos.append(motivo)
                filas.append([
                    i_modelo[clave], pais, round(r["precio"]), i_tienda[r["tienda"]], r["url"],
                    _detalle(cat, r, d),
                    max(0, int((ahora - visto).total_seconds() // 60)),     # hace cuántos minutos se vio
                    r["tipo_precio"] if r["tipo_precio"] in TIPOS_PRECIO else "",
                    1 if d.get("via") == "staticICE" else 0,                # vino de staticICE
                    i_motivo[motivo],                                       # 0 = stock confirmado
                ])
    limite = (ahora - timedelta(hours=HORAS_POSTS)).isoformat(timespec="seconds")
    posts = [[p["titulo"], p["url"], p["votos"], p["precio"],
              max(0, int((ahora - datetime.fromisoformat(p["publicado"])).total_seconds() // 60))]
             for p in db.c.execute("SELECT * FROM posts WHERE fuente='ozbargain' AND publicado>=? "
                                   "ORDER BY publicado DESC LIMIT ?", (limite, MAX_POSTS))]
    return {
        "v": VERSION,
        "ts": ahora.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "cot": ({"mep": cot.mep, "aud_usd": cot.aud_usd, "nota": cot.nota_respaldo()} if cot else None),
        "reglas": {"franquicia_usd": FRANQUICIA_USD, "arancel": ARANCEL, "valija_aud": valija_de(cfg),
                   "conviene_pct": CONVIENE_PCT},
        "tiendas": tiendas,
        "modelos": modelos,
        # [modelo, país, precio, tienda, link, detalle, hace_min, tipo_precio, staticICE, motivo]
        "p": filas,
        "motivos": motivos,
        # los "❌ Sin stock" que ya incorporó la base (clave = sha1(link)[:16] → cuándo lo tocaste). El
        # Worker oculta lo que tocaste DESPUÉS (todavía no está acá); lo de acá ya lo resuelve la base:
        # fuera del JSON mientras siga sin stock, de vuelta cuando la tienda lo tiene otra vez
        "ocultos": {o["h"]: o["ts"] for o in db.c.execute("SELECT h, ts FROM ocultos")},
        # [título, link, votos, precio A$, hace_min]
        "posts": posts,
        "estado": comandos.estado_texto(db),
        "filtros": comandos.filtros_texto(cfg),
    }


def por_categoria(datos: dict) -> dict[str, dict]:
    """Además del JSON completo, uno chico por categoría (lo que lee el Worker para cada búsqueda:
    leer 300 KB enteros en cada pedido se pasaba de los 10 ms de CPU del plan gratis) y un índice
    sin precios (chips, /estado y /filtros). Cada uno tiene el mismo formato que el completo."""
    chips = sorted({m[2]["chip"] for m in datos["modelos"] if m[2].get("chip")})
    salida = {"indice": {**datos, "modelos": [], "p": [], "chips": chips}}
    for cat in CATEGORIAS:
        nuevo: dict[int, int] = {}
        modelos = []
        for i, m in enumerate(datos["modelos"]):
            if m[1] == cat:
                nuevo[i] = len(modelos)
                modelos.append(m)
        filas = [[nuevo[f[0]], *f[1:]] for f in datos["p"] if f[0] in nuevo]
        salida[cat] = {**datos, "modelos": modelos, "p": filas, "chips": chips}
    return salida


def guardar_todo(datos: dict, ruta: Path) -> int:
    """precios.json y, al lado, precios-indice.json y precios-<categoría>.json. Devuelve los bytes del completo."""
    for nombre, parte in por_categoria(datos).items():
        guardar(parte, ruta.with_name(f"{ruta.stem}-{nombre}{ruta.suffix}"))
    return guardar(datos, ruta)


def guardar(datos: dict, ruta: Path) -> int:
    """Escribe el JSON compacto (sin espacios) de forma atómica. Devuelve los bytes."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(ruta)
    return len(texto.encode("utf-8"))


# ------------------------------------------------------------------ regexes para el Worker

# Las mismas expresiones que usan los avisos, para que el Worker entienda la búsqueda igual
# ("5070ti", "rtx 5070 ti" y "5070 Ti 16GB" → RTX 5070 Ti). Python y JavaScript comparten la
# sintaxis de todas estas (lookbehind incluido); el test de paridad corre las dos y compara.
REGEXES = ("USADO", "NOTEBOOK", "PC_ARMADA", "TRAY", "RE_NVIDIA", "RE_NVIDIA_PEGADO", "RE_AMD", "RE_VRAM",
           "RE_RYZEN", "RE_RYZEN_SUELTO", "RE_ULTRA", "RE_ULTRA_LEJOS", "RE_ULTRA_PLUS", "RE_I14",
           "RE_CORSAIR", "RE_GSKILL", "RE_KINGSTON", "RE_KIT", "RE_KIT_INV", "RE_GB", "RE_VEL", "RE_VEL_DDR", "RE_VEL_SUELTA", "RE_CL",
           "SSD_NO", "SSD_SI", "RE_SSD_TB", "RE_SSD_GB", "RE_SSD_GEN")
TABLAS = ("VRAM_VALIDAS", "VRAM_POR_DEFECTO", "LINEAS_SSD")


def regex_js() -> str:
    lineas = ["// GENERADO por `python -m bot generar-worker` desde bot/normalizar.py: no editar a mano.",
              "// (tests/test_worker.py falla si quedó desactualizado)", ""]
    for nombre in REGEXES:
        lineas.append(f"export const {nombre} = {json.dumps(getattr(N, nombre).pattern)};")
    for nombre in TABLAS:
        v = getattr(N, nombre)
        v = sorted(v) if isinstance(v, set) else v
        lineas.append(f"export const {nombre} = {json.dumps(v, ensure_ascii=False)};")
    return "\n".join(lineas) + "\n"


RUTA_GEN = RAIZ / "worker" / "src" / "normalizador_gen.js"


def generar_worker() -> Path:
    RUTA_GEN.write_text(regex_js(), encoding="utf-8", newline="\n")
    return RUTA_GEN
