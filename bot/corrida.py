"""Una corrida completa: cotización → tiendas (por turnos) → foros → alertas → exportar.

Los comandos de Telegram ya no se leen acá: los responde al instante el Worker de Cloudflare
(worker/), que recibe los mensajes por webhook. Con webhook, getUpdates no anda."""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import alertas, black_friday, config, cotizaciones, cuotas, exportar, feeds, fichas, historial
from . import resumen as resumen_diario, stock
from .alertas import Aviso, Motor
from .db import DB
from .fuentes import TIENDAS
from .modelos import Oferta
from .normalizar import normalizar
from .red import Bloqueado, Cliente, ProhibidoPorRobots
from .telegram import Telegram

log = logging.getLogger("bot.corrida")


def _minutos_desde(db: DB, clave: str) -> float:
    v = db.get(clave)
    if not v:
        return 1e9
    return (datetime.now(timezone.utc) - datetime.fromisoformat(v)).total_seconds() / 60


def tiendas_del_turno(turno: int, turnos: int, activas: list[str] | None = None) -> list[str]:
    ids = sorted(activas if activas is not None else TIENDAS)
    if turnos <= 1:
        return ids
    # alterno países para que cada turno tenga AU y AR mezcladas, y las tiendas que comparten
    # servidor (Umart y MSY) quedan pegadas en el orden, así caen en turnos distintos
    ids.sort(key=lambda i: (TIENDAS[i].pais, TIENDAS[i].servidor or i, i))
    return [t for n, t in enumerate(ids) if n % turnos == turno % turnos]


FASE2 = {"mothers", "ssd", "fuentes", "refrigeracion", "gabinetes", "monitores", "teclados", "mouse"}


def categorias_a_leer(db: DB, cfg: dict, aj: dict, tid: str, ahora: datetime) -> list[str]:
    """Las de la Fase 1 (placas, cpu, ram) en cada turno; de las de la Fase 2, como mucho UNA por
    corrida (la que hace más que no se lee) y cada N horas, para no cargar de pedidos a las
    tiendas. Las que están apagadas en config.yaml no se leen."""
    cats, pendientes = [], []
    una = getattr(TIENDAS[tid], "una_categoria_por_corrida", False)
    for n, cat in enumerate(TIENDAS[tid].categorias):
        if not (cfg.get(cat) or {}).get("activo", True):
            continue
        if una and cat not in FASE2:   # tiendas pesadas (HardGamers): una sola categoría por corrida
            pendientes.append((db.get(f"ult_cat:{tid}:{cat}") or "", n, cat))
            continue
        if cat in FASE2:
            ult = db.get(f"ult_cat:{tid}:{cat}")
            if not ult or ahora - datetime.fromisoformat(ult) >= timedelta(hours=aj["fase2_cada_horas"]):
                pendientes.append((ult or "", n, cat))  # a igual fecha, en el orden de la tienda
            continue
        cats.append(cat)
    if pendientes:
        cats.append(min(pendientes)[2])
    return cats


def caidas_ar(db: DB, ahora: datetime) -> set[str]:
    """Tiendas argentinas que leemos directo pero están en pausa o fallaron las 3 últimas corridas:
    HardGamers las lee por nosotros (sin pedirle nada a la tienda)."""
    salida = set()
    for tid, cls in TIENDAS.items():
        if cls.pais != "AR" or tid == "hardgamers":
            continue
        ult = [r["ok"] for r in db.c.execute(
            "SELECT ok FROM corridas_tienda WHERE tienda=? ORDER BY ts DESC LIMIT 3", (tid,))]
        if en_pausa(db, tid, ahora) or (len(ult) == 3 and not any(ult)):
            salida.add(tid)
    return salida


def pausa_por_bloqueo(db: DB, aj: dict, tid: str, ahora: datetime) -> datetime:
    """Si nos frena de nuevo, la pausa se duplica (2 h, 4 h, 8 h... hasta 24 h)."""
    n = int(db.get(f"bloqueos:{tid}", "0")) + 1
    db.set(f"bloqueos:{tid}", str(n))
    horas = min(24.0, aj["pausa_si_bloquea_horas"] * 2 ** (n - 1))
    hasta = ahora + timedelta(hours=horas)
    db.set(f"pausa:{tid}", hasta.isoformat())
    return hasta


