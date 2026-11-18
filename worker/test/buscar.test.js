import { test } from "node:test";
import assert from "node:assert/strict";
import { interpretar, preparar, responderBusqueda, MOSTRAR } from "../src/buscar.js";

const TS = Date.parse("2026-11-18T15:00:00Z");
const AHORA = TS + 12 * 60_000;

// un JSON como el que exporta bot/exportar.py
function datos() {
  return preparar({
    v: 1, ts: "2026-11-18T15:00:00+00:00",
    cot: { mep: 1600, aud_usd: 0.67, nota: null },
    reglas: { franquicia_usd: 500, arancel: 0.5, valija_aud: 150, conviene_pct: 10 },
    tiendas: ["Venex", "WIZ TECH", "Umart", "Mwave Australia"],
    modelos: [
      ["RTX 5070 Ti 16GB", "placas", { chip: "RTX 5070 Ti", vram: 16 }],
      ["DDR5 32GB (2x16) 6000 CL30", "ram", { capacidad_gb: 32, modulos: 2, velocidad: 6000, cl: 30 }],
      ["DDR5 32GB (1x32) 5600", "ram", { capacidad_gb: 32, modulos: 1, velocidad: 5600 }],
      ["DDR5 64GB (2x32) 6000 CL30", "ram", { capacidad_gb: 64, modulos: 2, velocidad: 6000, cl: 30 }],
      ["Ryzen 7 9800X3D", "cpu", { marca: "AMD", nucleos: 8 }],
    ],
    p: [
      [0, "AR", 2_269_000, 1, "https://hg/1", "MSI Shadow 3X OC", 30, "contado", 0],
      [0, "AR", 2_319_990, 0, "https://v/1", "Gigabyte Eagle OC", 30, "contado", 0],
      ...[1, 2, 3, 4, 5, 6].map((i) => [0, "AU", 1799 + i * 10, 3, `https://m/${i}`, i === 2 ? "ASUS Prime" : "MSI Ventus", 40, "", 1]),
      [1, "AU", 199, 2, "https://u/1", "Kingston", 20, "", 0],
      [2, "AU", 189, 2, "https://u/2", "Crucial", 20, "", 0],
      [3, "AU", 379, 2, "https://u/3", "Kingston", 20, "", 0],
      [1, "AR", 320_000, 0, "https://v/2", "Kingston", 20, "contado", 0],
      [4, "AU", 645, 2, "https://u/4", "Box", 20, "", 0],
    ],
    posts: [["Gigabyte RTX 5070 Ti Eagle $1549 @ Scorptec", "https://oz/1", 45, 1549, 90]],
    estado: "📊 <b>Tiendas, últimas 24 h</b>",
    filtros: "⚙️ <b>Filtros activos</b>",
  });
}

test("5070ti, rtx 5070 ti y 5070 Ti 16GB son lo mismo", () => {
  const chips = datos().chips;
  for (const q of ["5070ti", "rtx 5070 ti", "5070 Ti 16GB", "RTX5070TI", "rtx 5070ti"]) {
    const r = interpretar(q, chips);
    assert.equal(r.cat, "placas", q);
    assert.equal(r.f.chip, "RTX 5070 Ti", q);
  }
  assert.equal(interpretar("5070 Ti 16GB", chips).f.vram, 16);
  assert.equal(interpretar("5070 ti", chips).f.vram, null);
});

test("país, RAM, CPU, SSD, AMD y PCs", () => {
  const chips = datos().chips;
  const ram = interpretar("ddr5 32gb au", chips);
  assert.deepEqual([ram.cat, ram.pais, ram.f.capacidad_gb, ram.f.dijo.modulos, ram.f.dijo.velocidad], ["ram", "AU", 32, false, false]);
  const kit = interpretar("ram 2x16 6000 ar", chips);
  assert.deepEqual([kit.cat, kit.pais, kit.f.capacidad_gb, kit.f.modulos, kit.f.velocidad], ["ram", "AR", 32, 2, 6000]);
  assert.equal(interpretar("9800x3d", chips).f.modelo, "Ryzen 7 9800X3D");
  assert.equal(interpretar("ryzen 7 9800x3d", chips).f.modelo, "Ryzen 7 9800X3D");
  assert.equal(interpretar("9070 xt", chips).f.chip, "RX 9070 XT");
  const s = interpretar("ssd 2tb gen4", chips);
  assert.deepEqual([s.cat, s.f.capacidad_tb, s.f.gen], ["ssd", 2, 4]);
  const pc = interpretar("pc 5070 ti 🇦🇺", chips);
  assert.deepEqual([pc.cat, pc.f.chip, pc.pais], ["pcs", "RTX 5070 Ti", "AU"]);
  assert.deepEqual(interpretar("asus 5070 ti", chips).extra, ["ASUS"]);
});

