// Worker de Cloudflare: recibe los mensajes de Telegram por webhook y responde al instante con los
// precios que exporta el bot en cada corrida (rama "datos", precios.json). Las alertas no pasan por
// acá: siguen saliendo de GitHub Actions.
//
// Secretos (wrangler secret put …, nunca en el código): TELEGRAM_TOKEN, TELEGRAM_CHAT_ID_YO y
// TELEGRAM_WEBHOOK_SECRET. Solo responde a TELEGRAM_CHAT_ID_YO; a cualquier otro, silencio.
import { preparar, responderBusqueda, pie } from "./buscar.js";
import { escapar } from "./formato.js";

const LIMITE = 4000;
const CACHE_MS = 60_000;
let cache = null; // { t, datos }: se reusa entre pedidos mientras viva el isolate

export const AYUDA = [
  "🔎 <b>Buscar precios</b> (responde al toque con lo que vio la última corrida)",
  "/buscar 5070 ti — los 5 más baratos en 🇦🇷 y 🇦🇺 y si conviene traerlo",
  "/buscar ddr5 32gb au — solo Australia (o <code>ar</code>, solo Argentina)",
  "/buscar ryzen 7 9800x3d · /buscar ssd 2tb gen4 · /buscar pc 5070 ti · /buscar asus 5070 ti",
  "También podés escribir lo que buscás directo, sin /buscar.",
  "",
  "/estado — cómo andan las tiendas y de cuándo son los precios",
  "/filtros — los filtros y objetivos de config.yaml",
  "",
  "Las alertas siguen llegando solas, como siempre.",
].join("\n");

/** Compara sin cortar en el primer carácter distinto (que no se pueda adivinar el secreto midiendo tiempos). */
export function iguales(a, b) {
  const x = new TextEncoder().encode(a), y = new TextEncoder().encode(b);
  let dif = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) dif |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return dif === 0 && x.length > 0;
}

async function cargar(env) {
  if (cache && Date.now() - cache.t < CACHE_MS) return cache.datos;
  try {
    const r = await fetch(env.DATOS_URL, { cf: { cacheTtl: 60, cacheEverything: true } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    cache = { t: Date.now(), datos: preparar(await r.json()) };
  } catch (e) {
    if (!cache) throw e;     // sin datos nuevos, uso los que tenía
    console.log("no pude actualizar los precios:", e.message);
  }
  return cache.datos;
}

export async function responder(texto, cargarDatos, ahora = Date.now()) {
  const t = texto.trim();
  const [primera, ...resto] = t.split(/\s+/);
  const cmd = primera.startsWith("/") ? primera.split("@")[0].toLowerCase() : null;
  const arg = cmd ? resto.join(" ") : t;
  if (cmd === "/start" || cmd === "/ayuda" || cmd === "/help") return AYUDA;
  if (cmd && !["/buscar", "/estado", "/filtros", "/precio"].includes(cmd)) {
    return `No conozco ${escapar(cmd)}.\n\n${AYUDA}`;
  }
  let datos;
  try {
    datos = await cargarDatos();
  } catch {
    return "⚠️ No pude leer los precios de la última corrida (GitHub no respondió). Probá en un rato.";
  }
  if (cmd === "/estado") return `${pie(datos, ahora)}\n\n${datos.estado}`;
  if (cmd === "/filtros") return datos.filtros;
  return responderBusqueda(datos, arg, ahora);
}

export function partir(texto) {
  const partes = [];
  let actual = "";
  for (const bloque of texto.split("\n\n")) {
    if (actual && actual.length + bloque.length + 2 > LIMITE) { partes.push(actual); actual = ""; }
    actual = actual ? `${actual}\n\n${bloque}` : bloque;
  }
  if (actual) partes.push(actual);
  return partes.flatMap((p) => (p.length > LIMITE ? p.match(new RegExp(`[\\s\\S]{1,${LIMITE}}`, "g")) : [p]));
}

async function enviar(env, chatId, texto) {
  for (const parte of partir(texto)) {
    // la URL lleva el token: nunca se loguea
    const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: parte, parse_mode: "HTML", disable_web_page_preview: true }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      console.log("Telegram no aceptó la respuesta:", r.status, j.description || "");
    }
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/telegram") return new Response("ok");
    if (!iguales(request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "", env.TELEGRAM_WEBHOOK_SECRET || "")) {
      return new Response("", { status: 401 });
    }
    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("");
    }
    const msg = update.message;
    const chat = String(msg?.chat?.id ?? "");
    // silencio total para cualquier otro chat (y para lo que no sea texto)
    if (!msg || typeof msg.text !== "string" || !env.TELEGRAM_CHAT_ID_YO || chat !== String(env.TELEGRAM_CHAT_ID_YO)) {
      return new Response("");
    }
    try {
      await enviar(env, chat, await responder(msg.text, () => cargar(env)));
    } catch (e) {
      console.log("error respondiendo:", e.name);
    }
    return new Response(""); // siempre 200: si no, Telegram reintenta el mismo mensaje
  },
};
