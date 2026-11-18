// Worker de Cloudflare: recibe los mensajes de Telegram por webhook y responde al instante con los
// precios que exporta el bot en cada corrida (rama "datos", precios.json). Las alertas no pasan por
// acá: siguen saliendo de GitHub Actions.
//
// Secretos (wrangler secret put …, nunca en el código): TELEGRAM_TOKEN, TELEGRAM_CHAT_ID_YO,
// TELEGRAM_WEBHOOK_SECRET y WORKER_SYNC_SECRET. Solo responde a TELEGRAM_CHAT_ID_YO; a cualquier
// otro, silencio.
//
// "❌ Sin stock": cada resultado (y cada alerta) trae un botón. Al tocarlo, la clave del link
// (sha1[:16]) se guarda en KV (OCULTOS, una sola clave "ocultos" = {clave: cuándo}) y deja de
// aparecer. La corrida siguiente la trae por GET /ocultos (con WORKER_SYNC_SECRET), la oculta en
// la base y la destapa cuando la tienda la vuelve a mostrar con stock.
import { buscar, interpretar, preparar, pie } from "./buscar.js";
import { escapar } from "./formato.js";

const LIMITE = 4000;
const CACHE_MS = 60_000;
const DIAS_MARCA = 60;   // las marcas más viejas se borran del KV (la base ya las tiene)
const cache = new Map(); // archivo → { t, datos }: se reusa entre pedidos mientras viva el isolate

