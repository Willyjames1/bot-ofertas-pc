from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot import config
from bot.alertas import Motor, despachar, objetivo_de, pasa_filtros
from bot.config import Secretos
from bot.cotizaciones import Cotizacion, calcular
from bot.db import DB
from bot.feeds import modelos_del_post, parsear_ozbargain, vigente
from bot.modelos import Oferta, Post
from bot.normalizar import normalizar
from bot.telegram import Telegram

FIX = Path(__file__).parent / "fixtures"
CFG = config.cargar()
AJ = config.ajustes(CFG, datetime(2026, 11, 15, tzinfo=timezone.utc))
COT = Cotizacion(mep=1580.0, aud_usd=0.68, ts=datetime.now(timezone.utc))


def oferta(titulo, precio, pais="AU", tienda="umart", cat="placas", url=None, fecha=None):
    o = Oferta(tienda, pais, cat, titulo, url or f"https://x/{tienda}/{titulo}", precio,
               "AUD" if pais == "AU" else "ARS", fecha=fecha or datetime.now(timezone.utc))
    return normalizar(o)


def test_filtros_placas():
    o = oferta("MSI RTX 5070 Ti 16G Ventus 3X OC", 1400)
    assert pasa_filtros(CFG, "placas", o.modelo, o.datos, 1400, "AUD")
    assert not pasa_filtros(CFG, "placas", o.modelo, o.datos, 2700, "AUD")  # sobre precio_max
    o8 = oferta("Zotac RTX 5060 Ti 8GB Twin Edge", 600)
    assert not pasa_filtros(CFG, "placas", o8.modelo, o8.datos, 600, "AUD")  # pide la de 16GB


def test_filtros_ram_y_cpu():
    r = oferta("Kingston FURY 64GB (2x32GB) DDR5 6000MHz CL30", 500, cat="ram")
    assert pasa_filtros(CFG, "ram", r.modelo, r.datos, 500, "AUD")
    r40 = oferta("Corsair 64GB (2x32GB) DDR5 6000MHz CL40", 400, cat="ram")
    assert not pasa_filtros(CFG, "ram", r40.modelo, r40.datos, 400, "AUD")  # CL40 > 36
    c = oferta("AMD Ryzen 5 7600X AM5", 300, cat="cpu")
    assert not pasa_filtros(CFG, "cpu", c.modelo, c.datos, 300, "AUD")  # 6 núcleos


def test_objetivos():
    o = oferta("MSI RTX 5070 Ti 16G Ventus 3X OC", 1400)
    assert objetivo_de(CFG, "placas", o.modelo, o.datos, "AUD") == 1500
    r = oferta("Kingston FURY 64GB (2x32GB) DDR5 6000MHz CL30", 500, cat="ram")
    assert objetivo_de(CFG, "ram", r.modelo, r.datos, "ARS") == 1800000
    c = oferta("AMD Ryzen 9 9950X3D AM5", 850, cat="cpu")
    assert objetivo_de(CFG, "cpu", c.modelo, c.datos, "AUD") == 880


def test_conviene():
    c = calcular(1100, COT, mejor_ar=2_000_000)
    assert c.costo_ars == pytest.approx(1100 * 10 / 11 * 0.68 * 1580)
    assert c.aduana_ars == pytest.approx(0.5 * (1000 * 0.68 - 500) * 1580)
    assert c.ahorro > 0


def test_motor_objetivo_y_repetidas():
    db = DB(":memory:")
    inicio = datetime.now(timezone.utc)
    m = Motor(CFG, AJ, db, COT, inicio)
    o = oferta("MSI RTX 5070 Ti 16G Ventus 3X OC", 1449)
    av = m.evaluar_oferta(o, db.guardar_oferta(o))
    assert len(av) == 1 and av[0].urgente and "objetivo" in av[0].texto
    assert "¿Conviene traerlo?" in av[0].texto and "Si te cobran aduana" in av[0].texto
    tg = Telegram(Secretos("", "1", ""), dry_run=True)
    despachar(av, tg, db, CFG, AJ, Secretos("", "1", ""), datetime(2026, 11, 15, 15, tzinfo=timezone.utc))
    # misma tienda+modelo, baja solo 1%: no repite
    o2 = oferta("MSI RTX 5070 Ti 16G Ventus 3X OC", 1435, url=o.url)
    assert not [a for a in m.evaluar_oferta(o2, db.guardar_oferta(o2)) if a.urgente]
    # baja otro 3%+: avisa de nuevo
    o3 = oferta("MSI RTX 5070 Ti 16G Ventus 3X OC", 1390, url=o.url)
    assert [a for a in m.evaluar_oferta(o3, db.guardar_oferta(o3)) if a.urgente]


