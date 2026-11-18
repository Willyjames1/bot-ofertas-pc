"""Normalización de títulos a un modelo canónico + limpieza (usados, notebooks, combos...).

Cada categoría tiene su parser. Todos trabajan sobre el título en MAYÚSCULAS y sin
tildes, y completan en la Oferta: modelo, variante, datos, tray, combo o descartada.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

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
    o.datos = {"chip": chip, "fabricante": "NVIDIA" if chip.startswith("RTX") else "AMD", "ram_gb": ram_de_pc(t),
               "ssd_tb": ssd_de_pc(t), **cpu_de_pc(t)}


def cpu_de_pc(t: str) -> dict:
    """Procesador de una PC armada: {'cpu': 'Ryzen 7 9800X3D', 'nucleos': 8, 'cpu_marca': 'AMD',
    'cpu_tier': 7} o {} si el título no lo dice (o es de una generación que no seguimos)."""
    tmp = Oferta(tienda="", pais="", categoria="cpu", titulo=t, url="", precio=0, moneda="")
    parsear_cpu(tmp, t)
    if tmp.descartada or not tmp.modelo:
        if m := re.search(r"\bI([3579])[- ]?(1[23]\d{3})", t):   # Core i7-12700 / 13700: tier sin núcleos
            return {"cpu": f"Core i{m.group(1)}-{m.group(2)}", "cpu_marca": "Intel", "cpu_tier": int(m.group(1)),
                    "nucleos": None}
        return {}
    tier = re.search(r"(?:Ryzen|Ultra|i)\s?(\d)", tmp.modelo)
    return {"cpu": tmp.modelo, "nucleos": tmp.datos.get("nucleos"), "cpu_marca": tmp.datos.get("marca"),
            "cpu_tier": int(tier.group(1)) if tier else None}


RE_TB_PC = _r(r"(?<![\d.])(\d)\s*TB\b")
RE_GB_DISCO_PC = _r(r"(?<![\d.])(256|500|512|1000|2000)\s*GB\s*(?:M\.2\s*)?(?:SSD|NVME|M\.2|PCIE)")


def ssd_de_pc(t: str) -> float | None:
    """Disco de una PC armada en TB ('2TB NVMe' → 2, '512GB SSD' → 0.5)."""
    if m := RE_TB_PC.search(t):
        return float(m.group(1))
    if m := RE_GB_DISCO_PC.search(t):
        return round(int(m.group(1)) / 1000, 1) if int(m.group(1)) >= 1000 else 0.5
    return None


# ---------------------------------------------------------------- SSD

# lo que no es un SSD (sí se guardan los externos y los carry, marcados: /buscar los muestra si los pedís)
SSD_NO = _r(r"\b(MICRO ?SD|SD CARD|MEMORY CARD|PENDRIVE|FLASH DRIVE|HDD|DISCO RIGIDO|HARD DRIVE)\b")
SSD_EXTERNO = _r(r"\b(PORTABLE|PORTATIL|EXTERN[OA]S?|EXTERNAL|USB)\b")
SSD_CARRY = _r(r"\b(ENCLOSURE|CARRY|DOCK|GABINETE|ADAPTADOR|ADAPTER|CADDY)\b")
SSD_SI = _r(r"\b(SSD|NVME|M\.2|SOLIDO|SOLID STATE)\b")
RE_SSD_TB = _r(r"(?<![\d.])(\d(?:[.,]\d)?)\s*TB\b")
RE_SSD_GB = _r(r"(?<![\d.])(240|250|256|480|500|512|960|1000|1024|2000|2048|4000|4096)\s*GB\b")
GB_A_TB = {240: 0.25, 250: 0.25, 256: 0.25, 480: 0.5, 500: 0.5, 512: 0.5, 960: 1, 1000: 1, 1024: 1,
           2000: 2, 2048: 2, 4000: 4, 4096: 4}
# "PCIe 4.0", "PCIe Gen4 x4", "Gen 4x4", "PCIe x4 4.0", "PCIe5.0", "PCI-E Gen5", "PCIe NVMe 4.0"
RE_SSD_GEN = _r(r"(?<![A-Z0-9])(?:(?:PCI-?E|PCI EXPRESS)\s*(?:NVME\s*)?(?:X\s*[124]\s*)?(?:GEN\s*)?|GEN\s*)([345])(?:\.0)?"
                r"(?![0-9]|\s*TB)")
RE_SSD_FORMA = _r(r"(?<![0-9])(22(?:30|42|80))(?![0-9])")
# velocidades: "7450/6900MB/s", "7.450 / 6.900 MB/s", "5000MB/s Read, 4800MB/s Write", "14000MB/s"
_MBS = r"(\d{1,2}[.,]?\d{3}|[1-9]\d{2})"
RE_SSD_VEL_PAR = _r(r"(?<![\d.,])" + _MBS + r"\s*(?:MB/?S)?\s*/\s*" + _MBS + r"\s*MB/?S")
RE_SSD_VEL_RW = _r(r"(?<![\d.,])" + _MBS + r"\s*MB/?S\s*(?:READ|LECTURA)[^0-9]{0,12}?" + _MBS +
                   r"\s*MB/?S\s*(?:WRITE|ESCRITURA)")
RE_SSD_VEL = _r(r"(?<![\d.,])" + _MBS + r"\s*MB/?S")
MARCAS_SSD = [("SAMSUNG", "Samsung"), ("WD_BLACK", "WD"), ("WD ", "WD"), ("WESTERN DIGITAL", "WD"),
              ("CRUCIAL", "Crucial"), ("KINGSTON", "Kingston"), ("CORSAIR", "Corsair"), ("SEAGATE", "Seagate"),
              ("ADATA", "ADATA"), ("XPG", "ADATA"), ("LEXAR", "Lexar"), ("SOLIDIGM", "Solidigm"),
              ("TEAMGROUP", "TeamGroup"), ("TEAM GROUP", "TeamGroup"), ("TEAM ", "TeamGroup"),
              ("HIKSEMI", "Hiksemi"), ("PNY", "PNY"), ("SABRENT", "Sabrent"), ("MSI", "MSI"),
              ("GIGABYTE", "Gigabyte"), ("PATRIOT", "Patriot"), ("SANDISK", "Sandisk"),
              ("SILICON POWER", "Silicon Power"), ("KINGBANK", "Kingbank"), ("TRANSCEND", "Transcend"),
              ("NETAC", "Netac"), ("SK HYNIX", "SK hynix"), ("HIKVISION", "Hikvision")]


def _cargar_ssd_modelos() -> list[list]:
    """ssd_modelos.yaml → [[nombre, marca, gen, [[tb, lectura, escritura], ...]], ...] y alias → índice."""
    import yaml   # acá y no arriba: el resto del normalizador no lo necesita
    ruta = Path(__file__).resolve().parent.parent / "ssd_modelos.yaml"
    modelos, alias = [], {}
    for m in yaml.safe_load(ruta.read_text(encoding="utf-8")) or []:
        vel = sorted([float(tb) if float(tb) != int(tb) else int(tb), int(v[0]), int(v[1])]
                     for tb, v in (m.get("velocidad") or {}).items())
        for a in m["alias"]:
            alias[limpiar(str(a))] = len(modelos)
        modelos.append([m["nombre"], m["marca"], int(m["gen"]), vel])
    return modelos, alias


SSD_MODELOS, _ALIAS_SSD = _cargar_ssd_modelos()
# alias sin espacios → índice ("990PRO"): se buscan juntando hasta 3 palabras seguidas del título, así
# "990 PRO", "990PRO" y "990-Pro" son lo mismo y "MP44" no agarra "MP44L" (sin regex: en el Worker,
# compilar una con 50 alternativas costaba medio ms de los 10 que da el plan gratis)
SSD_ALIAS = {re.sub(r"[^A-Z0-9]", "", a): i for a, i in _ALIAS_SSD.items()}
MAX_PALABRAS_ALIAS = max(len(a.split()) for a in _ALIAS_SSD)


def marca_ssd(t: str) -> str | None:
    return next((v for k, v in MARCAS_SSD if k in t), None)


def buscar_linea_ssd(t: str) -> tuple[int, list[str]] | None:
    """(índice en SSD_MODELOS, palabras) del modelo que nombra el texto, si no es de otra marca. El
    más largo primero ("990 EVO PLUS" antes que "990 EVO")."""
    marca = marca_ssd(t)
    w = [x for x in re.split(r"[^A-Z0-9]+", t) if x]
    for i in range(len(w)):
        for n in range(min(MAX_PALABRAS_ALIAS, len(w) - i), 0, -1):
            j = SSD_ALIAS.get("".join(w[i:i + n]))
            if j is not None and (marca is None or SSD_MODELOS[j][1] == marca):
                return j, w[i:i + n]
    return None


def linea_ssd(t: str) -> int | None:
    """Índice en SSD_MODELOS del modelo que nombra el título (si no es de otra marca)."""
    return r[0] if (r := buscar_linea_ssd(t)) else None


def capacidad_ssd(t: str) -> float | None:
    if m := RE_SSD_TB.search(t):
        tb = float(m.group(1).replace(",", "."))
        return int(tb) if tb == int(tb) else tb
    if m := RE_SSD_GB.search(t):
        return GB_A_TB[int(m.group(1))]
    return None


def _mbs(x: str) -> int:
    return int(re.sub(r"[.,]", "", x))


def velocidad_ssd(t: str, tb: float, linea: int | None) -> tuple[int | None, int | None]:
    """(lectura, escritura) en MB/s: primero el título; si no la dice, la tabla. Si el título dice solo
    la lectura, la escritura sale de la tabla únicamente si la lectura coincide."""
    for rx in (RE_SSD_VEL_RW, RE_SSD_VEL_PAR):
        if m := rx.search(t):
            r, w = _mbs(m.group(1)), _mbs(m.group(2))
            if 400 <= r <= 16000 and 100 <= w <= r * 1.2:
                return r, w
    tabla = next(((r, w) for cap, r, w in SSD_MODELOS[linea][3] if cap == tb), None) if linea is not None else None
    if (m := RE_SSD_VEL.search(t)) and 400 <= (r := _mbs(m.group(1))) <= 16000:
        return (r, tabla[1]) if tabla and tabla[0] == r else (r, None)
    return tabla or (None, None)


def datos_ssd(t: str, exigir_palabra: bool = True) -> dict | str:
    """Lo que se sabe de un SSD por el título (y ssd_modelos.yaml), o un texto con por qué no es uno.
    formato: "2280", "2230", "2242" (M.2 NVMe), "M.2" o "2.5" (SATA), "externo" o "carry"."""
    if SSD_NO.search(t):
        return "no es un SSD"
    i = linea_ssd(t)
    if exigir_palabra and not SSD_SI.search(t) and i is None:
        return "no es un SSD"
    tb = capacidad_ssd(t)
    if tb is None:
        return "sin capacidad reconocible"
    linea = SSD_MODELOS[i] if i is not None else None
    sata = ("SATA" in t and "NVME" not in t) or (linea is not None and linea[2] == 0)
    if SSD_CARRY.search(t):
        formato = "carry"
    elif SSD_EXTERNO.search(t):
        formato = "externo"
    elif sata:
        formato = "M.2" if "M.2" in t else "2.5"
    elif m := RE_SSD_FORMA.search(t):
        formato = m.group(1)
    else:
        formato = "2280"
    if sata:
        gen = None
    elif linea is not None:
        gen = linea[2]       # la de la tabla manda (hay títulos con "Gen5" en un 990 Evo Plus)
    else:
        gen = int(m.group(1)) if (m := RE_SSD_GEN.search(t)) else None
    lectura, escritura = velocidad_ssd(t, tb, i)
    return {"capacidad_tb": tb, "interfaz": "SATA" if sata else "NVMe", "gen": gen,
            "marca": linea[1] if linea else marca_ssd(t), "formato": formato,
            "linea": linea[0] if linea else None, "lectura": lectura, "escritura": escritura}


def ssd_estandar(d: dict) -> bool:
    """Lo que se muestra si no pedís otra cosa: M.2 2280 NVMe Gen4 o Gen5 (con la generación conocida)."""
    return d.get("interfaz") == "NVMe" and d.get("gen") in (4, 5) and (d.get("formato") or "2280") == "2280"


def nombre_ssd(d: dict) -> str:
    tb = d["capacidad_tb"]
    cap = f"{tb:g}TB" if tb >= 1 else f"{round(tb * 1000)}GB"
    formato = d.get("formato") or "2280"
    if formato in ("externo", "carry"):
        return f"SSD {formato} {cap}"
    if d["interfaz"] == "SATA":
        return f"SSD SATA {cap}"
    base = f"SSD NVMe Gen{d['gen']} {cap}" if d.get("gen") else f"SSD NVMe {cap}"
    return base if formato == "2280" else f"{base} {formato}"


RE_PIDE_VEL = _r(r"(?<![A-Z0-9])(VEL|VELOCIDAD|RAPIDOS?|FAST(?:EST)?)(?![A-Z0-9])")


def consulta_ssd(t: str) -> dict | None:
    """Lo que pide una búsqueda de SSD ("990 pro 2tb", "ssd gen5 2tb", "ssd sata 1tb", "ssd externo"):
    None si no es de SSD. El Worker tiene la misma (buscar.js) y coincide_ssd para filtrar."""
    i = linea_ssd(t)
    if SSD_NO.search(t) or not (SSD_SI.search(t) or i is not None or RE_SSD_TB.search(t)):
        return None
    g = RE_SSD_GEN.search(t)
    if SSD_CARRY.search(t):
        formato = "carry"
    elif SSD_EXTERNO.search(t):
        formato = "externo"
    else:
        formato = m.group(1) if (m := RE_SSD_FORMA.search(t)) and m.group(1) != "2280" else None
    return {"capacidad_tb": capacidad_ssd(t), "gen": int(g.group(1)) if g else None,
            "linea": SSD_MODELOS[i][0] if i is not None else None, "sata": "SATA" in t,
            "formato": formato, "vel": bool(RE_PIDE_VEL.search(t))}


def coincide_ssd(q: dict, d: dict) -> bool:
    """¿El SSD d es lo que pide la búsqueda q? Sin pedirlo, solo M.2 2280 NVMe Gen4/Gen5."""
    if q.get("capacidad_tb") is not None and d.get("capacidad_tb") != q["capacidad_tb"]:
        return False
    if q.get("linea") and d.get("linea") != q["linea"]:
        return False
    formato = d.get("formato") or "2280"
    if q.get("formato") in ("externo", "carry"):
        return formato == q["formato"]
    if formato in ("externo", "carry"):
        return False
    if q.get("sata"):
        return d.get("interfaz") == "SATA"
    if d.get("interfaz") != "NVMe" or formato != (q.get("formato") or "2280"):
        return False
    return d.get("gen") == q["gen"] if q.get("gen") else d.get("gen") in (4, 5)


def parsear_ssd(o: Oferta, t: str) -> None:
    """Modelo canónico "SSD NVMe Gen4 2TB" (o "SSD SATA 1TB", "SSD NVMe Gen4 1TB 2230", "SSD externo 2TB");
    el modelo de la tabla ("Samsung 990 Pro") va en la variante, y las velocidades en los datos."""
    d = datos_ssd(t)
    if isinstance(d, str):
        o.descartada = d
        return
    o.modelo = nombre_ssd(d)
    o.variante = d["linea"] or d["marca"]
    o.datos = d


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

PARSERS = {"placas": parsear_placa, "cpu": parsear_cpu, "ram": parsear_ram, "pcs": parsear_pc,
           "ssd": parsear_ssd}


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
