"""Línea de comandos.

  python -m bot correr [--dry-run] [--forzar] [--solo tiendas|feeds]
  python -m bot probar <tienda> [--categoria placas] [--guardar-html]
  python -m bot tiendas
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
    a = p.parse_args(argv)
    _log(a.verbose)
    a.f(a)


if __name__ == "__main__":
    main()
