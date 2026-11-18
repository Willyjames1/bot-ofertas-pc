"""SSD: solo M.2 2280 NVMe Gen4/Gen5 en /buscar, avisos y resumen (lo demás, si lo pedís), con la
generación y las velocidades del título o de ssd_modelos.yaml."""
from datetime import datetime, timedelta, timezone

import pytest

from bot import exportar, resumen
from bot.alertas import pasa_filtros
from bot.cotizaciones import Cotizacion
from bot.db import DB
from bot.modelos import Oferta
from bot.normalizar import (SSD_MODELOS, coincide_ssd, consulta_ssd, datos_ssd, limpiar, normalizar,
                            ssd_estandar)

AHORA = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
CFG = {"ssd": {"activo": True, "capacidad_tb": [2, 4], "gen_min": 4}}


def d(titulo):
    return datos_ssd(limpiar(titulo))


def test_la_tabla_trae_los_modelos_pedidos():
    nombres = {m[0] for m in SSD_MODELOS}
    for n in ("Samsung 990 Pro", "Samsung 990 Evo Plus", "Samsung 9100 Pro", "WD SN850X", "WD SN7100", "WD SN8100",
              "Crucial T500", "Crucial T700", "Crucial T705", "Corsair MP700 Pro", "Corsair MP600 Pro",
              "Kingston KC3000", "Kingston NV3", "Kingston Fury Renegade", "Lexar NM790", "Seagate FireCuda 530",
              "Solidigm P44 Pro", "Team MP44"):
        assert n in nombres, n
        m = next(m for m in SSD_MODELOS if m[0] == n)
        assert m[2] in (4, 5) and m[3], n                        # generación y velocidades de fábrica


@pytest.mark.parametrize("titulo,esperado", [
    # el modelo de la tabla, con sus velocidades
    ("Samsung 990 Pro 2TB PCIe 4.0 M.2 2280 NVMe SSD (MZ-V9P2T0BW)", ("Samsung 990 Pro", 4, "2280", 7450, 6900)),
    ("Samsung 990PRO 4TB", ("Samsung 990 Pro", 4, "2280", 7450, 6900)),
    ("Samsung 2TB 9100 Pro MZ-VAP2T0BW PCIe 5.0 NVMe M.2 Gen 5 SSD", ("Samsung 9100 Pro", 5, "2280", 14700, 13400)),
    # la generación de la tabla manda: el 990 Evo Plus anda en 5.0 x2 pero es Gen4
    ("Disco Solido SSD M.2 Samsung 2TB 990 EVO PLUS 7250MB/s NVMe PCI-E Gen5 2.0",
     ("Samsung 990 Evo Plus", 4, "2280", 7250, 6300)),
    # otra marca: "XPG Mars 980 Pro" no es un Samsung 980 Pro
    ("Disco Solido SSD M.2 ADATA 2TB XPG MARS 980 PRO AIR 14000MB/s NVMe PCIe Gen5 x4", (None, 5, "2280", 14000, None)),
    # la palabra entera: MP44L no es MP44
    ("Disco Solido SSD M.2 Team 500GB MP44L 5000MB/s NVMe PCI-E x4 Gen4", (None, 4, "2280", 5000, None)),
    # el título manda sobre la tabla (dice 7000, la tabla 7400: sin escritura)
    ("Disco Solido SSD M.2 Team 1TB MP44 7000MB/s NVMe PCI-E Gen4 x4", ("Team MP44", 4, "2280", 7000, None)),
    # lectura y escritura del título
    ("SP Silicon Power UD90 1TB PCIe Gen4 x4 NVMe M.2 2280 SSD, 5000MB/s Read, 4800MB/s Write",
     (None, 4, "2280", 5000, 4800)),
    ("Samsung 990 Pro 2TB 7.450/6.900 MB/s", ("Samsung 990 Pro", 4, "2280", 7450, 6900)),
    # generaciones escritas de mil maneras
    ("Disco Solido SSD 256GB Hiksemi Wave M.2 NVMe PCIe x4 3.0", (None, 3, "2280", None, None)),
    ("Disco Solido SSD 2TB Patriot P410 M.2 PCIe NVMe 4.0 X4", (None, 4, "2280", None, None)),
    ("SSD Lexar NM790 4TB PCIe Gen 4x4", ("Lexar NM790", 4, "2280", 7400, 6500)),
    ("Sandisk Optimus GX 7100 500GB SDSP71500GAN-000E0 M.2 2280 NVMe SSD", (None, None, "2280", None, None)),
    # formatos
    ("Crucial P310 2TB PCIe 4.0 M.2 NVMe 2230 SSD (CT2000P310SSD2)", ("Crucial P310", 4, "2230", None, None)),
    ("WD Blue SA510 SATA SSD M.2 2280 - 250GB", (None, None, "M.2", None, None)),
    ("Kingston A400 960GB 2.5in SATA III SSD", (None, None, "2.5", None, None)),
    ("Samsung T7 Portable SSD 1TB USB 3.2", (None, None, "externo", None, None)),
    ("Orico M.2 NVMe SSD Enclosure USB-C 2TB", (None, None, "carry", None, None)),
])
def test_datos_del_titulo(titulo, esperado):
    x = d(titulo)
    assert (x["linea"], x["gen"], x["formato"], x["lectura"], x["escritura"]) == esperado