def en_pausa(db: DB, tid: str, ahora: datetime) -> bool:
    hasta = db.get(f"pausa:{tid}")
    return bool(hasta) and ahora < datetime.fromisoformat(hasta)


def leer_tienda(tid: str, cats: list[str] | None = None) -> tuple[str, list[Oferta], str | None, float]:
    """Corre en un hilo aparte. NO toca la base: solo baja y devuelve ofertas."""
    t0 = time.monotonic()
    cls = TIENDAS[tid]
    tienda = cls()
    ofertas: list[Oferta] = []
    try:
        for cat in (cats if cats is not None else list(cls.categorias)):
            ofertas += tienda.leer(cat)
        return tid, ofertas, None, time.monotonic() - t0
    except Bloqueado as e:
        return tid, ofertas, f"bloqueada: {e}", time.monotonic() - t0
    except ProhibidoPorRobots as e:
        return tid, ofertas, f"robots.txt no permite {e}", time.monotonic() - t0
    except Exception as e:  # noqa: BLE001
        log.exception("Falló %s", tid)
        return tid, ofertas, f"{type(e).__name__}: {e}", time.monotonic() - t0
    finally:
        tienda.cliente.cerrar()


def verificar_stock(db: DB, cfg: dict, aj: dict, avisos: list[Aviso], resumen: dict) -> list[Aviso]:
    """Mira el stock en la tienda real de lo que viene de staticICE / HardGamers (o de tiendas que
    no lo informan): primero lo que va a avisar, después lo que aparecería primero en /buscar
    (las 5 más baratas de cada modelo y país). Saca de los avisos lo que está sin stock."""
    verif = stock.Verificador(db)
    try:
        avisos = alertas.filtrar_por_stock(avisos, db, verif)
        desde = datetime.now(timezone.utc) - timedelta(hours=exportar.HORAS_OTRO_PAIS)
        est = db.estado_stock()
        candidatos = []
        for pais in ("AU", "AR"):
            for cat in exportar.CATEGORIAS:
                puesto: Counter = Counter()
                for r in sorted(db.vigentes(pais, cat, desde), key=lambda f: f["precio"]):
                    n = puesto[r["modelo"]]
                    if n >= 5:
                        continue
                    puesto[r["modelo"]] += 1
                    if est.necesita_verificar(r):
                        d = json.loads(r["datos"] or "{}")
                        interesa = alertas.pasa_filtros(cfg, cat, r["modelo"], d, None, r["moneda"],
                                                        bool(r["tray"]), bool(r["combo"]))
                        candidatos.append((n, not interesa, r))
        candidatos.sort(key=lambda x: (x[0], x[1]))
        urls, precio, por_host = [], {}, Counter()
        for _, _, r in candidatos:
            host = stock._host(r["url"])
            if motivo := verif.bloqueada(host):       # tienda que frena o no publica stock: ni se pide
                db.guardar_verificacion(r["url"], None, motivo, r["precio"])
                continue
            if len(urls) >= aj["verificar_por_corrida"] or por_host[host] >= verif.tope_por_host:
                continue
            por_host[host] += 1
            urls.append(r["url"])
            precio[r["url"]] = r["precio"]
        cuenta: Counter = Counter()
        for u, v in verif.verificar_varios(urls).items():
            if v.motivo.startswith("sin verificar todavía"):
                continue
            db.guardar_verificacion(u, v.disponible, v.motivo, precio[u], v.destino)
            cuenta[{True: "con_stock", False: "sin_stock", None: "sin_confirmar"}[v.disponible]] += 1
        resumen["verificados"] = dict(cuenta, pedidos=verif.pedidos)
        log.info("Stock verificado en la tienda: %s (%d pedidos)", dict(cuenta), verif.pedidos)
    finally:
        verif.cerrar()
    if n := db.actualizar_ocultos():
        log.info("%d publicaciones que marcaste sin stock volvieron a tener stock", n)
    db.commit()
    return avisos


