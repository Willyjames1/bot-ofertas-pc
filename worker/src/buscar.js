// /buscar: entiende el texto con el normalizador de los avisos, junta los precios del JSON que
// exporta el bot y arma la respuesta (los 5 más baratos por país y, si son los dos, la cuenta).
import * as N from "./normalizador.js";
import { VRAM_POR_DEFECTO } from "./normalizador_gen.js";
import { cuenta, lineasCuenta } from "./comparar.js";
import { ars, escapar, hace, horaArgentina, plata, usd } from "./formato.js";
import { claveUrl } from "./sha1.js";

export const MOSTRAR = 5;
const BANDERA = { AU: "🇦🇺", AR: "🇦🇷" };
const NOMBRE_PAIS = { AU: "Australia", AR: "Argentina" };
const PAISES = ["AU", "AR"];
// palabras que describen el producto pero que ya entendió el normalizador (o que no filtran nada)
const NO_FILTRA = new Set(["RTX", "RX", "GTX", "TI", "SUPER", "XT", "XTX", "GRE", "GB", "TB", "DDR5", "DDR", "RAM",
  "MEMORIA", "MEMORIAS", "SSD", "NVME", "M.2", "M2", "SATA", "PCIE", "GEN", "PC", "PCS", "DE", "LA", "EL", "Y", "CON",
  "EN", "PARA", "KIT", "DUAL", "X", "RYZEN", "CORE", "ULTRA", "INTEL", "AMD", "NVIDIA", "PLACA", "PLACAS", "VIDEO",
  "GPU", "CPU", "PROCESADOR", "MICRO", "MICROPROCESADOR", "DESKTOP", "COMPUTADORA", "ARMADA", "GAMER", "GAMING",
  "PREBUILT", "MHZ", "BOX", "TRAY", "DISCO", "SOLIDO", "PLUS", "OMEN", "VICTUS"]);

/** Arma los índices una vez por cada JSON (el Worker lo guarda en memoria entre pedidos). */
export function preparar(d) {
  const modelos = d.modelos.map(([nombre, cat, datos], i) => ({
    i, nombre, cat, datos, clave: N.limpiar(nombre), filas: { AR: [], AU: [] },
  }));
  for (const [mi, pais, precio, ti, url, detalle, haceMin, tipo, staticice, iMotivo] of d.p) {
    const m = modelos[mi];
    const busca = `${m.clave} ${N.limpiar(detalle)} ${N.limpiar(d.tiendas[ti])}`;   // para el texto libre y las marcas
    // motivo vacío = stock confirmado (JSON viejo, sin motivos: lo de staticICE queda sin confirmar)
    const motivo = iMotivo == null ? (staticice ? "staticICE no informa stock" : "") : (d.motivos?.[iMotivo] ?? "");
    m.filas[pais].push({ m, pais, precio, tienda: d.tiendas[ti], url, detalle, haceMin, tipo, ok: !motivo, motivo, busca });
  }
  const chips = new Set(Object.keys(VRAM_POR_DEFECTO));
  for (const m of modelos) if (m.datos.chip) chips.add(m.datos.chip);
  // los "❌ Sin stock" que ya incorporó la corrida (clave → cuándo lo tocaste)
  const procesados = d.ocultos && !Array.isArray(d.ocultos) ? d.ocultos : {};
  return { ...d, modelos, chips, procesados, generado: Date.parse(d.ts) };
}

// ---------------------------------------------------------------- entender la búsqueda

