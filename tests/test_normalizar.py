"""Tests de normalización con títulos REALES copiados de tiendas argentinas (vía Hard Gamers)
y australianas (vía staticICE), noviembre 2026."""
import pytest

from bot.modelos import Oferta
from bot.normalizar import normalizar, parsear_chip_config


def n(cat, titulo, pais="AR"):
    return normalizar(Oferta("t", pais, cat, titulo, "u", 1000.0, "ARS" if pais == "AR" else "AUD"))


@pytest.mark.parametrize("titulo,modelo,variante", [
    ("MSI GeForce RTX 5070 Ti 16G VENTUS 3X OC", "RTX 5070 Ti 16GB", "MSI Ventus 3X OC"),  # ejemplo del pedido
    ("PLACA DE VIDEO MSI NVIDIA GEFORCE RTX 5070 TI 16GB VENTUS 3X OC", "RTX 5070 Ti 16GB", "MSI Ventus 3X OC"),
    ("MSI PLACA DE VIDEO RTX 5070TI SHADOW 3X OC 16GB", "RTX 5070 Ti 16GB", "MSI Shadow 3X OC"),
    ("VGA MSI GEFORCE RTX 5070 TI 16G SHADOW 3X OC (7184)", "RTX 5070 Ti 16GB", "MSI Shadow 3X OC"),
    ("PLACA DE VIDEO ASUS PRIME GEFORCE RTX 5070 TI OC 16GB GDDR7", "RTX 5070 Ti 16GB", "ASUS Prime OC"),
    ("PLACA DE VIDEO GIGABYTE GEFORCE RTX 5070 TI WINDFORCE OC 16GB", "RTX 5070 Ti 16GB", "Gigabyte Windforce OC"),
    ("PLACA DE VIDEO PALIT NVIDIA GEFORCE RTX 5070 TI GAMING PRO S 16GB GDDR", "RTX 5070 Ti 16GB", "Palit GamingPro"),
    ("PLACA DE VIDEO RTX 5070 12GB ZOTAC GDDR7 AMP WHITE EDITION", "RTX 5070 12GB", "Zotac AMP"),
    ("PLACA DE VIDEO ZOTAC RTX 5060TI 8GB TWIN EDGE OC WHITE", "RTX 5060 Ti 8GB", "Zotac Twin Edge OC"),
    ("PLACA DE VIDEO POWERCOLOR REAPER AMD RADEON RX 9070 XT 16GB GDDR6", "RX 9070 XT 16GB", "PowerColor Reaper"),
    ("POWERCOLOR PLACA DE VIDEO REAPER RX 9070XT 16GB GDDR6", "RX 9070 XT 16GB", "PowerColor Reaper"),
    ("GPU ASROCK RADEON RX9070XT STEEL LEGEND 16GB (VG-9070XT SL 16G)", "RX 9070 XT 16GB", "ASRock Steel Legend"),
    ("SAPPHIRE PLACA DE VIDEO RX 9070XT PULSE 16GB", "RX 9070 XT 16GB", "Sapphire Pulse"),
    ("VGA GIGABYTE GAMING OC RX 9070XT 16G", "RX 9070 XT 16GB", "Gigabyte Gaming OC"),
    # Australia
    ("[TUF-RTX5070-O12G-GAMING] ASUS TUF Gaming GeForce RTX 5070 OC Edition, 12GB", "RTX 5070 12GB", "ASUS TUF Gaming OC"),
    ("Asus NVidia GeForce Dual-RTX5070-O12G 12GB GDDR7 OC Edition, 2542MHz Boost", "RTX 5070 12GB", "ASUS Dual OC"),
    ("Inno3D GeForce RTX 5070 TI X3 16GB GDDR7 Video Card", "RTX 5070 Ti 16GB", "Inno3D X3"),
    ("Gigabyte GeForce RTX 5070 EAGLE OC ICE 12GB Video Card - White Edition", "RTX 5070 12GB", "Gigabyte Eagle OC"),
])
def test_placas(titulo, modelo, variante):
    o = n("placas", titulo)
    assert o.descartada is None
    assert o.modelo == modelo
    assert o.variante == variante