def correr(dry_run: bool = False, forzar: bool = False, solo: str | None = None,
           db_ruta=None) -> dict:
    cfg = config.cargar()
    aj = config.ajustes(cfg)
    sec = config.Secretos.desde_entorno()
    db = DB(db_ruta or config.ruta_db())
    db.horas_stock = aj["stock_sin_confirmar_horas"]
    db.horas_verif = aj["verificacion_vale_horas"]
    tg = Telegram(sec, dry_run=dry_run)
    inicio = datetime.now(timezone.utc)
    # nombres lindos: los de los adaptadores + los que fue viendo staticICE (PC Case Gear, Scorptec...)
    alertas.NOMBRE_TIENDA.update(json.loads(db.get("nombres_tiendas", "{}")))
    alertas.NOMBRE_TIENDA.update({k: v.nombre for k, v in TIENDAS.items()})
    resumen: dict = {"black_friday": aj["black_friday"], "tiendas": {}, "posts": 0}

    # Saludo único: confirma que el token y el chat_id andan
    if not tg.dry_run and not db.get("saludo"):
        if tg.enviar(sec.chat_yo, "✅ <b>Bot conectado.</b> Ya estoy leyendo OzBargain; las tiendas "
                                  "se suman en los próximos días. Comandos: /filtros, /estado.",
                     silencioso=True):
            db.set("saludo", inicio.isoformat())

    cot = cotizaciones.obtener(db)
    # el MEP de cada día (para comparar en USD contra hace 7 y 30 días) y la tasa de plazo fijo
    # (para pasar las cuotas a contado): una vez por día cada una
    cli_datos = Cliente(pausa=(0.3, 0.6), respetar_robots=False)
    try:
        historial.actualizar_mep(db, cli_datos, cot.mep if cot else None, inicio)
    except Exception as e:  # noqa: BLE001
        log.warning("No pude actualizar el historial del MEP: %s", type(e).__name__)
    try:
        tasa, tasa_desc = cuotas.tasa_mensual(db, cfg, cli_datos, inicio)
    except Exception as e:  # noqa: BLE001
        log.warning("No pude bajar la tasa de plazo fijo: %s", type(e).__name__)
        tasa, tasa_desc = cuotas.TASA_RESPALDO_MENSUAL, "respaldo"
    cli_datos.cerrar()
    resumen["tasa_mensual"] = round(tasa * 100, 2)
    motor = Motor(cfg, aj, db, cot, inicio, tasa=tasa)
    avisos: list[Aviso] = []

    # los "❌ Sin stock" que tocaste en Telegram (los guarda el Worker)
    try:
        if n := stock.sincronizar_ocultos(db, aj["worker_url"], sec.worker_sync):
            log.info("%d publicaciones marcadas sin stock desde Telegram", n)
    except Exception as e:  # noqa: BLE001
        log.warning("No pude traer del Worker los marcados sin stock: %s", type(e).__name__)

    # 2) tiendas
    hacer_tiendas = solo in (None, "tiendas") and (forzar or _minutos_desde(db, "ult_tiendas") >= aj["tiendas_cada_min"] - 3)
    if hacer_tiendas and TIENDAS:
        turno = int(db.get("turno", "0"))
        ids = tiendas_del_turno(turno, aj["turnos_tiendas"])
        if "mercadolibre" in ids:
            from .fuentes import mercadolibre
            if not mercadolibre.preparar(db):   # sin credenciales (o no se pudo renovar el token): no se lee
                ids.remove("mercadolibre")
                resumen["tiendas"]["mercadolibre"] = {"productos": 0, "error": None, "nota": "sin credenciales"}
        for t in [t for t in ids if en_pausa(db, t, inicio)]:
            ids.remove(t)
            resumen["tiendas"][t] = {"productos": 0, "error": f"en pausa hasta {db.get(f'pausa:{t}')}"}
        cats = {t: categorias_a_leer(db, cfg, aj, t, inicio) for t in ids}
        if "hardgamers" in TIENDAS:
            TIENDAS["hardgamers"].tambien = caidas_ar(db, inicio)
        log.info("Turno %d: %s", turno, ", ".join(ids))
        with ThreadPoolExecutor(max_workers=max(1, len(ids))) as ex:
            futuros = [ex.submit(leer_tienda, t, cats[t]) for t in ids if cats[t]]
            for fut in as_completed(futuros):
                tid, ofertas, error, seg = fut.result()
                validas = 0
                por_cat: Counter = Counter()
                for o in ofertas:
                    normalizar(o)
                    if o.descartada:
                        continue
                    validas += 1
                    por_cat[o.categoria] += 1
                    info = db.guardar_oferta(o)
                    avisos += motor.evaluar_oferta(o, info)
                ok = error is None or validas > 0
                if error is None and validas and hasattr(TIENDAS[tid], "tiendas_seguidas"):
                    for seguida in TIENDAS[tid].tiendas_seguidas(cfg):
                        if n := db.marcar_sin_stock(seguida, inicio):
                            log.info("%s: %d productos dejaron de aparecer (sin stock)", seguida, n)
                db.registrar_tienda(tid, error is None, validas, error, seg)
                if error is None:
                    # lectura completa: lo de esa tienda (o comparador) que no apareció, ya no está
                    for cat in cats[tid]:
                        if por_cat[cat]:
                            db.registrar_pasada(tid, cat, inicio)
                resumen["tiendas"][tid] = {"productos": validas, "error": error, "segundos": round(seg)}
                log.info("%s: %d productos válidos%s (%.0fs)", tid, validas, f", ERROR {error}" if error else "", seg)
                for cat in cats[tid]:
                    if cat in FASE2 or getattr(TIENDAS[tid], "una_categoria_por_corrida", False):
                        db.set(f"ult_cat:{tid}:{cat}", inicio.isoformat())
                if error and error.startswith("bloqueada"):
                    # nos frenó: la dejamos descansar antes de volver a pedirle nada (cada vez más)
                    hasta = pausa_por_bloqueo(db, aj, tid, inicio)
                    log.warning("%s nos frenó: la dejo en pausa hasta %s", tid, hasta.isoformat())
                elif error is None:
                    db.set(f"bloqueos:{tid}", "0")
                if not ok:
                    log.warning("%s quedó como caída", tid)
        db.set("nombres_tiendas", json.dumps(alertas.NOMBRE_TIENDA, ensure_ascii=False, sort_keys=True))
        db.set("turno", str(turno + 1))
        db.set("ult_tiendas", inicio.isoformat())
        db.commit()
        avisos += motor.evaluar_oportunidades()

    # 2b) cuotas y promos de lo que te falta comprar: las promos de las páginas de las tiendas (una vez
    # por día) y las fichas de producto de las 5 más baratas de cada cosa (cuotas, y en HardGamers el
    # mínimo de 75 días y el historial). Avisa si una tienda agregó o aumentó cuotas sin interés.
    if hacer_tiendas and solo in (None, "tiendas"):
        cli = Cliente(pausa=(2.0, 4.0))
        cli_hg = Cliente(pausa=(5.0, 7.0), timeout=40.0)    # HardGamers: Crawl-delay 5
        try:
            nuevas = fichas.leer_promos(db, cli, inicio)
            avisos += motor.evaluar_promos(nuevas)
            cambios = fichas.leer_fichas(db, cfg, inicio, cli_hg, cli, aj)
            avisos += motor.evaluar_cuotas(cambios)
            resumen["fichas"] = {"promos_nuevas": len(nuevas), "cuotas_nuevas": len(cambios)}
        except Exception as e:  # noqa: BLE001 — que no frene la corrida
            log.warning("Falló la lectura de cuotas y promos: %s: %s", type(e).__name__, e)
        finally:
            cli.cerrar()
            cli_hg.cerrar()
        db.commit()

    # 3) foros
    hacer_feeds = solo in (None, "feeds") and (forzar or _minutos_desde(db, "ult_feeds") >= aj["feeds_cada_min"] - 3)
    if hacer_feeds:
        cli = Cliente(pausa=(2.0, 4.0))
        foros = cfg.get("foros") or {}
        vistos: set[str] = set()   # el mismo post sale en varios feeds (Computing y el de la tienda)
        for fuente, parser in (("ozbargain", feeds.parsear_ozbargain),):
            for url in foros.get(fuente, []):
                try:
                    posts = parser(cli.get(url).text)
                except Exception as e:  # noqa: BLE001
                    log.warning("No pude leer %s: %s", url, e)
                    db.registrar_tienda(fuente, False, 0, str(e), 0)
                    continue
                db.registrar_tienda(fuente, True, len(posts), None, 0)
                pcs = cfg.get("pcs") or {}
                palabras_pc = pcs.get("palabras_ozbargain") if pcs.get("activo") else None
                for p in posts:
                    if p.id in vistos:
                        continue
                    vistos.add(p.id)
                    modelos = feeds.modelos_del_post(p, palabras_pc)
                    info = db.guardar_post(p, [o.modelo for o in modelos])
                    nuevos = motor.evaluar_post(p, info, modelos)
                    if any(a.urgente for a in nuevos):
                        db.marcar_post_notificado(p.fuente, p.id)
                    avisos += nuevos
                    resumen["posts"] += 1
        cli.cerrar()
        db.set("ult_feeds", inicio.isoformat())

    # 4) aviso diario de tiendas caídas (una vez por día, desde las 21:00 hora argentina)
    ahora_ar = inicio.astimezone(config.TZ_AR)
    if ahora_ar.hour >= 21 and db.get("aviso_caidas") != str(ahora_ar.date()):
        desde = (inicio - timedelta(hours=24)).isoformat(timespec="seconds")
        caidas = db.c.execute(
            "SELECT tienda, COUNT(*) n, SUM(ok) ok FROM corridas_tienda WHERE ts>=? GROUP BY tienda "
            "HAVING SUM(ok) < COUNT(*)", (desde,)).fetchall()
        if caidas:
            txt = "🛠️ <b>Tiendas con fallas en las últimas 24 h</b>\n" + "\n".join(
                f"• {TIENDAS[r['tienda']].nombre if r['tienda'] in TIENDAS else r['tienda']}: "
                f"{r['n'] - r['ok']} de {r['n']} corridas fallaron" for r in caidas) + "\n\nMás detalle: /estado"
            tg.enviar(sec.chat_yo, txt, silencioso=True)
        db.set("aviso_caidas", str(ahora_ar.date()))

    # 4b) resumen de Black Friday (27/11 a las 9, 13 y 20 h): lo que te falta comprar y el veredicto
    if slot := black_friday.toca(db, cfg, inicio):
        try:
            msgs = black_friday.textos(motor)
            if all(tg.enviar(sec.chat_yo, m) for m in msgs):
                black_friday.marcar_enviado(db, slot)
                resumen["resumen_black_friday"] = slot
        except Exception as e:  # noqa: BLE001
            log.warning("Falló el resumen de Black Friday: %s: %s", type(e).__name__, e)

    # 5) resumen diario (desde las 12:00 hora argentina, una vez por día; suena)
    if resumen_diario.toca(db, cfg, inicio):
        txt = resumen_diario.texto(db, cfg, cot, inicio)
        if txt and tg.enviar(sec.chat_yo, txt):
            resumen_diario.marcar_enviado(db, inicio)
            resumen["resumen_diario"] = True

    try:
        avisos = verificar_stock(db, cfg, aj, avisos, resumen)
    except Exception as e:  # noqa: BLE001 — sin verificar, igual se filtra lo que se sabe sin stock
        log.warning("Falló la verificación de stock: %s", type(e).__name__)
        avisos = alertas.filtrar_por_stock(avisos, db)
    resumen["alertas"] = alertas.despachar(avisos, tg, db, cfg, aj, sec)
    db.commit()

    # 6) los precios actuales para /buscar (el Worker los lee de la rama datos)
    try:
        ruta = exportar.ruta_json() if db_ruta is None else Path(db_ruta).with_name("precios.json")
        resumen["exportado_kb"] = round(exportar.guardar_todo(
            exportar.armar(db, cfg, cot, alertas.NOMBRE_TIENDA, datetime.now(timezone.utc)), ruta) / 1024)
    except Exception as e:  # noqa: BLE001 — que no frene la corrida: las alertas ya salieron
        log.warning("No pude exportar los precios para /buscar: %s", type(e).__name__)
    db.cerrar()
    return resumen
