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

// ---------------------------------------------------------------- cuántos resultados (r<N>)

function muchos() {
  const tiendas = Array.from({ length: 20 }, (_, i) => `Tienda con nombre largo número ${i}`);
  const p = [];
  for (let i = 0; i < 20; i++) {
    p.push([0, "AU", 1700 + i * 10, i, `https://au.example.com/productos/placa-de-video-${i}-con-un-link-largo`,
      `MSI Gaming Trio OC White Edition ${i}`, 30, "", 0, 0]);
    p.push([0, "AR", 2_300_000 + i * 10_000, i, `https://ar.example.com/productos/placa-de-video-${i}-con-un-link-largo`,
      `ASUS ROG Astral OC Edition ${i}`, 30, "transferencia", 0, 0]);
  }
  p.push([1, "AU", 199, 0, "https://u/r1", "Kingston", 20, "", 0, 0]);
  return preparar({
    v: 2, ts: "2026-11-18T15:00:00+00:00", cot: { mep: 1600, aud_usd: 0.67, nota: null },
    reglas: { franquicia_usd: 500, arancel: 0.5, valija_aud: 150, conviene_pct: 10 }, tiendas,
    modelos: [["RTX 5070 Ti 16GB", "placas", { chip: "RTX 5070 Ti", vram: 16 }],
      ["DDR5 32GB (2x16) 6000 CL30", "ram", { capacidad_gb: 32, modulos: 2, velocidad: 6000, cl: 30 }],
      ["Ryzen 7 9800X3D", "cpu", { marca: "AMD", nucleos: 8 }]],
    p, motivos: [""], ocultos: {}, posts: [], estado: "", filtros: "",
  });
}
const cuantos = (txt, bandera) => (txt.split(`${bandera} <b>`)[1]?.split("\n\n")[0].match(/^\d+\. /gm) || []).length;

test("r<N>: cuántos por país, en cualquier parte del texto, con país y marca", () => {
  const d = muchos();
  assert.equal(cuantos(buscar(d, "5070 ti", AHORA).texto, "🇦🇺"), 5);                 // sin r: 5
  const r10 = buscar(d, "5070 ti r10", AHORA).texto;
  assert.equal(cuantos(r10, "🇦🇺"), 10);
  assert.equal(cuantos(r10, "🇦🇷"), 10);
  assert.match(r10, /🔎 <b>RTX 5070 Ti 16GB<\/b>\n/);
  assert.doesNotMatch(r10, /Pediste/);
  assert.equal(cuantos(buscar(d, "r3 5070 ti au", AHORA).texto, "🇦🇺"), 3);
  assert.equal(cuantos(buscar(d, "msi R12 5070 ti au", AHORA).texto, "🇦🇺"), 12);
  const ar = buscar(d, "5070ti ar r7", AHORA).texto;
  assert.equal(cuantos(ar, "🇦🇷"), 7);
  assert.doesNotMatch(ar, /Australia/);
});

test("r<N>: hasta 16; si pedís más, 16 y lo avisa; r7 9800x3d es Ryzen", () => {
  const d = muchos();
  const r40 = buscar(d, "/buscar 5070 ti r40".replace("/buscar ", ""), AHORA);
  assert.equal(cuantos(r40.texto, "🇦🇺"), 16);
  assert.match(r40.texto, /ℹ️ Pediste r40: muestro hasta 16 por país \(lo máximo\)/);
  // los botones: 16 por país, en filas de 8, numerados como la lista
  assert.deepEqual(r40.botones.map((f) => f.length), [8, 8, 8, 8]);
  assert.equal(r40.botones[1][7].text, "❌ 🇦🇺 16");
  assert.equal(r40.botones[2][0].text, "❌ 🇦🇷 1");
  assert.equal(interpretar("r7 9800x3d", d.chips).f.modelo, "Ryzen 7 9800X3D");
  assert.equal(interpretar("r7 9800x3d", d.chips).cantidad, 5);
  assert.equal(interpretar("r16 ddr5 32gb au", d.chips).cantidad, 16);
  assert.equal(interpretar("r16 ddr5 32gb au", d.chips).cat, "ram");
  assert.equal(interpretar("r10 5070 ti", d.chips).cantidad, 10);
  assert.equal(interpretar("r5 7600x", d.chips).cantidad, 5);
  assert.equal(interpretar("r9 9950x3d au", d.chips).pedida, null);
  assert.equal(interpretar("r3 5070 ti", d.chips).cantidad, 3);
  assert.equal(interpretar("ddr5 32gb", d.chips).cantidad, 5);              // "ddr5" no es r5
  // sin resultados: la sugerencia mantiene la cantidad
  assert.match(buscar(d, "zotac 5070 ti r10", AHORA).texto, /No encontré «zotac 5070 ti»[\s\S]*\/buscar 5070 TI r10/i);
});

