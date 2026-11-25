# Bot de ofertas de hardware 🇦🇷 🇦🇺

Bot de Telegram personal que recorre tiendas de Argentina y Australia, guarda el precio de
todos los productos de las categorías que seguimos (placas de video, CPU y RAM en la Fase 1),
lee OzBargain y me avisa **solo** de lo que pasa mis filtros de `config.yaml`.

- **Suena** (pocas veces por semana): precio bajo el objetivo, nuevo mínimo histórico, post de
  OzBargain muy votado en su primera hora y "oportunidad fuerte" (una gama más alta al precio de una
  más baja).
- **Todo lo demás** (bajas, vuelta de stock, gangas, posts nuevos) se guarda para el resumen
  (Fase 2).
- **Cada aviso viene comparado con el otro país**: el precio pasado a dólares y pesos, el mejor precio
  con stock del producto equivalente del otro lado (visto en las últimas 48 h), la diferencia, la
  cuenta con aduana y un veredicto. Si el aviso es de Argentina, se invierte: primero el precio
  argentino y abajo el australiano convertido.

  ```
  🔻 RTX 5070 Ti 16GB — bajó 15% en 🇦🇺
  🇦🇺 MSI Ventus 3X OC @ Centre Com: A$1.441 (antes A$1.699)
     ≈ USD 974 ≈ $1.546.994 (MEP $1.589)
  🇦🇷 Mejor precio: Venex $2.319.990 contado (mismo chip)
  💰 Diferencia: ~$772.996 más barato en 🇦🇺 (33%)
  🛃 Traído con valija extra (A$150) y aduana declarada (50% sobre lo que pase de USD 500): ~$2.085.384 → ~$234.606 más barato
  ✅ Veredicto: conviene
  ```

  - **Cotizaciones**: en cada corrida se baja una vez el AUD/USD de frankfurter.app y el dólar MEP de
    dolarapi.com (`/v1/dolares/bolsa`) y se guardan en la base. Si alguna falla, se usa la última
    guardada y el aviso lo aclara ("⚠️ Cotización guardada: MEP del 16/11 14:00").
  - **Cuenta**: A$ × AUD/USD = USD; USD × MEP = pesos. No se descuenta el reintegro del TRS (el GST).
    Aduana: 50% de lo que pase de USD 500. Ojo: la franquicia es **por viajero y por viaje**, no por
    producto. A todo lo que se trae de 🇦🇺 se le suma una valija extra (`general.valija_extra_aud`,
    A$150 por defecto).
  - **Equivalente**: placas, el mismo chip y la misma VRAM de cualquier marca; CPU, el mismo modelo;
    RAM, la misma capacidad, cantidad de módulos y velocidad; PCs, la misma placa y la misma cantidad
    de RAM. Si no está, se usa el más parecido y se marca "aprox." (por ejemplo "CL36 en vez de CL30").
  - **Veredicto** (con valija y aduana): "conviene" si traerlo sale más de 10% más barato, "casi igual"
    entre 0 y 10%, "no conviene" si sale más caro.
  - **PCs armadas de 🇦🇺**: se comparan contra lo que sale armarla en 🇦🇷 por partes (la placa, el
    procesador, la RAM y el SSD más baratos de las tiendas que leemos, más `pcs.resto_estimado_ars`
    por mother + fuente + gabinete, que es un **estimado**). Si falta alguna parte se usa la PC armada
    parecida. Como es para DaVinci Resolve, avisa ⚠️ si el procesador tiene menos de 12 núcleos o el
    SSD es de menos de 2TB (`pcs.davinci`).
- **Resumen diario** a las 12:00 hora argentina (sección `resumen_diario` de `config.yaml`): un
  mensaje con el mejor precio de hoy en 🇦🇷 y 🇦🇺 de cada producto, pasado a pesos y con la diferencia
  entre países. Sale en la primera corrida desde esa hora; para verlo ya: `python -m bot resumen --dry-run`.