def test_capacidades_y_descartes():
    assert d("Disco Solido SSD 256GB Memox Nvme Pcie Gen3 x4")["capacidad_tb"] == 0.25    # no "260GB"
    assert d("Disco Solido SSD 2048GB (2TB) Hiksemi Future X Lite M.2 NVMe PCIe 4.0")["capacidad_tb"] == 2
    o = normalizar(Oferta("x", "AU", "ssd", "Kingston A400 480GB 2.5in SATA III SSD", "u", 50, "AUD"))
    assert o.modelo == "SSD SATA 500GB"
    o = normalizar(Oferta("x", "AU", "ssd", "Crucial P310 1TB PCIe 4.0 M.2 2230 NVMe SSD", "u", 50, "AUD"))
    assert (o.modelo, o.variante) == ("SSD NVMe Gen4 1TB 2230", "Crucial P310")
    assert isinstance(d("Silicon Power 5TB Armor A60 Portable External Hard Drive USB 3.0"), str)


def test_estandar_es_m2_2280_nvme_gen4_o_gen5_conocida():
    si = ["Samsung 990 Pro 2TB NVMe", "WD_BLACK SN8100 2TB PCIe Gen5", "Kingston NV3 2TB M.2 2280 NVMe PCIe 4.0"]
    no = ["Crucial MX500 2TB SATA SSD", "Samsung T7 Portable SSD 2TB USB 3.2", "Crucial P310 2TB M.2 2230 NVMe",
          "WD SN740 2TB M.2 2242 NVMe PCIe 4.0", "Hiksemi Wave 2TB M.2 NVMe PCIe 3.0",
          "Sandisk Optimus GX 7100 2TB M.2 2280 NVMe SSD", "Orico M.2 NVMe SSD Enclosure 2TB"]
    assert all(ssd_estandar(d(t)) for t in si)
    assert not any(ssd_estandar(d(t)) for t in no)


def test_avisos_solo_lo_estandar():
    for t, pasa in [("Samsung 990 Pro 2TB NVMe", True), ("Crucial P310 2TB M.2 2230 NVMe PCIe 4.0", False),
                    ("Sandisk Optimus GX 7100 2TB M.2 2280 NVMe SSD", False),   # generación desconocida
                    ("Crucial MX500 2TB SATA SSD", False), ("Samsung T7 Portable SSD 2TB", False),
                    ("Hiksemi Wave 2TB M.2 NVMe PCIe 3.0", False)]:
        o = normalizar(Oferta("x", "AU", "ssd", t, "u", 199, "AUD"))
        assert pasa_filtros(CFG, "ssd", o.modelo, o.datos, 199, "AUD") is pasa, t


@pytest.mark.parametrize("busqueda,titulo,coincide", [
    ("ssd gen5 2tb", "Samsung 2TB 9100 Pro PCIe 5.0 NVMe M.2", True),
    ("ssd gen5 2tb", "Samsung 990 Pro 2TB NVMe", False),
    ("990 pro 2tb", "Samsung 990 Pro 2TB PCIe 4.0 NVMe", True),
    ("990pro 2tb", "Samsung 990 Pro 2TB PCIe 4.0 NVMe", True),
    ("Samsung 990 Pro NVMe", "Samsung 990 Pro 4TB PCIe 4.0 NVMe", True),
    ("990 pro 2tb", "Samsung 990 EVO Plus 2TB NVMe", False),
    ("990 pro", "Samsung 990 Pro 2TB M.2 2230 NVMe", False),    # el de notebook, solo si lo pedís
    ("ssd 2230 2tb", "Crucial P310 2TB M.2 2230 NVMe PCIe 4.0", True),
    ("ssd 2tb", "Crucial MX500 2TB SATA SSD", False),
    ("ssd sata 2tb", "Crucial MX500 2TB SATA SSD", True),
    ("ssd externo 2tb", "Samsung T7 Portable SSD 2TB USB 3.2", True),
    ("ssd 2tb", "Samsung T7 Portable SSD 2TB USB 3.2", False),
    ("ssd gen3 1tb", "Hiksemi Wave 1TB M.2 NVMe PCIe 3.0", True),
    ("ssd 1tb", "Hiksemi Wave 1TB M.2 NVMe PCIe 3.0", False),
])
def test_consulta(busqueda, titulo, coincide):
    q = consulta_ssd(limpiar(busqueda))
    assert q is not None
    assert coincide_ssd(q, d(titulo)) is coincide


