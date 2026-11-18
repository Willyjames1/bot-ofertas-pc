"""Motor de alertas: decide qué SUENA (urgente) y qué va al resumen diario,
y despacha a Telegram respetando silencio nocturno, tope diario y repetidas."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from . import perf
from .config import TZ_AR, Secretos
from .comparar import aviso_davinci, lineas_comparacion
from .cotizaciones import Cotizacion, ars
from .db import DB
from .feeds import codigo_descuento, es_codigo_ebay, precio_con_codigo, vigente
from .modelos import Oferta, Post
from .normalizar import canon, parsear_chip_config, ssd_estandar
from .telegram import Telegram

log = logging.getLogger("bot.alertas")

ICONO = {"placas": "🎮 PLACA", "cpu": "🧠 CPU", "ram": "💾 RAM", "mothers": "🔌 MOTHER",
         "ssd": "💽 SSD", "fuentes": "⚡ FUENTE", "refrigeracion": "❄️ REFRIGERACIÓN",
         "pcs": "🖥️ PC ARMADA"}
BANDERA = {"AU": "🇦🇺", "AR": "🇦🇷"}
NOMBRE_TIENDA: dict[str, str] = {}  # lo completa corrida.py con los nombres lindos
# Fase 2: de las tiendas se guardan los precios, pero solo avisan si hay un objetivo puesto
SOLO_OBJETIVO = {"ssd", "mothers", "fuentes", "refrigeracion", "gabinetes", "monitores"}
CODIGOS_DIAS = 10   # un código de OzBargain se aplica durante 10 días (o hasta que vence el post)


@dataclass
class Aviso:
    tipo: str          # objetivo|minimo|ozbargain|oportunidad  (urgentes)  baja|ganga|stock|post (resumen)
    clave: str
    urgente: bool
    texto: str
    pais: str | None = None
    precio: float | None = None
    url: str | None = None      # la publicación (para verificar el stock y el botón "❌ Sin stock")


def plata(x: float | None, moneda: str) -> str:
    if x is None:
        return "—"
    return ("A$" + f"{x:,.0f}".replace(",", ".")) if moneda == "AUD" else ars(x)


def bajo_objetivo(precio: float, objetivo: float | None, moneda: str) -> str:
    """'🎯 Objetivo: A$1.450 · 6% abajo (A$90 menos)'."""
    if not objetivo or precio > objetivo:
        return f"🎯 Objetivo: {plata(objetivo, moneda)}"
    return (f"🎯 Objetivo: {plata(objetivo, moneda)} · <b>{(1 - precio / objetivo) * 100:.0f}% abajo</b> "
            f"({plata(objetivo - precio, moneda)} menos)")


RE_OBJ_RAM = re.compile(r"(\d+)\s*GB(?:\s*\(\s*(\d+)\s*x\s*(\d+)\s*(?:GB)?\s*\))?(?:\s+(\d{4}))?", re.I)


def ram_cumple(nombre: str, datos: dict) -> bool:
    """'32GB (2x16) 6000': capacidad exacta, módulos si se ponen, velocidad como mínimo."""
    m = RE_OBJ_RAM.fullmatch(nombre.strip())
    if not m:
        return False
    total, mods, per, vel = (int(x) if x else None for x in m.groups())
    if datos.get("capacidad_gb") != total:
        return False
    if mods and (datos.get("modulos") != mods or (per and mods * per != total)):
        return False
    return not vel or (datos.get("velocidad") or 0) >= vel


def gpu_alcanza(cfg_pcs: dict, datos: dict) -> bool:
    """¿La placa de la PC es gpu_min o mejor, según el orden de perf.yaml?"""
    minimo = cfg_pcs.get("gpu_min")
    if not minimo:
        return True
    chip = datos.get("chip")
    if not chip or (minimo.upper().startswith("RTX") and not chip.startswith("RTX")):
        return False
    tabla = perf.orden().get("placas", {})

    def nivel(c: str) -> int | None:  # "RTX 4060 Ti" está como "rtx 4060 ti 8gb" y "rtx 4060 ti 16gb"
        return max((v for k, v in tabla.items() if k == canon(c) or k.startswith(canon(c) + " ")
                    and k[len(canon(c)) + 1:].endswith("gb")), default=None)
    a, b = nivel(chip), nivel(minimo)
    return a is not None and b is not None and a >= b


def es_marketplace(cfg: dict, p: Post) -> bool:
    """Posts de eBay, Catch, MyDeal...: por el link de la tienda o por el '@ Tienda' del título."""
    g = cfg.get("general") or {}
    nombres = [x.lower() for x in g.get("marketplaces") or []]
    host = (p.url_tienda or "").lower()
    titulo = p.titulo.lower()
    if any(f"@ {x.lower()}" in titulo for x in g.get("marketplaces_permitidos") or []):
        return False  # tienda oficial dentro del marketplace (ej. "@ HP eBay")
    return any(n in host or f"@ {n}" in titulo or (" " in n and n in titulo) for n in nombres)


# ------------------------------------------------------------------ filtros

def pasa_filtros(cfg: dict, categoria: str, modelo: str | None, datos: dict, precio: float | None,
                 moneda: str, tray: bool = False, combo: bool = False) -> bool:
    c = cfg.get(categoria) or {}
    g = cfg.get("general") or {}
    if not c.get("activo") or not modelo:
        return False
    if combo and not g.get("combos", False):
        return False
    if tray and not g.get("mostrar_tray", True):
        return False
    pmax = (c.get("precio_max") or {}).get(moneda)
    if pmax and precio and precio > pmax:
        return False
    if categoria == "pcs":
        return gpu_alcanza(c, datos)
    if categoria == "placas":
        chips = [parsear_chip_config(x) for x in c.get("chips", [])]
        if chips and not any(ch == datos.get("chip") and (v is None or v == datos.get("vram"))
                             for ch, v in chips):
            return False
        if (vmin := c.get("vram_min_gb")) and (datos.get("vram") or 0) < vmin:
            return False
    elif categoria == "cpu":
        if (s := c.get("socket")) and datos.get("socket") not in s:
            return False
        if (n := c.get("nucleos_min")) and datos.get("nucleos") is not None and datos["nucleos"] < n:
            return False
        if (lista := c.get("modelos")) and canon(modelo) not in {canon(x) for x in lista}:
            return False
    elif categoria == "ssd":
        # solo M.2 2280 NVMe Gen4/Gen5 con la generación conocida (ni SATA, ni externos, ni carry, ni
        # Gen3, ni los 2230/2242 de notebook): lo mismo que muestra /buscar si no pedís otra cosa
        if not ssd_estandar(datos):
            return False
        if (caps := c.get("capacidad_tb")) and datos.get("capacidad_tb") not in caps:
            return False
        if (gmin := c.get("gen_min")) and datos["gen"] < gmin:
            return False
    elif categoria == "ram":
        if (caps := c.get("capacidad_gb")) and datos.get("capacidad_gb") not in caps:
            return False
        if (vmin := c.get("velocidad_min")) and (datos.get("velocidad") or 0) < vmin:
            return False
        if (clmax := c.get("cl_max")) and datos.get("cl") and datos["cl"] > clmax:
            return False
        if (mods := c.get("modulos")) and datos.get("modulos") != mods:
            return False
    return True


def objetivo_de(cfg: dict, categoria: str, modelo: str, datos: dict, moneda: str) -> float | None:
    if categoria == "pcs":
        obj = ((cfg.get("pcs") or {}).get("objetivo") or {}).get(moneda)
        return float(obj) if obj else None
    objetivos = (cfg.get(categoria) or {}).get("objetivos") or {}
    for nombre, precios in objetivos.items():
        if not isinstance(precios, dict) or moneda not in precios:
            continue
        if categoria == "placas":
            ch, v = parsear_chip_config(nombre)
            if ch == datos.get("chip") and (v is None or v == datos.get("vram")):
                return float(precios[moneda])
        elif categoria == "ram":
            if ram_cumple(str(nombre), datos):
                return float(precios[moneda])
        elif canon(nombre) == canon(modelo):
            return float(precios[moneda])
    return None


# ------------------------------------------------------------------ motor

class Motor:
    def __init__(self, cfg: dict, ajustes: dict, db: DB, cot: Cotizacion | None, inicio: datetime):
        self.cfg, self.aj, self.db, self.cot, self.inicio = cfg, ajustes, db, cot, inicio

    # -------------------------------------------------- textos
    def _comparacion(self, pais: str, categoria: str, modelo: str, datos: dict, precio: float) -> list[str]:
        lineas = lineas_comparacion(self.db, self.cot, pais, categoria, modelo, datos, precio,
                                    NOMBRE_TIENDA, self.inicio, self.cfg)
        if categoria == "pcs" and (dv := aviso_davinci(self.cfg, datos)):
            lineas.append(dv)
        return lineas

    # -------------------------------------------------- códigos de descuento (OzBargain)
    def codigos(self) -> dict:
        try:
            return json.loads(self.db.get("codigos_ebay", "{}"))
        except ValueError:
            return {}

    def guardar_codigo(self, p: Post, cod: dict):
        """Guarda un código visto en OzBargain para aplicarlo a lo que leemos de eBay."""
        todos = self.codigos()
        vendedor = None
        t = p.titulo.upper()
        for usuario, nombre in ((self.cfg.get("ebay") or {}).get("vendedores_seguidos") or {}).items():
            marca = nombre.split()[0].upper()   # "HP Official Store" -> "HP"
            if f"@ {marca} EBAY" in t or f"{marca} OFFICIAL" in t:
                vendedor = usuario
        vence = p.expira or (self.inicio + timedelta(days=CODIGOS_DIAS))
        todos[cod["codigo"]] = {**cod, "vendedor": vendedor, "post": p.url, "vence": vence.isoformat()}
        self.db.set("codigos_ebay", json.dumps(todos, ensure_ascii=False))

    def codigo_para(self, o: Oferta) -> dict | None:
        """El mejor código vigente que aplica a este producto de eBay (del vendedor o de todo eBay)."""
        if o.datos.get("via") != "eBay":
            return None
        mejores = []
        for cod in self.codigos().values():
            if datetime.fromisoformat(cod["vence"]) < self.inicio or not cod.get("pct"):
                continue
            if cod.get("vendedor") not in (None, o.datos.get("vendedor")):
                continue
            if cod.get("vendedor") is None:
                continue   # "selected sellers": no sabemos si entra; se muestra, no se aplica
            if cod.get("minimo") and o.precio < cod["minimo"]:
                continue
            desc = min(o.precio * cod["pct"] / 100, cod.get("tope") or 1e12)
            mejores.append((desc, cod))
        return max(mejores, key=lambda x: x[0])[1] if mejores else None

    @staticmethod
    def con_codigo(precio: float, cod: dict | None) -> float:
        if not cod:
            return precio
        return round(precio - min(precio * cod["pct"] / 100, cod.get("tope") or 1e12), 2)

    @staticmethod
    def _linea_precio(o: Oferta, tienda: str, precio_antes: float | None) -> str:
        """'🇦🇺 MSI Ventus 3X @ Centre Com: A$1.441 (antes A$1.699)'."""
        nombre = o.titulo if o.categoria == "pcs" else (o.variante or o.titulo[:60])
        linea = f"{BANDERA.get(o.pais, '')} {escape(nombre)} @ {escape(tienda)}: <b>{plata(o.precio, o.moneda)}</b>"
        if o.pais == "AR" and o.tipo_precio in ("transferencia", "contado"):
            linea += f" {o.tipo_precio}"
            if o.precio_lista:
                linea += f" · lista {plata(o.precio_lista, o.moneda)}"
        if precio_antes and precio_antes > o.precio:
            linea += f" (antes {plata(precio_antes, o.moneda)})"
        return linea

    def texto_oferta(self, tipo: str, o: Oferta, precio_antes: float | None,
                     minimo: float | None, objetivo: float | None, codigo: dict | None = None) -> str:
        """tipo: 'objetivo' | 'minimo'. Formato:
        🔻 RTX 5070 Ti — bajó 15% en 🇦🇺 / precio y tienda / el otro país / diferencia / aduana / veredicto."""
        tienda = NOMBRE_TIENDA.get(o.tienda, o.tienda)
        bandera = BANDERA.get(o.pais, "")
        modelo = escape(o.modelo or "")
        final = self.con_codigo(o.precio, codigo)
        if tipo == "stock":
            cabeza = f"📦 <b>{modelo}</b> — volvió a tener stock en {bandera}"
        elif precio_antes and precio_antes > o.precio:
            cabeza = f"🔻 <b>{modelo}</b> — bajó {(1 - o.precio / precio_antes) * 100:.0f}% en {bandera}"
        elif tipo == "objetivo":
            cabeza = f"🎯 <b>{modelo}</b> — bajo tu objetivo en {bandera}"
        else:
            cabeza = f"📉 <b>{modelo}</b> — nuevo mínimo histórico en {bandera}"
        lineas = [cabeza, self._linea_precio(o, tienda, precio_antes)]
        if codigo:
            tope = f", tope {plata(codigo['tope'], o.moneda)}" if codigo.get("tope") else ""
            lineas.append(f"🏷️ Con el código <b>{escape(codigo['codigo'])}</b> (−{codigo['pct']}%{tope}, visto en "
                          f"OzBargain): <b>{plata(final, o.moneda)}</b> — la cuenta usa este precio")
        lineas += self._comparacion(o.pais, o.categoria, o.modelo, o.datos, final)
        if o.cuotas:
            lineas.append(f"💳 {escape(o.cuotas)}")
        extra = [bajo_objetivo(final, objetivo, o.moneda)] if objetivo else []
        if minimo and o.categoria != "pcs":
            extra.append(f"📉 Mín. histórico: {plata(minimo, o.moneda)}")
        if extra:
            lineas.append(" · ".join(extra))
        if o.tray:
            lineas.append("📦 Tray / sin caja")
        if o.datos.get("via") == "staticICE":
            fecha = o.datos.get("actualizado", "")
            fecha = f"{fecha[8:10]}/{fecha[5:7]}" if len(fecha) == 10 else "?"
            lineas.append(f"ℹ️ Precio visto en staticICE (actualizado el {fecha}): confirmá el precio en la tienda")
        lineas.append(f'🔗 <a href="{escape(o.url)}">Ver en la tienda</a>')
        return "\n".join(lineas)

    # -------------------------------------------------- ofertas de tiendas
    def evaluar_oferta(self, o: Oferta, info: dict) -> list[Aviso]:
        avisos = self._evaluar_oferta(o, info)
        for a in avisos:
            a.url = a.url or o.url
        return avisos

    def _evaluar_oferta(self, o: Oferta, info: dict) -> list[Aviso]:
        # stock None = la fuente no lo informa (staticICE): se evalúa igual; antes de mandar el aviso
        # se mira la tienda real (filtrar_por_stock) y, si no se pudo confirmar, el aviso lo dice
        if o.descartada or not o.modelo or o.stock is False:
            return []
        if not pasa_filtros(self.cfg, o.categoria, o.modelo, o.datos, o.precio, o.moneda, o.tray, o.combo):
            return []
        if o.categoria == "pcs":
            return self._evaluar_pc(o, info)
        mediana = self.db.mediana(o.modelo, o.pais)
        if mediana and o.precio <= mediana * (1 - self.aj["sospechoso_vs_mediana_pct"] / 100):
            self.db.marcar_sospechoso(info["id"], True)
            log.info("Sospechoso: %s %s a %s (mediana %s)", o.tienda, o.modelo, o.precio, mediana)
            return []
        minimo, desde = self.db.minimo_historico(o.modelo, o.pais, self.inicio)
        objetivo = objetivo_de(self.cfg, o.categoria, o.modelo, o.datos, o.moneda)
        historial_ok = desde is not None and (self.inicio - desde) >= timedelta(
            hours=self.aj["horas_historial_para_minimo"])

        tipo = None
        if objetivo and o.precio <= objetivo:
            tipo = "objetivo"
        elif historial_ok and minimo and o.precio < minimo and o.categoria not in SOLO_OBJETIVO:
            tipo = "minimo"

        avisos: list[Aviso] = []
        clave = f"precio|{o.tienda}|{o.modelo}"
        if tipo:
            ult = self.db.ultima_alerta(clave)
            repetida = ult is not None and ult["precio"] and \
                o.precio > ult["precio"] * (1 - self.aj["re_aviso_baja_pct"] / 100)
            if not repetida:
                avisos.append(Aviso(tipo, clave, True, self.texto_oferta(tipo, o, info["precio_antes"],
                                                                          minimo, objetivo), o.pais, o.precio))
                return avisos
        # ---- no suena: va al resumen
        resumen = f"{o.modelo} {o.variante or ''} {plata(o.precio, o.moneda)} en {NOMBRE_TIENDA.get(o.tienda, o.tienda)}"
        antes = info.get("precio_antes")
        if antes and o.precio <= antes * (1 - self.aj.get("baja_minima_pct", 5) / 100):
            avisos.append(Aviso("baja", f"baja|{o.url}|{o.precio}", False,
                                f"{resumen} (−{(1 - o.precio / antes) * 100:.0f}%)", o.pais, o.precio))
        if info.get("stock_antes") is False:
            avisos.append(Aviso("stock", f"stock|{o.url}|{self.inicio.date()}", False,
                                f"{resumen} volvió a tener stock", o.pais, o.precio))
        if mediana and o.precio <= mediana * (1 - self.aj.get("ganga_vs_mediana_pct", 15) / 100):
            avisos.append(Aviso("ganga", f"ganga|{o.url}|{o.precio}", False,
                                f"{resumen} ({(1 - o.precio / mediana) * 100:.0f}% bajo la mediana)",
                                o.pais, o.precio))
        return [a for a in avisos if not self.db.ultima_alerta(a.clave)]

    def _evaluar_pc(self, o: Oferta, info: dict) -> list[Aviso]:
        """PCs armadas: cada una es distinta (CPU, RAM, disco), así que no hay mediana ni mínimo
        histórico por modelo. Solo el objetivo, y la clave es el producto (su link)."""
        objetivo = objetivo_de(self.cfg, "pcs", o.modelo, o.datos, o.moneda)
        cod = self.codigo_para(o)
        final = self.con_codigo(o.precio, cod)
        antes = info.get("precio_antes")
        if o.datos.get("seguido"):
            # vendedores seguidos (HP Official Store): también avisan si vuelven a tener stock o bajan
            if info.get("stock_antes") is False and o.stock:
                clave = f"stock|{o.url}|{self.inicio.date()}"
                if not self.db.ultima_alerta(clave):
                    return [Aviso("stock", clave, True, self.texto_oferta("stock", o, None, None, objetivo, cod),
                                  o.pais, final)]
            if antes and o.precio <= antes * (1 - self.aj.get("baja_minima_pct", 5) / 100):
                clave = f"baja|{o.url}|{o.precio}"
                if not self.db.ultima_alerta(clave):
                    return [Aviso("baja_seguido", clave, True, self.texto_oferta("baja", o, antes, None, objetivo, cod),
                                  o.pais, final)]
        if not objetivo or final > objetivo:
            return []
        clave = f"precio|{o.tienda}|{o.url}"
        ult = self.db.ultima_alerta(clave)
        if ult is not None and ult["precio"] and final > ult["precio"] * (1 - self.aj["re_aviso_baja_pct"] / 100):
            return []
        texto = self.texto_oferta("objetivo", o, antes, None, objetivo, cod)
        return [Aviso("objetivo", clave, True, texto, o.pais, final)]

    # -------------------------------------------------- oportunidades
    def evaluar_oportunidades(self) -> list[Aviso]:
        avisos = []
        for pais in ("AU", "AR"):
            for cat in ("placas", "cpu"):
                mejores: dict[str, dict] = {}
                for r in self.db.ofertas_recientes(pais, horas=6):
                    if r["categoria"] != cat or r["sospechoso"] or r["stock"] == 0:
                        continue
                    if self.db.estado_stock().de(r).nivel == "no":
                        continue
                    datos = json.loads(r["datos"] or "{}")
                    if not pasa_filtros(self.cfg, cat, r["modelo"], datos, r["precio"], r["moneda"],
                                        bool(r["tray"]), bool(r["combo"])):
                        continue
                    k = perf.clave_perf(cat, r["modelo"], datos)
                    if k and (k not in mejores or r["precio"] < mejores[k]["precio"]):
                        mejores[k] = dict(r)
                for alto, ra in mejores.items():
                    vencidos = [(bajo, rb) for bajo, rb in mejores.items()
                                if bajo != alto and perf.domina(cat, alto, bajo) and ra["precio"] <= rb["precio"]]
                    if not vencidos:
                        continue
                    clave = f"opo|{pais}|{alto}"
                    ult = self.db.ultima_alerta(clave)
                    if ult and ult["precio"] and ra["precio"] > ult["precio"] * (1 - self.aj["re_aviso_baja_pct"] / 100):
                        continue
                    m = ra["moneda"]
                    tienda = NOMBRE_TIENDA.get(ra["tienda"], ra["tienda"])
                    datos_a = json.loads(ra["datos"] or "{}")
                    nombre = escape(ra["variante"] or ra["titulo"][:60])
                    lineas = [f"💥 <b>{escape(ra['modelo'])}</b> — oportunidad fuerte en {BANDERA[pais]}",
                              f"{BANDERA[pais]} {nombre} @ {escape(tienda)}: <b>{plata(ra['precio'], m)}</b>, "
                              "igual o menos que:"]
                    for bajo, rb in sorted(vencidos, key=lambda x: -x[1]["precio"])[:3]:
                        lineas.append(f"   • {escape(rb['modelo'])} a {plata(rb['precio'], m)} "
                                      f"({escape(NOMBRE_TIENDA.get(rb['tienda'], rb['tienda']))})")
                    lineas += self._comparacion(pais, cat, ra["modelo"], datos_a, ra["precio"])
                    if datos_a.get("via") == "staticICE":
                        lineas.append("ℹ️ Precio visto en staticICE: confirmá el precio en la tienda")
                    lineas.append(f'🔗 <a href="{escape(ra["url"])}">Ver en la tienda</a>')
                    avisos.append(Aviso("oportunidad", clave, True, "\n".join(lineas), pais, ra["precio"], ra["url"]))
        return avisos

    # -------------------------------------------------- foros
    def evaluar_codigo_ebay(self, p: Post) -> list[Aviso]:
        """Un código de eBay que salió en OzBargain: avisa una vez y lo guarda para aplicarlo."""
        cod = codigo_descuento(p)
        self.guardar_codigo(p, cod)
        lineas = [f"🏷️ <b>Código de eBay</b> en OzBargain 🇦🇺: <b>{escape(cod['codigo'])}</b>",
                  f"📝 {escape(p.titulo)}"]
        partes = [f"−{cod['pct']}%"]
        if cod.get("tope"):
            partes.append(f"tope {plata(cod['tope'], 'AUD')}")
        if cod.get("minimo"):
            partes.append(f"compra mínima {plata(cod['minimo'], 'AUD')}")
        if p.expira:
            partes.append(f"vence {p.expira.astimezone(TZ_AR):%d/%m %H:%M} hora argentina")
        lineas.append(" · ".join(partes))
        guardado = self.codigos().get(cod["codigo"], {})
        if guardado.get("vendedor"):
            nombre = ((self.cfg.get("ebay") or {}).get("vendedores_seguidos") or {}).get(guardado["vendedor"])
            lineas.append(f"✅ Lo aplico a lo que lea de {escape(nombre or guardado['vendedor'])} en eBay")
        else:
            lineas.append("ℹ️ Suele ser para vendedores seleccionados: confirmá en eBay si entra la PC que querés")
        lineas.append(f'🔗 <a href="{escape(p.url)}">Ver el post</a>')
        return [Aviso("codigo_ebay", f"codigo|{cod['codigo']}", True, "\n".join(lineas), "AU", None)]

    def evaluar_post(self, p: Post, info: dict, modelos: list[Oferta]) -> list[Aviso]:
        if info.get("notificado"):
            return []
        ok, motivo_no = vigente(p)
        if not ok:  # expirado, agotado o viejo: ni alerta ni resumen
            log.debug("Ignoro post %s: %s", p.id, motivo_no)
            return []
        if es_codigo_ebay(p, modelos):
            return self.evaluar_codigo_ebay(p)
        if (cod_post := codigo_descuento(p)) and cod_post.get("pct"):
            self.guardar_codigo(p, cod_post)   # ej. "Extra 20% off with code HPNOV26 @ HP eBay"
        if es_marketplace(self.cfg, p):
            log.debug("Ignoro post %s: marketplace", p.id)
            return []
        en_filtros = [o for o in modelos if pasa_filtros(self.cfg, o.categoria, o.modelo, o.datos,
                                                         p.precio, "AUD", o.tray, o.combo)]
        if not en_filtros:
            return []
        o = en_filtros[0]
        objetivo = objetivo_de(self.cfg, o.categoria, o.modelo, o.datos, "AUD")
        precio, cod, aplicado = precio_con_codigo(p)
        edad = datetime.now(timezone.utc) - p.publicado
        umbral = self.aj["votos_ozbargain_urgente"]
        motivo = None
        fuente = "OzBargain" if p.fuente == "ozbargain" else "Reddit"
        if precio and objetivo and precio <= objetivo:
            motivo = f"🎯 <b>{escape(o.modelo)}</b> — bajo tu objetivo en {fuente} 🇦🇺"
        elif o.categoria == "pcs":
            motivo = None  # PCs armadas: solo por precio, no por votos
        elif p.fuente == "ozbargain" and p.votos is not None and p.votos >= umbral and edad <= timedelta(hours=1):
            motivo = (f"🔥 <b>{escape(o.modelo)}</b> — {p.votos} votos en "
                      f"{int(edad.total_seconds() // 60)} min en {fuente} 🇦🇺")
        if motivo:
            lineas = [motivo, f"📝 {escape(p.titulo)}"]
            if "upcoming" in p.estados:
                lineas.append("⏳ Todavía no arrancó (OzBargain lo marca como 'upcoming')")
            if p.expira:
                lineas.append(f"⌛ Vence: {p.expira.astimezone(TZ_AR):%d/%m %H:%M} hora argentina")
            if p.precio:
                tienda = f" @ {escape(p.titulo.rsplit(' @ ', 1)[1])}" if " @ " in p.titulo else ""
                lineas.append(f"🇦🇺{tienda}: <b>{plata(p.precio, 'AUD')}</b>")
                if cod and aplicado:
                    tope = f", tope {plata(cod['tope'], 'AUD')}" if cod.get("tope") else ""
                    lineas.append(f"🏷️ Con el código <b>{escape(cod['codigo'])}</b> (−{cod['pct']}%{tope}): "
                                  f"<b>{plata(precio, 'AUD')}</b> — la cuenta usa este precio")
                elif cod:
                    lineas.append(f"🏷️ Código <b>{escape(cod['codigo'])}</b> (el precio de arriba ya lo incluye)")
                lineas += self._comparacion("AU", o.categoria, o.modelo, o.datos, precio)
                if objetivo:
                    lineas.append(bajo_objetivo(precio, objetivo, "AUD"))
            lineas.append(f'🔗 <a href="{escape(p.url)}">Ver el post</a>')
            return [Aviso("ozbargain" if p.fuente == "ozbargain" else "post_urgente",
                          f"post|{p.fuente}|{p.id}", True, "\n".join(lineas), "AU", precio)]
        if info.get("nuevo"):
            return [Aviso("post", f"postnuevo|{p.fuente}|{p.id}", False,
                          f"[{fuente}] {p.titulo} ({p.votos if p.votos is not None else '?'} votos) {p.url}",
                          "AU", p.precio)]
        return []


# ------------------------------------------------------------------ despacho

# ------------------------------------------------------------------ stock antes de avisar

def _con_linea(texto: str, linea: str) -> str:
    """Agrega una línea antes del "🔗 Ver en la tienda" (o al final)."""
    i = texto.rfind("\n🔗")
    return texto[:i] + "\n" + linea + texto[i:] if i >= 0 else texto + "\n" + linea


def filtrar_por_stock(avisos: list[Aviso], db: DB, verificador=None) -> list[Aviso]:
    """Antes de mandar: lo que está sin stock no se avisa (tampoco lo que marcaste "❌ Sin stock").
    Para los urgentes que vienen de un comparador o de una tienda que no informa stock, se mira
    la tienda real en el momento; si no se puede confirmar, el aviso sale con "⚠️ Stock sin confirmar"."""
    salida = []
    for a in avisos:
        fila = db.c.execute("SELECT * FROM ofertas WHERE url=?", (a.url,)).fetchone() if a.url else None
        if fila is None:
            salida.append(a)
            continue
        if a.urgente and verificador is not None and db.estado_stock().necesita_verificar(fila):
            v = verificador.verificar(a.url)
            db.guardar_verificacion(a.url, v.disponible, v.motivo, fila["precio"], v.destino)
        e = db.estado_stock().de(fila)
        if e.nivel == "no":
            log.info("No aviso %s: %s", a.clave, e.motivo)
            continue
        if e.nivel == "?" and a.urgente:
            a.texto = _con_linea(a.texto, f"⚠️ Stock sin confirmar: {escape(e.motivo)}")
        salida.append(a)
    return salida


def boton_sin_stock(url: str | None) -> list | None:
    """El botón que va debajo de cada aviso: lo tocás y la publicación se oculta (ver worker/)."""
    from .stock import clave_url
    return [[{"text": "❌ Sin stock", "callback_data": f"x:{clave_url(url)}"}]] if url else None


def _en_rango(hora: time, desde: str, hasta: str) -> bool:
    d, h = time.fromisoformat(desde), time.fromisoformat(hasta)
    return d <= hora < h if d <= h else (hora >= d or hora < h)


def _inicio_dia(ahora: datetime, tz: ZoneInfo) -> datetime:
    local = ahora.astimezone(tz)
    return datetime.combine(local.date(), time(0), tz)


def despachar(avisos: list[Aviso], tg: Telegram, db: DB, cfg: dict, aj: dict, sec: Secretos,
              ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    urgentes = [a for a in avisos if a.urgente]
    for a in avisos:
        if not a.urgente:
            db.registrar_alerta(a.tipo, a.clave, a.precio, False, "resumen", a.texto)
    stats = {"urgentes": len(urgentes), "resumen": len(avisos) - len(urgentes), "sonaron": 0}
    if not urgentes:
        return stats
    dest = cfg.get("destinatarios") or {}
    tope = aj["tope_alertas_que_suenan_por_dia"]

    # ---------------- yo
    if (dest.get("yo") or {}).get("activo", True) and (sec.chat_yo or tg.dry_run):
        sn = aj.get("silencio_noche") or {}
        noche = _en_rango(ahora.astimezone(TZ_AR).time(), sn.get("desde", "00:00"), sn.get("hasta", "08:00"))
        pausa = db.get("pausa_hasta")
        pausado = bool(pausa) and datetime.fromisoformat(pausa) > ahora
        libres = max(0, tope - db.sonaron_desde(_inicio_dia(ahora, TZ_AR), "yo"))
        silencio = noche or pausado
        sueltas = urgentes if silencio else urgentes[:libres]
        juntas = [] if silencio else urgentes[libres:]
        for a in sueltas:
            if tg.enviar(sec.chat_yo, a.texto, silencioso=silencio, botones=boton_sin_stock(a.url)):
                db.registrar_alerta(a.tipo, a.clave, a.precio, not silencio, "yo", a.texto)
                stats["sonaron"] += 0 if silencio else 1
        if juntas:
            texto = f"📦 <b>{len(juntas)} alertas más</b> (ya sonaron {tope} hoy, te las junto):\n\n" + \
                    "\n\n— — —\n\n".join(a.texto for a in juntas)
            if tg.enviar(sec.chat_yo, texto, silencioso=True):
                for a in juntas:
                    db.registrar_alerta(a.tipo, a.clave, a.precio, False, "yo", a.texto)

    # ---------------- hermano: solo urgentes de Australia, hasta su fecha de viaje
    h = dest.get("hermano") or {}
    if h.get("activo") and sec.chat_hermano:
        tz = ZoneInfo(h.get("zona_horaria", "Australia/Sydney"))
        viaje = h.get("fecha_viaje")
        viaje = viaje if isinstance(viaje, date) else date.fromisoformat(str(viaje)) if viaje else None
        if not viaje or ahora.astimezone(tz).date() <= viaje:
            despierto = _en_rango(ahora.astimezone(tz).time(), "08:00", "23:00")
            libres = max(0, tope - db.sonaron_desde(_inicio_dia(ahora, tz), "hermano"))
            for i, a in enumerate(x for x in urgentes if x.pais == "AU"):
                suena = despierto and i < libres
                if tg.enviar(sec.chat_hermano, a.texto, silencioso=not suena):
                    db.registrar_alerta(a.tipo, a.clave + "|h", a.precio, suena, "hermano", a.texto)
    return stats
