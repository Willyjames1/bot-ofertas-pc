# Bot de ofertas de hardware 🇦🇷 🇦🇺

Bot de Telegram personal que recorre tiendas de Argentina y Australia, guarda el precio de
todos los productos de las categorías que seguimos (placas de video, CPU y RAM en la Fase 1),
lee OzBargain y me avisa **solo** de lo que pasa mis filtros de `config.yaml`.

- **Suena** (pocas veces por semana): precio bajo el objetivo, nuevo mínimo histórico, post de
  OzBargain muy votado en su primera hora y "oportunidad fuerte" (una gama más alta al precio de una
  más baja).
- **Todo lo demás** (bajas, vuelta de stock, gangas, posts nuevos) se guarda para el resumen diario
  (Fase 2).
- Las alertas de Australia traen la línea **"¿conviene traerlo?"**: precio AUD × AUD/USD × MEP × (1 − 1/11)
  por el reintegro del TRS, comparado con el mejor precio argentino de transferencia, y la línea
  "Si te cobran aduana: +$X" (50% de lo que pase los USD 500 de franquicia). Ojo: la franquicia es
  **por viajero y por viaje**, no por producto.

## Cómo está armado

```
bot/
  config.py        carga config.yaml, .env y el modo Black Friday
  modelos.py       Oferta y Post
  normalizar.py    título → modelo canónico; descarta usados, notebooks, PCs armadas
  fuentes/         un archivo por tienda, todos con la misma interfaz (base.py)
  feeds.py         OzBargain por RSS (ignora expirados, agotados y posts de más de 7 días)
  cotizaciones.py  MEP (dolarapi.com) y AUD/USD (frankfurter) + cálculo de "conviene"
  alertas.py       filtros, objetivos, mínimos, oportunidades, tope diario, silencio nocturno
  telegram.py      envío y lectura de comandos (solo chat_id autorizados)
  db.py            SQLite: el historial guarda solo los CAMBIOS de precio
  corrida.py       una corrida completa
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

## Cambiar los filtros

Editá `config.yaml`. Cada categoría tiene `activo`, sus condiciones (`chips`, `socket`,
`capacidad_gb`, etc.), `precio_max` por moneda y `objetivos`:

```yaml
placas:
  objetivos:
    RTX 5070 Ti: {AUD: 1500, ARS: 2100000}   # suena si alguna tienda lo pone a ese precio o menos
```

Los precios argentinos se comparan con el de **transferencia/contado**; los australianos incluyen GST.
En `general` están el tope de alertas por día, el silencio nocturno (00 a 08 hora argentina: llegan
sin sonido), `aduana`, `mostrar_tray` y `combos`. El modo Black Friday (23/11 al 1/12) cambia solo
la frecuencia de los foros, el umbral de votos y el tope; después vuelve solo a lo normal.

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
3. **GitHub**: repo público, subir este código, y en *Settings → Secrets and variables → Actions*
   cargar `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID_YO`.
4. **cron-job.org** (para que corra puntual): un token de GitHub *fine-grained* con permiso
   *Actions: read and write* solo sobre este repo, y un cron cada 10 minutos que haga
   `POST https://api.github.com/repos/<usuario>/<repo>/actions/workflows/bot.yml/dispatches`
   con el cuerpo `{"ref":"main"}`.

## Tiendas conectadas

| Tienda | País | Cómo se lee | Notas |
|---|---|---|---|
| Umart | 🇦🇺 | listados por categoría (`?page=N`) | misma empresa y servidor que MSY: van en turnos distintos y con pausas de 6–9 s |
| MSY | 🇦🇺 | igual que Umart | si reciben muchos pedidos contestan "404" a todo: el bot lo toma como freno y las deja 2 h en pausa |
| staticICE | 🇦🇺 | búsquedas armadas desde `config.yaml` | cubre PC Case Gear, Scorptec, Mwave, PLE, JW, CCPU, Computer Alliance, MegaBuy, I-Tech y más. No informa stock: el aviso lo aclara. Saltea filas sin actualizar hace más de 3 días y tiendas con precios viejos (ver abajo) |

- **Categorías de la Fase 2** (mothers, SSD, fuentes, refrigeración): se guardan pero todavía no
  avisan. Se leen cada 6 h y de a una por corrida, para no cargar a las tiendas.
- **Precios viejos en staticICE**: algunas tiendas le pasan precios desactualizados (en RAM,
  Computer & Parts Land y Austin aparecían a la mitad de lo que cobra el resto). Si la mitad o más
  de los productos de una tienda están por debajo del 75% de lo que cobran las demás por el mismo
  modelo, esa tienda no se usa en esa categoría (queda en el log).
- `robots.txt` se respeta con comodines (`Disallow: /*sort=*`), cosa que el lector de Python no hace.

## Fuentes que no se pueden leer

| Fuente | Estado | Motivo |
|---|---|---|
| PC Case Gear, Scorptec | bloqueadas | Cloudflare pide verificación. Se cubren con staticICE y OzBargain |
| Centre Com | bloqueada | AWS WAF "Human Verification" |
| Mwave (directo) | 429 | Shopify contesta "demasiados pedidos" aun con 1 pedido cada 15 min. Se cubre con staticICE |
| Computer & Parts Land (directo) | bloqueada | Cloudflare. Sus precios en staticICE se filtran si están desfasados |
| Reddit | fuera de la Fase 1 | RSS cortado el 13/11/2026, API sin acceso nuevo desde el 31/10/2026 y `robots.txt` con `Disallow: /` |
| Mercado Libre | Fase 3 | la API pide token OAuth (sin token: 403) |
| Twitter/X | no | la API cobra por post leído |