def test_consulta_vel_y_lo_que_no_es_ssd():
    assert consulta_ssd(limpiar("ssd gen4 2tb vel"))["vel"] is True
    assert consulta_ssd(limpiar("ddr5 32gb")) is None and consulta_ssd(limpiar("5070 ti")) is None


# ------------------------------------------------------------------ resumen y export

def _guardar(db, tienda, pais, titulo, precio, url):
    o = normalizar(Oferta(tienda, pais, "ssd", titulo, url, precio, "AUD" if pais == "AU" else "ARS", stock=True,
                          fecha=AHORA - timedelta(minutes=10)))
    db.guardar_oferta(o)
    db.registrar_pasada(tienda, "ssd", AHORA - timedelta(minutes=10))


def test_resumen_con_ssd():
    db = DB(":memory:")
    _guardar(db, "umart", "AU", "Crucial P310 2TB M.2 2230 NVMe PCIe 4.0", 150, "https://u/1")   # 2230: no
    _guardar(db, "umart", "AU", "Samsung 990 EVO Plus 2TB PCIe 4.0 NVMe M.2 2280", 230, "https://u/2")
    _guardar(db, "umart", "AU", "Samsung 990 Pro 2TB PCIe 4.0 NVMe M.2 2280", 249, "https://u/3")
    db.estado_stock(AHORA)
    cfg = {**CFG, "resumen_diario": {"productos": {"ssd": ["990 Pro 2TB", "Gen4 2TB"]}}}
    desde = AHORA - timedelta(hours=5)
    assert resumen.mejor_de_hoy(db, cfg, "ssd", "990 Pro 2TB", "AU", desde)["precio"] == 249
    assert resumen.mejor_de_hoy(db, cfg, "ssd", "Gen4 2TB", "AU", desde)["precio"] == 230
    assert resumen.mejor_de_hoy(db, cfg, "ssd", "Gen5 2TB", "AU", desde) is None


def test_exportar_ssd():
    db = DB(":memory:")
    for i in range(20):    # 20 NV3 2TB más baratos: el 990 Pro igual entra (16 por cada modelo, no por "Gen4 2TB")
        _guardar(db, "umart", "AU", f"Kingston NV3 2TB PCIe 4.0 NVMe M.2 2280 v{i}", 150 + i, f"https://u/nv{i}")
    _guardar(db, "umart", "AU", "Samsung 990 Pro 2TB PCIe 4.0 NVMe M.2 2280 (MZ-V9P2T0BW)", 249, "https://u/990")
    _guardar(db, "umart", "AU", "Sandisk 2TB Optimus GX PRO 850X PCIe 4.0 M.2 2280 NVMe SSD (SDSP81200TAN-000E0)",
             199, "https://u/sd")
    db.c.execute("INSERT INTO posts(fuente,id,titulo,url,publicado,visto,votos,precio) VALUES(?,?,?,?,?,?,?,?)",
                 ("ozbargain", "1", "Samsung 990 Pro 2TB $239 @ Amazon AU", "https://oz/1",
                  (AHORA - timedelta(hours=2)).isoformat(), AHORA.isoformat(), 40, 239.0))
    db.estado_stock(AHORA)
    x = exportar.armar(db, CFG, Cotizacion(1600, 0.67, AHORA), {"umart": "Umart"}, AHORA)
    # el post, ya parseado (el Worker no corre el normalizador de SSD sobre cada post)
    assert x["posts"][0][6] == {"capacidad_tb": 2, "interfaz": "NVMe", "gen": 4, "formato": "2280",
                                "linea": "Samsung 990 Pro"}
    assert x["modelos"] == [["SSD NVMe Gen4 2TB", "ssd", {"capacidad_tb": 2, "interfaz": "NVMe", "gen": 4,
                                                         "formato": "2280"}]]
    filas = {f[4]: f for f in x["p"]}
    assert len([u for u in filas if "/nv" in u]) == exportar.POR_MODELO
    assert filas["https://u/990"][5] == "Samsung 990 Pro" and filas["https://u/990"][11] == ["Samsung 990 Pro", 7450, 6900]
    assert filas["https://u/sd"][5] == "Sandisk 2TB Optimus GX PRO 850X" and filas["https://u/sd"][11] == [None, None, None]
