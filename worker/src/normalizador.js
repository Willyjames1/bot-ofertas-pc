// El normalizador de los avisos (bot/normalizar.py), del lado del Worker.
//
// Las expresiones regulares y las tablas NO se copian a mano: vienen de normalizador_gen.js, que
// genera Python a partir de bot/normalizar.py. Acá está solo la lógica que las usa, en el mismo
// orden que en Python, y tests/test_worker.py corre los dos sobre los mismos títulos y compara.
import * as G from "./normalizador_gen.js";

const re = (fuente) => new RegExp(fuente);
const reG = (fuente) => new RegExp(fuente, "g");
const R = Object.fromEntries(Object.keys(G).filter((k) => typeof G[k] === "string").map((k) => [k, re(G[k])]));
const VRAM_VALIDAS = new Set(G.VRAM_VALIDAS);

/** Python: re.search(patron, t, desde) */
function buscarDesde(nombre, t, desde = 0) {
  const g = reG(G[nombre]);
  g.lastIndex = desde;
  return g.exec(t);
}

function todos(nombre, t) {
  return [...t.matchAll(reG(G[nombre]))];
}

/** Mayúsculas, sin tildes y con los espacios normalizados (limpiar() en Python). */
export function limpiar(titulo) {
  let t = String(titulo).normalize("NFKD").replace(/[̀-ͯ]/g, "");
  t = t.toUpperCase().replaceAll("×", "X").replaceAll("–", "-").replaceAll(" ", " ");
  return t.replace(/\s+/g, " ").trim();
}

// ---------------------------------------------------------------- placas de video

export function chipGpu(t) {
  const m = R.RE_NVIDIA.exec(t) || R.RE_NVIDIA_PEGADO.exec(t);
  if (m) {
    const suf = (m[2] || "").replaceAll(" ", "");
    const nombre = { TI: " Ti", SUPER: " Super", TISUPER: " Ti Super", S: " Super" }[suf] || "";
    return `RTX ${m[1]}${nombre}`;
  }
  const a = R.RE_AMD.exec(t);
  if (a) return `RX ${a[1]}${a[2] ? " " + a[2] : ""}`;
  return null;
}

export function vramDe(t) {
  for (const m of todos("RE_VRAM", t)) {
    const v = parseInt(m[1], 10);
    if (VRAM_VALIDAS.has(v)) return v;
  }
  return null;
}

const palabra = (token, t) => new RegExp(`(?<![A-Z0-9])${token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Z0-9])`).test(t);

/** {chip, vram, modelo} como parsear_placa (sin los descartes de accesorios). */
export function placa(t) {
  let chip = chipGpu(t);
  if (!chip) return null;
  let vram = vramDe(t) ?? G.VRAM_POR_DEFECTO[chip] ?? null;
  if (chip === "RX 9070" && (palabra("GRE", t) || vram === 12)) [chip, vram] = ["RX 9070 GRE", 12];
  return { chip, vram, modelo: vram ? `${chip} ${vram}GB` : chip };
}

// ---------------------------------------------------------------- CPU

function ryzenPorNumero(num) {
  const resto = parseInt(num.slice(1), 10);
  if (resto >= 950) return 9;
  if (resto >= 900) return 9;
  if (resto >= 700) return 7;
  return 5;
}

/** {modelo, marca} como parsear_cpu: "Ryzen 7 9800X3D", "Core Ultra 7 265K", "Core i7-14700K". */
export function cpu(t) {
  let m = R.RE_RYZEN.exec(t);
  if (m && m[2].endsWith("000")) m = buscarDesde("RE_RYZEN", t, m.index + m[0].length); // "Ryzen 9 9000 9950X3D"
  const suelto = m ? null : R.RE_RYZEN_SUELTO.exec(t);
  if (m || suelto) {
    const num = m ? m[2] : suelto[1];
    const suf = (m ? m[3] : suelto[2]) || "";
    const tier = m && m[1] ? parseInt(m[1], 10) : ryzenPorNumero(num);
    return { modelo: `Ryzen ${tier} ${num}${suf}`, marca: "AMD" };
  }
  m = R.RE_ULTRA.exec(t) || R.RE_ULTRA_LEJOS.exec(t);
  if (m) {
    const plus = R.RE_ULTRA_PLUS.test(t) ? " Plus" : "";
    return { modelo: `Core Ultra ${m[1]} ${m[2]}${m[3] || ""}${plus}`, marca: "Intel" };
  }
  m = R.RE_I14.exec(t);
  if (m) return { modelo: `Core i${m[1]}-${m[2]}${m[3] || ""}`, marca: "Intel" };
  return null;
}

// ---------------------------------------------------------------- RAM

