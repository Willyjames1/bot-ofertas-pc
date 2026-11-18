"""El Worker de /buscar (worker/): que entienda los títulos igual que el normalizador de los
avisos, que haga la misma cuenta, y el JSON que le exporta cada corrida."""
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import pytest

from bot import exportar
from bot.comparar import cuenta, lineas_cuenta
from bot.cotizaciones import Cotizacion
from bot.db import DB
from bot.modelos import Oferta
from bot.normalizar import chip_gpu, limpiar, normalizar, vram_de

RAIZ = Path(__file__).resolve().parent.parent
WORKER = RAIZ / "worker"
NODE = shutil.which("node")
sin_node = pytest.mark.skipif(NODE is None, reason="hace falta Node.js para probar el Worker")

TITULOS = [
    ("placas", "Placa de Video MSI GeForce RTX 5070 Ti 16GB SHADOW 3X OC"),
    ("placas", "ASUS PRIME RTX5070TI-O16G Gaming Graphics Card"),
    ("placas", "Gigabyte GeForce RTX 5060 Ti WINDFORCE 8G"),
    ("placas", "Sapphire PULSE AMD Radeon RX 9070 XT 16GB 11348-03-20G"),
    ("placas", "PowerColor Reaper RX 9070 12GB GRE"),
    ("placas", "Zotac Gaming GeForce RTX 5090 Solid OC 32GB"),
    ("placas", "Palit RTX 5080 GamingPro-S 16G"),
    ("placas", "MSI RTX 4070 SUPER 12G VENTUS 2X"),
    ("placas", "XFX Swift RX 7900 XTX 24GB"),
    ("placas", "Inno3D GeForce RTX 5070 Twin X2 12GB GDDR7"),
    ("cpu", "Procesador AMD Ryzen 7 9800X3D 5.2GHz AM5"),
    ("cpu", "AMD Ryzen 9 9000 Series 9950X3D 16-Core"),
    ("cpu", "Micro Intel Core Ultra 7 265K LGA1851"),
    ("cpu", "Intel Core Ultra 5 14 Core LGA 1851 245KF"),
    ("cpu", "Intel Core i7-14700K 20 Cores"),
    ("cpu", "AMD 9600X 6-Core Processor"),
    ("cpu", "Intel Core Ultra 7 270K Plus Desktop Processor"),
    ("ram", "Memoria Kingston Fury Beast DDR5 32GB (2x16GB) 6000MHz CL30"),
    ("ram", "Corsair Vengeance CMK32GX5M2B6000C30 32GB DDR5"),
    ("ram", "G.Skill Trident Z5 F5-6400J3239G16GX2-TZ5RK 32GB"),
    ("ram", "Kingston FURY KF560C30BBEK2-32 32GB"),
    ("ram", "TeamGroup T-Create 64GB 2x32GB 6400 CL32"),
    ("ram", "Crucial 32GB DDR5 5600 UDIMM"),
    ("ram", "Memoria DDR4 16GB 3200 Kingston"),
    ("ram", "Patriot Viper Venom 48GB (2 x 24GB) 7200MT/s CL36"),
    ("ssd", "Samsung 990 PRO 2TB NVMe M.2"),
    ("ssd", "WD_BLACK SN8100 2TB PCIe Gen5"),
    ("ssd", "Crucial MX500 1TB SATA SSD"),
    ("ssd", "Kingston NV3 1TB M.2 2280 NVMe PCIe 4.0"),
    ("ssd", "Samsung T7 Portable SSD 1TB USB 3.2"),
    ("ssd", "SSD Lexar NM790 4TB PCIe Gen 4x4"),
    ("ssd", "ADATA Legend 960 Max 2TB"),
]


def _python(categoria: str, titulo: str) -> dict:
    t = limpiar(titulo)
    r = {"t": t, "chip": chip_gpu(t), "vram": vram_de(t)}
    o = normalizar(Oferta(tienda="x", pais="AU", categoria=categoria, titulo=titulo, url="u", precio=100, moneda="AUD"))
    if categoria == "placas":
        r["placa"] = None if o.descartada else o.modelo
    elif categoria == "cpu":
        r["cpu"] = None if o.descartada else o.modelo
    elif categoria == "ram":
        r["ram"] = None if o.descartada else {k: o.datos[k] for k in ("capacidad_gb", "modulos", "velocidad", "cl")}
    elif categoria == "ssd":
        r["ssd"] = None if o.descartada else {k: o.datos[k] for k in ("capacidad_tb", "interfaz", "gen")}
    return r


