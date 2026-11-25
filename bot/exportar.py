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
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import comandos, normalizar as N
from .stock import clave_url
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
          "ssd": ("capacidad_tb", "interfaz", "gen", "formato"), "pcs": ("chip", "ram_gb", "ssd_tb", "cpu", "nucleos")}
TIPOS_PRECIO = ("transferencia", "contado")


def ruta_json() -> Path:
    return RAIZ / os.getenv("BOT_JSON", "datos/precios.json")


# lo que el renglón de /buscar ya dice aparte (Gen, velocidad) o que no ayuda a reconocerlo
RE_RUIDO_SSD = re.compile(
    r"(?<![\w.])(?:DISCO|S[OÓ]LIDO|INTERNO|INTERNAL|SSD|SOLID STATE DRIVE|M\.2|2280|NVME(?:\s*V?1\.\d)?|"
    r"PCI-?E\s*(?:GEN\s*)?\d?(?:\.0)?(?:\s*X\s*4)?|GEN\s*\d(?:\s*X\s*4)?|X\s*4|3D\s*(?:TLC\s*)?NAND|TLC|"
    r"[\d.,]+\s*MB/?S|[345]\.0|READ|WRITE|HEAT\s*SINK|DISIPADOR(?:\s*T[EÉ]RMICO)?|WITH|CON|SIN|DRIVE|BULK|[-,])"
    r"(?![\w.])", re.I)
# códigos de pieza: CT2000E100SSD8, TM8FFD002T0C101, MZ-V9V2T0BW, SNV3S/2000G
RE_CODIGO_SSD = re.compile(r"(?<!\S)(?=\S*\d)(?=\S*[A-Za-z])\S{9,}(?!\S)")


def titulo_corto_ssd(titulo: str) -> str:
    """El nombre de un SSD que no está en ssd_modelos.yaml: el título sin "Disco Sólido SSD M.2 NVMe PCIe
    4.0", sin códigos de pieza ni lo que va entre paréntesis ("Team 2TB MP44Q", "PNY CS2241 2TB")."""
    t = re.sub(r"\([^)]*\)", " ", " ".join(titulo.split()))
    for _ in range(2):                    # "M.2 2280 NVMe PCIe 4.0": las pegadas salen en la segunda vuelta
        t = RE_RUIDO_SSD.sub(" ", t)
    t = " ".join(RE_CODIGO_SSD.sub(" ", t).split())
    return t if len(t) <= 40 else t[:39].rstrip() + "…"


def _detalle(cat: str, r, d: dict) -> str:
    """Lo que va al lado de la tienda: la marca y línea, o el procesador/RAM/disco de una PC."""
    if cat == "ssd":
        return d.get("linea") or titulo_corto_ssd(r["titulo"] or "")
    if cat == "pcs":
        partes = [d.get("cpu"), f"{d['ram_gb']}GB RAM" if d.get("ram_gb") else None,
                  f"{d['ssd_tb']:g}TB SSD" if d.get("ssd_tb") else None]
        partes = [p for p in partes if p]
        return " · ".join(partes) if partes else (r["titulo"] or "")[:60]
    return r["variante"] or ""