def test_minimo_historico_necesita_un_dia():
    db = DB(":memory:")
    hace2 = datetime.now(timezone.utc) - timedelta(days=2)
    viejo = oferta("Sapphire RX 9070 Pulse 16GB", 1000, fecha=hace2, url="https://x/a")
    db.guardar_oferta(viejo)
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    nuevo = oferta("Sapphire RX 9070 Pulse 16GB", 960, url="https://x/b", tienda="msy")
    av = m.evaluar_oferta(nuevo, db.guardar_oferta(nuevo))
    assert av and "mínimo histórico" in av[0].texto
    db2 = DB(":memory:")
    db2.guardar_oferta(oferta("Sapphire RX 9070 Pulse 16GB", 1000, url="https://x/a",
                              fecha=datetime.now(timezone.utc) - timedelta(hours=2)))
    m2 = Motor(CFG, AJ, db2, COT, datetime.now(timezone.utc))
    n2 = oferta("Sapphire RX 9070 Pulse 16GB", 960, url="https://x/b", tienda="msy")
    assert not [a for a in m2.evaluar_oferta(n2, db2.guardar_oferta(n2)) if a.urgente]


def test_sospechoso_no_avisa():
    db = DB(":memory:")
    for i, p in enumerate((1500, 1520, 1550, 1600)):
        db.guardar_oferta(oferta("MSI RTX 5070 Ti 16G Ventus", p, url=f"https://x/{i}", tienda=f"t{i}"))
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    raro = oferta("MSI RTX 5070 Ti 16G Ventus", 700, url="https://x/raro", tienda="ml")
    assert m.evaluar_oferta(raro, db.guardar_oferta(raro)) == []


def test_oportunidad_fuerte():
    db = DB(":memory:")
    db.guardar_oferta(oferta("Gigabyte RX 9070 XT Gaming OC 16GB", 1100, url="https://x/9070"))
    db.guardar_oferta(oferta("MSI RTX 5070 Ti 16G Ventus 3X OC", 1090, url="https://x/5070ti", tienda="msy"))
    av = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc)).evaluar_oportunidades()
    assert len(av) == 1 and "RTX 5070 Ti" in av[0].texto and "RX 9070 XT" in av[0].texto


def _avisos_urgentes(n):
    from bot.alertas import Aviso
    return [Aviso("objetivo", f"k{i}", True, f"alerta {i}", "AU", 100) for i in range(n)]


def test_tope_diario_y_noche():
    db = DB(":memory:")
    sec = Secretos("", "1", "")
    tg = Telegram(sec, dry_run=True)
    tarde = datetime(2026, 11, 16, 18, tzinfo=timezone.utc)  # 15:00 en Argentina
    despachar(_avisos_urgentes(8), tg, db, CFG, AJ, sec, tarde)
    sonaron = [e for e in tg.enviados if not e["silencioso"]]
    juntas = [e for e in tg.enviados if e["silencioso"]]
    assert len(sonaron) == 6 and len(juntas) == 1 and "2 alertas más" in juntas[0]["texto"]
    tg2 = Telegram(sec, dry_run=True)
    noche = datetime(2026, 11, 17, 5, tzinfo=timezone.utc)  # 02:00 en Argentina
    despachar(_avisos_urgentes(2), tg2, DB(":memory:"), CFG, AJ, sec, noche)
    assert all(e["silencioso"] for e in tg2.enviados)


def test_hermano_solo_australia_y_hasta_el_viaje():
    cfg = {**CFG, "destinatarios": {"yo": {"activo": False},
                                    "hermano": {"activo": True, "zona_horaria": "Australia/Sydney",
                                                "fecha_viaje": "2026-12-01"}}}
    from bot.alertas import Aviso
    av = [Aviso("objetivo", "a", True, "AU", "AU", 1), Aviso("objetivo", "b", True, "AR", "AR", 1)]
    sec = Secretos("", "1", "2")
    tg = Telegram(sec, dry_run=True)
    despachar(av, tg, DB(":memory:"), cfg, AJ, sec, datetime(2026, 11, 20, 2, tzinfo=timezone.utc))
    assert [e["texto"] for e in tg.enviados] == ["AU"] and not tg.enviados[0]["silencioso"]
    tg2 = Telegram(sec, dry_run=True)
    despachar(av, tg2, DB(":memory:"), cfg, AJ, sec, datetime(2026, 12, 3, 2, tzinfo=timezone.utc))
    assert tg2.enviados == []


