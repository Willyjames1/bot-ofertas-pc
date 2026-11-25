"""Resumen especial de Black Friday (config.yaml → black_friday.resumen): lo que te falta comprar,
con el precio real de hoy contra hace 7 días, hace 30 días y el mínimo de 75 días de HardGamers
(en USD MEP en 🇦🇷), las cuotas y promos de la tienda, un veredicto (comprar ya / esperar / inflado)
y la cuenta de lo que puede traer tu hermano: la franquicia de USD 500 es UNA para todo lo que traiga,
así que la aduana se calcula sobre el total."""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from html import escape

from . import compras, cuotas as CU, historial
from .comparar import HORAS_OTRO_PAIS, valija_de
from .config import TZ_AR
from .cotizaciones import ARANCEL, ars, usd

log = logging.getLogger("bot.black_friday")
LIMITE_MENSAJE = 3800
CERCA_DEL_MINIMO = 0.02        # a 2% o menos del mínimo de 75 días = "comprar ya"
SLOT_VALE_HORAS = 3            # un horario que se pasó hace más de 3 h ya no se manda
CANDIDATAS = 8                 # de las más baratas por transferencia, se calcula el precio real de estas


def _plata_au(x: float) -> str:
    return "A$" + f"{x:,.0f}".replace(",", ".")


@dataclass
class Mejor:
    pais: str
    fila: dict
    real: float                  # 🇦🇷: min(transferencia, cuotas a contado); 🇦🇺: el precio
    pagos: CU.Pagos | None
    ref: historial.Referencias
    inflado: str | None

    @property
    def usd(self) -> float | None:
        return self.ref.hoy.usd


@dataclass
class Veredicto:
    clave: str                   # comprar | esperar | inflado
    motivo: str

    def texto(self) -> str:
        return {"comprar": "✅ Comprar ya", "esperar": "⏳ Esperar", "inflado": "⚠️ Inflado"}[self.clave] + \
            f" — {self.motivo}"


def mejor(motor, item: compras.Item, pais: str) -> Mejor | None:
    """La publicación con el precio real más bajo hoy (vista en las últimas 48 h, con stock)."""
    desde = motor.inicio - timedelta(hours=HORAS_OTRO_PAIS)
    filas = [r for r in motor.db.vigentes(pais, item.categoria, desde, motor.inicio) if item.cumple(r)]
    if not filas:
        return None
    confirmadas = [r for r in filas if r.get("stock_ok")] or filas
    candidatas = sorted(confirmadas, key=lambda r: r["precio"])[:CANDIDATAS]
    if pais == "AR":
        con_pagos = [(r, motor.pagos(r)) for r in candidatas]
        fila, pg = min(con_pagos, key=lambda x: x[1].real)
        real = pg.real
    else:
        fila, pg, real = candidatas[0], None, candidatas[0]["precio"]
    ref = historial.referencias(motor.db, pais, item.categoria, item.cumple, real, motor.inicio)
    infl = historial.inflado(motor.db, fila, motor.inicio, motor.anclaje) if fila.get("id") else None
    return Mejor(pais, fila, real, pg, ref, infl)


def veredicto(item: compras.Item, m: Mejor) -> Veredicto:
    if m.inflado:
        return Veredicto("inflado", "lo subieron antes de \"bajarlo\": no es una oferta de verdad")
    ref = m.ref
    hoy = ref.hoy.valor()
    obj = item.objetivo_en("USD" if m.pais == "AR" else "AUD")
    fmt = usd if m.pais == "AR" else _plata_au
    if obj and hoy <= obj:
        return Veredicto("comprar", f"{(1 - hoy / obj) * 100:.0f}% abajo de tu objetivo ({fmt(obj)})")
    piso = ref.piso
    # con poco historial propio (y sin HardGamers) no son 75 días: se dice desde cuándo
    largo = ref.minimo_fuente == "HardGamers" or (ref.desde_propio and (ref.hoy.fecha or date.today()) -
                                                 ref.desde_propio >= timedelta(days=60))
    cuanto = "de 75 días" if largo else (f"desde el {ref.desde_propio:%d/%m}" if ref.desde_propio else "")
    if piso and hoy <= piso.valor() * (1 + CERCA_DEL_MINIMO):
        return Veredicto("comprar", f"en el mínimo {cuanto}".strip())
    if ref.bajo_mediana_pct is not None and ref.bajo_mediana_pct >= item.umbral:
        return Veredicto("comprar", f"{ref.bajo_mediana_pct:.0f}% abajo de la mediana de 30 días")
    partes = []
    if obj:
        partes.append(f"{(hoy / obj - 1) * 100:.0f}% arriba de tu objetivo ({fmt(obj)})")
    if piso:
        partes.append(f"{(hoy / piso.valor() - 1) * 100:.0f}% arriba del mínimo {cuanto}".strip())
    return Veredicto("esperar", " · ".join(partes) or "no está más barato que lo normal")