export function interpretar(texto, chips) {
  let pais = null;
  let t = String(texto).replaceAll("🇦🇺", " AU ").replaceAll("🇦🇷", " AR ");
  t = N.limpiar(t).replace(/(?<![A-Z0-9])(AU|AUS|AUSTRALIA|AR|ARG|ARGENTINA)(?![A-Z0-9])/g, (x) => {
    pais = x.startsWith("AU") ? "AU" : "AR";
    return " ";
  }).replace(/\s+/g, " ").trim();
  const extra = t.split(" ").filter((w) => w && !/\d/.test(w) && !NO_FILTRA.has(w));
  const esPc = /(?<![A-Z0-9])(PC|PCS|COMPUTADORA|DESKTOP|PREBUILT|OMEN|VICTUS)(?![A-Z0-9])/.test(t) || N.esPcArmada(t);
  const q = { texto: t, pais, extra, cat: null, f: {} };
  if (!t) return q;

  let gpu = N.placa(t);
  const proc = N.cpu(t);
  if (!gpu && !proc) {
    // "5070ti", "9070 xt", "5060 ti 8gb": el chip sin RTX/RX adelante
    for (const pre of ["RTX ", "RX "]) {
      const p = N.placa(t.replace(/(?<![A-Z0-9])(?=\d{4}(?!\d))/, pre));
      if (p && chips.has(p.chip)) { gpu = p; break; }
    }
  }
  if (gpu && !chips.has(gpu.chip)) gpu = null;
  if (esPc) {
    Object.assign(q, { cat: "pcs", f: { chip: gpu?.chip ?? null, cpu: proc?.modelo ?? null } });
  } else if (gpu) {
    Object.assign(q, { cat: "placas", f: { chip: gpu.chip, vram: N.vramDe(t) } });
  } else if (proc) {
    Object.assign(q, { cat: "cpu", f: { modelo: proc.modelo } });
  } else if (/(?<![A-Z0-9])(DDR5|RAM|MEMORIAS?)(?![A-Z0-9])/.test(t) && N.ram(t.includes("DDR5") ? t : `${t} DDR5`)) {
    Object.assign(q, { cat: "ram", f: N.ram(t.includes("DDR5") ? t : `${t} DDR5`) });
  } else if (N.ssd(t) || (/\d\s*TB\b/.test(t) && N.ssd(t, false))) {
    const s = N.ssd(t) || N.ssd(t, false);
    Object.assign(q, { cat: "ssd", f: { ...s, sata: t.includes("SATA"), nvme: t.includes("NVME") } });
    if (s.linea) q.extra = q.extra.concat(s.linea.split(" ").filter((w) => !/\d/.test(w) && !NO_FILTRA.has(w)));
  }
  return q;
}

function coincide(q, m) {
  const d = m.datos, f = q.f;
  if (q.cat !== m.cat) return false;
  switch (q.cat) {
    case "placas": return d.chip === f.chip && (f.vram == null || d.vram === f.vram);
    case "pcs": return (!f.chip || d.chip === f.chip) && (!f.cpu || d.cpu === f.cpu);
    case "cpu": return m.nombre === f.modelo;
    case "ram":
      return d.capacidad_gb === f.capacidad_gb && (!f.dijo.modulos || d.modulos === f.modulos) &&
        (!f.dijo.velocidad || d.velocidad === f.velocidad) && (!f.dijo.cl || d.cl === f.cl);
    case "ssd":
      return d.capacidad_tb === f.capacidad_tb && (!f.dijo.gen || d.gen === f.gen) &&
        (!f.sata || d.interfaz === "SATA") && (!f.nvme || d.interfaz === "NVMe");
    default: return false;
  }
}

