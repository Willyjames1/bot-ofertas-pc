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

// Argentina está en UTC−3 fijo (sin horario de verano desde 2009). Con cuentas y no con
// Intl.DateTimeFormat: armarlo con zona horaria carga la tabla de zonas y costaba ~13 ms de CPU
// en el primer pedido (el plan gratis da 10).
const OFFSET_AR_MS = -3 * 3600_000;
const dos = (n) => String(n).padStart(2, "0");

export function horaArgentina(fecha) {
  const d = new Date(fecha.getTime() + OFFSET_AR_MS);
  return `${dos(d.getUTCDate())}/${dos(d.getUTCMonth() + 1)} ${dos(d.getUTCHours())}:${dos(d.getUTCMinutes())}`;
}
