"""Tiendas argentinas, con páginas y JSON guardados de la web real (recortados a pocos productos)."""
import json
from pathlib import Path

import httpx

from datetime import datetime, timezone

from bot import alertas, config
from bot.alertas import Motor
from bot.db import DB
from bot.fuentes import TIENDAS
from bot.fuentes.compragamer import CompraGamer, url_producto
from bot.fuentes.gezatek import Gezatek
from bot.fuentes.katech import Katech, url_api
from bot.fuentes.mexx import Mexx
from bot.fuentes.venex import Venex
from bot.modelos import Oferta
from bot.normalizar import normalizar
from bot.red import Cliente

FIX = Path(__file__).parent / "fixtures"


def leer(nombre):
    return (FIX / nombre).read_text(encoding="utf-8")


def cliente(respuestas: dict[str, httpx.Response] | None = None):
    """Cliente sin internet: contesta lo que le pasemos por URL y cuenta los pedidos."""
    pedidos = []

    def responder(req):
        pedidos.append(str(req.url))
        for url, r in (respuestas or {}).items():
            if str(req.url) == url:
                return r
        raise AssertionError(f"pedido inesperado a {req.url}")
    c = Cliente(respetar_robots=False, pausa=(0, 0))
    c.http = httpx.Client(transport=httpx.MockTransport(responder))
    c.lista_pedidos = pedidos
    return c


# ------------------------------------------------------------------ Compra Gamer

def test_compragamer_un_solo_pedido_para_todas_las_categorias():
    productos = json.loads(leer("compragamer_productos.json"))
    c = cliente({"https://static.compragamer.com/productos": httpx.Response(200, json=productos)})
    cg = CompraGamer(c)
    placas, cpus, ram = cg.leer("placas"), cg.leer("cpu"), cg.leer("ram")
    assert len(c.lista_pedidos) == 1
    assert len(placas) == 2 and all(o.stock and o.tipo_precio == "transferencia" for o in placas)
    o = placas[0]
    assert o.precio == 942900 and o.precio_lista > o.precio and o.moneda == "ARS"
    assert o.url == url_producto(o.sku and int(o.sku), o.titulo) and o.url.endswith(f"_{o.sku}")
    # el outlet que solo se vende en "Armá tu PC" no entra; el Pentium sí (después lo descarta normalizar)
    assert [x.titulo[:30] for x in cpus] == ["Procesador Intel Pentium G4560"]
    # la de notebook (subcategoría 47) no se lee como RAM de escritorio
    assert len(ram) == 1 and "DDR4" in ram[0].titulo


def test_compragamer_url_igual_a_la_web():
    assert url_producto(123, "Placa de Video ASUS DUAL GeForce RTX 5060 Ti 8GB GDDR7 OC") == \
        "https://compragamer.com/producto/Placa_de_Video_ASUS_DUAL_GeForce_RTX_5060_Ti_8GB_GDDR7_OC_123"


def test_compragamer_sin_stock_y_outlet():
    cg = CompraGamer(cliente())
    base = {"id_subcategoria": 6, "precioEspecial": 1000, "precioLista": 1100, "stock": 5}
    sin = cg.parsear([{**base, "id_producto": 1, "nombre": "RTX 5070", "vendible": 0}], "placas")
    assert sin[0].stock is False
    out = cg.parsear([{**base, "id_producto": 2, "nombre": "RTX 5070", "vendible": 1, "es_outlet": True}], "placas")
    assert out[0].descartada == "outlet"


# ------------------------------------------------------------------ Katech

def test_katech_api_precio_en_centavos_stock_y_paginas():
    k = Katech(cliente())
    ofertas = k.parsear(json.loads(leer("katech_placas.json")), "placas")
    assert len(ofertas) == 3
    assert ofertas[1].precio == 1588874.0 and ofertas[1].tipo_precio == "transferencia"
    assert ofertas[1].precio_lista is None  # el de lista solo está en la ficha: no lo inventamos
    assert [o.stock for o in ofertas] == [True, True, False]
    assert ofertas[1].url.startswith("https://katech.com.ar/producto/")
    assert normalizar(ofertas[1]).modelo == "RTX 5070 12GB"
    url = url_api("placas-de-video")
    assert k._siguiente(url, 3) == url_api("placas-de-video", 2)
    assert k._siguiente(url_api("placas-de-video", 3), 3) is None


def test_katech_ram_sin_ddr5_en_el_titulo():
    k = Katech(cliente())
    p = {"id": 1, "name": "MEMORIA RAM 32GB (2X16) 7400 PATRIOT VIPER VENOM CL36", "permalink": "https://katech.com.ar/p/1",
         "prices": {"price": "30000000", "currency_minor_unit": 2}, "is_in_stock": True}
    o = normalizar(k.parsear([p], "ram")[0])
    assert o.modelo == "DDR5 32GB (2x16) 7400 CL36" and o.precio == 300000


