from datetime import datetime, timedelta, timezone

from bot import alertas, config, cotizaciones, resumen
from bot.alertas import Motor
from bot.comparar import equivalente, lineas_comparacion
from bot.cotizaciones import Cotizacion
from bot.db import DB
from bot.modelos import Oferta
from bot.normalizar import normalizar, ram_de_pc

CFG = config.cargar()
AHORA = datetime.now(timezone.utc)
AJ = config.ajustes(CFG, AHORA)
COT = Cotizacion(mep=1577.0, aud_usd=0.6775, ts=AHORA)


def oferta(titulo, precio, pais="AR", tienda="compragamer", cat="placas", url=None, fecha=None, **kw):
    o = Oferta(tienda, pais, cat, titulo, url or f"https://x/{tienda}/{titulo}", precio,
               "AUD" if pais == "AU" else "ARS", fecha=fecha or AHORA, **kw)
    return normalizar(o)


def db_con(*ofertas):
    db = DB(":memory:")
    for o in ofertas:
        db.guardar_oferta(o)
    return db


# ------------------------------------------------------------------ equivalentes

def test_placa_mismo_chip_cualquier_marca_el_mas_barato():
    db = db_con(oferta("Placa de Video ASUS RTX 5070 Ti 16GB Prime", 2_300_000),
                oferta("Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", 2_244_000),
                oferta("Placa de Video MSI RTX 5080 16GB Ventus 3X", 2_900_000))
    o = oferta("Gigabyte RTX 5070 Ti 16GB Windforce", 1441, pais="AU", tienda="centrecom")
    eq = equivalente(db, "placas", o.modelo, o.datos, "AR")
    assert eq.exacto and eq.nota == "mismo chip" and eq.fila["precio"] == 2_244_000


def test_placa_sin_stock_o_vieja_no_cuenta():
    viejo = AHORA - timedelta(days=5)
    db = db_con(oferta("Placa de Video MSI RTX 5070 Ti 16GB Ventus", 2_000_000, fecha=viejo),
                oferta("Placa de Video ASUS RTX 5070 Ti 16GB TUF", 2_100_000, stock=False),
                oferta("Placa de Video ASUS RTX 5070 Ti 16GB Prime", 2_400_000))
    o = oferta("Gigabyte RTX 5070 Ti 16GB Windforce", 1441, pais="AU", tienda="centrecom")
    assert equivalente(db, "placas", o.modelo, o.datos, "AR").fila["precio"] == 2_400_000


def test_ram_aprox_si_cambia_cl_o_velocidad():
    db = db_con(oferta("Memoria Kingston DDR5 32GB (2x16GB) 6000MHz CL36", 800_000, cat="ram"),
                oferta("Memoria Corsair DDR5 32GB (2x16GB) 5600MHz CL30", 700_000, cat="ram"))
    o = oferta("G.Skill Flare X5 32GB (2x16GB) DDR5 6000MHz CL30", 450, pais="AU", tienda="umart", cat="ram")
    eq = equivalente(db, "ram", o.modelo, o.datos, "AR")
    # prioriza la misma velocidad aunque sea más cara; el CL distinto la vuelve "aprox."
    assert eq.fila["precio"] == 800_000 and not eq.exacto and eq.nota == "aprox.: CL36 en vez de CL30"
    db2 = db_con(oferta("Memoria Corsair DDR5 32GB (2x16GB) 5600MHz CL30", 700_000, cat="ram"))
    assert equivalente(db2, "ram", o.modelo, o.datos, "AR").nota == "aprox.: 5600 en vez de 6000"
    db3 = db_con(oferta("Memoria Patriot DDR5 32GB (2x16GB) 6000MHz CL30", 820_000, cat="ram"))
    eq3 = equivalente(db3, "ram", o.modelo, o.datos, "AR")
    assert eq3.exacto and eq3.nota == "misma capacidad, módulos y velocidad"


