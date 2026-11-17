"""Alertas por precio objetivo: RAM por capacidad/módulos/velocidad, PCs armadas, marketplaces
y el "% abajo del objetivo" en el mensaje."""
from datetime import datetime, timedelta, timezone

import pytest

from bot import alertas, config
from bot.alertas import Motor, bajo_objetivo, despachar, objetivo_de, pasa_filtros, ram_cumple
from bot.config import Secretos
from bot.cotizaciones import Cotizacion
from bot.db import DB
from bot.feeds import es_pc, modelos_del_post
from bot.fuentes import TIENDAS
from bot.fuentes.mexx import Mexx
from bot.modelos import Oferta, Post
from bot.normalizar import normalizar
from bot.telegram import Telegram

CFG = config.cargar()
AJ = config.ajustes(CFG, datetime(2026, 11, 16, tzinfo=timezone.utc))
COT = Cotizacion(mep=1580.0, aud_usd=0.68, ts=datetime.now(timezone.utc))
PALABRAS = CFG["pcs"]["palabras_ozbargain"]
alertas.NOMBRE_TIENDA.update({k: v.nombre for k, v in TIENDAS.items()})


def oferta(titulo, precio, cat="placas", pais="AU", tienda="umart", url=None):
    return normalizar(Oferta(tienda, pais, cat, titulo, url or f"https://x/{tienda}/{titulo}", precio,
                             "AUD" if pais == "AU" else "ARS"))


def post(id_, titulo, votos=3, url_tienda=None):
    from bot.feeds import precio_en_titulo
    return Post("ozbargain", id_, titulo, f"https://www.ozbargain.com.au/node/{id_}",
                datetime.now(timezone.utc) - timedelta(minutes=20), votos=votos, url_tienda=url_tienda,
                precio=precio_en_titulo(titulo), moneda="AUD")


# ------------------------------------------------------------------ objetivos cargados

@pytest.mark.parametrize("titulo,cat,moneda,esperado", [
    ("MSI RTX 5070 Ti 16G Ventus 3X OC", "placas", "AUD", 1450),
    ("MSI RTX 5070 Ti 16G Ventus 3X OC", "placas", "ARS", 2100000),
    ("Gigabyte RTX 5080 16GB Windforce", "placas", "AUD", 1900),
    ("Gigabyte RTX 5080 16GB Windforce", "placas", "ARS", 2800000),
    ("AMD Ryzen 9 9900X AM5", "cpu", "AUD", 580),
    ("AMD Ryzen 9 9900X AM5", "cpu", "ARS", 650000),
    ("AMD Ryzen 9 9950X AM5", "cpu", "AUD", 800),
    ("AMD Ryzen 9 9950X AM5", "cpu", "ARS", 1000000),
    ("Kingston FURY 32GB (2x16GB) DDR5 6000MHz CL30", "ram", "AUD", 550),
    ("Kingston FURY 32GB (2x16GB) DDR5 6000MHz CL30", "ram", "ARS", 750000),
    ("Kingston FURY 32GB (2x16GB) DDR5 6400MHz CL32", "ram", "AUD", 550),  # 6400 también cuenta
    ("G.Skill 64GB (2x32GB) DDR5 6000MHz CL30", "ram", "AUD", 1100),
])
def test_objetivos_del_pedido(titulo, cat, moneda, esperado):
    o = oferta(titulo, 1, cat=cat)
    assert objetivo_de(CFG, cat, o.modelo, o.datos, moneda) == esperado


def test_objetivos_que_no_aplican():
    x3d = oferta("AMD Ryzen 9 9900X3D AM5", 1, cat="cpu")
    assert objetivo_de(CFG, "cpu", x3d.modelo, x3d.datos, "AUD") is None  # 9900X no es 9900X3D
    lenta = oferta("Kingston 32GB (2x16GB) DDR5 5600MHz CL36", 1, cat="ram")
    assert objetivo_de(CFG, "ram", lenta.modelo, lenta.datos, "AUD") is None
    assert objetivo_de(CFG, "ram", lenta.modelo, lenta.datos, "ARS") is None
    assert objetivo_de(CFG, "ram", "x", {"capacidad_gb": 64, "modulos": 2, "velocidad": 5600}, "ARS") == 1800000


