import { test } from "node:test";
import assert from "node:assert/strict";
import { buscar, interpretar, preparar, responderBusqueda, MOSTRAR } from "../src/buscar.js";
import { claveUrl } from "../src/sha1.js";

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
  assert.match(au, /⚠️ stock sin confirmar \(staticICE no informa stock\)/);
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

// el formato nuevo (v2): motivo por fila (0 = stock confirmado) y los "❌ Sin stock" ya incorporados
function datosV2(ocultos = {}) {
  return preparar({
    v: 2, ts: "2026-11-18T15:00:00+00:00",
    cot: { mep: 1600, aud_usd: 0.67, nota: null },
    reglas: { franquicia_usd: 500, arancel: 0.5, valija_aud: 150, conviene_pct: 10 },
    tiendas: ["Umart", "Mwave Australia", "Scorptec"],
    modelos: [["RTX 5070 Ti 16GB", "placas", { chip: "RTX 5070 Ti", vram: 16 }]],
    p: [
      [0, "AU", 1599, 2, "https://s/1", "Gigabyte", 30, "", 1, 1],
      [0, "AU", 1699, 1, "https://m/1", "MSI", 30, "", 1, 0],
      [0, "AU", 1799, 0, "https://u/1", "ASUS", 30, "", 0, 0],
      [0, "AU", 1749, 1, "https://m/2", "Zotac", 30, "", 1, 2],
    ],
    motivos: ["", "la tienda no deja verificar el stock", "no pude leer staticICE hace 9 h"],
    ocultos, posts: [], estado: "", filtros: "",
  });
}

test("stock: primero lo confirmado (por precio) y al final lo sin confirmar, con el motivo", () => {
  const txt = responderBusqueda(datosV2(), "5070 ti au", AHORA);
  const orden = [...txt.matchAll(/^\d\. <b>A\$([\d.]+)<\/b>/gm)].map((m) => m[1]);
  assert.deepEqual(orden, ["1.699", "1.799", "1.599", "1.749"]);
  assert.match(txt, /los 4 más baratos \(primero los de stock confirmado\)/);
  assert.match(txt, /Gigabyte · hace 42 min · ⚠️ stock sin confirmar \(la tienda no deja verificar el stock\)/);
  assert.match(txt, /Zotac · hace 42 min · ⚠️ stock sin confirmar \(no pude leer staticICE hace 9 h\)/);
  assert.doesNotMatch(txt, /MSI · hace 42 min · ⚠️/);
});

test("❌ Sin stock: un botón por resultado y lo marcado no aparece hasta que la corrida lo destape", () => {
  const r = buscar(datosV2(), "5070 ti au", AHORA);
  assert.deepEqual(r.botones[0].map((b) => b.text), ["❌ 🇦🇺 1", "❌ 🇦🇺 2", "❌ 🇦🇺 3", "❌ 🇦🇺 4"]);
  assert.equal(r.botones[0][0].callback_data, `x:${claveUrl("https://m/1")}`);
  assert.ok(r.botones.flat().every((b) => b.callback_data.length <= 64));
  const h = claveUrl("https://m/1");
  // lo tocaste después de la corrida: oculto
  const marcas = { [h]: "2026-11-18T15:05:00.000Z" };
  const oculto = buscar(datosV2(), "5070 ti au", AHORA, marcas);
  assert.doesNotMatch(oculto.texto, /https:\/\/m\/1"/);
  assert.equal(oculto.botones[0].length, 3);
  // la corrida ya lo incorporó (misma fecha) y lo volvió a mostrar porque la tienda lo tiene de nuevo
  const destapado = buscar(datosV2({ [h]: "2026-11-18T15:05:00+00:00" }), "5070 ti au", AHORA, marcas);
  assert.match(destapado.texto, /https:\/\/m\/1"/);
  // lo volviste a tocar después: oculto otra vez
  const otraVez = buscar(datosV2({ [h]: "2026-11-18T15:05:00+00:00" }), "5070 ti au", AHORA,
    { [h]: "2026-11-18T16:00:00.000Z" });
  assert.doesNotMatch(otraVez.texto, /https:\/\/m\/1"/);
});
