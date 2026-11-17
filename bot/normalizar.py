"""Normalización de títulos a un modelo canónico + limpieza (usados, notebooks, combos...).

Cada categoría tiene su parser. Todos trabajan sobre el título en MAYÚSCULAS y sin
tildes, y completan en la Oferta: modelo, variante, datos, tray, combo o descartada.
"""
from __future__ import annotations

import re
import unicodedata

from .modelos import Oferta

# ---------------------------------------------------------------- utilidades


def limpiar(titulo: str) -> str:
    t = unicodedata.normalize("NFKD", titulo)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.upper().replace("×", "X").replace("–", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def _r(p: str) -> re.Pattern:
    return re.compile(p)


USADO = _r(r"\b(USAD[OA]S?|REACONDICIONAD[OA]S?|REFURBISHED|REFURB|RENEWED|OPEN ?BOX|OUTLET|"
           r"SEGUNDA MANO|EX[- ]?DEMO|B[- ]GRADE|PRE[- ]?OWNED|SECOND ?HAND|CAJA ABIERTA|"
           r"REPARAD[OA]|DEMO UNIT)\b")
NOTEBOOK = _r(r"\b(NOTEBOOK|LAPTOP|PORTATIL|NETBOOK|ULTRABOOK|CHROMEBOOK)\b")
PC_ARMADA = _r(r"^(PC|COMPUTADORA|EQUIPO|CPU)\s+(GAMER|ARMAD|DE ESCRITORIO|COMPLET)|"
               r"\b(PC ARMADA|EQUIPO ARMADO|GAMING PC|GAMING DESKTOP|DESKTOP PC(?! COMPUTER| RAM| MEMORY)|PRE-?BUILT|"
               r"MINI PC|ALL[- ]IN[- ]ONE PC|PC GAMER (AMD|INTEL|RYZEN|CORE))\b")
COMBO = _r(r"\b(COMBO|BUNDLE KIT|KIT (DE )?ACTUALIZACION|UPGRADE KIT|KIT UPGRADE)\b|"
           r"\s\+\s*(MOTHER|MOTHERBOARD|PLACA MADRE|MEMORIA|RAM|PROCESADOR|MICRO|RYZEN|CORE|CPU|"
           r"B[68]50|X[68]70|Z[89]90|B[67]60)")
TRAY = _r(r"\b(TRAY|SIN CAJA|S/CAJA|OEM|BULK|MPK)\b")


def _primero(patron: re.Pattern, t: str):
    m = patron.search(t)
    return m


# ---------------------------------------------------------------- placas de video

ACCESORIO_GPU = _r(r"\b(WATER ?BLOCK|WATERBLOCK|SOPORTE|HOLDER|BRACKET|RISER|CABLE|BACKPLATE|"
                   r"ANTI[- ]?SAG|EXTENSOR|ADAPTADOR|THERMAL PAD|PAD TERMICO|GPU SUPPORT|"
                   r"VERTICAL MOUNT|SAG)\b")
RE_NVIDIA = _r(r"\bRTX\s*-?\s*(\d{4})\s*(TI\s*SUPER|TI|SUPER)?(?![A-Z0-9])")
RE_NVIDIA_PEGADO = _r(r"\bRTX\s*-?\s*(\d{4})(TI|S)?(?=[-\s/]|$)")
RE_AMD = _r(r"\bRX\s*-?\s*(\d{4})\s*(XTX|XT|GRE)?(?![A-Z0-9])")
# (?<!\d-): no tomar el final de un SKU como VRAM (Sapphire "11350-02-20G" es una 16GB)
RE_VRAM = _r(r"(?<![\dX.])(?<!\d-)(\d{1,2})\s*G(?:B)?(?![A-Z0-9])")
RE_LARGO = _r(r"(\d{3})\s?MM\b")
VRAM_VALIDAS = {4, 6, 8, 10, 12, 16, 20, 24, 32}

VRAM_POR_DEFECTO = {
    "RTX 4060": 8, "RTX 4070": 12, "RTX 4070 Super": 12, "RTX 4070 Ti": 12,
    "RTX 4070 Ti Super": 16, "RTX 4080": 16, "RTX 4080 Super": 16, "RTX 4090": 24,
    "RTX 5050": 8, "RTX 5060": 8, "RTX 5070": 12, "RTX 5070 Ti": 16, "RTX 5080": 16,
    "RTX 5090": 32, "RX 7600": 8, "RX 7600 XT": 16, "RX 7700 XT": 12, "RX 7800 XT": 16,
    "RX 7900 GRE": 16, "RX 7900 XT": 20, "RX 7900 XTX": 24, "RX 9060": 8, "RX 9070 GRE": 12,
    "RX 9070": 16, "RX 9070 XT": 16,
}  # RTX 4060 Ti, RTX 5060 Ti y RX 9060 XT salen en 8 y 16 GB: hay que leerlo del título

MARCAS_GPU = [
    ("ASUS", "ASUS"), ("ROG", "ASUS"), ("TUF", "ASUS"), ("MSI", "MSI"), ("GIGABYTE", "Gigabyte"),
    ("AORUS", "Gigabyte"), ("ZOTAC", "Zotac"), ("PALIT", "Palit"), ("GAINWARD", "Gainward"),
    ("PNY", "PNY"), ("INNO3D", "Inno3D"), ("GALAX", "Galax"), ("KFA2", "Galax"),
    ("COLORFUL", "Colorful"), ("SAPPHIRE", "Sapphire"), ("POWERCOLOR", "PowerColor"),
    ("POWER COLOR", "PowerColor"), ("XFX", "XFX"), ("ASROCK", "ASRock"), ("ACER", "Acer"),
    ("BIOSTAR", "Biostar"), ("MANLI", "Manli"), ("LEADTEK", "Leadtek"), ("YESTON", "Yeston"),
    ("MAXSUN", "Maxsun"), ("FOUNDERS EDITION", "NVIDIA"), ("DELL", "Dell"), ("HP ", "HP"),
]

LINEAS_GPU = {
    "ASUS": [("ROG ASTRAL", "ROG Astral"), ("ROG STRIX", "ROG Strix"), ("STRIX", "ROG Strix"),
             ("TUF", "TUF Gaming"), ("PROART", "ProArt"), ("PRIME", "Prime"), ("DUAL", "Dual"),
             ("T1", "T1"), ("KO", "KO"), ("TURBO", "Turbo")],
    "MSI": [("SUPRIM LIQUID", "Suprim Liquid"), ("SUPRIM", "Suprim"), ("GAMING X TRIO", "Gaming X Trio"),
            ("GAMING TRIO", "Gaming Trio"), ("VANGUARD", "Vanguard"), ("EXPERT", "Expert"),
            ("INSPIRE", "Inspire"), ("SHADOW 3X", "Shadow 3X"), ("SHADOW 2X", "Shadow 2X"),
            ("SHADOW", "Shadow"), ("VENTUS 3X", "Ventus 3X"), ("VENTUS 2X", "Ventus 2X"),
            ("VENTUS", "Ventus"), ("GAMING X", "Gaming X"), ("GAMING", "Gaming")],
    "Gigabyte": [("AORUS XTREME", "Aorus Xtreme"), ("AORUS MASTER", "Aorus Master"),
                 ("AORUS ELITE", "Aorus Elite"), ("AORUS", "Aorus"), ("GAMING", "Gaming"),
                 ("WINDFORCE", "Windforce"), ("EAGLE", "Eagle"), ("AERO", "Aero")],
    "Zotac": [("AMP EXTREME", "AMP Extreme"), ("AMP", "AMP"), ("TWIN EDGE", "Twin Edge"),
              ("SOLID CORE", "Solid Core"), ("SOLID", "Solid")],
    "Palit": [("GAMEROCK", "GameRock"), ("GAMINGPRO", "GamingPro"), ("GAMING PRO", "GamingPro"),
              ("INFINITY", "Infinity"), ("DUAL", "Dual")],
    "Gainward": [("PHANTOM", "Phantom"), ("PHOENIX", "Phoenix"), ("PYTHON", "Python"),
                 ("GHOST", "Ghost")],
    "PNY": [("EPIC-X", "Epic-X"), ("TRIPLE FAN", "Triple Fan"), ("DUAL FAN", "Dual Fan")],
    "Inno3D": [("ICHILL", "iChill"), ("TWIN X2", "Twin X2"), ("X3", "X3"), ("X2", "X2")],
    "Galax": [("HOF", "HOF"), ("EX GAMER", "EX Gamer"), ("1-CLICK", "1-Click")],
    "Sapphire": [("NITRO", "Nitro+"), ("PURE", "Pure"), ("PULSE", "Pulse")],
    "PowerColor": [("RED DEVIL", "Red Devil"), ("HELLHOUND", "Hellhound"), ("REAPER", "Reaper"),
                   ("RED DRAGON", "Red Dragon"), ("FIGHTER", "Fighter")],
    "XFX": [("MERCURY", "Mercury"), ("QUICKSILVER", "Quicksilver"), ("SWIFT", "Swift")],
    "ASRock": [("TAICHI", "Taichi"), ("STEEL LEGEND", "Steel Legend"), ("CHALLENGER", "Challenger"),
               ("PHANTOM GAMING", "Phantom Gaming"), ("CREATOR", "Creator")],
    "Acer": [("PREDATOR", "Predator"), ("NITRO", "Nitro")],
}
RE_OC = _r(r"\bOC\b|\bO\d{1,2}G\b|OVERCLOCK")


def _palabra(token: str, t: str) -> bool:
    return re.search(r"(?<![A-Z0-9])" + re.escape(token) + r"(?![A-Z0-9])", t) is not None


def chip_gpu(t: str) -> str | None:
    """Devuelve el chip canónico ('RTX 5070 Ti', 'RX 9070 XT') o None."""
    m = RE_NVIDIA.search(t) or RE_NVIDIA_PEGADO.search(t)
    if m:
        num, suf = m.group(1), (m.group(2) or "").replace(" ", "")
        suf = {"TI": " Ti", "SUPER": " Super", "TISUPER": " Ti Super", "S": " Super"}.get(suf, "")
        return f"RTX {num}{suf}"
    m = RE_AMD.search(t)
    if m:
        suf = f" {m.group(2)}" if m.group(2) else ""
        return f"RX {m.group(1)}{suf}"
    return None


def generacion_gpu(chip: str) -> str | None:
    num = chip.split()[1]
    if chip.startswith("RTX") and num[:2] in ("40", "50"):
        return f"RTX {num[:2]}"
    if chip.startswith("RX") and num[0] in ("7", "9"):
        return f"RX {num[0]}000"
    return None


def vram_de(t: str) -> int | None:
    for m in RE_VRAM.finditer(t):
        v = int(m.group(1))
        if v in VRAM_VALIDAS:
            return v
    return None


def marca_gpu(t: str) -> str | None:
    for token, marca in MARCAS_GPU:
        if _palabra(token.strip(), t):
            return marca
    return None


def linea_gpu(t: str, marca: str | None) -> str | None:
    linea = None
    for token, nombre in LINEAS_GPU.get(marca or "", []):
        if _palabra(token, t):
            linea = nombre
            break
    if RE_OC.search(t):
        linea = f"{linea} OC" if linea else "OC"
    return linea


def parsear_placa(o: Oferta, t: str) -> None:
    if ACCESORIO_GPU.search(t):
        o.descartada = "accesorio"
        return
    chip = chip_gpu(t)
    if not chip:
        o.descartada = "sin chip reconocible"
        return
    gen = generacion_gpu(chip)
    if not gen:
        o.descartada = f"generación vieja ({chip})"
        return
    vram = vram_de(t) or VRAM_POR_DEFECTO.get(chip)
    # "RX 9070 12GB GRE", "RX 9070 Reaper GRE": el GRE viene suelto. Toda RX 9070 de 12GB es GRE.
    if chip == "RX 9070" and (_palabra("GRE", t) or vram == 12):
        chip, vram = "RX 9070 GRE", 12
    marca = marca_gpu(t)
    linea = linea_gpu(t, marca)
    largo = None
    if (m := RE_LARGO.search(t)) and 150 <= int(m.group(1)) <= 400:
        largo = int(m.group(1))
    o.modelo = f"{chip} {vram}GB" if vram else chip
    o.variante = " ".join(x for x in (marca, linea) if x) or None
    o.datos = {"chip": chip, "vram": vram, "marca": marca, "linea": linea, "largo_mm": largo,
               "generacion": gen, "fabricante": "NVIDIA" if chip.startswith("RTX") else "AMD"}


# ---------------------------------------------------------------- CPU

RE_RYZEN = _r(r"\bRYZEN\s*([3579])?\s*(?:PRO\s*)?([789]\d{3})\s*(X3D2|X3D|X|F|G|GT|E)?(?![A-Z0-9])")
RE_RYZEN_SUELTO = _r(r"(?<![A-Z0-9])([789]\d{3})(X3D2|X3D|X|F|G)(?![A-Z0-9])")
RE_RYZEN_VIEJO = _r(r"\bRYZEN\s*[3579]?\s*[1-5]\d{3}")
RE_ULTRA = _r(r"\bULTRA\s*([579])\s*-?\s*(2\d{2})\s*(KF|K|F|T)?(?:\s*PLUS)?(?![A-Z0-9])")
# "Core Ultra 5 14 Core LGA 1851 245K": el número de modelo aparece más adelante
RE_ULTRA_LEJOS = _r(r"\bULTRA\s*([579])\b.{0,30}?(?<![\d.])(2\d{2})\s*(KF|K|F|T)?(?![A-Z0-9.])")
RE_ULTRA_PLUS = _r(r"\bULTRA\s*[579]\s*-?\s*2\d{2}\s*(?:KF|K|F|T)?\s*PLUS\b")
RE_I14 = _r(r"\bI([3579])\s*-?\s*(14\d{2}0)\s*(KS|KF|K|F|T)?(?![A-Z0-9])")
RE_INTEL_VIEJO = _r(r"\bI[3579]\s*-?\s*(1[0-3]\d{3}|[2-9]\d{3})")

NUCLEOS_ULTRA = {"285": 24, "270": 24, "265": 20, "250": 18, "245": 14, "235": 14, "225": 10}
NUCLEOS_I14 = {"149": 24, "147": 20, "146": 14, "145": 14, "144": 10, "141": 4}


def _ryzen_por_numero(num: str) -> tuple[int, int]:
    """(tier, núcleos) a partir del número: x950→(9,16), x900→(9,12), x800/x700→(7,8), resto (5,6)."""
    resto = int(num[1:])
    if resto >= 950:
        return 9, 16
    if resto >= 900:
        return 9, 12
    if resto >= 700:
        return 7, 8
    return 5, 6


def parsear_cpu(o: Oferta, t: str) -> None:
    if re.search(r"\b(DISIPADOR|WATER ?COOLER|PASTA TERMICA|AIO \d{3})\b", t) and "PROCESADOR" not in t:
        o.descartada = "accesorio"
        return
    m = RE_RYZEN.search(t)
    if m and m.group(2).endswith("000"):  # "Ryzen 9 9000 9950X3D": el 9000 es la familia
        m = RE_RYZEN.search(t, m.end()) or None
    suelto = None if m else RE_RYZEN_SUELTO.search(t)
    if m or suelto:
        num = (m or suelto).group(2 if m else 1)
        suf = ((m.group(3) if m else suelto.group(2)) or "")
        tier_calc, nucleos = _ryzen_por_numero(num)
        tier = int(m.group(1)) if m and m.group(1) else tier_calc
        modelo = f"Ryzen {tier} {num}{suf}"
        if n := re.search(r"(\d{1,2})\s*(?:NUCLEOS|CORES?|C/|C\b)", t):
            nucleos = int(n.group(1)) if 4 <= int(n.group(1)) <= 32 else nucleos
        o.modelo = modelo
        o.datos = {"marca": "AMD", "socket": "AM5", "nucleos": nucleos, "x3d": suf.startswith("X3D"),
                   "familia": f"Ryzen {num[0]}000"}
    elif (m := RE_ULTRA.search(t) or RE_ULTRA_LEJOS.search(t)):
        tier, num, suf = m.group(1), m.group(2), m.group(3) or ""
        plus = " Plus" if RE_ULTRA_PLUS.search(t) else ""
        o.modelo = f"Core Ultra {tier} {num}{suf}{plus}"
        o.datos = {"marca": "Intel", "socket": "LGA1851", "nucleos": NUCLEOS_ULTRA.get(num[:3]),
                   "x3d": False, "familia": "Core Ultra 200S"}
    elif (m := RE_I14.search(t)):
        tier, num, suf = m.group(1), m.group(2), m.group(3) or ""
        o.modelo = f"Core i{tier}-{num}{suf}"
        o.datos = {"marca": "Intel", "socket": "LGA1700", "nucleos": NUCLEOS_I14.get(num[:3]),
                   "x3d": False, "familia": "Core 14ª gen"}
    elif RE_RYZEN_VIEJO.search(t) or RE_INTEL_VIEJO.search(t):
        o.descartada = "generación vieja"
        return
    else:
        o.descartada = "sin modelo reconocible"
        return
    o.variante = "Tray" if o.tray else "Box"


# ---------------------------------------------------------------- RAM

RAM_NO_DESKTOP = _r(r"\b(SO-?DIMM|SODIMM|NOTEBOOK|LAPTOP|PORTATIL|SERVER|SERVIDOR|ECC|RDIMM|"
                    r"REGISTERED|RECC|HPE|P/DELL|PC5-\d+B-R|CAMM2?|MOTHERBOARD|MOTHER|PLACA MADRE|"
                    r"EMMC|NUC|ANDROID|MINI-ITX|TABLET)\b")
RE_KIT = _r(r"(?<!\d)([1-4])\s*[X\*]\s*(8|16|24|32|48|64)\s*(?:GB?)?(?![\dA-Z])")
RE_KIT_INV = _r(r"(?<!\d)(\d{1,2})\s*GB?\s*[X\*]\s*([1-4])(?!\d)")
RE_GB = _r(r"(?<![X\*\d])(\d{1,3})\s*GB\b")
RE_CORSAIR = _r(r"\bCM[A-Z0-9]*?(\d{2,3})GX5M(\d)[A-Z](\d{4})[CZ](\d{2})")
RE_GSKILL = _r(r"\bF5-(\d{4})[A-Z](\d{2})\d{2}[A-Z](\d{2})G[A-Z]?X(\d)")
RE_KINGSTON = _r(r"\bKF5(\d{2})C(\d{2})[A-Z0-9]*?(?:K(\d))?-(\d{2,3})\b")
RE_VEL = _r(r"(?<!\d)(\d{4})\s*(?:MHZ|MT/?S)")
RE_VEL_DDR = _r(r"DDR5[- ]?(\d{4})(?!\d)")
RE_VEL_SUELTA = _r(r"(?<!\d)([4-9][0-9]00)(?!\d|\s*GB)")
RE_CL = _r(r"\bCL\s?-?(\d{2})\b|\bC(\d{2})\b")
MARCAS_RAM = [("KINGSTON", "Kingston"), ("FURY", "Kingston"), ("CORSAIR", "Corsair"),
              ("G.SKILL", "G.Skill"), ("GSKILL", "G.Skill"), ("G SKILL", "G.Skill"),
              ("CRUCIAL", "Crucial"), ("T-FORCE", "TeamGroup"), ("TEAMGROUP", "TeamGroup"),
              ("TEAM GROUP", "TeamGroup"), ("TEAM", "TeamGroup"), ("XPG", "ADATA"), ("ADATA", "ADATA"),
              ("PATRIOT", "Patriot"), ("VIPER", "Patriot"), ("LEXAR", "Lexar"), ("PNY", "PNY"),
              ("NETAC", "Netac"), ("GEIL", "GeIL"), ("KLEVV", "Klevv"), ("HIKSEMI", "Hiksemi"),
              ("THERMALTAKE", "Thermaltake"), ("MEMOX", "Memox"), ("SAMSUNG", "Samsung"),
              ("ACER", "Acer"), ("ASGARD", "Asgard"), ("KINGBANK", "Kingbank")]


def parsear_ram(o: Oferta, t: str) -> None:
    if RAM_NO_DESKTOP.search(t):
        o.descartada = "no es RAM de escritorio"
        return
    total = mods = vel = cl = None
    # algunas tiendas no repiten "DDR5" en el título cuando la categoría ya es solo DDR5
    es_ddr5 = "DDR5" in t or (o.datos.get("ddr") == "DDR5" and "DDR4" not in t)
    if m := RE_CORSAIR.search(t):
        total, mods, vel, cl = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        es_ddr5 = True
    elif m := RE_GSKILL.search(t):
        vel, cl, per, mods = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        total, es_ddr5 = per * mods, True
    elif m := RE_KINGSTON.search(t):
        vel, cl = int(m.group(1)) * 100, int(m.group(2))
        mods, total, es_ddr5 = int(m.group(3) or 1), int(m.group(4)), True
    if "DDR4" in t and not es_ddr5:
        o.descartada = "DDR4"
        return
    if not es_ddr5 and not re.search(r"\bDDR\d", t):
        # sin "DDRx" en el título: 5200 MHz o más solo existe en DDR5
        for patron in (RE_VEL, RE_VEL_DDR, RE_VEL_SUELTA):
            if (m := patron.search(t)) and 5200 <= int(m.group(1)) <= 10000:
                es_ddr5 = True
                break
    if not es_ddr5:
        o.descartada = "no dice DDR5"
        return
    if m := RE_KIT.search(t):
        mods, per = int(m.group(1)), int(m.group(2))
        total = mods * per
    elif m := RE_KIT_INV.search(t):
        per, mods = int(m.group(1)), int(m.group(2))
        total = mods * per
    if total is None:
        gbs = [int(x) for x in RE_GB.findall(t) if 8 <= int(x) <= 256]
        if gbs:
            total = max(gbs)
    if mods is None:
        mods = 2 if re.search(r"\b(KIT|DUAL|2 MODULOS|DOBLE)\b", t) else 1
    if vel is None:
        for patron in (RE_VEL, RE_VEL_DDR, RE_VEL_SUELTA):
            if m := patron.search(t):
                v = int(m.group(1))
                if 4000 <= v <= 10000:
                    vel = v
                    break
    if cl is None and (m := RE_CL.search(t)):
        v = int(m.group(1) or m.group(2))
        cl = v if 20 <= v <= 60 else None
    if total is None:
        o.descartada = "sin capacidad"
        return
    if not 32 <= total <= 128:
        o.descartada = f"fuera de rango ({total}GB)"
        return
    marca = next((m_ for tok, m_ in MARCAS_RAM if _palabra(tok, t)), None)
    per = total // mods if mods else None
    partes = [f"DDR5 {total}GB", f"({mods}x{per})" if mods and mods > 1 else f"(1x{total})"]
    if vel:
        partes.append(str(vel))
    if cl:
        partes.append(f"CL{cl}")
    o.modelo = " ".join(partes)
    o.variante = marca
    o.datos = {"marca": marca, "capacidad_gb": total, "modulos": mods, "velocidad": vel, "cl": cl,
               "expo": "EXPO" in t, "xmp": "XMP" in t, "tipo": "DDR5"}


# ---------------------------------------------------------------- PCs armadas

def parsear_pc(o: Oferta, t: str) -> None:
    """Una PC armada se identifica por su placa de video: modelo "PC RTX 5070 Ti".
    Si la tienda leyó la placa aparte (Mexx corta el nombre), manda esa."""
    chip = chip_gpu(limpiar(o.datos.get("placa") or "")) or chip_gpu(t)
    if not chip:
        o.descartada = "PC sin placa de video reconocible"
        return
    o.modelo = f"PC {chip}"
    o.datos = {"chip": chip, "fabricante": "NVIDIA" if chip.startswith("RTX") else "AMD", "ram_gb": ram_de_pc(t)}


RAM_PC_VALIDAS = {8, 16, 24, 32, 48, 64, 96, 128}
# "32GB DDR5", "16GB (2x8GB) DDR4", "32GB RAM": la RAM dicha como tal
RE_RAM_PC = _r(r"(?<![\d.])(\d{1,3})\s*GB?\s*(?:\(\s*\d\s*X\s*\d+\s*GB?\s*\)\s*)?(?:DDR\d|RAM|MEMORIA)")
# la placa con su VRAM ("RTX 5070 TI 16GB", "RX 9070 XT 16GB GDDR6"), para no confundirla con la RAM
RE_GPU_VRAM = _r(r"\b(?:RTX|RX)\s*-?\s*\d{4}\s*(?:TI SUPER|TI|SUPER|XTX|XT|GRE|S)?\s*\d{1,2}\s*GB?\b(?:\s*GDDR\d)?")
RE_GB_SUELTO = _r(r"(?<![\d.])(\d{1,3})\s*GB?(?![A-Z0-9])(?!\s*(?:GDDR|VRAM|SSD|NVME|M\.2|HDD))")


def ram_de_pc(t: str) -> int | None:
    """Cantidad de RAM de una PC armada, sin tomar la VRAM de la placa ni el disco."""
    for m in RE_RAM_PC.finditer(t):
        if int(m.group(1)) in RAM_PC_VALIDAS:
            return int(m.group(1))
    sin_gpu = RE_GPU_VRAM.sub(" ", t)
    for m in RE_GB_SUELTO.finditer(sin_gpu):
        if int(m.group(1)) in RAM_PC_VALIDAS:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------- entrada principal

PARSERS = {"placas": parsear_placa, "cpu": parsear_cpu, "ram": parsear_ram, "pcs": parsear_pc}


def normalizar(o: Oferta) -> Oferta:
    extra = dict(o.datos)  # lo que trajo la tienda (fecha de actualización, estado de stock...)
    t = limpiar(o.titulo)
    o.tray = bool(TRAY.search(t))
    o.combo = bool(COMBO.search(t))
    if USADO.search(t):
        o.descartada = "usado/reacondicionado"
    elif NOTEBOOK.search(t):
        o.descartada = "notebook"
    elif o.categoria != "pcs" and PC_ARMADA.search(t):
        o.descartada = "PC armada"
    elif (p := PARSERS.get(o.categoria)):
        p(o, t)
    else:
        o.modelo = None  # categorías de Fase 2: se guardan sin normalizar todavía
    o.datos = {**extra, **o.datos}
    if o.datos.get("capacidad_gb") and o.precio:
        o.datos["precio_por_gb"] = round(o.precio / o.datos["capacidad_gb"], 2)
    return o


def parsear_chip_config(texto: str) -> tuple[str | None, int | None]:
    """'RTX 5060 Ti 16GB' -> ('RTX 5060 Ti', 16)."""
    t = limpiar(texto)
    return chip_gpu(t), vram_de(t)


def canon(texto: str) -> str:
    """Clave comparable para modelos: sin espacios extra, minúsculas."""
    return re.sub(r"[\s\-]+", " ", texto.strip().lower())