def _bloque_pais(motor, item: compras.Item, m: Mejor | None, pais: str) -> list[str]:
    from .alertas import BANDERA, NOMBRE_TIENDA
    if m is None:
        return [f"{BANDERA[pais]} sin precio hoy en las tiendas que leo"]
    f = m.fila
    tienda = NOMBRE_TIENDA.get(f["tienda"], f["tienda"])
    nombre = escape((f.get("variante") or f.get("titulo") or "")[:55])
    lineas = [f'{BANDERA[pais]} {nombre} @ <a href="{escape(f["url"])}">{escape(tienda)}</a>'
              + ("" if f.get("stock_ok", True) else " (stock sin confirmar)")]
    if m.pagos:
        lineas += CU.lineas_pagos(m.pagos, f.get("tipo_precio") or "transferencia")
    elif motor.cot:
        lineas.append(f"💵 <b>{_plata_au(m.real)}</b> ≈ {usd(motor.cot.aud_a_usd(m.real))}")
    if m.inflado:
        lineas.append(escape(m.inflado))
    lineas += historial.lineas_referencias(m.ref)
    lineas.append(veredicto(item, m).texto())
    return lineas


# ------------------------------------------------------------------ lo que trae tu hermano

@dataclass
class Canasta:
    traer: list[str]             # nombres de lo que conviene que traiga
    usd_total: float
    aduana_ars: float
    valija_ars: float
    total_traido_ars: float      # lo que trae (en pesos) + aduana + valija
    total_ar_ars: float          # lo mismo comprado en 🇦🇷 (precio real)
    total_ars: float             # todo lo de la canasta: lo traído + lo que se compra acá


def canasta(motor, mejores: dict[str, tuple[Mejor | None, Mejor | None]]) -> tuple[Canasta | None, list[Canasta]]:
    """La mejor combinación de qué traer (prueba todas): aduana 50% sobre lo que pase de USD 500 del
    TOTAL, y una valija extra si trae algo. mejores: {nombre: (mejor 🇦🇷, mejor 🇦🇺)}."""
    cot = motor.cot
    h = compras.hermano(motor.cfg)
    franquicia = h["franquicia_usd"]
    comparables = {n: (ar, au) for n, (ar, au) in mejores.items() if ar and au}
    if not cot or not comparables:
        return None, []
    valija = cot.aud_a_ars(valija_de(motor.cfg))
    opciones = []
    nombres = list(comparables)
    for k in range(len(nombres) + 1):
        for traer in itertools.combinations(nombres, k):
            u = sum(cot.aud_a_usd(comparables[n][1].real) for n in traer)
            aduana = ARANCEL * max(0.0, u - franquicia) * cot.mep
            traido = sum(cot.usd_a_ars(cot.aud_a_usd(comparables[n][1].real)) for n in traer)
            traido += aduana + (valija if traer else 0)
            en_ar = sum(comparables[n][0].real for n in traer)
            resto = sum(comparables[n][0].real for n in nombres if n not in traer)
            opciones.append(Canasta(list(traer), u, aduana, valija if traer else 0, traido, en_ar, traido + resto))
    mejor_op = min(opciones, key=lambda c: (c.total_ars, len(c.traer)))
    todo = next(c for c in opciones if len(c.traer) == len(nombres))
    return mejor_op, [todo]


def lineas_canasta(motor, mejores: dict[str, tuple[Mejor | None, Mejor | None]]) -> list[str]:
    h = compras.hermano(motor.cfg)
    mejor_op, otras = canasta(motor, mejores)
    todo = otras[0] if otras else None
    lineas = [f"🧳 <b>Lo que puede traer tu hermano</b> (franquicia USD {h['franquicia_usd']:.0f} para todo junto, "
              f"{ARANCEL * 100:.0f}% sobre lo que pase)"]
    if mejor_op is None:
        lineas.append("   Sin precios de los dos países para comparar")
        return lineas
    sin_par = [n for n, (ar, au) in mejores.items() if not (ar and au)]

    def resumen(c: Canasta) -> str:
        return (f"USD {c.usd_total:,.0f}".replace(",", ".") + f" → aduana {ars(c.aduana_ars)}"
                + (f" + valija {ars(c.valija_ars)}" if c.valija_ars else "")
                + f" = {ars(c.total_traido_ars)} vs {ars(c.total_ar_ars)} en 🇦🇷")
    if todo and todo.traer:
        lineas.append(f"• Si trae todo ({', '.join(todo.traer)}): {resumen(todo)}")
    if mejor_op.traer:
        ahorro = mejor_op.total_ar_ars - mejor_op.total_traido_ars
        lineas.append(f"✅ Conviene que traiga: <b>{', '.join(mejor_op.traer)}</b> — {resumen(mejor_op)} "
                      f"(ahorrás ~{ars(ahorro)})")
        aca = [n for n in mejores if n not in mejor_op.traer and n not in sin_par]
        if aca:
            lineas.append(f"🇦🇷 Comprar acá: {', '.join(aca)}")
    else:
        lineas.append("🇦🇷 Hoy no conviene que traiga nada: sale igual o más barato comprarlo acá")
    if sin_par:
        lineas.append(f"   (sin precio en los dos países: {', '.join(sin_par)})")
    if h.get("viaje"):
        lineas.append(f"   Viaja: {h['viaje']}")
    return lineas


