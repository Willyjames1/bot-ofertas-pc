// La cuenta de los avisos (bot/comparar.py: cuenta, veredicto y lineas_cuenta), con las reglas que
// exporta Python en el JSON (aduana, franquicia, valija, umbral). tests/test_worker.py compara el
// texto de las dos versiones con los mismos números.
import { ars, plata, redondear } from "./formato.js";

export function cuenta(cot, reglas, precioAud, precioArs, valijaAud = 0) {
  const u = precioAud * cot.aud_usd;
  const auArs = u * cot.mep;
  const aduana = reglas.arancel * Math.max(0, u - reglas.franquicia_usd) * cot.mep;
  const valija = valijaAud * cot.aud_usd * cot.mep;
  const c = { au_aud: precioAud, au_usd: u, au_ars: auArs, ar_ars: precioArs, aduana_ars: aduana,
              valija_ars: valija, au_con_aduana: auArs + aduana + valija };
  c.diferencia = c.ar_ars - c.au_ars;
  c.diferencia_pct = (c.diferencia / Math.max(c.ar_ars, c.au_ars)) * 100;
  c.ahorro_con_aduana = c.ar_ars - c.au_con_aduana;
  c.ahorro_con_aduana_pct = (c.ahorro_con_aduana / c.ar_ars) * 100;
  return c;
}

export function veredicto(c, reglas) {
  const p = c.ahorro_con_aduana_pct;
  if (p > reglas.conviene_pct) return "conviene";
  if (p >= 0) return "casi igual";
  return "no conviene";
}

const ICONO = { conviene: "✅", "casi igual": "🟰", "no conviene": "❌" };

/** Diferencia, traerlo (valija + aduana) y veredicto: las mismas líneas que los avisos. */
export function lineasCuenta(c, pais, valija, reglas) {
  const lineas = [];
  if (c.diferencia >= 0) {
    lineas.push(`💰 Diferencia: ~${ars(c.diferencia)} más barato en 🇦🇺 (${redondear(c.diferencia_pct)}%)`);
  } else {
    lineas.push(`💰 Diferencia: ~${ars(-c.diferencia)} más barato en 🇦🇷 (${redondear(-c.diferencia_pct)}%)`);
  }
  const franq = reglas.franquicia_usd;
  const regla = `${redondear(reglas.arancel * 100)}% sobre lo que pase de USD ${franq}`;
  const sentido = c.ahorro_con_aduana >= 0 ? "más barato" : "más caro";
  const quien = pais === "AU" ? "" : " traído de 🇦🇺";
  const resultado = `~${ars(c.au_con_aduana)} → ~${ars(Math.abs(c.ahorro_con_aduana))} ${sentido}${quien}`;
  const conValija = valija ? `valija extra (${plata(valija, "AUD")})` : "";
  let aduana;
  if (c.aduana_ars <= 0 && !valija) aduana = `🛃 Aduana: no paga (vale menos de USD ${franq})`;
  else if (c.aduana_ars <= 0) aduana = `🧳 Traído con ${conValija}, sin aduana (vale menos de USD ${franq}): ${resultado}`;
  else if (valija) aduana = `🛃 Traído con ${conValija} y aduana declarada (${regla}): ${resultado}`;
  else aduana = `🛃 Si se declara en aduana (${regla}): ${resultado}`;
  lineas.push(aduana);
  const v = veredicto(c, reglas);
  const extra = pais === "AR" ? { conviene: " traerlo de 🇦🇺", "casi igual": "", "no conviene": " traerlo: comprá en 🇦🇷" }[v] : "";
  lineas.push(`${ICONO[v]} Veredicto: ${v}${extra}`);
  return lineas;
}
