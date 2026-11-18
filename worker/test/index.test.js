import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import worker, { AYUDA, iguales, partir, responder } from "../src/index.js";

const ENV = {
  TELEGRAM_TOKEN: "123456:token-de-prueba",
  TELEGRAM_CHAT_ID_YO: "111",
  TELEGRAM_WEBHOOK_SECRET: "secreto-de-prueba",
  DATOS_URL: "https://raw.example/precios.json",
};
const DATOS = {
  v: 1, ts: new Date().toISOString(), cot: { mep: 1600, aud_usd: 0.67, nota: null },
  reglas: { franquicia_usd: 500, arancel: 0.5, valija_aud: 150, conviene_pct: 10 },
  tiendas: ["Umart"], modelos: [["RTX 5070 Ti 16GB", "placas", { chip: "RTX 5070 Ti", vram: 16 }]],
  p: [[0, "AU", 1799, 0, "https://u/1", "MSI", 5, "", 0]], posts: [],
  estado: "📊 <b>Tiendas, últimas 24 h</b>", filtros: "⚙️ <b>Filtros activos</b>",
};

let pedidos, fetchOriginal, logs, logOriginal;
beforeEach(() => {
  pedidos = [];
  logs = [];
  fetchOriginal = globalThis.fetch;
  logOriginal = console.log;
  console.log = (...a) => logs.push(a.join(" "));
  globalThis.fetch = async (url, opciones = {}) => {
    pedidos.push({ url: String(url), cuerpo: opciones.body ? JSON.parse(opciones.body) : null });
    if (String(url) === ENV.DATOS_URL) return new Response(JSON.stringify(DATOS));
    return new Response(JSON.stringify({ ok: true }));
  };
});
afterEach(() => {
  globalThis.fetch = fetchOriginal;
  console.log = logOriginal;
});

const mensaje = (texto, chat = 111, secreto = ENV.TELEGRAM_WEBHOOK_SECRET) =>
  new Request("https://bot.workers.dev/telegram", {
    method: "POST",
    headers: { "content-type": "application/json", "X-Telegram-Bot-Api-Secret-Token": secreto },
    body: JSON.stringify({ update_id: 1, message: { message_id: 1, chat: { id: chat }, text: texto } }),
  });

const aTelegram = () => pedidos.filter((p) => p.url.startsWith("https://api.telegram.org/"));

test("sin el secret_token del webhook: 401 y no hace nada", async () => {
  for (const secreto of ["", "otro", "secreto-de-prueba-y-algo"]) {
    const r = await worker.fetch(mensaje("/buscar 5070 ti", 111, secreto), ENV);
    assert.equal(r.status, 401);
  }
  assert.equal(pedidos.length, 0);
});

test("otro chat: silencio total", async () => {
  const r = await worker.fetch(mensaje("/buscar 5070 ti", 999), ENV);
  assert.equal(r.status, 200);
  assert.equal(pedidos.length, 0);
});

test("mi chat: busca y responde por sendMessage, sin loguear el token", async () => {
  const r = await worker.fetch(mensaje("/buscar 5070 ti"), ENV);
  assert.equal(r.status, 200);
  const [envio] = aTelegram();
  assert.equal(envio.url, `https://api.telegram.org/bot${ENV.TELEGRAM_TOKEN}/sendMessage`);
  assert.equal(envio.cuerpo.chat_id, "111");
  assert.equal(envio.cuerpo.parse_mode, "HTML");
  assert.match(envio.cuerpo.text, /RTX 5070 Ti 16GB/);
  assert.ok(logs.every((l) => !l.includes(ENV.TELEGRAM_TOKEN)));
});

test("GET o rutas que no son el webhook: nada", async () => {
  const r = await worker.fetch(new Request("https://bot.workers.dev/"), ENV);
  assert.equal(await r.text(), "ok");
  assert.equal(pedidos.length, 0);
});

test("comandos", async () => {
  const cargar = async () => (await import("../src/buscar.js")).preparar(DATOS);
  assert.equal(await responder("/ayuda", cargar), AYUDA);
  assert.equal(await responder("/start", cargar), AYUDA);
  assert.match(await responder("/estado@mi_bot", cargar), /🕒 Precios de la corrida[\s\S]*📊 <b>Tiendas/);
  assert.equal(await responder("/filtros", cargar), DATOS.filtros);
  assert.match(await responder("/pausa", cargar), /No conozco \/pausa/);
  assert.match(await responder("5070 ti", cargar), /RTX 5070 Ti 16GB/);          // sin /buscar también
  assert.match(await responder("/buscar 5070 ti", async () => { throw new Error("x"); }), /No pude leer los precios/);
});