def test_black_friday():
    bf = config.ajustes(CFG, datetime(2026, 11, 27, 15, tzinfo=timezone.utc))
    assert bf["black_friday"] and bf["feeds_cada_min"] == 10 and bf["votos_ozbargain_urgente"] == 15
    assert bf["tope_alertas_que_suenan_por_dia"] == 10
    assert not config.ajustes(CFG, datetime(2026, 12, 3, 15, tzinfo=timezone.utc))["black_friday"]


def test_feed_real_ozbargain():
    ozb = parsear_ozbargain((FIX / "ozbargain_computing.xml").read_text(encoding="utf-8"))
    assert len(ozb) >= 10 and all(p.votos is not None for p in ozb)
    assert any(p.precio for p in ozb)
    assert any(p.expira for p in ozb) and any("expired" in p.estados for p in ozb)


HOY = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def test_posts_viejos_reales_no_cuentan():
    """El feed del tag rtx-5080 trae los posts de A$1.600-1.700 de nov-2025 a jun-2026 y el de
    A$2.399 del 2/11: todos expirados. Ninguno puede disparar alertas."""
    posts = parsear_ozbargain((FIX / "ozbargain_tag_rtx5080.xml").read_text(encoding="utf-8"))
    assert posts and all(not vigente(p, HOY)[0] for p in posts)
    p2399 = next(p for p in posts if p.precio == 2399)
    assert p2399.publicado.date().isoformat() == "2026-11-02" and "expired" in p2399.estados
    # aunque fingiera ser reciente y muy votado, sigue sin sonar por estar marcado expirado
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    p2399.publicado, p2399.votos = datetime.now(timezone.utc) - timedelta(minutes=20), 99
    mods = modelos_del_post(p2399)
    assert m.evaluar_post(p2399, db.guardar_post(p2399, [o.modelo for o in mods]), mods) == []


@pytest.mark.parametrize("cambio,motivo", [
    ({"publicado": HOY - timedelta(days=8)}, "más de 7 días"),
    ({"expira": HOY - timedelta(hours=1)}, "venció"),
    ({"estados": ["outofstock"]}, "outofstock"),
    ({"titulo": "RTX 5080 $1999 @ Mwave [SOLD OUT]"}, "agotado"),
])
def test_post_no_vigente(cambio, motivo):
    p = Post("ozbargain", "9", "RTX 5080 $1999 @ Mwave", "u", HOY - timedelta(hours=2), votos=50)
    for k, v in cambio.items():
        setattr(p, k, v)
    ok, por_que = vigente(p, HOY)
    assert not ok and motivo in por_que
    assert vigente(Post("ozbargain", "8", "RTX 5080 $1999", "u", HOY - timedelta(days=6)), HOY)[0]


def test_posts_no_entran_al_historial():
    """Mínimo histórico y mediana salen solo de lo que el bot lee en las tiendas, nunca de posts."""
    db = DB(":memory:")
    for p in parsear_ozbargain((FIX / "ozbargain_tag_rtx5080.xml").read_text(encoding="utf-8")):
        db.guardar_post(p, [o.modelo for o in modelos_del_post(p)])
    assert db.minimo_historico("RTX 5080 16GB", "AU", datetime.now(timezone.utc)) == (None, None)
    assert db.mediana("RTX 5080 16GB", "AU") is None and db.mejor("RTX 5080 16GB", "AU") is None


def test_oportunidad_usa_solo_orden_de_gamas():
    from bot import perf
    # con los números provisorios el 9900X NO le gana al 9800X3D en juegos; por orden de gama sí
    assert perf.domina("cpu", "ryzen 9 9900x", "ryzen 7 9800x3d")
    assert not perf.domina("cpu", "ryzen 7 9800x3d", "ryzen 9 9900x")
    db = DB(":memory:")
    db.guardar_oferta(oferta("AMD Ryzen 9 9950X AM5", 900, cat="cpu", url="https://x/9950x"))
    db.guardar_oferta(oferta("AMD Ryzen 9 9950X3D AM5", 890, cat="cpu", url="https://x/x3d", tienda="msy"))
    av = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc)).evaluar_oportunidades()
    assert len(av) == 1 and "9950X3D" in av[0].texto and "Ryzen 9 9950X a" in av[0].texto