def test_cpu_mismo_modelo():
    db = db_con(oferta("Procesador AMD Ryzen 9 9900X AM5", 759_800, cat="cpu"),
                oferta("Procesador AMD Ryzen 9 9950X AM5", 1_062_990, cat="cpu"))
    o = oferta("AMD Ryzen 9 9900X Processor", 625, pais="AU", tienda="umart", cat="cpu")
    eq = equivalente(db, "cpu", o.modelo, o.datos, "AR")
    assert eq.exacto and eq.fila["precio"] == 759_800


def test_pc_misma_placa_y_ram():
    db = db_con(oferta("PC Gamer Ryzen 7 9700X 32GB DDR5 1TB RTX 5070 Ti 16GB", 5_100_000, cat="pcs", tienda="venex"),
                oferta("PC Gamer Ryzen 5 9600X 16GB DDR5 1TB RTX 5070 Ti 16GB", 4_500_000, cat="pcs", tienda="venex"))
    o = oferta("Gaming PC Ryzen 7 9800X3D RTX 5070 Ti 32GB DDR5 2TB", 2799, pais="AU", tienda="umart", cat="pcs")
    eq = equivalente(db, "pcs", o.modelo, o.datos, "AR")
    assert eq.exacto and eq.fila["precio"] == 5_100_000
    o64 = oferta("Gaming PC Ryzen 7 9800X3D RTX 5070 Ti 64GB DDR5 2TB", 3299, pais="AU", tienda="umart", cat="pcs")
    eq64 = equivalente(db, "pcs", o64.modelo, o64.datos, "AR")
    assert not eq64.exacto and eq64.nota == "aprox.: 32GB de RAM en vez de 64GB"


def test_ram_de_pc():
    assert ram_de_pc("PC GAMER RYZEN 7 9700X 32GB DDR5 RTX 5070 TI 16GB") == 32
    assert ram_de_pc("HP OMEN 35L RYZEN 7 RTX 5070 TI 16GB 32GB RAM 2TB") == 32
    assert ram_de_pc("PREBUILT RYZEN 7 RTX 5080 16GB, 1TB SSD") is None


# ------------------------------------------------------------------ texto

def test_aviso_au_con_comparacion_aduana_y_veredicto():
    alertas.NOMBRE_TIENDA.update({"compragamer": "Compra Gamer", "centrecom": "Centre Com"})
    db = db_con(oferta("Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", 2_244_000))
    m = Motor(CFG, AJ, db, COT, AHORA)
    o = oferta("MSI GeForce RTX 5070 Ti 16G Ventus 3X OC", 1441, pais="AU", tienda="centrecom")
    t = m.texto_oferta("baja", o, 1699, None, 1450)
    assert t.startswith("🔻 <b>RTX 5070 Ti 16GB</b> — bajó 15% en 🇦🇺")
    # no se muestra el "precio anterior" de la tienda: las referencias son las de 7 y 30 días
    assert "@ Centre Com: <b>A$1.441</b>\n" in t and "antes A$1.699" not in t
    assert "≈ USD 976 ≈ $1.539.590 (MEP $1.577)" in t
    assert "Compra Gamer</a> $2.244.000 (mismo chip)" in t
    assert "💰 Diferencia: ~$704.410 más barato en 🇦🇺 (31%)" in t
    # aduana: 50% de (976,28 − 500) USD × 1577 = $375.544; valija A$150 = $160.263 → traído $2.075.397
    assert ("🛃 Traído con valija extra (A$150) y aduana declarada (50% sobre lo que pase de USD 500): "
            "~$2.075.397 → ~$168.603 más barato") in t
    # 7,5% más barato traído: entre 0 y 10% es "casi igual"
    assert "🟰 Veredicto: casi igual" in t and "Ver en la tienda" in t


