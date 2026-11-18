// /buscar: entiende el texto con el normalizador de los avisos, junta los precios del JSON que
// exporta el bot y arma la respuesta (los 5 más baratos por país y, si son los dos, la cuenta).
import * as N from "./normalizador.js";
import { VRAM_POR_DEFECTO } from "./normalizador_gen.js";
import { cuenta, lineasCuenta } from "./comparar.js";
import { ars, escapar, hace, horaArgentina, miles, plata, usd } from "./formato.js";
import { claveUrl } from "./sha1.js";

export const MOSTRAR = 5;       // por país, si no pedís otra cantidad con r<N>
export const MAX_MOSTRAR = 16;  // lo más que se puede pedir (lo que exporta cada corrida por modelo y país)
const BANDERA = { AU: "🇦🇺", AR: "🇦🇷" };
const BOTONES_POR_FILA = 8;     // Telegram muestra hasta 8 botones por fila
const NOMBRE_PAIS = { AU: "Australia", AR: "Argentina" };
const PAISES = ["AU", "AR"];
// palabras que describen el producto pero que ya entendió el normalizador (o que no filtran nada)
const NO_FILTRA = new Set(["RTX", "RX", "GTX", "TI", "SUPER", "XT", "XTX", "GRE", "GB", "TB", "DDR5", "DDR", "RAM",
  "MEMORIA", "MEMORIAS", "SSD", "NVME", "M.2", "M2", "SATA", "PCIE", "GEN", "PC", "PCS", "DE", "LA", "EL", "Y", "CON",
  "EN", "PARA", "KIT", "DUAL", "X", "RYZEN", "CORE", "ULTRA", "INTEL", "AMD", "NVIDIA", "PLACA", "PLACAS", "VIDEO",
  "GPU", "CPU", "PROCESADOR", "MICRO", "MICROPROCESADOR", "DESKTOP", "COMPUTADORA", "ARMADA", "GAMER", "GAMING",
  "PREBUILT", "MHZ", "BOX", "TRAY", "DISCO", "SOLIDO", "PLUS", "OMEN", "VICTUS",
  // SSD: lo entiende consultaSsd (velocidad, externos, carry)
  "VEL", "VELOCIDAD", "RAPIDO", "RAPIDOS", "FAST", "FASTEST", "EXTERNO", "EXTERNA", "EXTERNOS", "EXTERNAS",
  "EXTERNAL", "PORTABLE", "PORTATIL", "USB", "CARRY", "ENCLOSURE", "CADDY", "GABINETE", "DOCK", "ADAPTADOR",
  "ADAPTER", "INTERNO", "SOLID", "STATE", "DRIVE", "DISCOS"]);

/** Arma los índices una vez por cada JSON (el Worker lo guarda en memoria entre pedidos). */
export function preparar(d) {
  const modelos = d.modelos.map(([nombre, cat, datos], i) => ({
    i, nombre, cat, datos, clave: N.limpiar(nombre), filas: { AR: [], AU: [] },
  }));
  for (const [mi, pais, precio, ti, url, detalle, haceMin, tipo, staticice, iMotivo, h, s] of d.p) {
    const m = modelos[mi];
    // motivo vacío = stock confirmado (JSON viejo, sin motivos: lo de staticICE queda sin confirmar)
    const motivo = iMotivo == null ? (staticice ? "staticICE no informa stock" : "") : (d.motivos?.[iMotivo] ?? "");
    m.filas[pais].push({ m, pais, precio, tienda: d.tiendas[ti], url, detalle, haceMin, tipo, ok: !motivo, motivo, busca: null, h: h ?? null,
      // SSD: el modelo de ssd_modelos.yaml y las velocidades (MB/s) de esta publicación
      linea: s?.[0] ?? null, lectura: s?.[1] ?? null, escritura: s?.[2] ?? null });
  }
  // los chips de TODAS las categorías (los archivos por categoría los traen en "chips")
  const chips = new Set([...Object.keys(VRAM_POR_DEFECTO), ...(d.chips || [])]);
  for (const m of modelos) if (m.datos.chip) chips.add(m.datos.chip);
  // los "❌ Sin stock" que ya incorporó la corrida (clave → cuándo lo tocaste)
  const procesados = d.ocultos && !Array.isArray(d.ocultos) ? d.ocultos : {};
  return { ...d, modelos, chips, procesados, generado: Date.parse(d.ts) };
}