def test_placa_datos():
    o = n("placas", "MSI GeForce RTX 5080 16G GAMING TRIO OC WHITE 338mm")
    assert o.datos["chip"] == "RTX 5080" and o.datos["vram"] == 16 and o.datos["marca"] == "MSI"
    assert o.datos["largo_mm"] == 338 and o.datos["generacion"] == "RTX 50"


@pytest.mark.parametrize("titulo,motivo", [
    ("Alphacool Core GeForce RTX 5080/5070 Ti TUF Gaming GPU Water Block (10266)", "accesorio"),
    ("PLACA DE VIDEO MSI RTX 3060 VENTUS 2X 12GB", "generación vieja"),
    ("PLACA DE VIDEO ASUS RTX 5070 TI 16GB USADA", "usado"),
    ("Gigabyte RTX 5080 Gaming OC 16GB - Open Box", "usado"),
    ("NOTEBOOK ASUS TUF GAMING RTX 5070 RYZEN 9", "notebook"),
    ("PC GAMER RYZEN 7 9800X3D RTX 5070 TI 32GB", "PC armada"),
])
def test_placas_descartadas(titulo, motivo):
    assert motivo in (n("placas", titulo).descartada or "")


def test_combo_se_marca():
    o = n("placas", "COMBO RTX 5070 TI MSI VENTUS + MOTHER B850")
    assert o.combo and o.modelo == "RTX 5070 Ti 16GB"


@pytest.mark.parametrize("titulo,modelo,nucleos,x3d", [
    ("PROCESADOR AMD RYZEN 9 9950X3D 16 NÚCLEOS 5.7GHZ TURBO SIN COOLER AM5", "Ryzen 9 9950X3D", 16, True),
    ("PROCESADOR AMD (AM5) RYZEN 9 9950X3D", "Ryzen 9 9950X3D", 16, True),
    ("MICRO AMD RYZEN 9 9950X3D C/VIDEO S/COOLER BOX AM5", "Ryzen 9 9950X3D", 16, True),
    ("PROCES. AMD RYZEN 9 9950X3D AM5 (16 CORE) CON VIDEO SIN COOLER (5555)", "Ryzen 9 9950X3D", 16, True),
    ("AMD Ryzen 9 9000 9950X3D Hexadeca-core (16 Core) 4.30 GHz Processor", "Ryzen 9 9950X3D", 16, True),
    ("PROCESADOR AMD RYZEN 9 9950X3D2 SIN COOLER AM5", "Ryzen 9 9950X3D2", 16, True),
    ("Micro AMD Ryzen 7 9800X3D 4.7GHz AM5", "Ryzen 7 9800X3D", 8, True),
    ("AMD Ryzen 5 7600 AM5 Box con Wraith Stealth", "Ryzen 5 7600", 6, False),
    ("Procesador AMD Ryzen 9 9950X AM5", "Ryzen 9 9950X", 16, False),
    ("Intel Core Ultra 7 265K 20 Core LGA1851", "Core Ultra 7 265K", 20, False),
    ("Procesador Intel Core i7-14700KF 5.6GHz LGA1700", "Core i7-14700KF", 20, False),
])
def test_cpu(titulo, modelo, nucleos, x3d):
    o = n("cpu", titulo)
    assert o.descartada is None
    assert o.modelo == modelo
    assert o.datos["nucleos"] == nucleos and o.datos["x3d"] == x3d


def test_cpu_tray_y_vieja():
    assert n("cpu", "AMD Ryzen 7 9800X3D Tray sin cooler").tray
    assert "vieja" in n("cpu", "MICRO AMD RYZEN 7 5800X3D 4.7 GHZ AM4").descartada
    assert n("cpu", "Intel Core i5-13400F").descartada