- **Búsquedas desde Telegram, al instante**: `/buscar 5070 ti` (o escribir directo "5070 ti")
  responde en segundos con los 5 más baratos de cada país, pasados a dólares y pesos, de hace cuánto
  es cada precio, el link y la misma cuenta de los avisos (diferencia, valija, aduana y veredicto).
  `/buscar ddr5 32gb au` (o `ar`) mira un solo país; `/buscar asus 5070 ti` filtra por marca.
  `r` y un número, en cualquier parte, elige cuántos por país (`/buscar 5070 ti r10`,
  `/buscar r16 ddr5 32gb au`): hasta 16; si pedís más, muestra 16 y lo avisa. `r7 9800x3d` sigue
  siendo un Ryzen. Si la respuesta pasa el límite de Telegram, llega en varios mensajes, sin
  cortar ningún producto. Si no encuentra nada sugiere el modelo más parecido. Los SSD van
  uno por renglón con la velocidad (`/buscar ssd gen5 2tb`, `/buscar 990 pro 2tb`; ver «SSD» abajo). Lo responde un Worker de Cloudflare (ver abajo).

## Cómo está armado

```
bot/
  config.py        carga config.yaml, .env y el modo Black Friday
  modelos.py       Oferta y Post
  normalizar.py    título → modelo canónico; descarta usados y notebooks; PCs armadas por su placa
  fuentes/         un archivo por tienda, todos con la misma interfaz (base.py)
  feeds.py         OzBargain por RSS (ignora expirados, agotados y posts de más de 7 días)
  cotizaciones.py  MEP (dolarapi.com) y AUD/USD (frankfurter.app), una vez por corrida
  comparar.py      producto equivalente del otro país, diferencia, aduana y veredicto
  resumen.py       resumen diario de las 12:00
  alertas.py       filtros, objetivos, mínimos, oportunidades, tope diario, silencio nocturno
  telegram.py      envío de mensajes (solo chat_id autorizados)
  comandos.py      los textos de /estado y /filtros (los arma Python, los manda el Worker)
  exportar.py      el JSON de precios actuales que lee el Worker (va a la rama datos)
  db.py            SQLite: el historial guarda solo los CAMBIOS de precio
  corrida.py       una corrida completa
worker/            Worker de Cloudflare: /buscar, /estado, /filtros y /ayuda por webhook
  src/normalizador_gen.js   las regexes de normalizar.py, generadas (python -m bot generar-worker)
config.yaml        tus filtros (editable)
perf.yaml          índice de rendimiento juegos 1440p / DaVinci (editable)
```

La base `datos/precios.db` **no** está en la rama principal: GitHub Actions la guarda en la rama
`datos` como un único commit que se pisa en cada corrida, así el repo no crece.

## Correrlo en tu PC

```bash
pip install -r requirements.txt
```

```bash
python -m pytest -q
```

```bash
python -m bot correr --dry-run --forzar
```

`--dry-run` no manda nada: imprime en pantalla lo que mandaría. `--forzar` ignora los intervalos.
Para usar Telegram de verdad en local, copiá `.env.example` como `.env` y completalo
(`.env` nunca se sube).

Probar una sola tienda contra la web (no guarda ni avisa):

```bash
python -m bot probar umart
```

```bash
python -m bot probar umart --categoria placas --guardar-html
```

Ver las tiendas registradas:

```bash
python -m bot tiendas
```

## Black Friday y lo que te falta comprar (`compras` en `config.yaml`)

Desde el Black Friday, **en las tiendas suena solo lo que te falta comprar** (`compras.items`): RTX
5070 Ti, RAM DDR5 32GB (2x16) 6000 CL30-36, SSD M.2 2TB Gen4/Gen5 (7.000 MB/s o más), mother B850
WiFi (TUF o equivalente), fuente 850W Gold ATX 3.1, gabinete mid tower con lugar para un 360, AIO 360,
teclado y mouse. Lo de `compras.comprado` (el Ryzen 9 9900X) no avisa más.

- **Cuándo suena** (Argentina, todo en USD MEP del día; Australia en A$):
  - bajo el objetivo (`objetivo: {AUD: 1440, USD: 1250}`): siempre;
  - X% abajo de la **mediana de 30 días** (`umbrales_baja`: placas 8, RAM/SSD/mother/fuente/gabinete/
    cooler 10, teclado y mouse 15);
  - placas: también un nuevo mínimo histórico.
  Nunca contra el "precio anterior" de la tienda.