// ---------------------------------------------------------------- entender la búsqueda

// "r10", "R16": cuántos resultados por país. "r7 9800x3d", "r5 7600" o "r7 7700x" son Ryzen, no una
// cantidad: r3/r5/r7/r9 seguido de un número con sufijo de Ryzen (X, X3D, G, F) o que no es de una placa
// ("r3 5070 ti" = 3 resultados de la 5070 Ti; "r7 7700" a secas, por la RX 7700 XT, también).
const RE_CANTIDAD = /(?<![A-Za-z0-9ÁÉÍÓÚÑáéíóúñ])r(\d{1,4})(?![A-Za-z0-9ÁÉÍÓÚÑáéíóúñ])/gi;
const RE_RYZEN_MODELO = /^\s+(\d{4})(X3D|XT|X|GE|G|F)?(?![A-Za-z0-9])/i;

/** Saca la cantidad del texto: { resto, pedida, cantidad, tope } (tope = pediste más del máximo). */
export function cantidadPedida(texto, chips = new Set()) {
  const esRyzen = (x) => {
    const m = /^[3579]$/.test(x[1]) && RE_RYZEN_MODELO.exec(texto.slice(x.index + x[0].length));
    if (!m) return false;
    const sufijo = (m[2] || "").toUpperCase();
    return (sufijo && sufijo !== "XT") || ![...chips].some((c) => c.split(" ").includes(m[1]));
  };
  const m = [...texto.matchAll(RE_CANTIDAD)].find((x) => !esRyzen(x));
  if (!m) return { resto: texto, pedida: null, cantidad: MOSTRAR, tope: false };
  const pedida = Number(m[1]);
  const resto = (texto.slice(0, m.index) + " " + texto.slice(m.index + m[0].length)).replace(/\s+/g, " ").trim();
  return { resto, pedida, cantidad: Math.min(MAX_MOSTRAR, Math.max(1, pedida)), tope: pedida > MAX_MOSTRAR };
}

export function interpretar(texto, chips) {
  let pais = null;
  const c = cantidadPedida(String(texto), chips);
  let t = c.resto.replaceAll("🇦🇺", " AU ").replaceAll("🇦🇷", " AR ");
  t = N.limpiar(t).replace(/(?<![A-Z0-9])(AU|AUS|AUSTRALIA|AR|ARG|ARGENTINA)(?![A-Z0-9])/g, (x) => {
    pais = x.startsWith("AU") ? "AU" : "AR";
    return " ";
  }).replace(/\s+/g, " ").trim();
  const extra = t.split(" ").filter((w) => w && !/\d/.test(w) && !NO_FILTRA.has(w));
  const esPc = /(?<![A-Z0-9])(PC|PCS|COMPUTADORA|DESKTOP|PREBUILT|OMEN|VICTUS)(?![A-Z0-9])/.test(t) || N.esPcArmada(t);
  const q = { texto: t, original: c.resto, pais, extra, cat: null, f: {}, cantidad: c.cantidad, pedida: c.pedida, tope: c.tope };
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
  } else {
    // "ssd gen5 2tb", "990 pro 2tb", "sn850x", "ssd sata 1tb", "ssd externo": sin pedirlo, solo M.2 NVMe Gen4/Gen5
    const s = N.consultaSsd(t);
    if (s) {
      Object.assign(q, { cat: "ssd", f: s });
      q.extra = q.extra.filter((w) => !s.palabras.includes(w));   // "990 PRO": el PRO ya es del modelo
    }
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
    case "ssd": return N.coincideSsd(f, d, false);    // el modelo (990 Pro…) se mira en cada publicación
    default: return false;
  }
}

