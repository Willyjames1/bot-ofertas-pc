"""Adaptadores de tiendas (con HTML guardado de la web real) y la lógica para no cargar a las tiendas."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from bot import config
from bot.alertas import Motor
from bot.corrida import FASE2, categorias_a_leer, en_pausa, tiendas_del_turno
from bot.cotizaciones import Cotizacion
from bot.db import DB
from bot.fuentes import TIENDAS
from bot.fuentes.staticice import StaticICE, busquedas
from bot.fuentes.umart import MSY, Umart
from bot.modelos import Oferta
from bot.normalizar import normalizar
from bot.red import Bloqueado, Cliente, Robots

FIX = Path(__file__).parent / "fixtures"
CFG = config.cargar()
AJ = config.ajustes(CFG, datetime(2026, 11, 16, tzinfo=timezone.utc))


def leer(nombre):
    return (FIX / nombre).read_text(encoding="utf-8")


def sin_red():
    """Cliente que no sale a internet (si algo intenta pedir, el test falla)."""
    def nada(req):
        raise AssertionError(f"pedido inesperado a {req.url}")
    c = Cliente(respetar_robots=False)
    c.http = httpx.Client(transport=httpx.MockTransport(nada))
    return c


# ------------------------------------------------------------------ Umart / MSY

def test_umart_placas_lee_precio_lista_stock_y_siguiente():
    u = Umart(sin_red())
    url = "https://www.umart.com.au/pc-parts/computer-parts/graphics-cards-gpu-610"
    ofertas, sig = u.parsear(leer("umart_placas.html"), url, "placas")
    assert len(ofertas) == 20
    assert sig == url + "?page=2"
    assert all(o.pais == "AU" and o.moneda == "AUD" and o.url.startswith("https://www.umart.com.au/product/")
               for o in ofertas)
    con_descuento = [o for o in ofertas if o.precio_lista]
    assert con_descuento and all(o.precio_lista > o.precio for o in con_descuento)
    normalizadas = [normalizar(o) for o in ofertas]
    assert any(o.modelo == "RTX 5080 16GB" for o in normalizadas)
    assert all(o.datos.get("estado_stock") for o in normalizadas)  # normalizar no pisa lo de la tienda


def test_umart_ultima_pagina_no_sigue():
    u = Umart(sin_red())
    url = "https://www.umart.com.au/pc-parts/computer-parts/cpu-processors-611?page=3"
    _, sig = u.parsear(leer("umart_cpu.html"), url, "cpu")   # 59 productos = 3 páginas
    assert sig is None


def test_umart_y_msy_comparten_plataforma():
    assert set(Umart.categorias) == set(MSY.categorias)
    assert MSY.categorias["ram"][0] == "https://www.msy.com.au/pc-parts/computer-parts/memory-ram/ddr5-ram-1085"
    o, _ = MSY(sin_red()).parsear(leer("umart_ram.html"), MSY.categorias["ram"][0], "ram")
    assert len(o) == 20 and all(x.tienda == "msy" for x in o)


def test_umart_404_a_todo_es_un_freno():
    c = Cliente(respetar_robots=False, pausa=(0, 0))
    c.http = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(404, text="<html><title>404 Not Found</title><h1>Not Found</h1></html>")))
    with pytest.raises(Bloqueado):
        Umart(c).leer_pagina(Umart.categorias["placas"][0], "placas")


def test_429_repetido_es_un_freno(monkeypatch):
    monkeypatch.setattr("bot.red.time.sleep", lambda s: None)
    c = Cliente(respetar_robots=False, pausa=(0, 0))
    c.http = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(429, headers={"retry-after": "1"}, json={"errors": []})))
    with pytest.raises(Bloqueado):
        c.get("https://www.mwave.com.au/collections/graphics-cards")


# ------------------------------------------------------------------ staticICE

def staticice():
    return StaticICE(sin_red(), cfg=CFG, hoy=date(2026, 11, 16))


def test_staticice_busquedas_salen_de_config():
    q = busquedas(CFG, ["Ryzen 5 9600X", "Ryzen 7 9800X3D", "Ryzen 9 9950X3D"])
    assert q["placas"] == CFG["placas"]["chips"]
    # nucleos_min 8: el Ryzen 5 no se busca; los objetivos de CPU (9900X, 9950X) sí
    assert q["cpu"] == ["9800X3D", "9950X3D", "9900X", "9950X"]
    assert q["ram"] == ["DDR5 32GB", "DDR5 64GB", "DDR5 96GB"]


def test_staticice_filas_tiendas_y_links_reales():
    s = staticice()
    url = s.url("RTX 5080", "placas")
    ofertas, sig = s.parsear(leer("staticice_rtx_5080_min1500.html"), url, "placas")
    assert len(ofertas) >= 40
    tiendas = {o.tienda for o in ofertas}
    assert {"scorptec", "pccasegear", "mwaveaustralia"} <= tiendas
    assert not tiendas & {"umart", "msy"}                     # esas las leemos directo
    assert s.nombres["pccasegear"] == "PC Case Gear"
    assert all("staticice" not in o.url and "cfjump" not in o.url for o in ofertas)
    assert all(o.stock is None and o.datos["via"] == "staticICE" for o in ofertas)
    # la página 2 empieza en A$3.280 y el tope de placas es A$2.600: no sigue
    assert sig is None
    assert normalizar(ofertas[0]).modelo == "RTX 5080 16GB"


def test_staticice_saltea_filas_viejas_y_sigue_si_conviene():
    s = StaticICE(sin_red(), cfg=CFG, hoy=date(2026, 11, 25))
    ofertas, _ = s.parsear(leer("staticice_rtx_5080_min1500.html"), s.url("RTX 5080", "placas"), "placas")
    assert ofertas == []                                       # todo actualizado hace más de 3 días
    cfg = {**CFG, "placas": {**CFG["placas"], "precio_max": {"AUD": 5000}}}
    s = StaticICE(sin_red(), cfg=cfg, hoy=date(2026, 11, 16))
    _, sig = s.parsear(leer("staticice_rtx_5080_min1500.html"), s.url("RTX 5080", "placas"), "placas")
    assert sig and sig.endswith("&start=51")


def test_sin_stock_informado_igual_avisa_y_lo_aclara():
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, Cotizacion(1580.0, 0.68, datetime.now(timezone.utc)), datetime.now(timezone.utc))
    o = normalizar(Oferta("scorptec", "AU", "placas", "MSI GeForce RTX 5070 Ti 16G Ventus 3X OC",
                          "https://www.scorptec.com.au/product/x", 1449, "AUD", stock=None,
                          datos={"via": "staticICE", "actualizado": "2026-11-16"}))
    av = m.evaluar_oferta(o, db.guardar_oferta(o))
    assert len(av) == 1 and "staticICE" in av[0].texto and "16/11" in av[0].texto
    sin = normalizar(Oferta("umart", "AU", "placas", "MSI GeForce RTX 5070 Ti 16G Ventus 3X OC",
                            "https://www.umart.com.au/product/y", 1449, "AUD", stock=False))
    assert m.evaluar_oferta(sin, db.guardar_oferta(sin)) == []


# ------------------------------------------------------------------ robots.txt y carga

def test_robots_con_comodines():
    r = Robots("User-agent: *\nDisallow: /*sort=*\nDisallow: /*pagesize=*\nDisallow: /edu/\nAllow: /edu/about\n"
               "Disallow: /cart.html\n\nUser-agent: Wget\nDisallow: /\n")
    base = "https://www.umart.com.au"
    assert r.permite(base + "/pc-parts/computer-parts/graphics-cards-gpu-610?page=2")
    assert not r.permite(base + "/pc-parts/computer-parts/graphics-cards-gpu-610?sort=price")
    assert not r.permite(base + "/x?pagesize=100")
    assert r.permite(base + "/edu/about") and not r.permite(base + "/edu/help")
    assert not r.permite(base + "/cart.html")
    oz = Robots("User-agent: *\nCrawl-Delay: 5\nDisallow: /search\n")
    assert oz.demora == 5 and not oz.permite("https://www.ozbargain.com.au/search?q=x")
    fin = Robots("User-agent: *\nDisallow: /*.pdf$\n")
    assert not fin.permite("https://a/x.pdf") and fin.permite("https://a/x.pdf?v=1")


def test_fase2_cada_6_horas_y_pausa_por_freno():
    db = DB(":memory:")
    ahora = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
    # primera vez: Fase 1 completa + una sola de la Fase 2
    assert categorias_a_leer(db, CFG, AJ, "umart", ahora) == ["placas", "cpu", "ram", "mothers"]
    db.set("ult_cat:umart:mothers", ahora.isoformat())
    assert categorias_a_leer(db, CFG, AJ, "umart", ahora)[-1] == "ssd"
    for c in FASE2:
        db.set(f"ult_cat:umart:{c}", (ahora - timedelta(hours=2)).isoformat())
    db.set("ult_cat:umart:fuentes", (ahora - timedelta(hours=3)).isoformat())
    assert categorias_a_leer(db, CFG, AJ, "umart", ahora) == ["placas", "cpu", "ram"]
    # a las 6 h vuelve, empezando por la más vieja
    assert categorias_a_leer(db, CFG, AJ, "umart", ahora + timedelta(hours=4))[-1] == "fuentes"
    db.set("pausa:msy", (ahora + timedelta(hours=2)).isoformat())
    assert en_pausa(db, "msy", ahora) and not en_pausa(db, "msy", ahora + timedelta(hours=3))


def test_umart_y_msy_van_en_turnos_distintos():
    a = tiendas_del_turno(0, 2, list(TIENDAS))
    b = tiendas_del_turno(1, 2, list(TIENDAS))
    assert ("umart" in a) != ("msy" in a)
    assert sorted(a + b) == sorted(TIENDAS)


def test_staticice_saca_tiendas_con_precios_viejos():
    """En RAM, CPL y Austin aparecían a la mitad de lo que cobra el resto (precios viejos)."""
    s = staticice()

    def o(tienda, precio, n):
        return Oferta(tienda, "AU", "ram", "G.Skill 64GB (2x32GB) DDR5 6000MHz CL30", f"https://{tienda}/{n}",
                      precio, "AUD", stock=None)
    ofertas = [o("computerpartsland", p, i) for i, p in enumerate([520, 610, 700, 760])]
    ofertas += [o("scorptec", 1499, 1), o("pccasegear", 1499, 2), o("mwaveaustralia", 1549, 3),
                o("jwcomputers", 1399, 4)]
    quedan = s.sin_desfasadas(ofertas, "ram")
    assert s.desfasadas["ram"] == ["computerpartsland"]
    assert {x.tienda for x in quedan} == {"scorptec", "pccasegear", "mwaveaustralia", "jwcomputers"}
    # una tienda apenas más barata que el resto no se saca
    ofertas = [o("plecomputers", 1290, i) for i in range(3)] + ofertas[4:]
    assert len(s.sin_desfasadas(ofertas, "ram")) == 7 and s.desfasadas["ram"] == []