export const AYUDA = [
  "🔎 <b>Buscar precios</b> (responde al toque con lo que vio la última corrida)",
  "/buscar 5070 ti — los 5 más baratos en 🇦🇷 y 🇦🇺 y si conviene traerlo",
  "/buscar ddr5 32gb au — solo Australia (o <code>ar</code>, solo Argentina)",
  "/buscar ryzen 7 9800x3d · /buscar pc 5070 ti · /buscar asus 5070 ti",
  "Cuántos: <code>r</code> y un número, en cualquier parte (hasta r16; sin r, 5 por país):",
  "/buscar 5070 ti r10 · /buscar r16 ddr5 32gb au · /buscar asus 5070 ti ar r3",
  "También podés escribir lo que buscás directo, sin /buscar.",
  "",
  "💽 <b>SSD</b>: solo M.2 NVMe Gen4 y Gen5, uno por renglón con la velocidad (lectura/escritura)",
  "/buscar ssd gen5 2tb au r10 · /buscar 990 pro 2tb · /buscar sn850x 4tb · /buscar samsung ssd 2tb",
  "Por modelo (990 pro, sn850x, mp700 pro, t705…), generación (gen4, gen5) y capacidad (1tb, 2tb, 4tb)",
  "<code>vel</code> ordena por velocidad: /buscar ssd gen4 2tb vel",
  "Lo demás solo si lo pedís: <code>sata</code>, <code>externo</code>, <code>carry</code>, <code>gen3</code>, <code>2230</code>, <code>2242</code>",
  "",
  "Primero aparece lo de stock confirmado; lo que no se pudo confirmar va al final y lo dice.",
  "Si algo ya no tiene stock, tocá su ❌ y lo oculto hasta que la tienda lo vuelva a tener.",
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

/**
 * Los precios: "indice" (sin precios: chips, /estado, /filtros), una categoría ("placas", "ram"…)
 * o null = el completo. Leer y preparar el JSON entero (300 KB) en cada isolate nuevo se pasaba de
 * los 10 ms de CPU del plan gratis; una categoría pesa de 40 a 140 KB.
 */
async function cargar(env, parte = null) {
  const url = parte ? env.DATOS_URL.replace(/\.json$/, `-${parte}.json`) : env.DATOS_URL;
  const hay = cache.get(url);
  if (hay && Date.now() - hay.t < CACHE_MS) return hay.datos;
  try {
    const r = await fetch(url, { cf: { cacheTtl: 60, cacheEverything: true } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const datos = preparar(await r.json());
    cache.set(url, { t: Date.now(), datos });
    return datos;
  } catch (e) {
    if (hay) {                 // sin datos nuevos, uso los que tenía
      console.log("no pude actualizar los precios:", e.message);
      return hay.datos;
    }
    if (parte) return cargar(env, null);   // (corridas viejas: solo el completo)
    throw e;
  }
}

// ---------------------------------------------------------------- marcas "❌ Sin stock" (KV)

export async function leerMarcas(env) {
  if (!env.OCULTOS) return {};
  try {
    return JSON.parse((await env.OCULTOS.get("ocultos")) || "{}");
  } catch {
    return {};
  }
}

async function guardarMarca(env, h, ahora = Date.now()) {
  const marcas = await leerMarcas(env);
  marcas[h] = new Date(ahora).toISOString();
  for (const [k, ts] of Object.entries(marcas)) {
    if (ahora - Date.parse(ts) > DIAS_MARCA * 86400_000) delete marcas[k];
  }
  await env.OCULTOS.put("ocultos", JSON.stringify(marcas));
}

// ---------------------------------------------------------------- respuestas

export async function responder(texto, cargarDatos, ahora = Date.now(), marcas = {}) {
  return (await responderConBotones(texto, cargarDatos, ahora, marcas)).texto;
}

/** { texto, botones? }: los botones van solo en /buscar (un ❌ por resultado). */
export async function responderConBotones(texto, cargarDatos, ahora = Date.now(), marcas = {}) {
  const t = texto.trim();
  const [primera, ...resto] = t.split(/\s+/);
  const cmd = primera.startsWith("/") ? primera.split("@")[0].toLowerCase() : null;
  const arg = cmd ? resto.join(" ") : t;
  if (cmd === "/start" || cmd === "/ayuda" || cmd === "/help") return { texto: AYUDA };
  if (cmd && !["/buscar", "/estado", "/filtros", "/precio"].includes(cmd)) {
    return { texto: `No conozco ${escapar(cmd)}.\n\n${AYUDA}` };
  }
  let datos;
  try {
    // primero el índice (chips, /estado, /filtros); para buscar, solo la categoría que hace falta
    datos = await cargarDatos("indice");
    if (cmd === "/estado") return { texto: `${pie(datos, ahora)}\n\n${datos.estado}` };
    if (cmd === "/filtros") return { texto: datos.filtros };
    if (arg.trim()) {
      const q = interpretar(arg, datos.chips);
      const conCategoria = await cargarDatos(q.cat);
      const r = buscar(conCategoria, arg, ahora, marcas, q);
      // sin nada en esa categoría: con el completo, para la sugerencia ("¿quisiste decir…?")
      if (q.cat && !r.botones?.length) return buscar(await cargarDatos(null), arg, ahora, marcas, q);
      return r;
    }
  } catch {
    return { texto: "⚠️ No pude leer los precios de la última corrida (GitHub no respondió). Probá en un rato." };
  }
  return buscar(datos, arg, ahora, marcas);
}

/**
 * Telegram corta en 4.096 caracteres: parto en mensajes de hasta LIMITE, primero entre bloques
 * (país, cuenta, OzBargain) y, si un bloque solo no entra, entre productos: un producto son su
 * línea de precio y las que siguen con sangría ("   detalle"), y nunca queda partido.
 */
export function partir(texto, limite = LIMITE) {
  const unidades = [];   // [texto, separador antes]
  for (const [b, bloque] of texto.split("\n\n").entries()) {
    if (bloque.length <= limite) { unidades.push([bloque, b ? "\n\n" : ""]); continue; }
    const productos = [];
    for (const linea of bloque.split("\n")) {
      if (productos.length && /^\s/.test(linea)) productos[productos.length - 1] += `\n${linea}`;
      else productos.push(linea);
    }
    productos.forEach((p, i) => unidades.push([p, i ? "\n" : (b ? "\n\n" : "")]));
  }
  const partes = [];
  let actual = "";
  for (const [u, sep] of unidades) {
    if (actual && actual.length + sep.length + u.length > limite) { partes.push(actual); actual = ""; }
    actual = actual ? actual + sep + u : u;
  }
  if (actual) partes.push(actual);
  // un solo producto de más de LIMITE no pasa nunca, pero por las dudas: corte duro
  return partes.flatMap((p) => (p.length > limite ? p.match(new RegExp(`[\\s\\S]{1,${limite}}`, "g")) : [p]));
}

async function api(env, metodo, cuerpo) {
  // la URL lleva el token: nunca se loguea
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/${metodo}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    console.log(`Telegram no aceptó ${metodo}:`, r.status, j.description || "");
  }
  return r;
}

async function enviar(env, chatId, texto, botones) {
  const partes = partir(texto);
  for (const [i, parte] of partes.entries()) {
    const cuerpo = { chat_id: chatId, text: parte, parse_mode: "HTML", disable_web_page_preview: true };
    if (botones?.length && i === partes.length - 1) cuerpo.reply_markup = { inline_keyboard: botones };
    await api(env, "sendMessage", cuerpo);
  }
}

/** Tocaste "❌ Sin stock" (en /buscar o en una alerta): se guarda y el botón pasa a "✅". */
export async function tocarBoton(env, cq, ahora = Date.now()) {
  const m = /^x:([0-9a-f]{16})$/.exec(cq.data || "");
  if (!m || !env.OCULTOS) {
    await api(env, "answerCallbackQuery", { callback_query_id: cq.id, text: m ? "No pude guardarlo" : "Ya está oculto" });
    return;
  }
  await guardarMarca(env, m[1], ahora);
  await api(env, "answerCallbackQuery", {
    callback_query_id: cq.id, text: "Listo: lo oculto hasta que la tienda lo vuelva a mostrar con stock",
  });
  const teclado = cq.message?.reply_markup?.inline_keyboard;
  if (teclado && cq.message?.message_id) {
    const nuevo = teclado.map((fila) => fila.map((b) => (b.callback_data === cq.data
      ? { text: b.text.replace("❌", "✅").replace("Sin stock", "oculto"), callback_data: "y" } : b)));
    await api(env, "editMessageReplyMarkup", {
      chat_id: cq.message.chat.id, message_id: cq.message.message_id, reply_markup: { inline_keyboard: nuevo },
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/ocultos") {
      // lo lee la corrida de GitHub (Authorization: Bearer WORKER_SYNC_SECRET)
      const auth = request.headers.get("Authorization") || "";
      if (!env.WORKER_SYNC_SECRET || !iguales(auth, `Bearer ${env.WORKER_SYNC_SECRET}`)) {
        return new Response("", { status: 401 });
      }
      return Response.json({ ocultos: await leerMarcas(env) });
    }
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
    const yo = String(env.TELEGRAM_CHAT_ID_YO || "");
    const cq = update.callback_query;
    if (cq) {
      // solo mis botones, en mi chat; los de cualquier otro: silencio
      if (yo && String(cq.from?.id ?? "") === yo && String(cq.message?.chat?.id ?? "") === yo) {
        try {
          await tocarBoton(env, cq);
        } catch (e) {
          console.log("error con el botón:", e.name);
        }
      }
      return new Response("");
    }
    const msg = update.message;
    const chat = String(msg?.chat?.id ?? "");
    // silencio total para cualquier otro chat (y para lo que no sea texto)
    if (!msg || typeof msg.text !== "string" || !yo || chat !== yo) {
      return new Response("");
    }
    try {
      const r = await responderConBotones(msg.text, (parte) => cargar(env, parte), Date.now(), await leerMarcas(env));
      await enviar(env, chat, r.texto, r.botones);
    } catch (e) {
      console.log("error respondiendo:", e.name);
    }
    return new Response(""); // siempre 200: si no, Telegram reintenta el mismo mensaje
  },
};