const regexPalabra = (w) => new RegExp(`(?<![A-Z0-9])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
const conPalabra = (w, texto) => regexPalabra(w).test(texto);

const tiendasLimpias = new Map();
const limpiarTienda = (t) => {
  if (!tiendasLimpias.has(t)) tiendasLimpias.set(t, N.limpiar(t));
  return tiendasLimpias.get(t);
};

/** Las publicaciones que coinciden, por país: primero las de stock confirmado, cada grupo por precio. */
export function filas(datos, q, extra = q.extra) {
  const porPais = { AU: [], AR: [] };
  const palabras = q.cat ? extra : q.texto.split(" ").filter(Boolean);
  const filtros = palabras.map(regexPalabra);
  for (const m of datos.modelos) {
    if (q.cat && !coincide(q, m)) continue;
    const linea = q.cat === "ssd" ? q.f.linea : null;
    for (const p of PAISES) {
      for (const f of m.filas[p]) {
        if (linea && f.linea !== linea) continue;
        // el texto para las marcas y el texto libre se arma solo cuando hace falta (limpiar
        // las ~2.000 filas de entrada se comía buena parte de los 10 ms de CPU del plan gratis)
        if (filtros.length) {
          f.busca ??= `${m.clave} ${N.limpiar(f.detalle)} ${limpiarTienda(f.tienda)}`;
          if (!filtros.every((r) => r.test(f.busca))) continue;
        }
        porPais[p].push(f);
      }
    }
  }
  // "vel": los más rápidos primero (lectura), los que no la dicen al final; si no, por precio
  const porVel = q.cat === "ssd" && q.f.vel;
  for (const p of PAISES) {
    porPais[p].sort((a, b) => (b.ok - a.ok) || (porVel && (b.lectura ?? -1) - (a.lectura ?? -1)) || a.precio - b.precio);
  }
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
  if (q.cat === "ssd" && (d.formato === "externo" || d.formato === "carry")) return null;  // no hay otro parecido
  if (q.cat === "ssd" && d.linea) {
    // un modelo sin stock (mp700 pro, t705 1tb): otro de la misma generación y capacidad
    const gen = N.genDeLinea(d.linea);
    const otra = { ...d, linea: null, gen: gen === 4 || gen === 5 ? gen : d.gen };
    const hay = filas(datos, { ...q, f: otra }, []);
    if (!paises.some((p) => hay[p].length)) return null;
    const g = otra.gen ? `Gen${otra.gen}` : "M.2 NVMe";
    const cap = d.capacidad_tb != null ? capacidad(d.capacidad_tb) : null;
    return { busqueda: ["ssd", g.toLowerCase().replace("m.2 nvme", ""), cap?.toLowerCase()].filter(Boolean).join(" "),
             que: `Otro SSD ${g}` + (cap ? ` de ${cap}` : "") };
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
    // otro modelo con lo mismo (capacidad, generación, tipo); si no hay, la misma capacidad
    candidatos = misma.filter((m) => N.coincideSsd({ ...d, linea: null }, m.datos, false));
    if (!candidatos.length) candidatos = misma.filter((m) => m.datos.capacidad_tb === d.capacidad_tb && N.coincideSsd({ ...d, linea: null, capacidad_tb: null, gen: null }, m.datos, false));
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

const capacidad = (tb) => (tb >= 1 ? `${tb}TB` : `${Math.round(tb * 1000)}GB`);

function tipoSsd(d) {
  const formato = d.formato || "2280";
  if (formato === "externo" || formato === "carry") return formato;
  if (d.interfaz === "SATA") return formato === "M.2" ? "SATA M.2" : "SATA";
  return (d.gen ? `Gen${d.gen}` : "Gen s/d") + (formato === "2280" ? "" : ` · ${formato}`);
}

/** Un SSD en un renglón: "Samsung 990 Pro 2TB · Gen4 · 7.450/6.900 MB/s · Mwave A$249 ≈ $267.000". */
function lineaSsd(f, cot) {
  const d = f.m.datos;
  const nombre = f.linea ? `${f.linea} ${capacidad(d.capacidad_tb)}` : f.detalle || f.m.nombre;
  const vel = f.lectura && f.escritura ? `${miles(f.lectura)}/${miles(f.escritura)} MB/s`
    : f.lectura ? `${miles(f.lectura)} MB/s` : "vel. s/d";
  const tienda = `<a href="${escapar(f.url)}">${escapar(f.tienda)}</a>`;
  let precio;
  if (f.pais === "AU") precio = `<b>${plata(f.precio, "AUD")}</b>` + (cot ? ` ≈ ${ars(f.precio * cot.aud_usd * cot.mep)}` : "");
  else precio = `<b>${ars(f.precio)}</b>${f.tipo ? " " + f.tipo : ""}` + (cot ? ` ≈ ${usd(f.precio / cot.mep)}` : "");
  return [escapar(nombre), tipoSsd(d), vel, `${tienda} ${precio}`].join(" · ") +
    (f.ok ? "" : ` · ⚠️ stock sin confirmar (${escapar(f.motivo)})`);
}

function linea(f, cot, varios) {
  if (f.m.cat === "ssd") return lineaSsd(f, cot);
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

function tituloSsd(f) {
  const cap = f.capacidad_tb != null ? " " + capacidad(f.capacidad_tb) : "";
  if (f.linea) return f.linea + cap;
  const tipo = f.formato === "externo" ? "SSD externo" : f.formato === "carry" ? "Carry / enclosure"
    : f.sata ? "SSD SATA" : `SSD M.2 NVMe ${f.gen ? "Gen" + f.gen : "Gen4/Gen5"}${f.formato ? " " + f.formato : ""}`;
  return tipo + cap;
}

function titulo(q, porPais, texto) {
  if (q.cat === "ssd") return tituloSsd(q.f) + (q.f.vel ? " — por velocidad" : "");
  const modelos = new Set(PAISES.flatMap((p) => porPais[p].slice(0, q.cantidad).map((f) => f.m.nombre)));
  if (modelos.size === 1) return [...modelos][0];
  const f = q.f;
  switch (q.cat) {
    case "placas": return f.vram ? `${f.chip} ${f.vram}GB` : f.chip;
    case "ram": return `RAM DDR5 ${f.capacidad_gb}GB` + (f.dijo.modulos ? ` (${f.modulos}x${f.capacidad_gb / f.modulos})` : "") +
      (f.dijo.velocidad ? ` ${f.velocidad}` : "") + (f.dijo.cl ? ` CL${f.cl}` : "");
    case "pcs": return "PC armada" + (f.chip ? ` con ${f.chip}` : "") + (f.cpu ? ` y ${f.cpu}` : "");
    case "cpu": return f.modelo;
    default: return texto.trim();
  }
}

// el número que tiene que aparecer sí o sí en el título (el 5070 de una RTX 5070 Ti, el 9800 de un
// 9800X3D): descarta la mayoría de los posts sin correr el normalizador entero (en un isolate nuevo
// cada regex cuesta). La RAM no: "2x16GB" son 32 GB sin que diga 32.
function numeroClave(q) {
  const fuente = { placas: q.f.chip, pcs: q.f.chip, cpu: q.f.modelo }[q.cat];
  return /\d{3,5}/.exec(fuente || "")?.[0] ?? null;
}

function postsQueCoinciden(datos, q) {
  if (q.pais === "AR") return [];
  const numero = numeroClave(q);
  return (datos.posts || []).filter(([tit, , , , , limpio, ssd]) => {
    if (q.cat === "ssd") {     // ya lo parseó Python (JSON viejo: acá)
      const s = ssd !== undefined ? ssd : N.ssd(limpio ?? N.limpiar(tit));
      return Boolean(s) && N.coincideSsd(q.f, s);
    }
    const t = limpio ?? N.limpiar(tit);
    if (numero && !t.includes(numero)) return false;
    switch (q.cat) {
      case "placas": return N.chipGpu(t) === q.f.chip;
      case "cpu": return N.cpu(t)?.modelo === q.f.modelo;
      case "ram": return N.ram(t)?.capacidad_gb === q.f.capacidad_gb;
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

/** Las primeras n que no marcaste sin stock (con su clave, para el botón). */
function primeras(datos, lista, marcas, n = MOSTRAR) {
  const salida = [];
  for (const f of lista) {
    f.h ??= claveUrl(f.url);
    if (oculto(datos, marcas, f.h)) continue;
    salida.push(f);
    if (salida.length >= n) break;
  }
  return salida;
}

export function responderBusqueda(datos, texto, ahora = Date.now(), marcas = {}) {
  return buscar(datos, texto, ahora, marcas).texto;
}

/** La respuesta a /buscar: { texto, botones } (botones = inline_keyboard con un ❌ por resultado). */
/** q: lo que ya entendió interpretar() (para no volver a correr el normalizador en el mismo pedido). */
export function buscar(datos, texto, ahora = Date.now(), marcas = {}, q0 = null) {
  if (!texto.trim()) {
    return { texto: "Decime qué buscás, por ejemplo:\n/buscar 5070 ti\n/buscar ddr5 32gb au\n/buscar ryzen 7 9800x3d ar" };
  }
  const q = q0 ?? interpretar(texto, datos.chips);
  const porPais = filas(datos, q);
  const edadDatos = Math.max(0, (ahora - datos.generado) / 60000);
  const paises = q.pais ? [q.pais] : PAISES;
  const top = {};
  for (const p of paises) top[p] = primeras(datos, porPais[p], marcas, q.cantidad).map((f) => ({ ...f, edadDatos }));
  const r = q.pedida != null ? ` r${q.cantidad}` : "";      // las sugerencias mantienen la cantidad que pediste
  if (!paises.some((p) => top[p].length)) {
    const s = sugerencia(datos, q);
    const donde = q.pais ? ` en ${BANDERA[q.pais]}` : "";
    let txt = `🔎 No encontré «${escapar(q.original)}»${donde} con stock en las tiendas que leo.`;
    if (s?.sinPalabras) {
      const sin = q.texto.split(" ").filter((w) => !s.sinPalabras.includes(w)).join(" ").toLowerCase();
      txt += `\nSin «${escapar(s.sinPalabras.join(" ").toLowerCase())}» sí hay: /buscar ${escapar(sin)}${q.pais ? " " + q.pais.toLowerCase() : ""}${r}`;
    } else if (s?.busqueda) {
      txt += `\n${escapar(s.que)}: /buscar ${escapar(s.busqueda)}${q.pais ? " " + q.pais.toLowerCase() : ""}${r}`;
    } else if (s?.modelo) {
      txt += `\n¿Quisiste decir <b>${escapar(s.modelo.nombre)}</b>? → /buscar ${escapar(s.modelo.nombre.toLowerCase())}` +
        (q.pais ? " " + q.pais.toLowerCase() : "") + r;
    } else {
      txt += "\nProbá con el chip, el modelo o la capacidad: /buscar 5070 ti · /buscar ddr5 32gb · /buscar ssd gen4 2tb";
    }
    return { texto: txt + "\n\n" + pie(datos, ahora) };
  }
  const varios = new Set(paises.flatMap((p) => top[p].map((f) => f.m.nombre))).size > 1;
  let cabeza = `🔎 <b>${escapar(titulo(q, porPais, q.original))}</b>` + (q.pais ? ` en ${BANDERA[q.pais]}` : "");
  if (q.tope) cabeza += `\nℹ️ Pediste r${q.pedida}: muestro hasta ${MAX_MOSTRAR} por país (lo máximo)`;
  const bloques = [cabeza];
  for (const p of paises) {
    if (!top[p].length) {
      bloques.push(`${BANDERA[p]} <b>${NOMBRE_PAIS[p]}</b>: sin precio con stock en las tiendas que leo`);
      continue;
    }
    const n = top[p].length;
    const mezcla = top[p].some((f) => f.ok) && top[p].some((f) => !f.ok);
    const cuantos = n === 1 ? (top[p][0].ok ? "el único con stock" : "el único que encontré")
      : `los ${n} más ${q.cat === "ssd" && q.f.vel ? "rápidos" : "baratos"}` + (mezcla ? " (primero los de stock confirmado)" : "");
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
    const cual = (f) => (f.m.cat === "ssd" ? `${f.linea || f.detalle} ${capacidad(f.m.datos.capacidad_tb)}` : f.m.nombre);
    if (cual(au) !== cual(ar)) cab += `\n   ojo: no es el mismo modelo (${escapar(cual(au))} / ${escapar(cual(ar))})`;
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
  // un ❌ por resultado, filas de hasta 8 por país (el número es el de la lista)
  const botones = [];
  for (const p of paises) {
    const fila = top[p].map((f, i) => ({ text: `❌ ${BANDERA[p]} ${i + 1}`, callback_data: `x:${f.h}` }));
    for (let i = 0; i < fila.length; i += BOTONES_POR_FILA) botones.push(fila.slice(i, i + BOTONES_POR_FILA));
  }
  return { texto: bloques.join("\n\n"), botones };
}