// ---------------------------------------------------------------- SSD

function datosSsd() {
  return preparar({
    v: 2, ts: "2026-11-18T15:00:00+00:00",
    cot: { mep: 1600, aud_usd: 0.67, nota: null },
    reglas: { franquicia_usd: 500, arancel: 0.5, valija_aud: 150, conviene_pct: 10 },
    tiendas: ["Mwave", "Umart", "Compra Gamer"],
    modelos: [
      ["SSD NVMe Gen4 2TB", "ssd", { capacidad_tb: 2, interfaz: "NVMe", gen: 4, formato: "2280" }],
      ["SSD NVMe Gen5 2TB", "ssd", { capacidad_tb: 2, interfaz: "NVMe", gen: 5, formato: "2280" }],
      ["SSD NVMe Gen4 2TB 2230", "ssd", { capacidad_tb: 2, interfaz: "NVMe", gen: 4, formato: "2230" }],
      ["SSD SATA 2TB", "ssd", { capacidad_tb: 2, interfaz: "SATA", formato: "2.5" }],
      ["SSD NVMe 2TB", "ssd", { capacidad_tb: 2, interfaz: "NVMe", formato: "2280" }],
      ["SSD NVMe Gen4 1TB", "ssd", { capacidad_tb: 1, interfaz: "NVMe", gen: 4, formato: "2280" }],
    ],
    p: [
      [0, "AU", 249, 0, "https://mw/990", "Samsung 990 Pro", 30, "", 0, 0, "a1", ["Samsung 990 Pro", 7450, 6900]],
      [0, "AU", 189, 1, "https://u/nv3", "Kingston NV3", 30, "", 0, 0, "a2", ["Kingston NV3", 6000, 5000]],
      [0, "AU", 179, 1, "https://u/sd", "Sandisk 2TB Optimus GX PRO 850X", 30, "", 0, 0, "a3", [null, null, null]],
      [1, "AU", 399, 1, "https://u/9100", "Samsung 9100 Pro", 30, "", 0, 0, "a4", ["Samsung 9100 Pro", 14700, 13400]],
      [1, "AU", 359, 0, "https://mw/t705", "Crucial T705", 30, "", 0, 1, "a5", ["Crucial T705", 14500, 12700]],
      [2, "AU", 150, 1, "https://u/p310", "Crucial P310", 30, "", 0, 0, "a6", ["Crucial P310", null, null]],
      [3, "AU", 120, 1, "https://u/mx", "Crucial MX500", 30, "", 0, 0, "a7", ["Crucial MX500", null, null]],
      [4, "AU", 110, 1, "https://u/gx", "Sandisk Optimus GX 7100", 30, "", 0, 0, "a8", [null, null, null]],
      [0, "AR", 420_000, 2, "https://cg/990", "Samsung 990 Pro", 30, "transferencia", 0, 0, "a9", ["Samsung 990 Pro", 7450, 6900]],
      [5, "AU", 129, 1, "https://u/990-1", "Samsung 990 Pro", 30, "", 0, 0, "b1", ["Samsung 990 Pro", 7450, 6900]],
    ],
    motivos: ["", "Mwave no informa stock"],
    posts: [["Samsung 990 Pro 2TB $239 @ Amazon AU", "https://oz/9", 30, 239, 60, "SAMSUNG 990 PRO 2TB $239 @ AMAZON AU"],
            ["Crucial P310 2TB 2230 $140 @ Amazon AU", "https://oz/8", 30, 140, 60, "CRUCIAL P310 2TB 2230 $140 @ AMAZON AU"]],
    estado: "", filtros: "",
  });
}

const sinLinks = (t) => t.replace(/<a href="[^"]*">([^<]*)<\/a>/g, "$1");