test("los dos países: 5 más baratos por país y la cuenta de los avisos", () => {
  const txt = responderBusqueda(datos(), "5070 ti", AHORA);
  assert.match(txt, /🔎 <b>RTX 5070 Ti 16GB<\/b>/);
  const au = txt.split("🇦🇺 <b>Australia</b>")[1].split("🇦🇷")[0];
  assert.equal((au.match(/^\d\. /gm) || []).length, MOSTRAR);       // 6 en el JSON, se muestran 5
  assert.match(au, /1\. <b>A\$1\.809<\/b> ≈ USD 1\.212 ≈ \$1\.939\.248 · <a href="https:\/\/m\/1">Mwave Australia<\/a>/);
  assert.match(au, /staticICE: confirmá stock/);
  assert.match(au, /hace 52 min/);                                   // 40 min antes de exportar + 12 desde entonces
  assert.match(txt, /1\. <b>\$2\.269\.000<\/b> contado ≈ USD 1\.418 · <a href="https:\/\/hg\/1">WIZ TECH<\/a>/);
  assert.match(txt, /⚖️ <b>Traerlo de 🇦🇺<\/b>/);
  assert.match(txt, /💰 Diferencia: ~\$329\.752 más barato en 🇦🇺 \(15%\)/);
  assert.match(txt, /🛃 Traído con valija extra \(A\$150\) y aduana declarada/);
  assert.match(txt, /Veredicto: no conviene traerlo: comprá en 🇦🇷/);
  assert.match(txt, /📰 <b>En OzBargain<\/b>\n• <a href="https:\/\/oz\/1">/);
  assert.match(txt, /🕒 Precios de la corrida de las 18\/11 12:00 \(hace 12 min\) · MEP \$1\.600 · A\$1 = USD 0,670/);
});

test("un país solo: sin cuenta; varios modelos: dice cuál es cada uno", () => {
  const txt = responderBusqueda(datos(), "ddr5 32gb au", AHORA);
  assert.match(txt, /🔎 <b>RAM DDR5 32GB<\/b> en 🇦🇺/);
  assert.doesNotMatch(txt, /Argentina|Veredicto/);
  assert.match(txt, /1\. <b>A\$189<\/b>.*\n   DDR5 32GB \(1x32\) 5600 · Crucial/);
  assert.match(txt, /2\. <b>A\$199<\/b>.*\n   DDR5 32GB \(2x16\) 6000 CL30 · Kingston/);
  assert.doesNotMatch(txt, /64GB/);
});

test("filtro por marca y sugerencias cuando no hay nada", () => {
  const d = datos();
  const asus = responderBusqueda(d, "asus 5070 ti au", AHORA);
  assert.equal((asus.match(/^\d\. /gm) || []).length, 1);
  const sinMarca = responderBusqueda(d, "zotac 5070 ti", AHORA);
  assert.match(sinMarca, /No encontré «zotac 5070 ti»/);
  assert.match(sinMarca, /Sin «zotac» sí hay: \/buscar 5070 TI/i);
  const vram = responderBusqueda(d, "rtx 5070 ti 12gb", AHORA);
  assert.match(vram, /¿Quisiste decir <b>RTX 5070 Ti 16GB<\/b>\? → \/buscar rtx 5070 ti 16gb/);
  const cpu = responderBusqueda(d, "9800x3d ar", AHORA);
  assert.match(cpu, /No encontré «9800x3d ar» en 🇦🇷/);
  const ram = responderBusqueda(d, "ddr5 48gb", AHORA);
  assert.match(ram, /¿Quisiste decir <b>DDR5 32GB/);
  assert.match(responderBusqueda(d, "", AHORA), /Decime qué buscás/);
});

test("datos viejos: avisa", () => {
  assert.match(responderBusqueda(datos(), "5070 ti", TS + 3 * 3600_000), /Hace más de 1 h que no hay una corrida nueva/);
});
