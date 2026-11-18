// Lo usa tests/test_worker.py: recibe por stdin {titulos, cuentas} y devuelve lo que entiende el
// normalizador del Worker y las líneas de la cuenta, para compararlos con Python.
import * as N from "../src/normalizador.js";
import { cuenta, lineasCuenta } from "../src/comparar.js";

let entrada = "";
for await (const parte of process.stdin) entrada += parte;
const { titulos = [], cuentas = [] } = JSON.parse(entrada);

const sinDijo = (x) => {
  if (!x) return null;
  const { dijo, ...resto } = x;
  return resto;
};

const salida = {
  titulos: titulos.map(([categoria, titulo]) => {
    const t = N.limpiar(titulo);
    const r = { t, chip: N.chipGpu(t), vram: N.vramDe(t) };
    if (categoria === "placas") r.placa = N.placa(t)?.modelo ?? null;
    if (categoria === "cpu") r.cpu = N.cpu(t)?.modelo ?? null;
    if (categoria === "ram") r.ram = sinDijo(N.ram(t));
    if (categoria === "ssd") r.ssd = N.ssd(t);
    if (categoria === "consulta_ssd") {
      const c = N.consultaSsd(t);
      if (c) delete c.palabras;
      r.consulta = c;
    }
    return r;
  }),
  cuentas: cuentas.map(({ cot, reglas, aud, ars, valija, pais }) =>
    lineasCuenta(cuenta(cot, reglas, aud, ars, valija), pais, valija, reglas)),
};
process.stdout.write(JSON.stringify(salida));