- **Cada aviso de 🇦🇷** trae los pagos y las referencias:
  ```
  💵 Transferencia: $2.348.000
  💳 Lista: $2.720.000 · 12 cuotas sin interés de $226.700 (≈ $2.390.000 contado)
  🏦 Promo: 12 cuotas sin interés con ICBC Mastercard
  📊 Hoy: $2.348.000 (USD 1.349)
     Hace 7 días: $2.269.000 (USD 1.424)
     Hace 30 días: … (si hay datos)
     Mínimo 75 días (HardGamers): $2.581.840
  → En USD está 5% más barato que hace una semana ✅
  ```
  - **Precio real** = la transferencia o las cuotas pasadas a contado, lo que sea menor. Con eso se
    decide el objetivo y la comparación con Australia. Las cuotas se pasan a contado con la tasa de
    plazo fijo (mediana de la TNA de los bancos / 12, de api.argentinadatos.com; o un % fijo en
    `cuotas.tasa_mensual_pct`).
  - **Cuotas**: de la ficha de las 5 más baratas de cada cosa (Mexx, Gezatek y Katech; las de
    HardGamers, de la ficha de la tienda real). Compra Gamer y Maximus: de sus promos.
  - **Promos**: una vez por día, de las páginas de promos de Compra Gamer, Maximus, Mexx, Katech y
    Gezatek. Las de todos los bancos, MODO y Mercado Pago cuentan para el precio real; las de un banco
    se muestran pero cuentan solo si lo ponés en `cuotas.mis_tarjetas` (ej. `[ICBC, Galicia]`).
    No se pueden leer: las que las tiendas publican solo como imagen, y las de Venex y FullH4rd
    (nos bloquean).
  - **Mínimo de 75 días**: el "precio más bajo de los últimos N días" de las fichas de HardGamers (y
    su gráfico, que se guarda día por día). Sin eso, el de nuestro historial (desde el 16/11).
  - **⚠️ Descuento inflado**: si en los 14 días antes del 27/11 una publicación subió 5% o más en USD
    y después "bajó" sin quedar más barata que antes de subir.
- **💳 Aviso de cuotas**: si una tienda agrega o aumenta cuotas sin interés (o publica una promo de
  banco) en lo que te falta, aunque no baje el precio: "no bajó de precio, pero agregó 12 cuotas sin
  interés … ≈ $X contado → conviene / no conviene vs. transferencia", con ⚠️ si al mismo tiempo subió
  la lista más de 10% en USD.
- **Resumen de Black Friday** (`black_friday.resumen`: el 27/11 a las 9, 13 y 20 h): cada cosa con el
  precio real de hoy contra 7 y 30 días y el mínimo de 75 días, en USD MEP; cuotas y promos; y un
  veredicto: **comprar ya** (bajo el objetivo, en el mínimo o muy abajo de la mediana), **esperar** o
  **inflado**. Al final, **lo que conviene que traiga tu hermano**: la franquicia de USD 500 es una
  sola para todo, así que prueba todas las combinaciones con la aduana (50% de lo que pase) sobre el
  total y una sola valija.
- **Modo Black Friday** (20/11 al 2/12): tiendas cada 10 min (cada tienda, cada 20 min en 2 turnos),
  mothers/fuentes/etc. cada 3 h, foros cada 10 min y hasta 12 avisos con sonido por día. Si una
  tienda nos frena, la pausa se duplica cada vez (2, 4, 8 h… hasta 24 h); si una tienda argentina
  está caída (Venex: 403 desde el 18/11), sus precios se toman de HardGamers.
- **Teclado y mouse**: no avisan hasta que pongas los modelos (`modelos: [G502 X, VIPER V3]`).

## Cambiar los filtros

Editá `config.yaml`. Cada categoría tiene `activo`, sus condiciones (`chips`, `socket`,
`capacidad_gb`, etc.), `precio_max` por moneda y `objetivos`:

```yaml
placas:
  objetivos:
    RTX 5070 Ti: {AUD: 1440}                 # posts de OzBargain a ese precio o menos
ram:
  objetivos:
    32GB (2x16) 6000: {AUD: 500}             # capacidad, módulos y velocidad mínima
pcs:
  gpu_min: RTX 5070 Ti                        # esa placa o mejor (orden de perf.yaml)
  objetivo: {AUD: 3000, ARS: 4000000}
```

