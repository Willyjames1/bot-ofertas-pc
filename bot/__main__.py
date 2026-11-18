"""Línea de comandos.

  python -m bot correr [--dry-run] [--forzar] [--solo tiendas|feeds]
  python -m bot probar <tienda> [--categoria placas] [--guardar-html]
  python -m bot tiendas
  python -m bot resumen [--dry-run]
  python -m bot prueba
  python -m bot exportar [--salida datos/precios.json]
  python -m bot generar-worker
  python -m bot webhook --url https://<worker>.workers.dev/telegram    (o --borrar)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path


def _log(verbose: bool):
    from .privacidad import configurar_logs
    configurar_logs(verbose)


def cmd_correr(a):
    from .corrida import correr
    r = correr(dry_run=a.dry_run, forzar=a.forzar, solo=a.solo)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


def cmd_probar(a):
    from .fuentes import TIENDAS
    from .normalizar import normalizar
    if a.tienda not in TIENDAS:
        sys.exit(f"No conozco '{a.tienda}'. Tiendas: {', '.join(sorted(TIENDAS))}")
    cls = TIENDAS[a.tienda]
    t = cls()
    cats = [a.categoria] if a.categoria else list(cls.categorias)
    if a.guardar_html:
        Path("tests/fixtures").mkdir(parents=True, exist_ok=True)
        for c in cats:
            url = cls.categorias[c][0]
            dest = Path(f"tests/fixtures/{a.tienda}_{c}.html")
            dest.write_text(t.cliente.get(url).text, encoding="utf-8")
            print(f"Guardé {dest}")
    total = 0
    for c in cats:
        ofertas = t.leer(c)
        motivos = Counter()
        print(f"\n=== {cls.nombre} · {c}: {len(ofertas)} productos leídos ===")
        for o in ofertas:
            normalizar(o)
            if o.descartada:
                motivos[o.descartada.split(" (")[0]] += 1
                continue
            total += 1
            extra = (f" lista {o.precio_lista:,.0f}" if o.precio_lista else "") + (" TRAY" if o.tray else "") + \
                    (" SIN STOCK" if o.stock is False else "") + (" COMBO" if o.combo else "")
            print(f"  {o.precio:>12,.0f} {o.moneda} | {(o.modelo or '(sin normalizar)'):<28} | {(o.variante or '')[:22]:<22} |{extra} {o.titulo[:60]}")
        if motivos:
            print("  Descartados: " + ", ".join(f"{k}: {v}" for k, v in motivos.most_common()))
    print(f"\nTotal válidos: {total} · pedidos HTTP: {t.cliente.pedidos}")
    t.cliente.cerrar()


def cmd_tiendas(_a):
    from .fuentes import TIENDAS
    for k, v in sorted(TIENDAS.items(), key=lambda x: (x[1].pais, x[0])):
        print(f"{k:<14} {v.pais}  {v.nombre:<20} {', '.join(v.categorias)}")


def cmd_resumen(a):
    """Arma el resumen diario ahora, sin esperar a las 12:00 (no lo marca como enviado)."""
    import json as _json
    from datetime import datetime, timezone
    from . import alertas, config, cotizaciones
    from .db import DB
    from .fuentes import TIENDAS
    from .resumen import texto
    from .telegram import Telegram
    cfg = config.cargar()
    db = DB(config.ruta_db())
    alertas.NOMBRE_TIENDA.update(_json.loads(db.get("nombres_tiendas", "{}")))
    alertas.NOMBRE_TIENDA.update({k: v.nombre for k, v in TIENDAS.items()})
    sec = config.Secretos.desde_entorno()
    txt = texto(db, cfg, cotizaciones.obtener(db), datetime.now(timezone.utc))
    db.commit()
    db.cerrar()
    if not txt:
        sys.exit("No hay productos en resumen_diario (config.yaml)")
    Telegram(sec, dry_run=a.dry_run).enviar(sec.chat_yo, txt)


def cmd_prueba(_a):
    """Manda un mensaje de prueba; sale con error si Telegram lo rechaza (token revocado, etc.)."""
    from datetime import datetime
    from . import config
    from .telegram import Telegram
    sec = config.Secretos.desde_entorno()
    if not sec.token or not sec.chat_yo:
        sys.exit("Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID_YO")
    hora = datetime.now(config.TZ_AR)
    if not Telegram(sec).enviar(sec.chat_yo, f"🧪 <b>Mensaje de prueba</b> desde GitHub Actions "
                                               f"({hora:%d/%m %H:%M} hora argentina): el bot está conectado."):
        sys.exit("Telegram rechazó el mensaje de prueba")
    print("Mensaje de prueba enviado")


def cmd_exportar(a):
    """Arma el JSON de /buscar con la base local (sin bajar nada) y dice cuánto pesa."""
    from datetime import datetime, timezone
    import json as _json
    from . import alertas, config, exportar
    from .cotizaciones import Cotizacion
    from .db import DB
    from .fuentes import TIENDAS
    db = DB(config.ruta_db())
    alertas.NOMBRE_TIENDA.update(_json.loads(db.get("nombres_tiendas", "{}")))
    alertas.NOMBRE_TIENDA.update({k: v.nombre for k, v in TIENDAS.items()})
    mep, aud = db.ultima_cotizacion("mep"), db.ultima_cotizacion("aud_usd")
    cot = Cotizacion(mep["mep"], aud["aud_usd"], datetime.now(timezone.utc)) if mep and aud else None
    datos = exportar.armar(db, config.cargar(), cot, alertas.NOMBRE_TIENDA)
    ruta = Path(a.salida) if a.salida else exportar.ruta_json()
    kb = exportar.guardar_todo(datos, ruta) / 1024
    print(f"{ruta}: {kb:.0f} KB, {len(datos['p'])} precios de {len(datos['modelos'])} modelos, "
          f"{len(datos['posts'])} posts")


def cmd_generar_worker(_a):
    from . import exportar
    print(f"Escrito {exportar.generar_worker()}")


COMANDOS_MENU = [
    {"command": "buscar", "description": "Buscar un producto: /buscar 5070 ti [au|ar]"},
    {"command": "estado", "description": "Cómo andan las tiendas y de cuándo son los datos"},
    {"command": "filtros", "description": "Los filtros y objetivos de config.yaml"},
    {"command": "ayuda", "description": "Qué puedo hacer"},
]


def cmd_webhook(a):
    """Apunta Telegram al Worker (setWebhook con secret_token) y registra el menú (setMyCommands).
    Lee TELEGRAM_TOKEN y TELEGRAM_WEBHOOK_SECRET del entorno o del .env; no imprime ninguno."""
    import os
    from . import config
    from .telegram import Telegram
    sec = config.Secretos.desde_entorno()
    if not sec.token:
        sys.exit("Falta TELEGRAM_TOKEN")
    tg = Telegram(sec)
    if a.borrar:
        tg._api("deleteWebhook")
        print("Webhook borrado (los comandos quedan sin responder hasta volver a ponerlo)")
        return
    secreto = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not secreto or not a.url:
        sys.exit("Falta --url o TELEGRAM_WEBHOOK_SECRET")
    tg._api("setWebhook", url=a.url, secret_token=secreto, allowed_updates=["message", "callback_query"],
            drop_pending_updates=True, max_connections=5)
    tg._api("setMyCommands", commands=COMANDOS_MENU)
    info = tg._api("getWebhookInfo")
    ok = info.get("url") == a.url
    print(f"Webhook {'apuntado al Worker' if ok else 'NO quedó puesto'}; menú con "
          f"{len(COMANDOS_MENU)} comandos registrado")
    if info.get("last_error_message"):
        print(f"Último error que vio Telegram: {info['last_error_message']}")
    if not ok:
        sys.exit(1)


def main(argv=None):
    # la consola de Windows no es UTF-8 por defecto y los avisos llevan emojis
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="python -m bot")
    p.add_argument("-v", "--verbose", action="store_true")
    sp = p.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("correr", help="una corrida completa")
    c.add_argument("--dry-run", action="store_true", help="no manda nada a Telegram, lo imprime")
    c.add_argument("--forzar", action="store_true", help="ignora los intervalos y lee todo ya")
    c.add_argument("--solo", choices=["tiendas", "feeds"])
    c.set_defaults(f=cmd_correr)
    pr = sp.add_parser("probar", help="prueba una sola tienda contra la web, sin guardar ni avisar")
    pr.add_argument("tienda")
    pr.add_argument("--categoria")
    pr.add_argument("--guardar-html", action="store_true", help="guarda la página 1 en tests/fixtures")
    pr.set_defaults(f=cmd_probar)
    sp.add_parser("tiendas", help="lista las tiendas registradas").set_defaults(f=cmd_tiendas)
    rs = sp.add_parser("resumen", help="arma el resumen diario ahora")
    rs.add_argument("--dry-run", action="store_true", help="no lo manda, lo imprime")
    rs.set_defaults(f=cmd_resumen)
    sp.add_parser("prueba", help="manda un mensaje de prueba a Telegram").set_defaults(f=cmd_prueba)
    ex = sp.add_parser("exportar", help="arma el JSON de /buscar con la base local")
    ex.add_argument("--salida")
    ex.set_defaults(f=cmd_exportar)
    sp.add_parser("generar-worker", help="regenera worker/src/normalizador_gen.js").set_defaults(
        f=cmd_generar_worker)
    wh = sp.add_parser("webhook", help="apunta Telegram al Worker y registra el menú de comandos")
    wh.add_argument("--url")
    wh.add_argument("--borrar", action="store_true", help="saca el webhook")
    wh.set_defaults(f=cmd_webhook)
    a = p.parse_args(argv)
    _log(a.verbose)
    a.f(a)


if __name__ == "__main__":
    main()