def _ssd_del_post(titulo: str) -> dict | None:
    """Si el post es de un SSD, lo que hace falta para /buscar (así el Worker no lo parsea en cada pedido)."""
    d = N.datos_ssd(N.limpiar(titulo))
    return None if isinstance(d, str) else {k: d[k] for k in ("capacidad_tb", "interfaz", "gen", "formato", "linea")}


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
    from . import cuotas as CU, fichas
    tasa = CU.tasa_mensual(db, cfg)[0]
    pagos: dict[str, list] = {}         # 🇦🇷: clave → [lista, cuotas, valor cuota, sin interés, contado, real]
    promos: dict[str, list[str]] = {}   # nombre de la tienda → las promos de banco (las 2 primeras)
    for pais in ("AR", "AU"):
        for cat in CATEGORIAS:
            vistos: Counter = Counter()
            for r in db.vigentes(pais, cat, desde, ahora):   # sin las que no tienen stock; confirmadas primero
                modelo, d = r["modelo"], json.loads(r["datos"] or "{}")
                if cat == "ssd":
                    # de nuevo desde el título: así vale ya la tabla de ssd_modelos.yaml (y lo que se
                    # leyó antes de un cambio en el normalizador), sin esperar a que se vuelva a leer la tienda
                    d = N.datos_ssd(N.limpiar(r["titulo"] or ""))
                    if isinstance(d, str):
                        continue
                    modelo = N.nombre_ssd(d)
                # los SSD, POR_MODELO de cada uno (990 Pro, NV3…): "SSD NVMe Gen4 2TB" junta decenas
                cupo = (modelo, d.get("linea") or r["titulo"]) if cat == "ssd" else modelo
                if not r["precio"] or vistos[cupo] >= POR_MODELO:
                    continue
                vistos[cupo] += 1
                clave = (cat, modelo)
                if clave not in i_modelo:
                    i_modelo[clave] = len(modelos)
                    modelos.append([modelo, cat, {k: d[k] for k in CAMPOS[cat] if d.get(k) is not None}])
                if r["tienda"] not in i_tienda:
                    i_tienda[r["tienda"]] = len(tiendas)
                    tiendas.append(nombres.get(r["tienda"], r["tienda"]))
                visto = datetime.fromisoformat(r["ultima_vez"])
                motivo = "" if r["stock_ok"] else (r["stock_motivo"] or "stock sin confirmar")
                if motivo not in i_motivo:
                    i_motivo[motivo] = len(motivos)
                    motivos.append(motivo)
                if pais == "AR":
                    pg = fichas.pagos_de(db, cfg, r, tasa, ahora)
                    if pg.plan or pg.lista:
                        pagos[clave_url(r["url"])] = pg.a_lista()
                    nombre_t = nombres.get(r["tienda"], r["tienda"])
                    if pg.promos and nombre_t not in promos:
                        promos[nombre_t] = pg.promos[:2]
                filas.append([
                    i_modelo[clave], pais, round(r["precio"]), i_tienda[r["tienda"]], r["url"],
                    _detalle(cat, r, d),
                    max(0, int((ahora - visto).total_seconds() // 60)),     # hace cuántos minutos se vio
                    r["tipo_precio"] if r["tipo_precio"] in TIPOS_PRECIO else "",
                    1 if d.get("via") == "staticICE" else 0,                # vino de staticICE
                    i_motivo[motivo],                                       # 0 = stock confirmado
                    clave_url(r["url"]),       # para el botón ❌ (así el Worker no calcula sha1 en cada pedido)
                    *([[d.get("linea"), d.get("lectura"), d.get("escritura")]] if cat == "ssd" else []),
                ])
    limite = (ahora - timedelta(hours=HORAS_POSTS)).isoformat(timespec="seconds")
    posts = [[p["titulo"], p["url"], p["votos"], p["precio"],
              max(0, int((ahora - datetime.fromisoformat(p["publicado"])).total_seconds() // 60)),
              N.limpiar(p["titulo"]),           # ya limpio: el Worker no lo hace en cada pedido
              _ssd_del_post(p["titulo"])]
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
        # [modelo, país, precio, tienda, link, detalle, hace_min, tipo_precio, staticICE, motivo, clave]
        # (+ los SSD: [modelo de ssd_modelos.yaml, lectura, escritura])
        "p": filas,
        "motivos": motivos,
        # 🇦🇷: clave → [lista, cuotas, valor cuota, sin interés (1/0), contado, precio real] (de las fichas
        # y las promos de la tienda; real = transferencia o cuotas a contado, lo que sea menor)
        "pagos": pagos,
        "promos": promos,
        # los "❌ Sin stock" que ya incorporó la base (clave = sha1(link)[:16] → cuándo lo tocaste). El
        # Worker oculta lo que tocaste DESPUÉS (todavía no está acá); lo de acá ya lo resuelve la base:
        # fuera del JSON mientras siga sin stock, de vuelta cuando la tienda lo tiene otra vez
        "ocultos": {o["h"]: o["ts"] for o in db.c.execute("SELECT h, ts FROM ocultos")},
        # [título, link, votos, precio A$, hace_min, título limpio, SSD (o null)]
        "posts": posts,
        "estado": comandos.estado_texto(db),
        "filtros": comandos.filtros_texto(cfg),
    }


def por_categoria(datos: dict) -> dict[str, dict]:
    """Además del JSON completo, uno chico por categoría (lo que lee el Worker para cada búsqueda:
    leer 300 KB enteros en cada pedido se pasaba de los 10 ms de CPU del plan gratis) y un índice
    sin precios (chips, /estado y /filtros). Cada uno tiene el mismo formato que el completo."""
    chips = sorted({m[2]["chip"] for m in datos["modelos"] if m[2].get("chip")})
    salida = {"indice": {**datos, "modelos": [], "p": [], "chips": chips, "pagos": {}}}
    for cat in CATEGORIAS:
        nuevo: dict[int, int] = {}
        modelos = []
        for i, m in enumerate(datos["modelos"]):
            if m[1] == cat:
                nuevo[i] = len(modelos)
                modelos.append(m)
        filas = [[nuevo[f[0]], *f[1:]] for f in datos["p"] if f[0] in nuevo]
        claves = {f[10] for f in filas}
        pagos = {k: v for k, v in (datos.get("pagos") or {}).items() if k in claves}
        salida[cat] = {**datos, "modelos": modelos, "p": filas, "chips": chips, "pagos": pagos}
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
           "SSD_NO", "SSD_EXTERNO", "SSD_CARRY", "SSD_SI", "RE_SSD_TB", "RE_SSD_GB", "RE_SSD_GEN", "RE_SSD_FORMA",
           "RE_SSD_VEL_PAR", "RE_SSD_VEL_RW", "RE_SSD_VEL", "RE_PIDE_VEL")
TABLAS = ("VRAM_VALIDAS", "VRAM_POR_DEFECTO", "SSD_MODELOS", "SSD_ALIAS", "MAX_PALABRAS_ALIAS", "MARCAS_SSD",
          "GB_A_TB")


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