Cada aviso trae producto, precio, tienda, link y cuánto está por debajo del objetivo. Avisa una vez
por tienda y modelo (en PCs, por producto) y vuelve a avisar solo si baja otro 3% (`re_aviso_baja_pct`).
El objetivo solo suena si el producto además pasa los filtros de su categoría (por ejemplo `cl_max`
en RAM). Usados y reacondicionados se descartan siempre, y los posts de `marketplaces` (eBay,
Catch, MyDeal...) no avisan.

**PCs armadas**: en Australia salen de OzBargain (posts con `palabras_ozbargain`; "desktop" solo
cuenta si el título trae una placa y no es "Desktop Processor/RAM"). En Argentina, de las secciones de
PCs de Venex, Gezatek, Mexx y Compra Gamer (esta última solo vende PCs de oficina; las gamer se arman
en "Armá tu PC"). Mexx corta los nombres, así que la placa se lee de la ficha, solo de las PCs que
cuestan menos que el objetivo (hasta 8 por corrida).

Los precios argentinos se comparan con el **precio real** (transferencia o cuotas a contado); los
australianos incluyen GST. En `general` están el tope de alertas por día, el silencio nocturno (00 a
08 hora argentina: llegan sin sonido), `mostrar_tray` y `combos`. El modo Black Friday (20/11 al 2/12)
cambia la frecuencia de tiendas y foros, el umbral de votos y el tope; después vuelve solo a lo normal.

Desde el Black Friday, los objetivos de las **tiendas** están en `compras.items` (ver arriba); los de
`placas.objetivos` y `ram.objetivos` quedan para los posts de OzBargain.

## Activar a tu hermano

1. Él abre el bot en Telegram y le manda `/start`.
2. Sacás su chat_id (ver "Puesta en marcha", paso 2) y lo cargás en el secret
   `TELEGRAM_CHAT_ID_HERMANO`.
3. En `config.yaml`: `hermano: {activo: true, ...}`.

Recibe **solo lo urgente de Australia**, suena de 08:00 a 23:00 hora de Sydney (fuera de ese horario
le llega en silencio) y deja de recibir después de `fecha_viaje`.

## Agregar una tienda

1. Creá `bot/fuentes/<id>.py`:

```python
from .base import Tienda, registrar, precio_au

@registrar
class MiTienda(Tienda):
    id = "mitienda"
    nombre = "Mi Tienda"
    pais, moneda = "AU", "AUD"
    web = "https://www.mitienda.com.au"
    categorias = {"placas": ["https://www.mitienda.com.au/graphics-cards"]}

    def leer_pagina(self, url, categoria):
        arbol = self.html(self.cliente.get(url).text)
        ofertas = [self.oferta(categoria=categoria, titulo=..., url=..., precio=..., stock=...)
                   for prod in arbol.css(".producto")]
        siguiente = ...  # URL de la página siguiente o None
        return ofertas, siguiente
```

2. Probala con `python -m bot probar mitienda --guardar-html`.
3. Sumá un test en `tests/` con el HTML guardado.

Orden de preferencia para leer: datos schema.org/JSON-LD (`self.json_ld(arbol)`) → API pública de
la tienda → HTML. Si la tienda muestra captcha o un desafío anti-bots, el cliente lanza `Bloqueado`
y la tienda queda como caída: **no se evade**.

## Puesta en marcha (lo que hacés vos)

Las instrucciones paso a paso te las voy dando en el chat; acá queda el resumen:

1. **BotFather**: en Telegram, hablale a @BotFather → `/newbot` → nombre y usuario → copiá el token.
2. **Tu chat_id**: mandale cualquier mensaje a tu bot y abrí
   `https://api.telegram.org/bot<TOKEN>/getUpdates`; el número en `"chat":{"id": ...}` es tu chat_id.
   (Con el webhook del Worker puesto, `getUpdates` no anda: sacalo antes con `python -m bot webhook --borrar`.)
3. **GitHub**: repo público, subir este código, y en *Settings → Secrets and variables → Actions*
   cargar `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID_YO`.