@pytest.mark.parametrize("titulo,modelo,mods,vel,cl", [
    ("MEMORIA DDR5 64GB 6000MHZ KLEVV (2X32GB) BOLT V CL30", "DDR5 64GB (2x32) 6000 CL30", 2, 6000, 30),
    ("MEMORIA DDR5 64GB 6000MHZ CORSAIR (2X32GB) VENGEANCE GREY CL40 AMD EXPO/INTEL XMP 3.0",
     "DDR5 64GB (2x32) 6000 CL40", 2, 6000, 40),
    ("MEMORIA RAM PATRIOT VIPER ELITE 5 RGB 32GB (2X16GB) DDR5 6600MHZ CL36", "DDR5 32GB (2x16) 6600 CL36", 2, 6600, 36),
    ("MEMORIA NETAC SHADOW III DDR5 4800 32GB C40 BLACK (16GBX2)", "DDR5 32GB (2x16) 4800 CL40", 2, 4800, 40),
    ("MEMORIA DDR5 32GB (2*16) 4800MHZ CORSAIR VENGEANCE LPX", "DDR5 32GB (2x16) 4800", 2, 4800, None),
    ("MEMORIA RAM LEXAR 32GB 5600MHZ DDR5 CL46 BLACK", "DDR5 32GB (1x) 5600 CL46", 1, 5600, 46),
    # Australia, con SKU
    ("G.Skill F5-6000J3040G32GX2-RS5K Ripjaws S5 64GB (2x 32GB) DDR5 6000MHz", "DDR5 64GB (2x32) 6000 CL30", 2, 6000, 30),
    ("Kingston KF556C36BBEAK2-64 FURY Beast Black DDR5 64GB (2x32GB) 5600MHz", "DDR5 64GB (2x32) 5600 CL36", 2, 5600, 36),
    ("Corsair CMP64GX5M2B6000Z30W Dominator Titanium 64GB (2 x 32GB) DDR5", "DDR5 64GB (2x32) 6000 CL30", 2, 6000, 30),
])
def test_ram(titulo, modelo, mods, vel, cl):
    o = n("ram", titulo)
    assert o.descartada is None
    assert o.modelo == modelo
    assert o.datos["modulos"] == mods and o.datos["velocidad"] == vel and o.datos["cl"] == cl


def test_ram_expo_y_precio_por_gb():
    o = normalizar(Oferta("t", "AR", "ram", "MEMORIA DDR5 64GB 6000MHZ CORSAIR (2X32GB) VENGEANCE CL30 AMD EXPO",
                          "u", 640000.0, "ARS"))
    assert o.datos["expo"] and o.datos["precio_por_gb"] == 10000.0


@pytest.mark.parametrize("titulo", [
    "MEMORIA RAM SODIMM ADATA DDR5 32GB 5600MHZ BLISTER",
    "DDR5 64GB P/DELL SERVER 6400MHZ KINGSTON",
    "DDR5 HPE 64GB 2RX4 PC5-4800B-R SMART KIT",
    "Kingston KSM56R46BD4PMI-64MDI 64GB 5600MT/s DDR5 ECC CL46 DIMM 2Rx4",
    "ASUS ROG STRIX B650E-I GAMING WIFI (AM5) Mini-ITX Motherboard 2x DDR5",
    "MEMORIA PUSKILL 8GB DDR5 5600MHZ UDIMM",
    "MEMORIA RAM KINGSTON FURY 16GB DDR4 3200",
])
def test_ram_descartada(titulo):
    assert n("ram", titulo).descartada


def test_chip_config():
    assert parsear_chip_config("RTX 5060 Ti 16GB") == ("RTX 5060 Ti", 16)
    assert parsear_chip_config("RX 9070 XT") == ("RX 9070 XT", None)
    assert parsear_chip_config("RX 9060 XT 16GB") == ("RX 9060 XT", 16)
