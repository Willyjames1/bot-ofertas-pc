// Prueba a mano, sin Telegram: node scripts/cli.mjs <precios.json> "/buscar 5070 ti"
import { readFileSync } from "node:fs";
import { preparar } from "../src/buscar.js";
import { responder } from "../src/index.js";

const [archivo, ...texto] = process.argv.slice(2);
const datos = preparar(JSON.parse(readFileSync(archivo, "utf-8")));
console.log(await responder(texto.join(" "), async () => datos));