4. **cron-job.org** (ya configurado; es lo que hace correr al bot puntual, y el `schedule` de GitHub
   queda de respaldo cada 30 min): un token de GitHub *fine-grained* con permiso
   *Actions: read and write* solo sobre este repo, y un cron cada 10 minutos que haga
   `POST https://api.github.com/repos/<usuario>/<repo>/actions/workflows/bot.yml/dispatches`
   con el cuerpo `{"ref":"main"}`.
5. **eBay** (opcional; sin esto eBay no se lee y no pasa nada):
   1. Entrá a <https://developer.ebay.com>, registrate con tu cuenta de eBay y esperá el mail de
      aprobación (suele ser en el día).
   2. *Application Keys* → creá un keyset de **Production**. El *App ID* es el Client ID y el
      *Cert ID* es el Client Secret.
   3. eBay pide, para activar el keyset, que digas qué hacés con las notificaciones de "cuenta
      borrada": elegí que **no guardás datos de usuarios de eBay** (pedí la exención). El bot solo
      usa la búsqueda pública.
   4. Cargalos sin que queden en ningún archivo del repo:
      `gh secret set EBAY_CLIENT_ID` y `gh secret set EBAY_CLIENT_SECRET` (te los pide por teclado),
      y en tu `.env` local para probar en la PC.
6. **Cloudflare** (para `/buscar`; plan gratis):
   1. Creá la cuenta en <https://dash.cloudflare.com/sign-up> y confirmá el mail. En
      *Workers & Pages* elegí el subdominio de `workers.dev` (queda `bot-ofertas.<subdominio>.workers.dev`).
   2. En una terminal, dentro de `worker/`: `npx wrangler login` (abre el navegador; autorizás vos).
   3. El resto lo hace Claude: `npx wrangler deploy`, los secretos (`TELEGRAM_TOKEN`,
      `TELEGRAM_CHAT_ID_YO` y `TELEGRAM_WEBHOOK_SECRET`, cargados con `wrangler secret put` desde el
      `.env`, sin mostrarlos) y `python -m bot webhook --url https://…workers.dev/telegram`, que apunta
      Telegram al Worker y registra el menú de comandos.

## Búsquedas desde Telegram (Worker de Cloudflare)

- **Cómo llegan los precios**: al final de cada corrida, `exportar.py` escribe `precios.json` y el
  workflow lo sube a la rama `datos` junto con la base. Tiene las 16 más baratas de cada modelo y
  país (nada sin stock, ver "Stock" abajo), las cotizaciones, las reglas de la cuenta, los posts de
  OzBargain de las últimas 48 h y los textos de `/estado` y `/filtros`. Pesa unos 220 KB.
- **El Worker** (`worker/src/index.js`) recibe cada mensaje por webhook, lee ese JSON de
  `raw.githubusercontent.com` (repo público: sin token de GitHub), lo guarda en memoria un minuto y
  responde. Parsear el JSON y buscar lleva 1 a 3 ms de CPU (el plan gratis da 10 ms por pedido).
- **Mismo normalizador**: las regexes del Worker las genera Python a partir de `normalizar.py`
  (`python -m bot generar-worker`), y `tests/test_worker.py` falla si quedaron desactualizadas o si
  el Worker entiende un título distinto que Python. Lo mismo con las líneas de la cuenta
  (`comparar.lineas_cuenta`).
- **Seguridad**: solo responde a `TELEGRAM_CHAT_ID_YO` (a cualquier otro, silencio), rechaza con 401
  todo pedido sin el `secret_token` del webhook, y el token de Telegram es un secreto de Cloudflare:
  no está en el código ni se loguea.
- **Con webhook, `getUpdates` no anda**: por eso los comandos ya no los lee la corrida de GitHub; las
  alertas sí siguen saliendo de ahí, igual que antes.
- Probarlo sin Telegram: `cd worker && node scripts/cli.mjs ../datos/precios.json "/buscar 5070 ti"`
  (antes `python -m bot exportar` arma el JSON con la base local). Tests: `npm test` en `worker/`.

## SSD (`ssd_modelos.yaml`)