def _node(entrada: dict) -> dict:
    p = subprocess.run([NODE, str(WORKER / "scripts" / "paridad.mjs")], input=json.dumps(entrada), capture_output=True,
                       text=True, encoding="utf-8", cwd=WORKER, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_regexes_generadas_al_dia():
    """worker/src/normalizador_gen.js sale de bot/normalizar.py: si cambia una regex, regenerar
    con `python -m bot generar-worker`."""
    assert exportar.RUTA_GEN.read_text(encoding="utf-8") == exportar.regex_js()


@sin_node
def test_mismo_normalizador_que_los_avisos():
    js = _node({"titulos": TITULOS})["titulos"]
    for (cat, titulo), j in zip(TITULOS, js):
        py = _python(cat, titulo)
        assert j["t"] == py["t"], titulo
        assert (j["chip"], j["vram"]) == (py["chip"], py["vram"]), titulo
        if cat == "ram" and py["ram"] is None:
            continue   # Python además descarta fuera de 32–128GB y la de notebook: el Worker no busca eso
        if cat == "ssd" and py["ssd"] is None and j["ssd"] is None:
            continue
        clave = {"placas": "placa", "cpu": "cpu", "ram": "ram", "ssd": "ssd"}[cat]
        assert j[clave] == py[clave], titulo


@sin_node
def test_misma_cuenta_que_los_avisos():
    casos = []
    for aud, ars_, valija, pais in product((150, 645, 899.5, 1441, 1799, 3599), (300_000, 782_876, 2_269_000, 5_020_836),
                                           (0, 150), ("AU", "AR")):
        casos.append({"cot": {"mep": 1601.8, "aud_usd": 0.67313}, "aud": aud, "ars": ars_, "valija": valija,
                      "pais": pais, "reglas": {"franquicia_usd": 500, "arancel": 0.5, "conviene_pct": 10}})
    js = _node({"cuentas": casos})["cuentas"]
    for caso, lineas in zip(casos, js):
        cot = Cotizacion(caso["cot"]["mep"], caso["cot"]["aud_usd"], datetime.now(timezone.utc))
        c = cuenta(cot, caso["aud"], caso["ars"], caso["valija"])
        assert lineas == lineas_cuenta(c, caso["pais"], caso["valija"]), caso


@sin_node
def test_tests_del_worker():
    p = subprocess.run([NODE, "--test", "test/*.test.js"], capture_output=True, text=True, encoding="utf-8", cwd=WORKER,
                       timeout=120)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-2000:]


# ------------------------------------------------------------------ exportar

AHORA = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)


def _oferta(db, tienda, pais, cat, titulo, precio, url, hace_min=10, **extra):
    o = normalizar(Oferta(tienda=tienda, pais=pais, categoria=cat, titulo=titulo, url=url, precio=precio,
                          moneda="AUD" if pais == "AU" else "ARS", stock=True, fecha=AHORA - timedelta(minutes=hace_min),
                          **extra))
    db.guardar_oferta(o)
    return o


