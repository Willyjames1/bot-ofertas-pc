// Formatos iguales a los de Python (cotizaciones.ars/usd y comparar.plata).

/** Python redondea al par en los empates exactos (f"{x:.0f}"); Math.round no. */
export function redondear(x) {
  const piso = Math.floor(x);
  const resto = x - piso;
  if (resto === 0.5) return piso % 2 === 0 ? piso : piso + 1;
  return resto > 0.5 ? piso + 1 : piso;
}

/** f"{x:,.0f}".replace(",", ".") */
export function miles(x) {
  const n = redondear(x);
  const s = String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return (n < 0 ? "-" : "") + s;
}

export const ars = (x) => "$" + miles(x);
export const usd = (x) => "USD " + miles(x);
export const plata = (x, moneda) => (x === null || x === undefined ? "—" : moneda === "AUD" ? "A$" + miles(x) : ars(x));

export function escapar(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

export function hace(min) {
  if (min < 2) return "recién";
  if (min < 60) return `hace ${Math.floor(min)} min`;
  if (min < 48 * 60) return `hace ${Math.floor(min / 60)} h`;
  return `hace ${Math.floor(min / 1440)} días`;
}

const HORA_AR = new Intl.DateTimeFormat("es-AR", {
  timeZone: "America/Argentina/Salta", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
});

export function horaArgentina(fecha) {
  const p = Object.fromEntries(HORA_AR.formatToParts(fecha).map((x) => [x.type, x.value]));
  return `${p.day}/${p.month} ${p.hour}:${p.minute}`;
}