En `/buscar`, en los avisos y en el resumen, un SSD es **M.2 2280 NVMe Gen4 o Gen5**: no salen los
SATA (2.5" y M.2), los externos o portátiles, los carry/enclosures, los Gen3, los de notebook
(2230/2242) ni los que no se sabe si son Gen4 o Gen5. En `/buscar` aparecen solo si los pedís:
`sata`, `externo`, `carry`, `gen3`, `2230`, `2242`.

Cada producto va en un renglón: `Samsung 990 Pro 2TB · Gen4 · 7.450/6.900 MB/s · Mwave A$249 ≈ $267.000`
(lectura/escritura secuencial; `vel. s/d` si no se sabe). La velocidad sale del título y, si no la
dice, de `ssd_modelos.yaml`: los modelos conocidos con su generación y velocidades de fábrica por
capacidad. La generación de la tabla manda sobre la del título (hay tiendas que ponen "Gen5" a un
990 Evo Plus porque anda en 5.0 x2). Para agregar un modelo: una entrada nueva en el YAML,
`python -m bot generar-worker` (el Worker usa la misma tabla) y subirlo.

- Por modelo: `/buscar 990 pro`, `/buscar samsung 990 pro`, `/buscar sn850x 4tb`, `/buscar mp700 pro`,
  `/buscar t705` ("990pro", "990 PRO" y "Samsung 990 Pro NVMe" son lo mismo).
- Por generación y capacidad: `/buscar ssd gen5 2tb au r10`, `/buscar ssd gen4 4tb`. Se combinan con
  país, marca y `r`.
- `vel` ordena por velocidad de lectura, de mayor a menor (`/buscar ssd gen4 2tb vel`); sin `vel`, por precio.
- En `resumen_diario.productos` se pueden poner SSD igual: `ssd: [990 Pro 2TB, Gen5 2TB]`.

## Stock (`bot/stock.py`)

Nada sin stock en `/buscar`, en las alertas ni en el resumen diario. Cada publicación queda en uno
de tres estados:

- **Afuera**: la tienda dice que no hay (agotado, sin stock, 0 unidades, consultar, preventa, sold
  out, out of stock, no longer available, discontinued, pre-order, back-order…), **no apareció en
  la última lectura completa** de su tienda o comparador (tabla `pasadas`, por categoría), la ficha
  de la tienda real dice que no hay, o lo marcaste "❌ Sin stock".
- **Sin confirmar** (va al final de la lista y lo dice, con el motivo): viene de staticICE o
  HardGamers y no se pudo mirar en la tienda real, la tienda no informa stock (Venex) o hace más
  de `stock.sin_confirmar_horas` (8) que no se pudo leer esa tienda. Las alertas salen igual, con
  "⚠️ Stock sin confirmar: motivo".
- **Con stock**: la tienda lo lista con stock en su última lectura, o se verificó en su página.

**Verificación en la tienda real**: lo que viene de un comparador (y lo de tiendas que no informan
stock) se mira en la página del producto: primero lo que va a avisar, después las 5 más baratas de
cada modelo y país. Como mucho `stock.verificar_por_corrida` (30) pedidos por corrida y 6 por
tienda, con pausas y robots.txt. Vale `stock.verificacion_vale_horas` (6 h) o hasta que cambie el
precio. Solo se leen datos estructurados (Shopify `/products/<handle>.js`, schema.org en JSON-LD o
microdatos, `product:availability`): nunca palabras sueltas, que en una ficha suelen ser de
banners o de otros productos. HardGamers: se abre su ficha, se sigue el link a la tienda y se mira
ahí. Si una tienda frena (403, 429, Cloudflare) o no publica stock en sus páginas, no se le vuelve
a pedir por 24 h.

| Se puede verificar | No se puede (queda "sin confirmar") |
|---|---|
| Mwave (Shopify), PLE, Austin, MegaBuy, LMC; en 🇦🇷 las tiendas de HardGamers con WooCommerce o Tiendanube (Liontech, The Gamer Shop, Maxtecno, Slot One, Shopgamer, Hydra) | Scorptec, PC Case Gear, JW, Computer Alliance y CPL (anti-bots), JB Hi-Fi (429), Officeworks, CCPU y Maco (no publican stock en la ficha) |

**"❌ Sin stock"**: cada resultado de `/buscar` y cada alerta traen el botón. Al tocarlo, el
Worker guarda la clave del link (`sha1(link)[:16]`) en KV (`OCULTOS`) y deja de mostrarlo. La
corrida siguiente lo trae (`GET /ocultos` con `WORKER_SYNC_SECRET`), lo oculta en la base y lo
vuelve a mostrar solo cuando la tienda lo deja de listar (o lo da sin stock) y después lo vuelve a
listar con stock. Solo valen tus botones (`TELEGRAM_CHAT_ID_YO`).

## Tiendas conectadas

| Tienda | País | Cómo se lee | Notas |
|---|---|---|---|
| Umart | 🇦🇺 | listados por categoría (`?page=N`) | misma empresa y servidor que MSY: van en turnos distintos y con pausas de 6–9 s |
| MSY | 🇦🇺 | igual que Umart | si reciben muchos pedidos contestan "404" a todo: el bot lo toma como freno y las deja 2 h en pausa |
| staticICE | 🇦🇺 | búsquedas armadas desde `config.yaml` | cubre PC Case Gear, Scorptec, Mwave, PLE, JW, CCPU, Computer Alliance, MegaBuy, I-Tech y más. No informa stock: el aviso lo aclara. Saltea filas sin actualizar hace más de 3 días y tiendas con precios viejos (ver abajo) |
| Compra Gamer | 🇦🇷 | el catálogo entero en un JSON (1 pedido por corrida) | precio especial (transferencia) y de lista. Saltea outlet y lo que solo se vende en combos o en "Armá tu PC" |
| Katech | 🇦🇷 | API pública de WooCommerce (100 productos por pedido) | precio efectivo/transferencia y stock. El de lista y las cuotas solo están en la ficha de cada producto: no se leen. **Desde GitHub Actions contesta 403 anti-bots** (desde una PC en Argentina anda): queda como caída, reintenta con 1 pedido cada 2 h y vuelve sola si la tienda lo permite |
| Venex | 🇦🇷 | listados de 12 (`?page=N`) | precio contado efectivo. El listado no informa stock ni precio de lista |
| Gezatek | 🇦🇷 | listados (`?page=N`) | "Precio Geza" (transferencia), precio con Mercado Pago como lista, y stock |
| Mexx | 🇦🇷 | cada categoría en una página (`?all=1`) | "Mejor precio" (efectivo/transferencia) y stock |
| Maximus | 🇦🇷 | listados (`PAGE=N`) | precio transferencia, precio de lista y stock (del JSON-LD de la página) |
| HardGamers | 🇦🇷 | comparador: listados de 54 ordenados por precio | cubre unas 45 tiendas, entre ellas **FullH4rd** (que nos bloquea). **Katech y Compra Gamer no están**. El aviso muestra la tienda real; las que ya leemos directo se saltean. Lee una categoría por corrida y solo la franja de precios que importa (búsqueda binaria), con 5–7 s entre pedidos |
| Mercado Libre | 🇦🇷 | API oficial (OAuth2): catálogo → publicaciones de cada producto | solo nuevos de tiendas oficiales o MercadoLíder. Necesita la app aprobada (ver «Mercado Libre» abajo); sin eso no se lee |
| eBay AU | 🇦🇺 | API oficial (Browse) | PCs nuevas de vendedores en Australia, con RTX 5070 Ti o más y Ryzen 7/9 o Core i7/i9/Ultra 7/9. Sigue a la **HP Official Store** (`hp_official`, confirmalo en su tienda de eBay): avisa si baja o si vuelve a tener stock un OMEN/Victus. Necesita las claves (ver arriba) |

- **Categorías de la Fase 2** (mothers, SSD, fuentes, refrigeración, gabinetes, teclados, mouse): se
  leen cada 6 h (3 h en Black Friday) y de a una por corrida, para no cargar a las tiendas. Avisan solo
  si están en `compras.items`.
- **Precios viejos en staticICE**: algunas tiendas le pasan precios desactualizados (en RAM,
  Computer & Parts Land y Austin aparecían a la mitad de lo que cobra el resto). Si la mitad o más
  de los productos de una tienda están por debajo del 75% de lo que cobran las demás por el mismo
  modelo, esa tienda no se usa en esa categoría (queda en el log).
- **Argentina**: se avisa y compara con el **precio real** (transferencia, o las cuotas pasadas a
  contado si salen menos). Las cuotas se leen solo de la ficha de las 5 más baratas de cada cosa que
  te falta (hasta 10 fichas de tiendas y 8 de HardGamers por corrida, 3 por tienda), cada 12 h en
  Black Friday. Ver «Black Friday y lo que te falta comprar».
- **OzBargain**: además del feed de *Computing*, se leen los de Amazon AU, eBay AU, Scorptec,
  PC Case Gear y JB Hi-Fi (los posts repetidos se saltean). Detecta PCs, placas, CPU, RAM y SSD.
  Si un post trae un código ("Extra 20% off with code HPNOV26"), el precio de la cuenta es el
  final con el código; los cupones de eBay sueltos avisan aparte y, si son de la tienda de HP, se
  aplican a lo que se lea de ella en los 10 días siguientes.
- **Black Friday** (`black_friday` en `config.yaml`, del 20/11 al 2/12): modo intensivo.
- `robots.txt` se respeta con comodines (`Disallow: /*sort=*`), cosa que el lector de Python no hace.

## Mercado Libre (API oficial)

Hace falta una app de Mercado Libre Developers aprobada (hoy la aprobación puede tardar hasta 10 días).

1. Completá el formulario de alta de desarrollador (https://forms.gle/2Q39SStHLJNQLjuK9) con tu cuenta
   de Mercado Libre y esperá el mail de aprobación. Te van a pedir validar tus datos personales.
2. En https://developers.mercadolibre.com.ar/devcenter/ → **Crear aplicación**:
   - Nombre y descripción: "Bot personal de precios" (uso personal, solo lectura).
   - **Redirect URI**: `https://www.mercadolibre.com.ar` (tiene que coincidir exacto con la del paso 4).
   - **Scopes**: lectura y `offline_access` (sin ese no hay refresh token). Permiso funcional:
     "Publicación y sincronización" (es el que habilita leer productos y publicaciones).
   - Sin notificaciones (no hace falta URL de callbacks).
3. Copiá el **App ID** y la **Secret Key** al `.env` local como `ML_CLIENT_ID` y `ML_CLIENT_SECRET`
   (nunca al código).
4. `python -m bot mercadolibre url` → abrí el link, aceptá, y copiá el `code=…` de la barra de
   direcciones (dura 10 minutos y se usa una vez).
5. `python -m bot mercadolibre codigo <el código>` → canjea el código, genera `ML_CLAVE` y carga los
   cuatro secretos (`ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ML_REFRESH_TOKEN`, `ML_CLAVE`) en GitHub con
   `gh secret set` (por stdin: no se imprimen).

El refresh token se usa una sola vez: en cada corrida se renueva y el nuevo se guarda **cifrado** con
`ML_CLAVE` en la base (la rama `datos` es pública). Si se pierde la base o pasan 6 meses sin usarlo,
repetí los pasos 4 y 5. Si la API contesta 401/403/429, Mercado Libre no se lee en esa corrida y no
cuenta como tienda caída.

## Fuentes que no se pueden leer

| Fuente | Estado | Motivo |
|---|---|---|
| PC Case Gear, Scorptec | bloqueadas | Cloudflare pide verificación. Se cubren con staticICE y OzBargain |
| Centre Com | bloqueada | AWS WAF "Human Verification" |
| FullH4rd | bloqueada | Cloudflare contesta 403 "Your request was blocked". Se cubre con HardGamers |
| Mwave (directo) | 429 | Shopify contesta "demasiados pedidos" aun con 1 pedido cada 15 min. Se cubre con staticICE |
| Computer & Parts Land (directo) | bloqueada | Cloudflare. Sus precios en staticICE se filtran si están desfasados |
| Reddit | fuera de la Fase 1 | RSS cortado el 13/11/2026, API sin acceso nuevo desde el 31/10/2026 y `robots.txt` con `Disallow: /` |
| Venex (directo) | 403 desde el 18/11 | contesta 403 a GitHub Actions: queda en pausa (cada vez más larga) y sus precios salen de HardGamers |
| Mercado Libre (búsqueda abierta) | 403 | `/sites/MLA/search` no contesta a servidores de datacenter: se usa el catálogo con la app (ver abajo) |
| Twitter/X | no | la API cobra por post leído |
