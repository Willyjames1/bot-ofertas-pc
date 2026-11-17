"""Fuentes nuevas para Black Friday: HardGamers, Maximus, OzBargain por tienda y códigos de
descuento, eBay (Browse API) con HP Official Store, y el veredicto con valija y por partes."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot import alertas, config
from bot.alertas import Motor, pasa_filtros
from bot.comparar import aviso_davinci, suma_partes
from bot.corrida import categorias_a_leer
from bot.cotizaciones import Cotizacion
from bot.db import DB
from bot.feeds import es_codigo_ebay, modelos_del_post, precio_con_codigo, precio_en_titulo
from bot.fuentes.ebay import EBay
from bot.fuentes.hardgamers import HardGamers
from bot.fuentes.maximus import Maximus
from bot.modelos import Oferta, Post
from bot.normalizar import normalizar

FIX = Path(__file__).parent / "fixtures"
CFG = config.cargar()
AHORA = datetime.now(timezone.utc)
AJ = config.ajustes(CFG, datetime(2026, 11, 18, tzinfo=timezone.utc))
COT = Cotizacion(mep=1577.0, aud_usd=0.6775, ts=AHORA)
PALABRAS = CFG["pcs"]["palabras_ozbargain"]


def oferta(titulo, precio, pais="AR", tienda="compragamer", cat="placas", **kw):
    return normalizar(Oferta(tienda, pais, cat, titulo, kw.pop("url", f"https://x/{tienda}/{titulo}"), precio,
                             "AUD" if pais == "AU" else "ARS", fecha=AHORA, **kw))


def post(titulo, desc="", url_tienda="https://www.ebay.com.au/itm/1", id_="1", expira=None):
    return Post("ozbargain", id_, titulo, f"https://www.ozbargain.com.au/node/{id_}", AHORA - timedelta(minutes=20),
                votos=3, url_tienda=url_tienda, precio=precio_en_titulo(titulo), descripcion=desc, expira=expira)


# ------------------------------------------------------------------ HardGamers

def test_hardgamers_guarda_la_tienda_real_y_saltea_las_que_leemos_directo():
    hg = HardGamers()
    ofertas, maximo, total = hg.parsear((FIX / "hardgamers_placas.html").read_text(encoding="utf-8"), "placas")
    assert total == 1940 and maximo and len(ofertas) > 40
    tiendas = {o.tienda for o in ofertas}
    assert "hg_fullh4rd" in tiendas and alertas.NOMBRE_TIENDA.get("hg_fullh4rd", hg.nombres["hg_fullh4rd"]) == "Full H4rd"
    assert not {"hg_gezatek", "hg_mexx"} & tiendas          # esas las leemos directo
    assert all(o.url.startswith("https://www.hardgamers.com.ar/product/") and o.tipo_precio == "contado"
               for o in ofertas)
    assert not any("Ofertas Destacadas" in o.titulo for o in ofertas)


class _ClienteHG:
    """36 páginas de 54 productos con precios crecientes (página n: de n·100.000 a n·100.000+53.000)."""

    def __init__(self):
        self.pedidas = []

    def get(self, url):
        n = int(url.rsplit("page=", 1)[1]) if "page=" in url else 1
        self.pedidas.append(n)
        arts = "".join(
            f'<article class="One-Bit-Product"><a href="/product/fullh4rd:p{n}x{i}"></a><p class="store">Full H4rd</p>'
            f'<p class="product-name">PLACA DE VIDEO MSI RTX 5070 TI 16GB {n}-{i}</p>'
            f'<link itemprop="availability" href="https://schema.org/InStock" />'
            f'<span itemprop="price" content="{n * 100_000 + i * 1000}">x</span></article>' for i in range(54))
        return type("R", (), {"text": f"<html>{arts}<script>var total = 1944;</script></html>"})()

    def cerrar(self):
        pass


def test_hardgamers_lee_solo_la_franja_de_precios():
    cli = _ClienteHG()
    ofertas = HardGamers(cliente=cli).leer("placas")   # franja 900.000 a 3.500.000
    precios = [o.precio for o in ofertas]
    # de la página 9 (desde $900.000) a la 35 (hasta $3.553.000): la 36 ya arranca arriba del techo
    assert min(precios) == 900_000 and max(precios) == 3_553_000
    assert not {2, 3, 4, 6, 7} & set(cli.pedidas)            # las baratas del principio no se piden
    assert len(cli.pedidas) == len(set(cli.pedidas)) < 40    # ninguna página dos veces


def test_hardgamers_una_categoria_por_corrida_rotando():
    db = DB(":memory:")
    primera = categorias_a_leer(db, CFG, AJ, "hardgamers", AHORA)
    assert len(primera) == 1
    db.set(f"ult_cat:hardgamers:{primera[0]}", AHORA.isoformat())
    segunda = categorias_a_leer(db, CFG, AJ, "hardgamers", AHORA)
    assert len(segunda) == 1 and segunda != primera


# ------------------------------------------------------------------ Maximus

def test_maximus_precio_contado_lista_y_stock():
    of, sig = Maximus().parsear((FIX / "maximus_placas.html").read_text(encoding="utf-8"),
                                Maximus.categorias["placas"][0], "placas")
    assert len(of) == 28 and sig and sig.endswith("/PAGE=2/")
    ti = next(o for o in of if "5070 TI Ventus" in o.titulo)
    assert ti.precio == 2_435_116 and ti.precio_lista == 2_727_200 and ti.tipo_precio == "transferencia"
    assert ti.stock is True and normalizar(ti).modelo == "RTX 5070 Ti 16GB"


# ------------------------------------------------------------------ SSD y PCs

def test_ssd():
    o = oferta("Samsung 990 PRO 2TB PCIe 4.0 NVMe M.2 SSD", 199, pais="AU", tienda="umart", cat="ssd")
    assert o.modelo == "SSD NVMe Gen4 2TB" and o.variante == "Samsung 990 PRO"
    assert pasa_filtros(CFG, "ssd", o.modelo, o.datos, 199, "AUD")
    assert oferta("WD_BLACK SN8100 4TB", 500, pais="AU", cat="ssd").modelo == "SSD NVMe Gen5 4TB"
    sata = oferta("Crucial MX500 2TB SATA SSD", 150, pais="AU", cat="ssd")
    assert sata.modelo == "SSD SATA 2TB" and not pasa_filtros(CFG, "ssd", sata.modelo, sata.datos, 150, "AUD")
    chico = oferta("Kingston NV3 1TB NVMe", 90, pais="AU", cat="ssd")
    assert not pasa_filtros(CFG, "ssd", chico.modelo, chico.datos, 90, "AUD")    # pide 2 o 4 TB
    assert oferta("Samsung T7 Portable SSD 2TB USB 3.2", 200, pais="AU", cat="ssd").descartada
    assert [m.modelo for m in modelos_del_post(post("Samsung 990 Pro 2TB $199 @ Amazon AU"))] == ["SSD NVMe Gen4 2TB"]


def test_pc_trae_procesador_nucleos_y_disco():
    o = oferta("HP OMEN 35L Gaming Desktop Ryzen 7 9800X3D RTX 5070 Ti 32GB DDR5 2TB SSD", 3299, pais="AU", cat="pcs")
    assert o.datos["cpu"] == "Ryzen 7 9800X3D" and o.datos["nucleos"] == 8 and o.datos["ssd_tb"] == 2
    assert aviso_davinci(CFG, o.datos) == "⚠️ Para DaVinci: el procesador tiene 8 núcleos (menos de 12)"
    o2 = oferta("PC Gamer Ryzen 9 9950X 64GB RAM 1TB NVMe RTX 5080 16GB", 9e6, cat="pcs")
    assert aviso_davinci(CFG, o2.datos) == "⚠️ Para DaVinci: el SSD es de 1TB (menos de 2TB)"
    o3 = oferta("PC Gamer Ryzen 9 9950X 64GB RAM 2TB NVMe RTX 5080 16GB", 9e6, cat="pcs")
    assert aviso_davinci(CFG, o3.datos) is None


def _db_partes():
    return [oferta("Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", 2_244_000),
            oferta("Procesador AMD Ryzen 7 9800X3D AM5", 980_939, tienda="maximus", cat="cpu"),
            oferta("Memoria Kingston DDR5 32GB (2x16GB) 6000MHz CL36", 800_000, cat="ram"),
            oferta("SSD Kingston NV3 2TB NVMe M.2", 290_000, tienda="venex", cat="ssd")]


def test_pc_australiana_contra_armarla_por_partes():
    db = DB(":memory:")
    for o in _db_partes():
        db.guardar_oferta(o)
    pc = oferta("HP OMEN 35L Gaming Desktop Ryzen 7 9800X3D RTX 5070 Ti 32GB DDR5 2TB SSD", 2899, pais="AU",
                tienda="ebay_hp_official", cat="pcs")
    alertas.NOMBRE_TIENDA.update({"maximus": "Maximus", "compragamer": "Compra Gamer", "venex": "Venex"})
    partes = suma_partes(db, CFG, pc.datos, alertas.NOMBRE_TIENDA)
    assert not partes.faltan
    assert partes.total == 2_244_000 + 980_939 + 800_000 + 290_000 + CFG["pcs"]["resto_estimado_ars"]
    t = Motor(CFG, AJ, db, COT, AHORA).texto_oferta("objetivo", pc, None, None, 3000)
    assert "🇦🇷 Armarla por partes en 🇦🇷: ~$4.864.939" in t
    assert "Ryzen 7 9800X3D $980.939 (Maximus)" in t and "mother + fuente + gabinete ~$550.000 (estimado)" in t
    assert "valija extra (A$150)" in t and "Veredicto:" in t
    assert "⚠️ Para DaVinci: el procesador tiene 8 núcleos (menos de 12)" in t


# ------------------------------------------------------------------ OzBargain y códigos

def test_black_friday_del_20_11_al_2_12():
    assert not config.es_black_friday(CFG, datetime(2026, 11, 19, 12, tzinfo=timezone.utc))
    assert config.es_black_friday(CFG, datetime(2026, 11, 20, 12, tzinfo=timezone.utc))
    assert config.es_black_friday(CFG, datetime(2026, 12, 2, 12, tzinfo=timezone.utc))
    assert not config.es_black_friday(CFG, datetime(2026, 12, 3, 12, tzinfo=timezone.utc))
    feeds = CFG["foros"]["ozbargain"]
    for tienda in ("amazon.com.au", "ebay.com.au", "scorptec.com.au", "pccasegear.com", "jbhifi.com.au"):
        assert any(f"/deals/{tienda}/feed" in f for f in feeds)


def test_codigo_se_aplica_si_el_precio_es_antes_del_codigo():
    p = post("HP OMEN 35L Ryzen 7 9800X3D RTX 5070 Ti 32GB 2TB $2,999 Delivered "
             "(Extra 20% off with code HPNOV26) @ HP eBay")
    precio, cod, aplicado = precio_con_codigo(p)
    assert cod["codigo"] == "HPNOV26" and aplicado and precio == 2399.2
    ya = post("HP OMEN 35L RTX 5080 $3,199 Delivered with Code HPNOV26 @ HP eBay")
    assert precio_con_codigo(ya)[0] == 3199 and not precio_con_codigo(ya)[2]
    tope = post("Gaming PC RTX 5070 Ti $3,000 (15% off with code PCDEAL, max discount $300) @ eBay AU")
    assert precio_con_codigo(tope)[0] == 2700


def test_post_hp_con_codigo_usa_el_precio_final():
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, AHORA)
    p = post("HP OMEN 35L Ryzen 7 9800X3D RTX 5070 Ti 32GB 2TB $3,599 Delivered (Extra 20% off with code HPNOV26) "
             "@ HP eBay")
    mods = modelos_del_post(p, PALABRAS)
    av = m.evaluar_post(p, db.guardar_post(p, [o.modelo for o in mods]), mods)
    assert av and av[0].precio == 2879.2                      # 3.599 − 20% = 2.879,20 < objetivo A$3.000
    t = av[0].texto
    assert "🏷️ Con el código <b>HPNOV26</b> (−20%): <b>A$2.879</b>" in t and "⚠️ Para DaVinci" in t
    assert json.loads(db.get("codigos_ebay"))["HPNOV26"]["vendedor"] == "hp_official"


def test_codigo_de_ebay_avisa_y_se_guarda():
    db = DB(":memory:")
    m = Motor(CFG, AJ, db, COT, AHORA)
    p = post("20% off Selected Sellers (Max Discount $500, Min Spend $100) @ eBay AU",
             desc="Use code PCPARTS20 at checkout.", id_="9")
    mods = modelos_del_post(p, PALABRAS)
    assert es_codigo_ebay(p, mods)
    av = m.evaluar_post(p, db.guardar_post(p, []), mods)
    assert len(av) == 1 and av[0].urgente and av[0].tipo == "codigo_ebay"
    assert "PCPARTS20" in av[0].texto and "−20% · tope A$500 · compra mínima A$100" in av[0].texto
    assert "vendedores seleccionados" in av[0].texto


# ------------------------------------------------------------------ eBay

def _item(titulo, precio, vendedor="pcworld_au", pais="AU", cond="1000", id_="1"):
    return {"itemId": f"v1|{id_}|0", "legacyItemId": id_, "title": titulo, "price": {"value": str(precio), "currency": "AUD"},
            "itemWebUrl": f"https://www.ebay.com.au/itm/{id_}?hash=abc", "seller": {"username": vendedor},
            "conditionId": cond, "itemLocation": {"country": pais}}


def test_ebay_filtra_vendedor_australiano_nueva_gpu_y_cpu():
    e = EBay(cfg=CFG, token="x")
    ok = e.oferta_de(_item("Gaming PC Ryzen 7 9800X3D RTX 5070 Ti 32GB DDR5 2TB NVMe", 2899))
    assert ok and ok.tienda == "ebay_pcworld_au" and ok.url == "https://www.ebay.com.au/itm/1"
    assert e.oferta_de(_item("Gaming PC Ryzen 7 9800X3D RTX 5070 Ti 32GB", 2899, pais="CN")) is None
    assert e.oferta_de(_item("Gaming PC Ryzen 7 9800X3D RTX 5070 Ti 32GB", 2899, cond="3000")) is None   # usada
    assert e.oferta_de(_item("Gaming PC Ryzen 5 9600X RTX 5070 Ti 32GB", 2299)) is None                 # Ryzen 5
    assert e.oferta_de(_item("Gaming PC Ryzen 7 9800X3D RTX 5070 32GB", 2299)) is None                  # 5070 a secas
    assert e.oferta_de(_item("Gaming PC Core Ultra 7 265K RTX 5080 32GB", 3299)) is not None


def test_hp_vuelve_a_tener_stock_y_aplica_su_codigo():
    db = DB(":memory:")
    e = EBay(cfg=CFG, token="x")
    hp = e.oferta_de(_item("HP OMEN 35L Gaming Desktop Ryzen 7 9800X3D RTX 5070 Ti 32GB 2TB", 3599,
                           vendedor="hp_official", id_="77"))
    assert hp.datos["seguido"] and alertas.NOMBRE_TIENDA["ebay_hp_official"] == "HP Official Store (eBay)"
    m = Motor(CFG, AJ, db, COT, AHORA - timedelta(hours=2))
    m.evaluar_oferta(hp, db.guardar_oferta(hp))
    # en la corrida siguiente no apareció: queda sin stock
    assert db.marcar_sin_stock("ebay_hp_official", datetime.now(timezone.utc) + timedelta(seconds=1)) == 1
    # y en la otra vuelve, con un código de HP visto en OzBargain
    m2 = Motor(CFG, AJ, db, COT, datetime.now(timezone.utc))
    m2.guardar_codigo(post("HP OMEN Extra 20% off with code HPNOV26 @ HP eBay"),
                      {"codigo": "HPNOV26", "pct": 20, "tope": None, "minimo": None})
    vuelve = e.oferta_de(_item("HP OMEN 35L Gaming Desktop Ryzen 7 9800X3D RTX 5070 Ti 32GB 2TB", 3599,
                               vendedor="hp_official", id_="77"))
    av = m2.evaluar_oferta(vuelve, db.guardar_oferta(vuelve))
    assert len(av) == 1 and av[0].urgente and av[0].tipo == "stock"
    t = av[0].texto
    assert t.startswith("📦 <b>PC RTX 5070 Ti</b> — volvió a tener stock en 🇦🇺")
    assert "@ HP Official Store (eBay): <b>A$3.599</b>" in t
    assert "🏷️ Con el código <b>HPNOV26</b> (−20%, visto en OzBargain): <b>A$2.879</b>" in t
    assert av[0].precio == 2879.2


def test_ebay_sin_claves_no_lee_ni_falla(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    assert EBay(cfg=CFG).leer("pcs") == []