def test_post_ozbargain_urgente_por_votos():
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    p = Post("ozbargain", "1", "Gigabyte Radeon RX 9070 XT Gaming OC 16GB $999 + Delivery @ Mwave",
             "https://www.ozbargain.com.au/node/1", datetime.now(timezone.utc) - timedelta(minutes=30), votos=40)
    mods = modelos_del_post(p)
    av = m.evaluar_post(p, db.guardar_post(p, [o.modelo for o in mods]), mods)
    assert av and av[0].urgente and "40 votos" in av[0].texto
    p2 = Post("ozbargain", "2", "Gigabyte Radeon RX 9070 XT Gaming OC 16GB $999 @ Mwave",
              "https://www.ozbargain.com.au/node/2", datetime.now(timezone.utc) - timedelta(minutes=30), votos=5)
    mods2 = modelos_del_post(p2)
    av2 = m.evaluar_post(p2, db.guardar_post(p2, [o.modelo for o in mods2]), mods2)
    assert av2 and not av2[0].urgente  # pocos votos: va al resumen


@pytest.mark.parametrize("titulo,precio", [
    ("Palit GeForce RTX 5080 GamingPro OC V1 16GB GPU $2399 + Delivery ($0 to Metro Areas)", 2399),
    ("Palit GeForce RTX 5080 GamingPro OC 16GB GDDR7 Graphics Card $1,699 Delivered @ Mwave", 1699),
    ("Zotac Gaming GeForce RTX 5080 Solid Core 16GB GDDR7 Graphics Card $1709.05 Delivered", 1709.05),
    ("$100 off $1000 Minimum Spend on Select Products: Palit GeForce RTX 5080 GPU $1499", 1499),
    ("Tomtoc Travel Backpack Liteway 28L $94.98 Delivered (RRP $139.99) @ Clever Gear", 94.98),
])
def test_precio_en_titulo_ozbargain(titulo, precio):
    from bot.feeds import precio_en_titulo
    assert precio_en_titulo(titulo) == pytest.approx(precio)


def test_logs_no_muestran_secretos(monkeypatch, capsys):
    import logging
    from bot.privacidad import configurar_logs, tachar
    token = "1234567890:AAH" + "x" * 32
    monkeypatch.setenv("TELEGRAM_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID_YO", "987654321")
    configurar_logs()
    log = logging.getLogger("bot.prueba")
    log.error("fallo en https://api.telegram.org/bot%s/sendMessage para %s", token, "987654321")
    try:
        raise RuntimeError(f"boom {token}")
    except RuntimeError:
        log.exception("con traceback")
    salida = capsys.readouterr().err
    assert token not in salida and "987654321" not in salida and "api.telegram.org" not in salida
    assert "[API de Telegram]" in salida and "[telegram_chat_id_yo]" in salida
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert tachar(f"x {token} y") == "x [token] y"


def test_orden_cpu_para_edicion():
    from bot import perf
    o = perf.orden()["cpu"]
    assert o["ryzen 7 9850x3d"] < o["ryzen 9 7900"]          # más núcleos, más arriba
    assert o["ryzen 9 9900x3d"] < o["ryzen 9 7950x"]
    for base, x3d in (("ryzen 7 7700x", "ryzen 7 7800x3d"), ("ryzen 7 9700x", "ryzen 7 9800x3d"),
                      ("ryzen 9 7900x", "ryzen 9 7900x3d"), ("ryzen 9 9900x", "ryzen 9 9900x3d"),
                      ("ryzen 9 7950x", "ryzen 9 7950x3d"), ("ryzen 9 9950x", "ryzen 9 9950x3d"),
                      ("ryzen 9 9950x3d", "ryzen 9 9950x3d2")):
        assert o[base] < o[x3d]


def test_telegram_reintenta_cortes_de_red_sin_mostrar_token(monkeypatch):
    import httpx
    import pytest
    from bot import telegram as tgmod
    monkeypatch.setattr(tgmod.time, "sleep", lambda s: None)
    llamadas = {"n": 0}

    def manejador(req):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise httpx.ConnectError("caído", request=req)
        return httpx.Response(200, json={"ok": True, "result": []})

    tg = Telegram(Secretos("123:SECRETO", "1", ""))
    tg.http = httpx.Client(transport=httpx.MockTransport(manejador))
    assert tg._api("getUpdates") == []
    assert llamadas["n"] == 2

    tg.http = httpx.Client(transport=httpx.MockTransport(
        lambda req: (_ for _ in ()).throw(httpx.ConnectError("caído", request=req))))
    with pytest.raises(RuntimeError) as e:
        tg._api("getUpdates")
    assert "SECRETO" not in str(e.value) and "api.telegram.org" not in str(e.value)