test("SSD: un renglón por producto, con Gen y velocidad; sin pedirlo, solo M.2 2280 NVMe Gen4/Gen5", () => {
  const t = sinLinks(responderBusqueda(datosSsd(), "ssd 2tb au r16", AHORA));
  assert.match(t, /SSD M\.2 NVMe Gen4\/Gen5 2TB/);
  assert.match(t, /\n1\. Sandisk 2TB Optimus GX PRO 850X · Gen4 · vel\. s\/d · Umart <b>A\$179<\/b> ≈ \$191\.888\n/);
  assert.match(t, /Samsung 990 Pro 2TB · Gen4 · 7\.450\/6\.900 MB\/s · Mwave <b>A\$249<\/b> ≈ \$266\.928/);
  assert.match(t, /Crucial T705 2TB · Gen5 · 14\.500\/12\.700 MB\/s · Mwave <b>A\$359<\/b> ≈ \$384\.848 · ⚠️ stock sin confirmar \(Mwave no informa stock\)/);
  for (const no of ["P310", "MX500", "GX 7100", "990 Pro 1TB"]) assert.ok(!t.includes(no), no);   // 2230, SATA, gen s/d, otra capacidad
});

test("SSD: por modelo (990pro = 990 PRO = Samsung 990 Pro NVMe), generación, capacidad y país", () => {
  for (const q of ["990 pro 2tb", "990pro 2tb", "Samsung 990 Pro NVMe 2tb", "samsung 990 PRO 2TB"]) {
    const t = sinLinks(responderBusqueda(datosSsd(), q, AHORA));
    assert.match(t, /🔎 <b>Samsung 990 Pro 2TB<\/b>/, q);
    assert.ok(!t.includes("NV3") && !t.includes("1TB ·"), q);
    assert.match(t, /Compra Gamer <b>\$420\.000<\/b> transferencia ≈ USD 262/, q);
  }
  const todos = sinLinks(responderBusqueda(datosSsd(), "990 pro au", AHORA));
  assert.match(todos, /Samsung 990 Pro 1TB/);
  assert.match(todos, /Samsung 990 Pro 2TB/);
  const g5 = sinLinks(responderBusqueda(datosSsd(), "ssd gen5 2tb au r10", AHORA));
  assert.match(g5, /SSD M\.2 NVMe Gen5 2TB<\/b> en 🇦🇺/);
  assert.ok(g5.includes("9100 Pro") && g5.includes("T705") && !g5.includes("990 Pro") && !g5.includes("Argentina"));
  // el post de OzBargain del mismo modelo, no el de 2230
  const post = responderBusqueda(datosSsd(), "990 pro 2tb", AHORA);
  assert.ok(post.includes("https://oz/9") && !post.includes("https://oz/8"));
});

test("SSD: vel ordena por lectura; sata, 2230 y gen3 solo si los pedís; sugerencia de otro modelo", () => {
  const v = sinLinks(responderBusqueda(datosSsd(), "ssd 2tb au vel r16", AHORA));
  const orden = [...v.matchAll(/\n\d+\. ([^·]+) ·/g)].map((m) => m[1].trim());
  // primero lo de stock confirmado (el T705 de Mwave no lo está): 9100 Pro, 990 Pro, NV3 y el que no dice
  assert.deepEqual(orden, ["Samsung 9100 Pro 2TB", "Samsung 990 Pro 2TB", "Kingston NV3 2TB", "Sandisk 2TB Optimus GX PRO 850X", "Crucial T705 2TB"]);
  assert.match(v, /los 5 más rápidos/);
  assert.match(sinLinks(responderBusqueda(datosSsd(), "ssd sata 2tb", AHORA)), /Crucial MX500 2TB · SATA · vel\. s\/d/);
  assert.match(sinLinks(responderBusqueda(datosSsd(), "ssd 2230 2tb", AHORA)), /Crucial P310 2TB · Gen4 · 2230 · vel\. s\/d/);
  const nada = responderBusqueda(datosSsd(), "t700 2tb au r3", AHORA);
  assert.match(nada, /No encontré «t700 2tb au»/);
  assert.match(nada, /Otro SSD Gen5 de 2TB: \/buscar ssd gen5 2tb au r3/);
});