# ------------------------------------------------------------------ el mensaje

def textos(motor) -> list[str]:
    """El resumen en uno o más mensajes (cortados entre bloques, nunca en el medio de un tag)."""
    cfg, cot = motor.cfg, motor.cot
    local = motor.inicio.astimezone(TZ_AR)
    cab = f"🛍️ <b>Black Friday — lo que te falta comprar</b> · {local:%d/%m %H:%M}"
    if cot:
        aud = f"{cot.aud_usd:.3f}".replace(".", ",")
        cab += f"\nMEP {ars(cot.mep)} · A$1 = USD {aud}"
    cab += f"\nCuotas a contado con la tasa de plazo fijo ({motor.tasa * 100:.1f}% por mes)".replace(".", ",")
    if comprado := (cfg.get("compras") or {}).get("comprado"):
        cab += "\nYa comprado: " + ", ".join(str(v) for v in comprado.values())
    bloques = [cab]
    mejores: dict[str, tuple[Mejor | None, Mejor | None]] = {}
    trae = set(compras.hermano(cfg)["trae"])
    cuenta = {"comprar": [], "esperar": [], "inflado": []}
    for it in compras.items(cfg):
        icono = compras.ICONO.get(it.categoria, "•")
        objetivo = []
        if it.objetivo.get("USD"):
            objetivo.append(f"🇦🇷 {usd(float(it.objetivo['USD']))}")
        if it.objetivo.get("AUD"):
            objetivo.append(f"🇦🇺 {_plata_au(float(it.objetivo['AUD']))}")
        lineas = [f"{icono} <b>{escape(it.nombre)}</b>" + (f" · objetivo {' / '.join(objetivo)}" if objetivo else "")]
        if it.categoria in ("teclados", "mouse") and not it.filtro.get("modelos"):
            lineas.append("   Decime qué modelo querés (o un presupuesto) y lo sigo")
            bloques.append("\n".join(lineas))
            continue
        ar = mejor(motor, it, "AR") if "AR" in it.paises else None
        au = mejor(motor, it, "AU") if "AU" in it.paises else None
        lineas += _bloque_pais(motor, it, ar, "AR")
        if "AU" in it.paises:
            lineas += _bloque_pais(motor, it, au, "AU")
        for m in (ar, au):
            if m:
                cuenta[veredicto(it, m).clave].append(f"{it.nombre} {'🇦🇷' if m.pais == 'AR' else '🇦🇺'}")
        if it.categoria in trae:
            mejores[it.nombre] = (ar, au)
        bloques.append("\n".join(lineas))
    if mejores:
        bloques.append("\n".join(lineas_canasta(motor, mejores)))
    final = []
    if cuenta["comprar"]:
        final.append("✅ Comprar ya: " + ", ".join(cuenta["comprar"]))
    if cuenta["inflado"]:
        final.append("⚠️ Inflado: " + ", ".join(cuenta["inflado"]))
    if cuenta["esperar"]:
        final.append("⏳ Esperar: " + ", ".join(cuenta["esperar"]))
    if final:
        bloques.append("\n".join(final))
    if cot and (nota := cot.nota_respaldo()):
        bloques.append(nota)
    return _juntar(bloques)


def _juntar(bloques: list[str]) -> list[str]:
    mensajes, actual = [], ""
    for b in bloques:
        if actual and len(actual) + 2 + len(b) > LIMITE_MENSAJE:
            mensajes.append(actual)
            actual = b
        else:
            actual = f"{actual}\n\n{b}" if actual else b
    if actual:
        mensajes.append(actual)
    return mensajes


# ------------------------------------------------------------------ cuándo

def horarios(cfg: dict) -> tuple[list[date], list[time]]:
    r = (cfg.get("black_friday") or {}).get("resumen") or {}
    dias = [d if isinstance(d, date) else date.fromisoformat(str(d)) for d in r.get("dias") or []]
    horas = [time.fromisoformat(str(h)) for h in r.get("horas") or []]
    return dias, horas


def toca(db, cfg: dict, ahora: datetime) -> str | None:
    """El horario que corresponde mandar ahora ('2026-11-27 13:00'), o None. Si se pasaron varios
    (el bot no corrió), se manda una sola vez, el último; uno de hace más de 3 h ya no."""
    if not ((cfg.get("black_friday") or {}).get("resumen") or {}).get("activo", True):
        return None
    dias, horas = horarios(cfg)
    local = ahora.astimezone(TZ_AR)
    if local.date() not in dias:
        return None
    pasados = [h for h in horas if h <= local.time()]
    if not pasados:
        return None
    h = max(pasados)
    slot = f"{local.date()} {h:%H:%M}"
    inicio_slot = datetime.combine(local.date(), h, TZ_AR)
    if local - inicio_slot > timedelta(hours=SLOT_VALE_HORAS) or db.get("bf_resumen") and db.get("bf_resumen") >= slot:
        return None
    return slot


def marcar_enviado(db, slot: str):
    db.set("bf_resumen", slot)
