"""Black Friday: cuotas y promos (fichas reales), mínimo de 75 días de HardGamers, referencias en USD MEP,
descuento inflado, lo que te falta comprar, la canasta del hermano y el resumen especial."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot import alertas, black_friday, compras, config, cuotas as C, fichas, historial
from bot.alertas import Motor
from bot.cotizaciones import Cotizacion
from bot.db import DB
from bot.modelos import Oferta
from bot.normalizar import normalizar

FIX = Path(__file__).parent / "fixtures"
CFG = config.cargar()
AHORA = datetime(2026, 11, 25, 17, tzinfo=timezone.utc)          # 14:00 en Argentina
AJ = config.ajustes(CFG, AHORA)
COT = Cotizacion(mep=1600.0, aud_usd=0.66, ts=AHORA)
TASA = 0.0167


def _oferta(db, tienda, titulo, precio, cat="placas", pais="AR", url=None, fecha=AHORA, **kw):
    o = normalizar(Oferta(tienda, pais, cat, titulo, url or f"https://{tienda}/{titulo}", precio,
                          "ARS" if pais == "AR" else "AUD", fecha=fecha, stock=True, **kw))
    db.guardar_oferta(o)
    db.registrar_pasada(tienda, cat, fecha)
    return o


# ------------------------------------------------------------------ cuotas de las fichas

@pytest.mark.parametrize("tienda,lista,planes", [
    # "Sin interés $2.089.989,00 3 cuotas sin interés de $696.663,00" y "12 Pagos $205863,92 (PTF: …)"
    ("gezatek", 2_089_989, {3: True, 6: False, 12: False}),
    # la tabla "Cuotas Interés 3 Sin interés 6 20.00% … 12 Sin interés" sobre el precio de lista
    ("mexx", 1_111_389, {3: True, 6: False, 9: False, 12: True, 18: False}),
    # "Cuotas Web 3 x … Sin interés"; lo de "Cuotas en el local … Mercado Pago 13% OFF" no cuenta
    ("katech", 1_114_412, {3: True, 6: True, 9: False, 12: False}),
])
def test_cuotas_de_fichas_reales(tienda, lista, planes):
    texto = (FIX / f"{tienda}_ficha_cuotas.txt").read_text(encoding="utf-8")
    assert C.lista_de_texto(texto) == lista
    leidos = C.planes_de_texto(texto, lista)
    assert {p.cuotas: p.sin_interes for p in leidos} == planes
    for p in leidos:
        assert p.total >= lista * 0.99     # nunca menos que la lista


def test_plan_mas_barato_que_la_lista_no_cuenta():
    """Katech: un "2 x $968.320" de otra cosa en la página (da menos que la lista) no es un plan."""
    t = "Precio de lista $3.058.744,00 Cuotas Web 2 x $968.320,00 3 x $1.019.581,33 Sin interés"
    assert [(p.cuotas, p.sin_interes) for p in C.planes_de_texto(t)] == [(3, True)]
    # y en el precio real, un plan que da menos que la transferencia se descarta
    pg = C.pagos(2_000_000, 2_200_000, [C.Plan(3, 500_000, True)], [], TASA)
    assert pg.plan is None and pg.real == 2_000_000


def test_valor_contado_y_precio_real():
    # 12 cuotas de $100.000 al 1,67% mensual: la primera se paga al mes
    v = C.valor_contado(100_000, 12, TASA)
    assert v == pytest.approx(sum(100_000 / (1 + TASA) ** k for k in range(1, 13)))
    assert v < 1_200_000
    # 12 sin interés de la lista $2.720.000 ≈ $2.390.000 de contado: más barato que $2.400.000 transferencia
    pg = C.pagos(2_400_000, 2_720_000, [C.Plan(12, 226_667, True)], [], 0.02)   # 2% por mes
    assert pg.conviene_cuotas and pg.real == pytest.approx(pg.contado) and pg.real < 2_400_000
    lineas = C.lineas_pagos(pg)
    assert lineas[0] == "💵 Transferencia: <b>$2.400.000</b>"
    assert lineas[1].startswith("💳 Lista: $2.720.000 · 12 cuotas sin interés de $226.667 (≈ $2.")


def test_tasa_de_plazo_fijo_y_configurable():
    db = DB(":memory:")
    db.set("tasa_plazo_fijo", json.dumps({"ts": AHORA.isoformat(), "tna": 0.24, "bancos": 30}))
    assert C.tasa_mensual(db, CFG, ahora=AHORA)[0] == pytest.approx(0.02)
    assert C.tasa_mensual(db, {"cuotas": {"tasa_mensual_pct": 3}}, ahora=AHORA)[0] == pytest.approx(0.03)


# ------------------------------------------------------------------ promos

def test_promos_compragamer_reales():
    datos = json.loads((FIX / "compragamer_promos.json").read_text(encoding="utf-8"))
    ps = C.promos_compragamer(datos, date(2026, 11, 25))
    modo = next(p for p in ps if p.medio == "MODO")
    assert modo.general and modo.sin_interes and modo.cuotas == 6 and "30/11/2026" in modo.texto
    icbc = [p for p in ps if p.medio == "Banco ICBC"]
    assert icbc and not any(p.general for p in icbc) and max(p.cuotas for p in icbc) == 12
    # las vencidas no salen
    assert not C.promos_compragamer(datos, date(2027, 3, 1)) or all(
        not p.vencida(date(2027, 3, 1)) for p in C.promos_compragamer(datos, date(2027, 3, 1)))


def test_promo_de_banco_cuenta_solo_con_tu_tarjeta():
    icbc = C.Promo("compragamer", "12 cuotas sin interés con Banco ICBC", 12, True, "Banco ICBC", general=False)
    modo = C.Promo("compragamer", "6 cuotas sin interés con MODO", 6, True, "MODO", general=True)
    assert not icbc.vale_para([]) and icbc.vale_para(["ICBC"]) and modo.vale_para([])
    sin = C.pagos(1_000_000, 1_111_100, [], [icbc, modo], TASA)
    con = C.pagos(1_000_000, 1_111_100, [], [icbc, modo], TASA, ["ICBC"])
    assert sin.plan.cuotas == 6 and con.plan.cuotas == 12 and con.contado < sin.contado
    assert sin.promos[0].startswith("12 cuotas sin interés con Banco ICBC")   # las de banco, primero


def test_promos_de_texto():
    ps = C.promos_de_texto("maximus", "Mercado Pago: 3 y 6 cuotas sin interés, o 1, 9, 12, 18 y 24 cuotas fijas")
    assert [(p.cuotas, p.sin_interes, p.general) for p in ps] == [(6, True, True)]


# ------------------------------------------------------------------ HardGamers: mínimo de 75 días

def test_ficha_hardgamers():
    f = fichas.parsear_ficha_hg((FIX / "hardgamers_ficha.html").read_text(encoding="utf-8"), date(2026, 11, 25))
    assert f["minimo"] == 2_249_000 and f["minimo_dias"] == 20
    assert f["destino"].startswith("https://wiztech.com.ar/")
    assert f["historial"][0] == (date(2026, 11, 6), 2_249_000) and f["historial"][-1][0] == date(2026, 11, 25)


# ------------------------------------------------------------------ referencias en USD MEP

def _base_con_historia():
    """Una 5070 Ti en Compra Gamer: $2.400.000 hace 30 días, $2.300.000 hace 7, hoy $2.250.000; el MEP
    subió de 1.450 a 1.600 (en pesos bajó 6%; en USD, más)."""
    db = DB(":memory:")
    meps = {AHORA.date() - timedelta(days=d): 1450 + (30 - d) * 5 for d in range(0, 76)}
    meps[AHORA.date()] = 1600
    db.c.executemany("INSERT INTO mep_diario VALUES(?,?)", [(str(d), m) for d, m in meps.items()])
    url = "https://compragamer.com/producto/MSI_RTX_5070_Ti_1"
    for dias, precio in ((30, 2_400_000), (7, 2_300_000), (0, 2_250_000)):
        _oferta(db, "compragamer", "Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", precio, url=url,
                fecha=AHORA - timedelta(days=dias))
    return db, url


def test_referencias_en_usd_mep():
    db, _ = _base_con_historia()
    it = compras.items(CFG)[0]
    ref = historial.referencias(db, "AR", "placas", it.cumple, 2_250_000, AHORA)
    assert ref.hoy.usd == pytest.approx(2_250_000 / 1600)
    assert ref.hace7.precio == 2_300_000 and ref.hace30.precio == 2_400_000
    lineas = historial.lineas_referencias(ref)
    assert lineas[0] == "📊 Hoy: $2.250.000 (USD 1.406)"
    assert lineas[1].startswith("   Hace 7 días: $2.300.000 (USD ")
    assert lineas[-1].startswith("→ En USD está ") and "más barato que hace una semana" in lineas[-1]


def test_minimo_de_hardgamers_en_las_referencias():
    db, _ = _base_con_historia()
    hg = "https://www.hardgamers.com.ar/product/tienda:abc"
    _oferta(db, "hg_tienda", "Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", 2_260_000, url=hg)
    db.c.execute("INSERT INTO fichas(url, ts, minimo, minimo_dias) VALUES(?,?,?,?)", (hg, AHORA.isoformat(), 2_190_000, 75))
    it = compras.items(CFG)[0]
    ref = historial.referencias(db, "AR", "placas", it.cumple, 2_250_000, AHORA)
    assert ref.minimo_fuente == "HardGamers" and ref.minimo.precio == 2_190_000
    assert any(x.startswith("   Mínimo 75 días (HardGamers): $2.190.000") for x in historial.lineas_referencias(ref))


def test_descuento_inflado():
    """Subió en USD en los 14 días antes del 27/11 y después "bajó": ⚠️ aunque en pesos parezca oferta.
    (Subió el 20/11 a la tarde: el mínimo de ese día es todavía el viejo; el primer día caro es el 21/11.)"""
    db = DB(":memory:")
    db.c.executemany("INSERT INTO mep_diario VALUES(?,?)",
                     [(str(date(2026, 11, 1) + timedelta(days=d)), 1500) for d in range(40)])
    url = "https://compragamer.com/producto/x"
    for d, precio in ((date(2026, 11, 12), 1_000_000), (date(2026, 11, 20), 1_150_000), (date(2026, 11, 27), 1_030_000)):
        _oferta(db, "compragamer", "Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", precio, url=url,
                fecha=datetime.combine(d, datetime.min.time(), timezone.utc) + timedelta(hours=15))
    fila = dict(db.c.execute("SELECT * FROM ofertas WHERE url=?", (url,)).fetchone())
    ahora = datetime(2026, 11, 27, 16, tzinfo=timezone.utc)
    t = historial.inflado(db, fila, ahora, date(2026, 11, 27))
    assert t and t.startswith("⚠️ Descuento inflado: el 21/11 lo subió a USD 767 (+15% desde el 13/11) "
                              "y ahora lo \"bajó\" 10% a USD 687: contra el 13/11 está 3% más caro")
    # una baja de verdad (queda abajo de lo que estaba antes de subir) no es inflado
    fila["precio"] = 900_000
    assert historial.inflado(db, fila, ahora, date(2026, 11, 27)) is None


# ------------------------------------------------------------------ lo que te falta comprar

@pytest.mark.parametrize("cat,titulo,falta", [
    ("ram", "Kingston FURY 32GB (2x16GB) DDR5 6000MHz CL30", True),
    ("ram", "Kingston FURY 32GB (2x16GB) DDR5 6000MHz CL40", False),          # CL40 > 36
    ("ram", "Kingston FURY 64GB (2x32GB) DDR5 6000MHz CL30", False),
    ("ssd", "Samsung 990 PRO 2TB NVMe M.2", True),
    ("ssd", "Kingston NV3 2TB NVMe M.2 Gen4", False),                         # 6.000 MB/s: menos de 7.000
    ("mothers", "Mother ASUS TUF GAMING B850-PLUS WIFI AM5", True),
    ("mothers", "Mother ASUS PRIME B850M-A AM5", False),                       # sin WiFi
    ("fuentes", "Fuente Corsair RM850e 850W 80 Plus Gold ATX 3.1 Full Modular", True),
    ("fuentes", "Fuente Corsair CX750 750W 80 Plus Bronze", False),
    ("refrigeracion", "Water Cooler Arctic Liquid Freezer III 360 ARGB", True),
    ("refrigeracion", "Water Cooler Arctic Liquid Freezer III 240", False),
    ("gabinetes", "Gabinete Lian Li Lancool 216 Mid Tower", True),
    ("gabinetes", "Gabinete Sentey con fuente 500W", False),
])
def test_items_de_la_lista(cat, titulo, falta):
    o = _oferta(DB(":memory:"), "compragamer", titulo, 100, cat=cat)
    fila = {"categoria": cat, "titulo": titulo, "modelo": o.modelo, "datos": o.datos}
    assert (compras.item_de(CFG, fila, "AR") is not None) is falta


def test_baja_contra_la_mediana_de_30_dias_avisa():
    """5070 Ti: 30 días a ~USD 1.550 y hoy USD 1.406 (−9%): pasa el umbral de 8% de las placas."""
    db = DB(":memory:")
    db.c.executemany("INSERT INTO mep_diario VALUES(?,?)", [(str(AHORA.date() - timedelta(days=d)), 1600) for d in range(40)])
    url = "https://compragamer.com/producto/a"
    for d in range(30, 0, -3):
        _oferta(db, "compragamer", "Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", 2_480_000, url=url,
                fecha=AHORA - timedelta(days=d))
    m = Motor(CFG, AJ, db, COT, AHORA, tasa=TASA)
    o = normalizar(Oferta("compragamer", "AR", "placas", "Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", url,
                          2_250_000, "ARS", fecha=AHORA, stock=True, tipo_precio="transferencia"))
    av = m.evaluar_oferta(o, db.guardar_oferta(o))
    assert len(av) == 1 and av[0].urgente
    t = av[0].texto
    assert t.startswith("🔻 <b>RTX 5070 Ti 16GB</b> — 9% abajo de la mediana de 30 días (en USD) en 🇦🇷")
    assert "💵 Transferencia: <b>$2.250.000</b>" in t and "📊 Hoy: $2.250.000 (USD 1.406)" in t
    assert "(antes" not in t     # no contra el "precio anterior" de la tienda


def test_cuotas_nuevas_avisan_aunque_no_baje():
    db = DB(":memory:")
    o = _oferta(db, "mexx", "Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", 2_000_000, tipo_precio="transferencia")
    fila = dict(db.c.execute("SELECT * FROM ofertas").fetchone())
    it = compras.items(CFG)[0]
    m = Motor(CFG, AJ, db, COT, AHORA, tasa=TASA)
    plan = C.Plan(12, 185_000, True)
    db.c.execute("INSERT INTO fichas(url, ts, lista, planes) VALUES(?,?,?,?)",
                 (o.url, AHORA.isoformat(), 2_220_000, json.dumps([plan.a_lista()])))
    av = m.evaluar_cuotas([fichas.Cambio(fila, it, 0, plan, 1_900_000, 2_220_000, "2026-11-20T15:00:00+00:00")])
    assert len(av) == 1 and av[0].tipo == "cuotas"
    t = av[0].texto
    assert t.startswith("💳 <b>RTX 5070 Ti 16GB</b> — no bajó de precio, pero agregó 12 cuotas sin interés ⚠️")
    # 12 × $185.000 al 1,67% mensual ≈ $1.998.000 de contado: apenas menos que $2.000.000 transferencia
    assert "→ ✅ Conviene: 12 cuotas de $185.000" in t
    assert "⚠️ Al mismo tiempo subió el precio de lista" in t   # $1,9M → $2,22M: +17% en USD


def test_comprado_no_avisa_y_umbrales():
    assert compras.comprado(CFG, "cpu") and not compras.comprado(CFG, "placas")
    assert compras.umbral(CFG, "placas") == 8 and compras.umbral(CFG, "ram") == 10
    assert compras.umbral(CFG, "teclados") == 15 and compras.umbral(CFG, "mouse") == 15
    assert compras.hermano(CFG)["trae"] == ["ram", "placas", "ssd", "mouse"]


# ------------------------------------------------------------------ resumen de Black Friday

def test_horarios_del_resumen():
    db = DB(":memory:")
    a = lambda h, m=0: datetime(2026, 11, 27, h + 3, m, tzinfo=timezone.utc)   # hora argentina + 3
    assert black_friday.toca(db, CFG, a(8, 59)) is None
    slot = black_friday.toca(db, CFG, a(9, 5))
    assert slot == "2026-11-27 09:00"
    black_friday.marcar_enviado(db, slot)
    assert black_friday.toca(db, CFG, a(10)) is None
    assert black_friday.toca(db, CFG, a(13, 1)) == "2026-11-27 13:00"
    assert black_friday.toca(db, CFG, a(17)) is None           # el de las 13 se pasó hace más de 3 h
    assert black_friday.toca(db, CFG, a(20, 30)) == "2026-11-27 20:00"
    assert black_friday.toca(db, CFG, datetime(2026, 11, 28, 13, tzinfo=timezone.utc)) is None


def test_canasta_del_hermano_aduana_sobre_el_total():
    """Cada cosa sola pasa sin aduana, pero juntas pasan los USD 500: la cuenta es sobre el total."""
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, AHORA, tasa=TASA)
    ref = historial.Referencias("AR", historial.Punto(1, None), None, None, None, "", None, 0)
    mk = lambda pais, precio: black_friday.Mejor(pais, {}, precio, None, ref, None)
    mejores = {"RAM": (mk("AR", 900_000), mk("AU", 450)),      # A$450 = USD 297
               "SSD": (mk("AR", 600_000), mk("AU", 400))}      # A$400 = USD 264 → juntas USD 561
    mejor, (todo,) = black_friday.canasta(m, mejores)
    assert todo.usd_total == pytest.approx(561, abs=1)
    assert todo.aduana_ars == pytest.approx(0.5 * (todo.usd_total - 500) * 1600)
    assert set(mejor.traer) == {"RAM", "SSD"}
    assert mejor.total_ars <= min(c.total_ars for c in [todo])


def test_resumen_black_friday_con_datos():
    db, _ = _base_con_historia()
    _oferta(db, "umart", "MSI GeForce RTX 5070 Ti 16G Ventus 3X OC", 1399, pais="AU")
    m = Motor(CFG, AJ, db, COT, AHORA, tasa=TASA)
    msgs = black_friday.textos(m)
    t = "\n\n".join(msgs)
    assert t.startswith("🛍️ <b>Black Friday — lo que te falta comprar</b>")
    assert "Ya comprado: Ryzen 9 9900X" in t
    assert "🎮 <b>RTX 5070 Ti</b> · objetivo 🇦🇷 USD 1.250 / 🇦🇺 A$1.440" in t
    assert "📊 Hoy: $2.250.000 (USD 1.406)" in t
    assert "✅ Comprar ya — 3% abajo de tu objetivo (A$1.440)" in t          # 🇦🇺 A$1.399
    # 🇦🇷 USD 1.406: 12% arriba del objetivo, pero el más barato desde que hay datos
    assert "✅ Comprar ya — en el mínimo desde el " in t
    assert "⌨️ <b>Teclado</b>\n   Decime qué modelo querés" in t
    assert all(len(x) <= black_friday.LIMITE_MENSAJE for x in msgs)