def test_exportar_compacto():
    db = DB(":memory:")
    for i in range(20):   # 20 RTX 5070 Ti en Argentina: van solo las 16 más baratas
        _oferta(db, "venex", "AR", "placas", f"MSI RTX 5070 Ti 16GB Ventus {i}", 2_300_000 + i * 10_000, f"https://v/{i}",
                tipo_precio="contado")
    _oferta(db, "staticice", "AU", "placas", "Gigabyte RTX 5070 Ti 16GB Eagle", 1799, "https://m/1",
            datos={"via": "staticICE"})
    _oferta(db, "umart", "AU", "ram", "Kingston Fury DDR5 32GB (2x16GB) 6000 CL30", 199, "https://u/1", hace_min=60 * 50)
    db.c.execute("INSERT INTO posts(fuente,id,titulo,url,publicado,visto,votos,precio) VALUES(?,?,?,?,?,?,?,?)",
                 ("ozbargain", "1", "RTX 5070 Ti $1599 @ Scorptec", "https://oz/1",
                  (AHORA - timedelta(hours=2)).isoformat(), AHORA.isoformat(), 40, 1599.0))
    cot = Cotizacion(1600, 0.67, AHORA)
    d = exportar.armar(db, {"general": {"valija_extra_aud": 150}}, cot, {"venex": "Venex"}, AHORA)
    assert d["v"] == exportar.VERSION and d["cot"]["mep"] == 1600
    assert d["reglas"] == {"franquicia_usd": 500, "arancel": 0.5, "valija_aud": 150.0, "conviene_pct": 10}
    assert d["modelos"] == [["RTX 5070 Ti 16GB", "placas", {"chip": "RTX 5070 Ti", "vram": 16}]]  # la RAM vieja no va
    ar = [f for f in d["p"] if f[1] == "AR"]
    au = [f for f in d["p"] if f[1] == "AU"]
    assert len(ar) == exportar.POR_MODELO and [f[2] for f in ar] == sorted(f[2] for f in ar)
    assert d["tiendas"][ar[0][3]] == "Venex" and ar[0][5] == "MSI Ventus" and ar[0][6] == 10 and ar[0][7] == "contado"
    assert au[0][8] == 1 and au[0][2] == 1799          # staticICE: avisa que no informa stock
    assert d["posts"] == [["RTX 5070 Ti $1599 @ Scorptec", "https://oz/1", 40, 1599.0, 120]]
    assert "Tiendas" in d["estado"] or "Todavía" in d["estado"]


def test_exportar_guarda_sin_espacios(tmp_path):
    ruta = tmp_path / "precios.json"
    n = exportar.guardar({"a": [1, 2], "b": "ñ"}, ruta)
    assert ruta.read_text(encoding="utf-8") == '{"a":[1,2],"b":"ñ"}' and n == len('{"a":[1,2],"b":"ñ"}'.encode())


@sin_node
def test_misma_clave_para_el_boton_sin_stock():
    """El botón "❌ Sin stock" lleva sha1(link)[:16]: el Worker y la corrida tienen que calcular lo mismo."""
    from bot.stock import clave_url
    urls = ["https://www.mwave.com.au/products/msi-rtx-5070-ti-ac92600?variant=47995034927235&currency=AUD",
            "https://www.hardgamers.com.ar/product/maxTecno:fqg5hv", "https://tienda.com/ñandú?x=1&y=á", ""]
    codigo = ("import { claveUrl } from './src/sha1.js';"
              f"console.log(JSON.stringify({json.dumps(urls)}.map(claveUrl)));")
    p = subprocess.run([NODE, "--input-type=module", "-e", codigo], capture_output=True, text=True,
                       encoding="utf-8", cwd=WORKER, timeout=60)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == [clave_url(u) for u in urls]


def test_exportar_por_categoria(tmp_path):
    db = DB(":memory:")
    _oferta(db, "umart", "AU", "ram", "Kingston Fury DDR5 32GB (2x16GB) 6000 CL30", 199, "https://u/1")
    _oferta(db, "umart", "AU", "placas", "MSI RTX 5070 Ti 16GB Ventus", 1799, "https://u/2")
    d = exportar.armar(db, {}, Cotizacion(1600, 0.67, AHORA), {}, AHORA)
    partes = exportar.por_categoria(d)
    assert set(partes) == {"indice", *exportar.CATEGORIAS}
    assert partes["indice"]["p"] == [] and partes["indice"]["chips"] == ["RTX 5070 Ti"]
    assert partes["indice"]["estado"] == d["estado"]
    placas = partes["placas"]
    assert [m[0] for m in placas["modelos"]] == ["RTX 5070 Ti 16GB"]
    assert [(placas["modelos"][f[0]][0], f[4]) for f in placas["p"]] == [("RTX 5070 Ti 16GB", "https://u/2")]
    assert [f[4] for f in partes["ram"]["p"]] == ["https://u/1"] and partes["ssd"]["p"] == []
    ruta = tmp_path / "precios.json"
    exportar.guardar_todo(d, ruta)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        ["precios.json", "precios-indice.json"] + [f"precios-{c}.json" for c in exportar.CATEGORIAS])