def test_katech_lee_todas_las_paginas_con_el_encabezado():
    pag = json.loads(leer("katech_placas.json"))
    u1, u2 = url_api("placas-de-video"), url_api("placas-de-video", 2)
    c = cliente({u1: httpx.Response(200, json=pag[:2], headers={"x-wp-totalpages": "2"}),
                 u2: httpx.Response(200, json=pag[2:], headers={"x-wp-totalpages": "2"})})
    k = Katech(c)
    k.categorias = {"placas": [u1]}
    assert len(k.leer("placas")) == 3 and c.lista_pedidos == [u1, u2]


# ------------------------------------------------------------------ Venex

def test_venex_titulo_completo_precio_contado_y_siguiente():
    v = Venex(cliente())
    texto = leer("venex_placas.html").replace(">Placa de Video ASUS NVIDIA GeForce RTX 3050 6GB Dual OC<",
                                              ">Placa de Video ASUS NVIDIA GeForce RT...<")
    ofertas, sig = v.parsear(texto, "placas")
    assert len(ofertas) == 3
    assert sig == "https://www.venex.com.ar/componentes-de-pc/placas-de-video?page=2"
    o = ofertas[2]
    assert o.titulo == "Placa de Video ASUS NVIDIA GeForce RTX 3050 6GB Dual OC"  # sale del dato completo
    assert o.precio == 509999 and o.tipo_precio == "contado" and o.datos["forma_pago"] == "Contado efectivo"
    assert normalizar(ofertas[0]).descartada == "accesorio"


def test_venex_ram_6000mhz_sin_ddr5_es_ddr5():
    o = Oferta(tienda="venex", pais="AR", categoria="ram", url="u", precio=1, moneda="ARS",
               titulo="Memoria RAM Corsair Vengeance 32GB(2x16GB) 6000MHz CL38")
    assert normalizar(o).modelo == "DDR5 32GB (2x16) 6000 CL38"
    o = Oferta(tienda="venex", pais="AR", categoria="ram", url="u", precio=1, moneda="ARS",
               titulo="Memoria RAM Kingdian DDR3 8GB 1600MHz")
    assert normalizar(o).descartada


# ------------------------------------------------------------------ Mexx

def test_mexx_mejor_precio_y_stock():
    ofertas = Mexx(cliente()).parsear(leer("mexx_placas.html"), "placas")
    assert len(ofertas) == 3
    o = ofertas[1]
    assert o.precio == 469539 and o.tipo_precio == "transferencia" and o.stock is True
    assert o.url.startswith("https://www.mexx.com.ar/productos-rubro/placas-de-video/")
    assert normalizar(o).descartada.startswith("generación vieja")  # la 3050 no entra en la búsqueda


# ------------------------------------------------------------------ Gezatek

def test_gezatek_precio_geza_lista_mercadopago_y_siguiente():
    url = "https://gezatek.com.ar/placas-de-video/"
    ofertas, sig = Gezatek(cliente()).parsear(leer("gezatek_placas.html"), url, "placas")
    assert len(ofertas) == 3 and sig == url + "?page=2"
    o = ofertas[0]
    assert (o.precio, o.precio_lista, o.stock, o.sku) == (999990, 1099989, True, "8806")
    assert o.tipo_precio == "transferencia"
    assert normalizar(o).modelo == "RTX 5060 Ti 8GB"


# ------------------------------------------------------------------ mensaje

def test_mensaje_ar_muestra_tipo_de_precio_y_lista(tmp_path):
    cfg = config.cargar()
    ahora = datetime(2026, 11, 16, tzinfo=timezone.utc)
    alertas.NOMBRE_TIENDA.update({k: v.nombre for k, v in TIENDAS.items()})
    m = Motor(cfg, config.ajustes(cfg, ahora), DB(tmp_path / "b.sqlite"), None, ahora)
    o = normalizar(Oferta(tienda="gezatek", pais="AR", categoria="placas", url="u", moneda="ARS",
                          titulo="Placa de Video ASUS RTX 5070 Ti 16GB Prime OC", precio=2_000_000,
                          tipo_precio="transferencia", precio_lista=2_200_000))
    texto = m.texto_oferta("prueba", o, None, None, None)
    assert "transferencia · lista" in texto and "Gezatek" in texto
    o.tienda, o.tipo_precio, o.precio_lista = "venex", "contado", None
    assert " contado en Venex" in m.texto_oferta("prueba", o, None, None, None)
