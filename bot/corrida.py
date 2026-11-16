"""Una corrida completa: comandos → cotización → tiendas (por turnos) → foros → alertas."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from . import alertas, comandos, config, cotizaciones, feeds
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
    # alterno países para que cada turno tenga AU y AR mezcladas
    ids.sort(key=lambda i: (TIENDAS[i].pais, i))
    return [t for n, t in enumerate(ids) if n % turnos == turno % turnos]


def leer_tienda(tid: str) -> tuple[str, list[Oferta], str | None, float]:
    """Corre en un hilo aparte. NO toca la base: solo baja y devuelve ofertas."""
    t0 = time.monotonic()
    cls = TIENDAS[tid]
    tienda = cls()
    ofertas: list[Oferta] = []
    try:
        for cat in cls.categorias:
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


def correr(dry_run: bool = False, forzar: bool = False, solo: str | None = None,
           db_ruta=None) -> dict:
    cfg = config.cargar()
    aj = config.ajustes(cfg)
    sec = config.Secretos.desde_entorno()
    db = DB(db_ruta or config.ruta_db())
    tg = Telegram(sec, dry_run=dry_run)
    inicio = datetime.now(timezone.utc)
    alertas.NOMBRE_TIENDA.update({k: v.nombre for k, v in TIENDAS.items()})
    resumen: dict = {"black_friday": aj["black_friday"], "tiendas": {}, "posts": 0}

    # 1) comandos pendientes
    offset = db.get("tg_offset")
    cmds, nuevo = tg.leer_comandos(int(offset) if offset else None)
    for c in cmds:
        tg.enviar(c["chat_id"], comandos.responder(c["texto"], cfg, db))
    if nuevo is not None:
        db.set("tg_offset", str(nuevo))

    # Saludo único: confirma que el token y el chat_id andan
    if not tg.dry_run and not db.get("saludo"):
        if tg.enviar(sec.chat_yo, "✅ <b>Bot conectado.</b> Ya estoy leyendo OzBargain; las tiendas "
                                  "se suman en los próximos días. Comandos: /filtros, /estado.",
                     silencioso=True):
            db.set("saludo", inicio.isoformat())

    cot = cotizaciones.obtener(db)
    motor = Motor(cfg, aj, db, cot, inicio)
    avisos: list[Aviso] = []

    # 2) tiendas
    hacer_tiendas = solo in (None, "tiendas") and (forzar or _minutos_desde(db, "ult_tiendas") >= aj["tiendas_cada_min"] - 3)
    if hacer_tiendas and TIENDAS:
        turno = int(db.get("turno", "0"))
        ids = tiendas_del_turno(turno, aj["turnos_tiendas"])
        log.info("Turno %d: %s", turno, ", ".join(ids))
        with ThreadPoolExecutor(max_workers=max(1, len(ids))) as ex:
            futuros = [ex.submit(leer_tienda, t) for t in ids]
            for fut in as_completed(futuros):
                tid, ofertas, error, seg = fut.result()
                validas = 0
                for o in ofertas:
                    normalizar(o)
                    if o.descartada:
                        continue
                    validas += 1
                    info = db.guardar_oferta(o)
                    avisos += motor.evaluar_oferta(o, info)
                ok = error is None or validas > 0
                db.registrar_tienda(tid, error is None, validas, error, seg)
                resumen["tiendas"][tid] = {"productos": validas, "error": error, "segundos": round(seg)}
                log.info("%s: %d productos válidos%s (%.0fs)", tid, validas, f", ERROR {error}" if error else "", seg)
                if not ok:
                    log.warning("%s quedó como caída", tid)
        db.set("turno", str(turno + 1))
        db.set("ult_tiendas", inicio.isoformat())
        db.commit()
        avisos += motor.evaluar_oportunidades()

    # 3) foros
    hacer_feeds = solo in (None, "feeds") and (forzar or _minutos_desde(db, "ult_feeds") >= aj["feeds_cada_min"] - 3)
    if hacer_feeds:
        cli = Cliente(pausa=(2.0, 4.0))
        foros = cfg.get("foros") or {}
        for fuente, parser in (("ozbargain", feeds.parsear_ozbargain),):
            for url in foros.get(fuente, []):
                try:
                    posts = parser(cli.get(url).text)
                except Exception as e:  # noqa: BLE001
                    log.warning("No pude leer %s: %s", url, e)
                    db.registrar_tienda(fuente, False, 0, str(e), 0)
                    continue
                db.registrar_tienda(fuente, True, len(posts), None, 0)
                for p in posts:
                    modelos = feeds.modelos_del_post(p)
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

    resumen["alertas"] = alertas.despachar(avisos, tg, db, cfg, aj, sec)
    db.commit()
    db.cerrar()
    return resumen