def test_ram_cumple():
    d = {"capacidad_gb": 32, "modulos": 2, "velocidad": 6000}
    assert ram_cumple("32GB (2x16) 6000", d) and ram_cumple("32GB", d) and ram_cumple("32GB (2x16GB)", d)
    assert not ram_cumple("32GB (1x32)", d) and not ram_cumple("32GB 6400", d) and not ram_cumple("64GB", d)


# ------------------------------------------------------------------ mensaje

def test_mensaje_dice_cuanto_abajo_del_objetivo():
    assert bajo_objetivo(1350, 1450, "AUD") == "🎯 Objetivo: A$1.450 · <b>7% abajo</b> (A$100 menos)"
    assert bajo_objetivo(1500, 1450, "AUD") == "🎯 Objetivo: A$1.450"
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    o = oferta("Gigabyte RTX 5070 Ti 16GB Eagle OC", 1_900_000, pais="AR", tienda="compragamer")
    o.tipo_precio, o.precio_lista = "transferencia", 2_100_000
    av = m.evaluar_oferta(o, db.guardar_oferta(o))
    assert len(av) == 1 and av[0].urgente
    t = av[0].texto
    assert "RTX 5070 Ti 16GB" in t and "$1.900.000</b> transferencia" in t and "Compra Gamer" in t
    assert "10% abajo" in t and "Ver en la tienda" in t and o.url in t


# ------------------------------------------------------------------ PCs armadas

def test_pc_de_tienda_ar_con_5070ti_bajo_objetivo_avisa_una_vez():
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    titulo = "PC Gamer Kairos AMD Ryzen 7 9700X 32GB 1TB NVMe NVIDIA GeForce RTX 5070 Ti"
    o = oferta(titulo, 3_800_000, cat="pcs", pais="AR", tienda="venex", url="https://v/pc1")
    assert o.modelo == "PC RTX 5070 Ti" and not o.descartada
    av = m.evaluar_oferta(o, db.guardar_oferta(o))
    assert len(av) == 1 and "PC ARMADA" in av[0].texto and titulo in av[0].texto and "5% abajo" in av[0].texto
    despachar(av, Telegram(Secretos("", "1", ""), dry_run=True), db, CFG, AJ, Secretos("", "1", ""),
              datetime(2026, 11, 16, 15, tzinfo=timezone.utc))
    o2 = oferta(titulo, 3_750_000, cat="pcs", pais="AR", tienda="venex", url="https://v/pc1")  # −1%
    assert not m.evaluar_oferta(o2, db.guardar_oferta(o2))
    o3 = oferta(titulo, 3_600_000, cat="pcs", pais="AR", tienda="venex", url="https://v/pc1")  # −5%
    assert m.evaluar_oferta(o3, db.guardar_oferta(o3))
    # otra PC con la misma placa es otro producto: avisa aparte
    o4 = oferta(titulo + " White", 3_900_000, cat="pcs", pais="AR", tienda="venex", url="https://v/pc2")
    assert m.evaluar_oferta(o4, db.guardar_oferta(o4))


@pytest.mark.parametrize("titulo,precio,avisa", [
    ("PC Gamer AMD Ryzen 5 8400F 16GB 1TB RTX 5060 Ti", 2_000_000, False),   # placa chica
    ("PC IA ASUS Ryzen 5 8600G 32GB 1TB Radeon RX9070 XT", 3_000_000, False),  # no es RTX
    ("PC IA Kairos Ryzen 5 9600X 32GB 1TB RTX 5070 Ti", 5_285_929, False),     # sobre el objetivo
    ("PC Gamer Ryzen 7 9800X3D 32GB RTX 5080", 3_990_000, True),
    ("PC Gamer Ryzen 7 9800X3D 32GB RTX 5090 Reacondicionada", 3_000_000, False),  # usada
])
def test_pc_filtros(titulo, precio, avisa):
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    o = oferta(titulo, precio, cat="pcs", pais="AR", tienda="gezatek")
    assert bool(m.evaluar_oferta(o, db.guardar_oferta(o))) is avisa