def test_aviso_ar_invertido():
    db = db_con(oferta("Gigabyte RTX 5070 Ti 16GB Windforce", 1441, pais="AU", tienda="centrecom"))
    m = Motor(CFG, AJ, db, COT, AHORA)
    o = oferta("Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", 1_700_000)
    t = m.texto_oferta("objetivo", o, None, None, 2_100_000)
    lineas = t.split("\n")
    assert lineas[0] == "🎯 <b>RTX 5070 Ti 16GB</b> — bajo tu objetivo en 🇦🇷"
    assert lineas[1].startswith("🇦🇷 ") and lineas[2] == "💵 Precio: <b>$1.700.000</b>"
    assert lineas[3] == "   ≈ USD 1.078 (MEP $1.577)"
    assert lineas[4].startswith("🇦🇺 Mejor precio:") and "≈ $1.539.590" in lineas[4]
    assert "más barato traído de 🇦🇺" not in t and "❌ Veredicto: no conviene traerlo: comprá en 🇦🇷" in t


def test_sin_par_en_el_otro_pais():
    t = lineas_comparacion(DB(":memory:"), COT, "AU", "cpu", "Ryzen 9 9900X", {}, 625, {})
    assert t[1] == "🇦🇷 Sin precio para comparar en las tiendas que leo"


# ------------------------------------------------------------------ cotizaciones

class _Resp:
    def __init__(self, j):
        self._j = j

    def json(self):
        return self._j


class _Cliente:
    def __init__(self, falla_mep=False):
        self.falla_mep = falla_mep

    def get(self, url):
        if "dolarapi" in url:
            if self.falla_mep:
                raise ConnectionError("caído")
            return _Resp({"venta": 1577})
        return _Resp({"rates": {"USD": 0.6775}})


def test_cotizacion_usa_la_guardada_si_falla_y_lo_aclara():
    db = DB(":memory:")
    c = cotizaciones.obtener(db, _Cliente())
    assert c.mep == 1577 and c.aud_usd == 0.6775 and c.nota_respaldo() is None
    c2 = cotizaciones.obtener(db, _Cliente(falla_mep=True))
    assert c2.mep == 1577 and "mep" in c2.respaldo
    assert c2.nota_respaldo().startswith("⚠️ Cotización guardada: MEP del ")
    assert "dolarapi.com no respondió" in c2.nota_respaldo()
    assert cotizaciones.obtener(DB(":memory:"), _Cliente(falla_mep=True)) is None  # nada guardado


# ------------------------------------------------------------------ resumen diario

def test_resumen_diario():
    alertas.NOMBRE_TIENDA.update({"compragamer": "Compra Gamer", "umart": "Umart"})
    db = db_con(oferta("Placa de Video MSI RTX 5070 Ti 16GB Ventus 3X", 2_244_000),
                oferta("Placa de Video ASUS RTX 5070 Ti 16GB TUF", 2_500_000),
                oferta("Gigabyte RTX 5070 Ti 16GB Windforce", 1441, pais="AU", tienda="umart"),
                oferta("AMD Ryzen 9 9900X", 625, pais="AU", tienda="umart", cat="cpu"))
    t = resumen.texto(db, CFG, COT, AHORA)
    bloques = t.split("\n\n")
    placa = next(b for b in bloques if "RTX 5070 Ti</b>" in b)
    assert "🇦🇷 $2.244.000 · " in placa and "🇦🇺 A$1.441 ≈ $1.539.590 · " in placa
    assert "→ 31% más barato en 🇦🇺 (con valija y aduana: 8% más barato traído)" in placa
    assert not any("9900X" in b for b in bloques)   # ya comprado: no va más en el resumen
    assert any("PC armada con RTX 5070 Ti" in b for b in bloques)


def test_resumen_toca_una_vez_desde_las_12():
    db = DB(":memory:")
    antes = datetime(2026, 11, 16, 14, 50, tzinfo=timezone.utc)   # 11:50 en Argentina
    despues = datetime(2026, 11, 16, 15, 10, tzinfo=timezone.utc)  # 12:10
    assert not resumen.toca(db, CFG, antes)
    assert resumen.toca(db, CFG, despues)
    resumen.marcar_enviado(db, despues)
    assert not resumen.toca(db, CFG, despues + timedelta(hours=3))
    assert resumen.toca(db, CFG, despues + timedelta(days=1))