test("secretos y mensajes largos", () => {
  assert.ok(iguales("abc", "abc"));
  assert.ok(!iguales("abc", "abd") && !iguales("abc", "abcd") && !iguales("", ""));
  const largo = Array.from({ length: 60 }, (_, i) => `bloque ${i} ` + "x".repeat(100)).join("\n\n");
  const partes = partir(largo);
  assert.ok(partes.length > 1 && partes.every((p) => p.length <= 4000));
  assert.equal(partes.join("\n\n"), largo);
});

// KV de mentira (como env.OCULTOS)
function kv() {
  const m = new Map();
  return { get: async (k) => m.get(k) ?? null, put: async (k, v) => { m.set(k, v); }, m };
}
const boton = (data, de = 111, chat = 111) =>
  new Request("https://bot.workers.dev/telegram", {
    method: "POST",
    headers: { "content-type": "application/json", "X-Telegram-Bot-Api-Secret-Token": ENV.TELEGRAM_WEBHOOK_SECRET },
    body: JSON.stringify({ update_id: 2, callback_query: { id: "cq1", data, from: { id: de },
      message: { message_id: 7, chat: { id: chat }, reply_markup: { inline_keyboard: [[
        { text: "❌ 🇦🇺 1", callback_data: data }, { text: "❌ 🇦🇺 2", callback_data: "x:00000000000000ff" }]] } } } }),
  });

test("❌ Sin stock: guarda la marca, contesta y cambia el botón; los resultados traen los botones", async () => {
  const env = { ...ENV, OCULTOS: kv(), WORKER_SYNC_SECRET: "sync-de-prueba" };
  await worker.fetch(mensaje("/buscar 5070 ti"), env);
  const [envio] = aTelegram();
  const teclado = envio.cuerpo.reply_markup.inline_keyboard;
  assert.equal(teclado[0][0].text, "❌ 🇦🇺 1");
  const data = teclado[0][0].callback_data;
  assert.match(data, /^x:[0-9a-f]{16}$/);

  pedidos = [];
  await worker.fetch(boton(data), env);
  const marcas = JSON.parse(env.OCULTOS.m.get("ocultos"));
  assert.ok(marcas[data.slice(2)]);
  const [respuesta, edicion] = aTelegram();
  assert.match(respuesta.url, /answerCallbackQuery$/);
  assert.match(respuesta.cuerpo.text, /lo oculto hasta que la tienda lo vuelva a mostrar con stock/);
  assert.match(edicion.url, /editMessageReplyMarkup$/);
  assert.deepEqual(edicion.cuerpo.reply_markup.inline_keyboard[0].map((b) => b.text), ["✅ 🇦🇺 1", "❌ 🇦🇺 2"]);

  // la misma búsqueda ya no lo muestra
  pedidos = [];
  await worker.fetch(mensaje("/buscar 5070 ti"), env);
  assert.match(aTelegram()[0].cuerpo.text, /No encontré «5070 ti»/);

  // la corrida lo lee con el secreto; sin el secreto, 401
  const sin = await worker.fetch(new Request("https://bot.workers.dev/ocultos"), env);
  assert.equal(sin.status, 401);
  const mal = await worker.fetch(new Request("https://bot.workers.dev/ocultos", { headers: { Authorization: "Bearer otro" } }), env);
  assert.equal(mal.status, 401);
  const ok = await worker.fetch(new Request("https://bot.workers.dev/ocultos",
    { headers: { Authorization: "Bearer sync-de-prueba" } }), env);
  assert.deepEqual(Object.keys((await ok.json()).ocultos), [data.slice(2)]);
});

test("botones de otro (o en otro chat): silencio y no guarda nada", async () => {
  const env = { ...ENV, OCULTOS: kv() };
  await worker.fetch(boton("x:00000000000000aa", 999, 111), env);
  await worker.fetch(boton("x:00000000000000aa", 111, 999), env);
  assert.equal(pedidos.length, 0);
  assert.equal(env.OCULTOS.m.size, 0);
});