const regexPalabra = (w) => new RegExp(`(?<![A-Z0-9])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
const conPalabra = (w, texto) => regexPalabra(w).test(texto);

/** Las publicaciones que coinciden, por país: primero las de stock confirmado, cada grupo por precio. */
export function filas(datos, q, extra = q.extra) {
  const porPais = { AU: [], AR: [] };
  const palabras = q.cat ? extra : q.texto.split(" ").filter(Boolean);
  const filtros = palabras.map(regexPalabra);
  for (const m of datos.modelos) {
    if (q.cat && !coincide(q, m)) continue;
    for (const p of PAISES) {
      for (const f of m.filas[p]) {
        if (filtros.length && !filtros.every((r) => r.test(f.busca))) continue;
        porPais[p].push(f);
      }
    }
  }
  for (const p of PAISES) porPais[p].sort((a, b) => (b.ok - a.ok) || a.precio - b.precio);
  return porPais;
}

// ---------------------------------------------------------------- "¿quisiste decir…?"

function bigramas(s) {
  const t = s.replace(/\s+/g, "");
  const b = new Map();
  for (let i = 0; i < t.length - 1; i++) b.set(t.slice(i, i + 2), (b.get(t.slice(i, i + 2)) || 0) + 1);
  return b;
}

function parecido(a, b) {
  const x = bigramas(a), y = bigramas(b);
  let comunes = 0, total = 0;
  for (const [k, n] of x) { comunes += Math.min(n, y.get(k) || 0); total += n; }
  for (const n of y.values()) total += n;
  return total ? (2 * comunes) / total : 0;
}

/** El modelo con precio más parecido a lo que se buscó (aflojando primero lo secundario). */
export function sugerencia(datos, q) {
  const paises = q.pais ? [q.pais] : PAISES;
  const conPrecio = datos.modelos.filter((m) => paises.some((p) => m.filas[p].length));
  const misma = conPrecio.filter((m) => !q.cat || m.cat === q.cat);
  const d = q.f;
  if (q.cat && q.extra.length) {
    // lo que sobra es una marca o línea que no está: sin esa palabra, ¿hay?
    const sin = filas(datos, q, []);
    if (paises.some((p) => sin[p].length)) return { sinPalabras: q.extra };
  }
  let candidatos = [];
  if (q.cat === "placas") {
    candidatos = misma.filter((m) => m.datos.chip === d.chip)
      .sort((a, b) => Math.abs((a.datos.vram || 0) - (d.vram || 0)) - Math.abs((b.datos.vram || 0) - (d.vram || 0)));
  } else if (q.cat === "ram") {
    candidatos = misma.filter((m) => m.datos.capacidad_gb === d.capacidad_gb);
    if (!candidatos.length) {
      candidatos = misma.slice().sort((a, b) => Math.abs(a.datos.capacidad_gb - d.capacidad_gb) - Math.abs(b.datos.capacidad_gb - d.capacidad_gb));
    }
  } else if (q.cat === "ssd") {
    candidatos = misma.filter((m) => m.datos.capacidad_tb === d.capacidad_tb);
  } else if (q.cat === "cpu") {
    const num = (d.modelo.match(/\d{3,5}/) || [""])[0];
    candidatos = misma.filter((m) => num && new RegExp(`(?<!\\d)${num}(?!\\d)`).test(m.nombre));
  } else if (q.cat === "pcs") {
    candidatos = misma.filter((m) => !d.chip || m.datos.chip === d.chip);
  }
  if (!candidatos.length) {
    const base = misma.length ? misma : conPrecio;
    candidatos = base.map((m) => [m, parecido(q.texto, m.clave)]).sort((a, b) => b[1] - a[1])
      .filter(([, s]) => s > 0.3).map(([m]) => m);
  }
  return candidatos.length ? { modelo: candidatos[0] } : null;
}

// ---------------------------------------------------------------- respuesta

function linea(f, cot, varios) {
  const tienda = `<a href="${escapar(f.url)}">${escapar(f.tienda)}</a>`;
  let precio;
  if (f.pais === "AU") {
    const u = cot ? f.precio * cot.aud_usd : null;
    precio = `<b>${plata(f.precio, "AUD")}</b>` + (cot ? ` ≈ ${usd(u)} ≈ ${ars(u * cot.mep)}` : "");
  } else {
    precio = `<b>${ars(f.precio)}</b>${f.tipo ? " " + f.tipo : ""}` + (cot ? ` ≈ ${usd(f.precio / cot.mep)}` : "");
  }
  const detalle = [varios ? f.m.nombre : null, f.detalle || null, hace(f.haceMin + f.edadDatos),
    f.ok ? null : `⚠️ stock sin confirmar (${f.motivo})`].filter(Boolean).map(escapar).join(" · ");
  return `${precio} · ${tienda}\n   ${detalle}`;
}

function titulo(q, porPais, texto) {
  const modelos = new Set(PAISES.flatMap((p) => porPais[p].slice(0, MOSTRAR).map((f) => f.m.nombre)));
  if (modelos.size === 1) return [...modelos][0];
  const f = q.f;
  switch (q.cat) {
    case "placas": return f.vram ? `${f.chip} ${f.vram}GB` : f.chip;
    case "ram": return `RAM DDR5 ${f.capacidad_gb}GB` + (f.dijo.modulos ? ` (${f.modulos}x${f.capacidad_gb / f.modulos})` : "") +
      (f.dijo.velocidad ? ` ${f.velocidad}` : "") + (f.dijo.cl ? ` CL${f.cl}` : "");
    case "ssd": return `SSD ${f.capacidad_tb >= 1 ? f.capacidad_tb + "TB" : f.capacidad_tb * 1000 + "GB"}`;
    case "pcs": return "PC armada" + (f.chip ? ` con ${f.chip}` : "") + (f.cpu ? ` y ${f.cpu}` : "");
    case "cpu": return f.modelo;
    default: return texto.trim();
  }
}

function postsQueCoinciden(datos, q) {
  if (q.pais === "AR") return [];
  return (datos.posts || []).filter(([tit]) => {
    const t = N.limpiar(tit);
    switch (q.cat) {
      case "placas": return N.chipGpu(t) === q.f.chip;
      case "cpu": return N.cpu(t)?.modelo === q.f.modelo;
      case "ram": return N.ram(t)?.capacidad_gb === q.f.capacidad_gb;
      case "ssd": return N.ssd(t)?.capacidad_tb === q.f.capacidad_tb;
      case "pcs": return Boolean(q.f.chip) && N.chipGpu(t) === q.f.chip && N.esPcArmada(t);
      default: return q.texto.split(" ").every((w) => conPalabra(w, t));
    }
  }).slice(0, 2);
}

export function pie(datos, ahora = Date.now()) {
  const min = Math.max(0, (ahora - datos.generado) / 60000);
  const partes = [`🕒 Precios de la corrida de las ${horaArgentina(new Date(datos.generado))} (${hace(min)})`];
  if (datos.cot) partes.push(`MEP ${ars(datos.cot.mep)} · A$1 = USD ${datos.cot.aud_usd.toFixed(3).replace(".", ",")}`);
  let txt = partes.join(" · ");
  if (min > 90) txt += "\n⚠️ Hace más de 1 h que no hay una corrida nueva: fijate /estado";
  if (datos.cot?.nota) txt += "\n" + datos.cot.nota;
  return txt;
}

/**
 * ¿Lo marcaste "❌ Sin stock"? marcas = lo que guardó el Worker (clave → cuándo lo tocaste). Si la
 * corrida ya lo incorporó (datos.procesados, con la misma fecha), manda la corrida: lo saca del JSON
 * mientras siga sin stock y lo vuelve a mostrar cuando la tienda lo tiene de nuevo.
 */
export function oculto(datos, marcas, h) {
  if (!marcas[h]) return false;
  const visto = datos.procesados[h];
  return !visto || Date.parse(marcas[h]) > Date.parse(visto) + 1000;
}

/** Las primeras MOSTRAR que no marcaste sin stock (con su clave, para el botón). */
function primeras(datos, lista, marcas) {
  const salida = [];
  for (const f of lista) {
    f.h ??= claveUrl(f.url);
    if (oculto(datos, marcas, f.h)) continue;
    salida.push(f);
    if (salida.length >= MOSTRAR) break;
  }
  return salida;
}

export function responderBusqueda(datos, texto, ahora = Date.now(), marcas = {}) {
  return buscar(datos, texto, ahora, marcas).texto;
}

/** La respuesta a /buscar: { texto, botones } (botones = inline_keyboard con un ❌ por resultado). */
export function buscar(datos, texto, ahora = Date.now(), marcas = {}) {
  if (!texto.trim()) {
    return { texto: "Decime qué buscás, por ejemplo:\n/buscar 5070 ti\n/buscar ddr5 32gb au\n/buscar ryzen 7 9800x3d ar" };
  }
  const q = interpretar(texto, datos.chips);
  const porPais = filas(datos, q);
  const edadDatos = Math.max(0, (ahora - datos.generado) / 60000);
  const paises = q.pais ? [q.pais] : PAISES;
  const top = {};
  for (const p of paises) top[p] = primeras(datos, porPais[p], marcas).map((f) => ({ ...f, edadDatos }));
  if (!paises.some((p) => top[p].length)) {
    const s = sugerencia(datos, q);
    const donde = q.pais ? ` en ${BANDERA[q.pais]}` : "";
    let txt = `🔎 No encontré «${escapar(texto.trim())}»${donde} con stock en las tiendas que leo.`;
    if (s?.sinPalabras) {
      const sin = q.texto.split(" ").filter((w) => !s.sinPalabras.includes(w)).join(" ").toLowerCase();
      txt += `\nSin «${escapar(s.sinPalabras.join(" ").toLowerCase())}» sí hay: /buscar ${escapar(sin)}${q.pais ? " " + q.pais.toLowerCase() : ""}`;
    } else if (s?.modelo) {
      txt += `\n¿Quisiste decir <b>${escapar(s.modelo.nombre)}</b>? → /buscar ${escapar(s.modelo.nombre.toLowerCase())}` +
        (q.pais ? " " + q.pais.toLowerCase() : "");
    } else {
      txt += "\nProbá con el chip, el modelo o la capacidad: /buscar 5070 ti · /buscar ddr5 32gb · /buscar ssd 2tb";
    }
    return { texto: txt + "\n\n" + pie(datos, ahora) };
  }
  const varios = new Set(paises.flatMap((p) => top[p].map((f) => f.m.nombre))).size > 1;
  const bloques = [`🔎 <b>${escapar(titulo(q, porPais, texto))}</b>` + (q.pais ? ` en ${BANDERA[q.pais]}` : "")];
  for (const p of paises) {
    if (!top[p].length) {
      bloques.push(`${BANDERA[p]} <b>${NOMBRE_PAIS[p]}</b>: sin precio con stock en las tiendas que leo`);
      continue;
    }
    const n = top[p].length;
    const mezcla = top[p].some((f) => f.ok) && top[p].some((f) => !f.ok);
    const cuantos = n === 1 ? (top[p][0].ok ? "el único con stock" : "el único que encontré")
      : `los ${n} más baratos` + (mezcla ? " (primero los de stock confirmado)" : "");
    bloques.push(`${BANDERA[p]} <b>${NOMBRE_PAIS[p]}</b> — ${cuantos}\n` +
      top[p].map((f, i) => `${i + 1}. ${linea(f, datos.cot, varios)}`).join("\n"));
  }
  if (!q.pais && top.AU.length && top.AR.length && datos.cot) {
    const au = top.AU[0], ar = top.AR[0];
    const valija = datos.reglas.valija_aud;
    const c = cuenta(datos.cot, datos.reglas, au.precio, ar.precio, valija);
    let cab = `⚖️ <b>Traerlo de 🇦🇺</b>: el más barato de cada país (${plata(au.precio, "AUD")} contra ${ars(ar.precio)})`;
    const dudosos = [au, ar].filter((f) => !f.ok).map((f) => `${BANDERA[f.pais]} ${f.tienda}`);
    if (dudosos.length) cab += `\n   ⚠️ stock sin confirmar: ${escapar(dudosos.join(", "))}`;
    if (au.m.nombre !== ar.m.nombre) cab += `\n   ojo: no es el mismo modelo (${escapar(au.m.nombre)} / ${escapar(ar.m.nombre)})`;
    if (q.cat === "pcs") cab += "\n   (contra la PC armada más barata de 🇦🇷; las alertas además la comparan por partes)";
    bloques.push([cab, ...lineasCuenta(c, "AR", valija, datos.reglas)].join("\n"));
  }
  const posts = postsQueCoinciden(datos, q);
  if (posts.length) {
    bloques.push("📰 <b>En OzBargain</b>\n" + posts.map(([tit, url, votos, precio, haceMin]) =>
      `• <a href="${escapar(url)}">${escapar(tit.length > 90 ? tit.slice(0, 89) + "…" : tit)}</a>` +
      ` (${[precio ? plata(precio, "AUD") : null, votos != null ? `${votos} votos` : null, hace(haceMin + edadDatos)]
        .filter(Boolean).join(" · ")})`).join("\n"));
  }
  bloques.push(pie(datos, ahora) + "\n❌ = ya no tiene stock: lo oculto hasta que la tienda lo vuelva a mostrar con stock");
  // un ❌ por resultado, una fila por país (el número es el de la lista)
  const botones = paises.filter((p) => top[p].length).map((p) =>
    top[p].map((f, i) => ({ text: `❌ ${BANDERA[p]} ${i + 1}`, callback_data: `x:${f.h}` })));
  return { texto: bloques.join("\n\n"), botones };
}