def test_pc_mexx_usa_la_placa_de_la_ficha():
    o = Oferta("mexx", "AR", "pcs", "GP715 Pc Amd Ryzen 7 7700X - 32Gb - 1Tb - RTX 5070", "u", 3_000_000, "ARS",
               datos={"placa": "Placa De Video GeForce RTX 5070 Ti 16Gb Asus Prime"})
    assert normalizar(o).modelo == "PC RTX 5070 Ti"
    ficha = ("<html><body>Componentes Gabinete Mid Tower Cant: 1 Garantía: 12 meses "
             "Placa De Video GeForce RTX 5060 8Gb Asus Dual Oc EvoCant: 1Garantía: 12 meses</body></html>")
    assert Mexx.__new__(Mexx).placa_de_ficha(ficha) == "Placa De Video GeForce RTX 5060 8Gb Asus Dual Oc Evo"


@pytest.mark.parametrize("titulo,pc", [
    ("Gaming PC Ryzen 7 9800X3D RTX 5070 Ti 32GB DDR5 2TB $2,799 @ Techfast", True),
    ("Prebuilt: Intel Ultra 7 265K, RTX 5080, 32GB $2,999 @ Scorptec", True),
    ("Desktop Ryzen 7 7700 RTX 5070 Ti 32GB 1TB $2,499 @ JB Hi-Fi", True),
    ("AMD Ryzen 9 9950X Desktop Processor $749 @ Amazon AU", False),
    ("Kingston 32GB DDR5 6000 Desktop RAM $149 @ Amazon AU", False),
    ("Gigabyte RTX 5080 Graphics Card for Desktop $1,499 @ Mwave", False),
])
def test_es_pc(titulo, pc):
    assert es_pc(titulo, PALABRAS) is pc


def test_post_pc_ozbargain_bajo_3000_avisa_y_componentes_siguen_igual():
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    p = post("10", "Gaming PC Ryzen 7 9800X3D RTX 5070 Ti 32GB DDR5 2TB $2,799 @ Techfast")
    mods = modelos_del_post(p, PALABRAS)
    assert [o.modelo for o in mods] == ["PC RTX 5070 Ti"]
    av = m.evaluar_post(p, db.guardar_post(p, [o.modelo for o in mods]), mods)
    assert av and av[0].urgente
    t = av[0].texto
    assert "PC ARMADA" in t and "A$2.799</b> en Techfast" in t and "7% abajo" in t and "Ver el post" in t
    caro = post("11", "Gaming PC Ryzen 7 9800X3D RTX 5080 32GB $3,299 @ Techfast", votos=80)
    mods = modelos_del_post(caro, PALABRAS)
    assert not [a for a in m.evaluar_post(caro, db.guardar_post(caro, ["x"]), mods) if a.urgente]  # PCs: solo por precio
    cpu = post("12", "AMD Ryzen 9 9950X Desktop Processor $749 @ Amazon AU")
    mods = modelos_del_post(cpu, PALABRAS)
    assert [o.modelo for o in mods] == ["Ryzen 9 9950X"]
    av = m.evaluar_post(cpu, db.guardar_post(cpu, ["Ryzen 9 9950X"]), mods)
    assert av and av[0].urgente and "6% abajo" in av[0].texto


@pytest.mark.parametrize("titulo,url_tienda", [
    ("Gigabyte RTX 5070 Ti 16GB Eagle $1,299 Delivered @ eBay (Shopping Express)", None),
    ("Gigabyte RTX 5070 Ti 16GB Eagle $1,299 Delivered", "https://www.ebay.com.au/itm/1"),
    ("Gigabyte RTX 5070 Ti 16GB Eagle $1,299 Delivered @ Catch", "https://www.catch.com.au/p/1"),
    ("Gigabyte RTX 5070 Ti 16GB Eagle $1,299 @ Amazon Marketplace", None),
    ("Gigabyte RTX 5070 Ti 16GB Eagle Refurbished $1,099 @ PCByte", None),
])
def test_posts_de_marketplace_y_usados_no_avisan(titulo, url_tienda):
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    p = post("20", titulo, url_tienda=url_tienda)
    mods = modelos_del_post(p, PALABRAS)
    assert not [a for a in m.evaluar_post(p, db.guardar_post(p, [o.modelo for o in mods]), mods) if a.urgente]


def test_post_de_tienda_normal_avisa():
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    p = post("21", "Gigabyte RTX 5070 Ti 16GB Eagle $1,299 Delivered @ Amazon AU", url_tienda="https://www.amazon.com.au/dp/1")
    mods = modelos_del_post(p, PALABRAS)
    av = m.evaluar_post(p, db.guardar_post(p, [o.modelo for o in mods]), mods)
    assert av and av[0].urgente and "10% abajo" in av[0].texto
