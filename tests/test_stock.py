"""Stock: qué cuenta como sin stock, la verificación en la tienda real, el estado de cada
publicación (confirmado / sin confirmar / afuera), el botón "❌ Sin stock" y la exportación."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from bot import alertas, exportar, stock
from bot.alertas import Aviso
from bot.cotizaciones import Cotizacion
from bot.db import DB
from bot.modelos import Oferta
from bot.normalizar import normalizar
from bot.red import Cliente
from bot.stock import (Verificador, clave_url, estado_etiqueta, estado_pagina, estado_schema, estado_shopify,
                       estado_texto, link_tienda_hg, sin_rastreo)

AHORA = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ textos

@pytest.mark.parametrize("texto", [
    "Agotado", "AGOTADA", "Sin stock", "SIN STOCK", "Sin existencias", "0 unidades", "Consultar", "Consultar stock",
    "Preventa", "Pre-venta", "Sold out", "Sold Out", "Out of stock", "Out Of Stock", "No longer available",
    "NO LONGER AVAILABLE", "Discontinued", "Discontinuado", "Pre-order", "Preorder", "PRE ORDER", "Back-order",
    "No disponible", "Not available", "Unavailable", "Arriving soon", "Disponible para preventa",
])
def test_sin_stock(texto):
    assert estado_texto(texto) is False
    assert estado_etiqueta(texto) is False


@pytest.mark.parametrize("texto", ["En stock", "In Stock", "Disponible", "Available", "Últimas unidades",
                                   "Limited stock", "Entrega inmediata"])
def test_con_stock(texto):
    assert estado_texto(texto) is True


def test_etiquetas_ar_y_casos_raros():
    assert estado_etiqueta("Stock: 3") is True          # Gezatek / Mexx: "STOCK" a secas es que hay
    assert estado_etiqueta("STOCK") is True
    assert estado_texto("Stock: 3") is None
    assert estado_texto("") is None and estado_etiqueta(None) is None
    assert estado_texto("Envío gratis") is None
    assert estado_texto("SOLDADOR") is None             # no confunde palabras que empiezan igual


@pytest.mark.parametrize("valor,esperado", [
    ("https://schema.org/InStock", True), ("http://schema.org/OutOfStock", False), ("SoldOut", False),
    ("https://schema.org/PreOrder", False), ("schema.org/Discontinued", False), ("BackOrder", False),
    ("LimitedAvailability", True), ("in stock", True), ("out of stock", False), ("preorder", False),
    ("", None), (None, None),
])
def test_schema(valor, esperado):
    assert estado_schema(valor) is esperado


# ------------------------------------------------------------------ ficha de producto

def _ld(*bloques):
    return "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in bloques)


def test_pagina_json_ld_el_primer_producto_manda():
    html = ("<div class='banner'>In stock! Free shipping</div>" +
            _ld({"@type": "Product", "name": "RTX 5070 Ti", "offers": {"@type": "Offer", "availability":
                                                                         "https://schema.org/OutOfStock"}},
                {"@type": "Product", "name": "relacionado", "offers": {"availability": "https://schema.org/InStock"}}))
    assert estado_pagina(html) == (False, "la tienda dice sin stock")


def test_pagina_graph_aggregate_y_variantes():
    html = _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "BreadcrumbList"},
        {"@type": ["Product"], "offers": {"@type": "AggregateOffer", "offers": [
            {"availability": "https://schema.org/OutOfStock"}, {"availability": "https://schema.org/InStock"}]}}]})
    assert estado_pagina(html)[0] is True
    grupo = _ld({"@type": "ProductGroup", "hasVariant": [{"offers": {"availability": "SoldOut"}}]})
    assert estado_pagina(grupo)[0] is False


def test_pagina_itemprop_meta_y_nada():
    assert estado_pagina('<link itemprop="availability" href="https://schema.org/InStock">')[0] is True
    assert estado_pagina('<meta property="product:availability" content="out of stock">')[0] is False
    assert estado_pagina('<meta content="in stock" property="og:availability">')[0] is True
    # sin datos estructurados no se adivina por palabras sueltas (CCPU muestra "In stock" de otro producto)
    assert estado_pagina("<p>In stock</p><button>Sold out</button>") == (None, "la página de la tienda no informa stock")
    assert estado_pagina('<script type="application/ld+json">{roto</script>')[0] is None


def test_shopify():
    d = {"available": True, "variants": [{"id": 1, "available": False}, {"id": 2, "available": True}]}
    assert estado_shopify(d, "1") is False and estado_shopify(d, "2") is True and estado_shopify(d, None) is True
    assert estado_shopify({"variants": [{"id": 1, "available": False}]}, None) is False


def test_link_de_hardgamers():
    html = ('<a href="https://tienda.com/logo.png?utm_source=hardgamers&amp;x=product_detail_logo">x</a>'
            '<a href="https://tienda.com/img.jpg?utm_source=hardgamers">x</a>'
            '<a href="https://tienda.com/producto/rtx?utm_source=hardgamers&amp;utm_medium=referral">ver</a>')
    assert link_tienda_hg(html) == "https://tienda.com/producto/rtx?utm_source=hardgamers&utm_medium=referral"
    assert sin_rastreo(link_tienda_hg(html)) == "https://tienda.com/producto/rtx"
    assert link_tienda_hg("<a href='https://x.com'>") is None


# ------------------------------------------------------------------ verificar en la tienda real

def _verificador(rutas: dict, db=None) -> tuple[Verificador, list]:
    pedidos = []

    def responder(req: httpx.Request):
        pedidos.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        clave = f"{req.url.host}{req.url.path}"
        if clave not in rutas:
            return httpx.Response(404, text="no")
        r = rutas[clave]
        return r if isinstance(r, httpx.Response) else httpx.Response(200, text=r)

    cli = Cliente(pausa=(0, 0), reintentos=1)
    cli.http = httpx.Client(transport=httpx.MockTransport(responder), follow_redirects=True)
    return Verificador(db, cliente=cli), pedidos


def test_verificar_shopify_un_pedido():
    js = json.dumps({"available": True, "variants": [{"id": 47995, "available": False}]})
    v, pedidos = _verificador({"www.mwave.com.au/products/msi-rtx-5070-ti-ac92600.js": js})
    r = v.verificar("https://www.mwave.com.au/products/msi-rtx-5070-ti-ac92600?variant=47995&currency=AUD")
    assert r.disponible is False and "Sold out" in r.motivo
    assert [p for p in pedidos if "robots" not in p] == ["https://www.mwave.com.au/products/msi-rtx-5070-ti-ac92600.js"]


def test_verificar_hardgamers_va_a_la_tienda():
    ficha = '<a href="https://liontech.com.ar/p/rtx-5070?utm_source=hardgamers&amp;utm_medium=referral">Ir</a>'
    tienda = _ld({"@type": "Product", "offers": {"availability": "https://schema.org/InStock"}})
    v, _ = _verificador({"www.hardgamers.com.ar/product/lionTech:123": ficha, "liontech.com.ar/p/rtx-5070": tienda})
    r = v.verificar("https://www.hardgamers.com.ar/product/lionTech:123")
    assert r.disponible is True and r.destino == "https://liontech.com.ar/p/rtx-5070"


def test_verificar_bloqueo_404_y_sin_datos():
    db = DB(":memory:")
    v, pedidos = _verificador({
        "www.scorptec.com.au/product/1": httpx.Response(403, text="Just a moment..."),
        "www.ccpu.com.au/product/a": "<p>In stock</p>", "www.ccpu.com.au/product/b": "<p>nada</p>",
    }, db)
    r = v.verificar("https://www.scorptec.com.au/product/1")
    assert r.disponible is None and "no deja verificar" in r.motivo
    antes = len(pedidos)
    assert v.verificar("https://www.scorptec.com.au/product/2").disponible is None
    assert len(pedidos) == antes                        # bloqueada: ni se le pide
    assert v.bloqueada("www.scorptec.com.au")
    assert v.verificar("https://www.ple.com.au/products/9/x").motivo == "la página del producto ya no existe"
    v.verificar("https://www.ccpu.com.au/product/a")
    v.verificar("https://www.ccpu.com.au/product/b")
    assert v.bloqueada("www.ccpu.com.au") == "la tienda no informa stock en su página"


# ------------------------------------------------------------------ estado de cada publicación

def _oferta(db, tienda, url, precio, cat="placas", pais="AU", hace_min=5, stock_=True, titulo="MSI RTX 5070 Ti 16GB",
            **datos):
    o = normalizar(Oferta(tienda=tienda, pais=pais, categoria=cat, titulo=titulo, url=url, precio=precio,
                          moneda="AUD" if pais == "AU" else "ARS", stock=stock_,
                          fecha=AHORA - timedelta(minutes=hace_min), datos=datos))
    db.guardar_oferta(o)
    return o


def _urls(db, pais="AU", cat="placas"):
    return [(r["url"], r["stock_ok"], r["stock_motivo"]) for r in db.vigentes(pais, cat, AHORA - timedelta(hours=48), AHORA)]


def test_ultima_pasada_y_sin_confirmar():
    db = DB(":memory:")
    _oferta(db, "umart", "https://u/vieja", 1500, hace_min=60)              # no apareció en la última pasada
    _oferta(db, "umart", "https://u/1", 1800)
    _oferta(db, "umart", "https://u/0", 1700, stock_=False)                  # la tienda dice sin stock
    _oferta(db, "mwaveaustralia", "https://m/1", 1600, via="staticICE")       # staticICE: sin confirmar
    db.registrar_pasada("umart", "placas", AHORA - timedelta(minutes=10))
    db.registrar_pasada("staticice", "placas", AHORA - timedelta(minutes=10))
    assert _urls(db) == [("https://u/1", True, ""), ("https://m/1", False, "staticICE no informa stock")]
    # staticICE no se pudo leer hace 9 h: sigue, sin confirmar y con el motivo
    db.registrar_pasada("staticice", "placas", AHORA - timedelta(hours=9))
    db.c.execute("UPDATE ofertas SET ultima_vez=? WHERE url='https://m/1'", ((AHORA - timedelta(hours=9)).isoformat(),))
    assert _urls(db)[1] == ("https://m/1", False, "no pude leer staticICE hace 9 h")


def test_verificacion_confirma_o_saca():
    db = DB(":memory:")
    _oferta(db, "mwaveaustralia", "https://m/1", 1600, via="staticICE")
    _oferta(db, "scorptec", "https://s/1", 1650, via="staticICE")
    db.registrar_pasada("staticice", "placas", AHORA - timedelta(minutes=10))
    db.guardar_verificacion("https://m/1", True, "la tienda dice que hay stock", 1600, ts=AHORA)
    db.guardar_verificacion("https://s/1", False, "la tienda dice sin stock", 1650, ts=AHORA)
    assert _urls(db) == [("https://m/1", True, "verificado en la tienda")]
    # cambió el precio: la verificación ya no vale, vuelve a "sin confirmar"
    _oferta(db, "mwaveaustralia", "https://m/1", 1550, via="staticICE")
    assert _urls(db) == [("https://m/1", False, "staticICE no informa stock")]
    assert db.estado_stock(AHORA).necesita_verificar(db.c.execute("SELECT * FROM ofertas WHERE url='https://m/1'").fetchone())


def test_ocultar_y_destapar():
    db = DB(":memory:")
    _oferta(db, "umart", "https://u/1", 1800)
    db.registrar_pasada("umart", "placas", AHORA - timedelta(minutes=10))
    h = clave_url("https://u/1")
    assert db.ocultar("https://u/1", h, AHORA) and not db.ocultar("https://u/1", h, AHORA)   # la misma marca, una vez
    assert _urls(db) == []
    # sigue con stock en la tienda: sigue oculto
    assert db.actualizar_ocultos(AHORA) == 0 and _urls(db) == []
    # desaparece de la tienda (sin stock) ...
    db.registrar_pasada("umart", "placas", AHORA + timedelta(minutes=30))
    db._cambio_stock()
    db.actualizar_ocultos(AHORA + timedelta(minutes=31))
    assert db.ocultos_activos()[0]["visto_sin_stock"]
    # ... y vuelve con stock: se destapa
    _oferta(db, "umart", "https://u/1", 1750, hace_min=-60)
    db.registrar_pasada("umart", "placas", AHORA + timedelta(minutes=59))
    assert db.actualizar_ocultos(AHORA + timedelta(minutes=61)) == 1
    assert [u for u, *_ in _urls(db)] == ["https://u/1"]


def test_sincronizar_ocultos_desde_el_worker():
    db = DB(":memory:")
    _oferta(db, "umart", "https://u/1", 1800)
    marcas = {clave_url("https://u/1"): "2026-11-18T15:05:00.000Z", "0000000000000000": "2026-11-18T15:05:00.000Z"}

    def responder(req):
        assert req.headers["Authorization"] == "Bearer s3"
        return httpx.Response(200, json={"ocultos": marcas})

    http = httpx.Client(transport=httpx.MockTransport(responder))
    assert stock.sincronizar_ocultos(db, "https://w.dev", "s3", http) == 1
    assert stock.sincronizar_ocultos(db, "https://w.dev", "s3", http) == 0     # ya estaba
    assert stock.sincronizar_ocultos(db, "", "s3", http) == 0                   # sin Worker configurado


# ------------------------------------------------------------------ avisos y exportación

def test_avisos_sin_stock_no_salen_y_los_dudosos_lo_dicen():
    db = DB(":memory:")
    _oferta(db, "umart", "https://u/1", 1800)
    _oferta(db, "umart", "https://u/vieja", 1500, hace_min=60)
    _oferta(db, "scorptec", "https://s/1", 1600, via="staticICE")
    db.registrar_pasada("umart", "placas", AHORA - timedelta(minutes=10))
    db.registrar_pasada("staticice", "placas", AHORA - timedelta(minutes=10))
    texto = "🎯 RTX\nprecio\n🔗 <a href='x'>Ver en la tienda</a>"
    avisos = [Aviso("objetivo", "a", True, texto, "AU", 1800, "https://u/1"),
              Aviso("objetivo", "b", True, texto, "AU", 1500, "https://u/vieja"),
              Aviso("objetivo", "c", True, texto, "AU", 1600, "https://s/1"),
              Aviso("ozbargain", "d", True, "post", "AU")]
    db._estado = db.estado_stock(AHORA)    # a la hora de la prueba (sin escrituras, no se rehace)
    salen = alertas.filtrar_por_stock(avisos, db)
    assert [a.clave for a in salen] == ["a", "c", "d"]
    assert "⚠️ Stock sin confirmar: staticICE no informa stock\n🔗" in salen[1].texto
    assert "Stock sin confirmar" not in salen[0].texto
    assert alertas.boton_sin_stock("https://u/1") == [[{"text": "❌ Sin stock", "callback_data": f"x:{clave_url('https://u/1')}"}]]


def test_exportar_motivos_y_ocultos():
    db = DB(":memory:")
    _oferta(db, "umart", "https://u/1", 1800)
    _oferta(db, "umart", "https://u/2", 1900)
    _oferta(db, "scorptec", "https://s/1", 1600, via="staticICE")
    db.registrar_pasada("umart", "placas", AHORA - timedelta(minutes=10))
    db.registrar_pasada("staticice", "placas", AHORA - timedelta(minutes=10))
    db.ocultar("https://u/2", clave_url("https://u/2"), AHORA)
    d = exportar.armar(db, {}, Cotizacion(1600, 0.67, AHORA), {}, AHORA)
    filas = [(f[4], d["motivos"][f[9]]) for f in d["p"]]
    assert filas == [("https://u/1", ""), ("https://s/1", "staticICE no informa stock")]   # confirmado primero
    assert d["ocultos"] == {clave_url("https://u/2"): AHORA.isoformat(timespec="seconds")}