/** {capacidad_gb, modulos, velocidad, cl} como parsear_ram, más qué dijo el texto a propósito
 *  (para buscar: "ddr5 32gb" no pide módulos ni velocidad). null si no es RAM DDR5 con capacidad. */
export function ram(t) {
  let total = null, mods = null, vel = null, cl = null;
  let ddr5 = t.includes("DDR5");
  const dijo = { modulos: false, velocidad: false, cl: false };
  let m;
  if ((m = R.RE_CORSAIR.exec(t))) {
    [total, mods, vel, cl] = [m[1], m[2], m[3], m[4]].map(Number);
    ddr5 = true;
  } else if ((m = R.RE_GSKILL.exec(t))) {
    vel = Number(m[1]); cl = Number(m[2]); mods = Number(m[4]); total = Number(m[3]) * mods; ddr5 = true;
  } else if ((m = R.RE_KINGSTON.exec(t))) {
    vel = Number(m[1]) * 100; cl = Number(m[2]); mods = Number(m[3] || 1); total = Number(m[4]); ddr5 = true;
  }
  if (mods !== null) Object.assign(dijo, { modulos: true, velocidad: true, cl: true });
  if (t.includes("DDR4") && !ddr5) return null;
  if (!ddr5 && !/\bDDR\d/.test(t)) {
    // sin "DDRx": 5200 MHz o más solo existe en DDR5
    for (const p of ["RE_VEL", "RE_VEL_DDR", "RE_VEL_SUELTA"]) {
      const v = R[p].exec(t);
      if (v && Number(v[1]) >= 5200 && Number(v[1]) <= 10000) { ddr5 = true; break; }
    }
  }
  if (!ddr5) return null;
  if ((m = R.RE_KIT.exec(t))) {
    mods = Number(m[1]); total = mods * Number(m[2]); dijo.modulos = true;
  } else if ((m = R.RE_KIT_INV.exec(t))) {
    mods = Number(m[2]); total = mods * Number(m[1]); dijo.modulos = true;
  }
  if (total === null) {
    const gbs = todos("RE_GB", t).map((x) => Number(x[1])).filter((x) => x >= 8 && x <= 256);
    if (gbs.length) total = Math.max(...gbs);
  }
  if (mods === null) {
    const kit = /\b(KIT|DUAL|2 MODULOS|DOBLE)\b/.test(t);
    mods = kit ? 2 : 1;
    dijo.modulos = kit;
  }
  if (vel === null) {
    for (const p of ["RE_VEL", "RE_VEL_DDR", "RE_VEL_SUELTA"]) {
      const v = R[p].exec(t);
      if (v && Number(v[1]) >= 4000 && Number(v[1]) <= 10000) { vel = Number(v[1]); dijo.velocidad = true; break; }
    }
  }
  if (cl === null && (m = R.RE_CL.exec(t))) {
    const v = Number(m[1] || m[2]);
    cl = v >= 20 && v <= 60 ? v : null;
    dijo.cl = cl !== null;
  }
  if (total === null) return null;
  return { capacidad_gb: total, modulos: mods, velocidad: vel, cl, dijo };
}

// ---------------------------------------------------------------- SSD

const EQUIV_TB = { 0.24: 0.25, 0.256: 0.25, 0.48: 0.5, 0.512: 0.5, 0.96: 1.0 };

/** {capacidad_tb, interfaz, gen, linea} como parsear_ssd. null si no es un SSD interno. */
export function ssd(t, exigirPalabra = true) {
  if (R.SSD_NO.test(t)) return null;
  const linea = G.LINEAS_SSD.find(([n]) => t.includes(n)) || null;
  if (exigirPalabra && !R.SSD_SI.test(t) && !linea) return null;
  let tb, m;
  if ((m = R.RE_SSD_TB.exec(t))) tb = parseFloat(m[1].replace(",", "."));
  else if ((m = R.RE_SSD_GB.exec(t))) tb = Math.round((parseInt(m[1], 10) / 1000) * 100) / 100;
  else return null;
  tb = EQUIV_TB[tb] ?? tb;
  const g = R.RE_SSD_GEN.exec(t);
  const gen = g ? parseInt(g[1], 10) : linea ? linea[2] || null : null;
  const sata = (t.includes("SATA") && !t.includes("NVME")) || (linea !== null && linea[2] === 0);
  return { capacidad_tb: tb, interfaz: sata ? "SATA" : "NVMe", gen: sata ? null : gen, linea: linea ? linea[0] : null,
           dijo: { gen: Boolean(g) || Boolean(linea), interfaz: t.includes("SATA") || t.includes("NVME") } };
}

export const descartable = (t) => R.USADO.test(t) || R.NOTEBOOK.test(t);
export const esPcArmada = (t) => R.PC_ARMADA.test(t);
