"""Base SQLite. Guarda cada oferta una vez y el historial de precios SOLO cuando cambia,
así la base crece poco (unos pocos MB por año)."""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .modelos import Oferta, Post

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ofertas(
  id INTEGER PRIMARY KEY, tienda TEXT NOT NULL, pais TEXT NOT NULL, categoria TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE, titulo TEXT, modelo TEXT, variante TEXT, datos TEXT,
  moneda TEXT, precio REAL, precio_lista REAL, cuotas TEXT, tipo_precio TEXT, stock INTEGER,
  tray INTEGER DEFAULT 0, combo INTEGER DEFAULT 0, sku TEXT, sospechoso INTEGER DEFAULT 0,
  primera_vez TEXT, ultima_vez TEXT);
CREATE INDEX IF NOT EXISTS ix_ofertas_modelo ON ofertas(modelo, pais);
CREATE TABLE IF NOT EXISTS precios(
  oferta_id INTEGER NOT NULL, ts TEXT NOT NULL, precio REAL, precio_lista REAL, stock INTEGER);
CREATE INDEX IF NOT EXISTS ix_precios_oferta ON precios(oferta_id, ts);
CREATE TABLE IF NOT EXISTS posts(
  fuente TEXT, id TEXT, titulo TEXT, url TEXT, publicado TEXT, visto TEXT, votos INTEGER,
  url_tienda TEXT, precio REAL, moneda TEXT, modelos TEXT, notificado INTEGER DEFAULT 0,
  PRIMARY KEY(fuente, id));
CREATE TABLE IF NOT EXISTS cotizaciones(ts TEXT, mep REAL, aud_usd REAL);
CREATE TABLE IF NOT EXISTS alertas(
  id INTEGER PRIMARY KEY, ts TEXT, tipo TEXT, clave TEXT, precio REAL, sono INTEGER,
  destino TEXT, texto TEXT);
CREATE INDEX IF NOT EXISTS ix_alertas_clave ON alertas(clave, ts);
CREATE TABLE IF NOT EXISTS corridas_tienda(
  ts TEXT, tienda TEXT, ok INTEGER, productos INTEGER, error TEXT, segundos REAL);
CREATE TABLE IF NOT EXISTS estado(clave TEXT PRIMARY KEY, valor TEXT);
"""


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, ruta: Path | str):
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(str(ruta), check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(ESQUEMA)

    def cerrar(self):
        self.c.commit()
        self.c.close()

    # ------------------------------------------------------------ ofertas

    def guardar_oferta(self, o: Oferta) -> dict:
        """Inserta o actualiza. Devuelve {'id', 'nueva', 'precio_antes', 'stock_antes'}."""
        ts = _iso(o.fecha)
        fila = self.c.execute("SELECT id, precio, stock FROM ofertas WHERE url=?", (o.url,)).fetchone()
        valores = (o.tienda, o.pais, o.categoria, o.titulo, o.modelo, o.variante,
                   json.dumps(o.datos, ensure_ascii=False), o.moneda, o.precio, o.precio_lista,
                   o.cuotas, o.tipo_precio, None if o.stock is None else int(o.stock),
                   int(o.tray), int(o.combo), o.sku)
        if fila is None:
            cur = self.c.execute(
                "INSERT INTO ofertas(tienda,pais,categoria,titulo,modelo,variante,datos,moneda,precio,"
                "precio_lista,cuotas,tipo_precio,stock,tray,combo,sku,primera_vez,ultima_vez,url) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*valores, ts, ts, o.url))
            oid = cur.lastrowid
            self.c.execute("INSERT INTO precios VALUES(?,?,?,?,?)",
                           (oid, ts, o.precio, o.precio_lista, valores[12]))
            return {"id": oid, "nueva": True, "precio_antes": None, "stock_antes": None}
        oid = fila["id"]
        self.c.execute(
            "UPDATE ofertas SET tienda=?,pais=?,categoria=?,titulo=?,modelo=?,variante=?,datos=?,"
            "moneda=?,precio=?,precio_lista=?,cuotas=?,tipo_precio=?,stock=?,tray=?,combo=?,sku=?,"
            "ultima_vez=? WHERE id=?", (*valores, ts, oid))
        stock_nuevo = valores[12]
        if fila["precio"] != o.precio or fila["stock"] != stock_nuevo:
            self.c.execute("INSERT INTO precios VALUES(?,?,?,?,?)",
                           (oid, ts, o.precio, o.precio_lista, stock_nuevo))
        return {"id": oid, "nueva": False, "precio_antes": fila["precio"],
                "stock_antes": None if fila["stock"] is None else bool(fila["stock"])}

    def marcar_sospechoso(self, oferta_id: int, valor: bool):
        self.c.execute("UPDATE ofertas SET sospechoso=? WHERE id=?", (int(valor), oferta_id))

    def minimo_historico(self, modelo: str, pais: str, antes_de: datetime,
                         excluir_tray: bool = False) -> tuple[float | None, datetime | None]:
        """Mínimo de precio (con stock) del modelo en el país, ANTES de esta corrida.
        Devuelve (mínimo, fecha del primer dato) para saber cuánto historial hay."""
        filtro_tray = "AND o.tray=0" if excluir_tray else ""
        fila = self.c.execute(
            f"SELECT MIN(p.precio) m, MIN(p.ts) desde FROM precios p JOIN ofertas o ON o.id=p.oferta_id "
            f"WHERE o.modelo=? AND o.pais=? AND p.ts<? AND (p.stock IS NULL OR p.stock=1) "
            f"AND o.sospechoso=0 AND o.combo=0 {filtro_tray}",
            (modelo, pais, _iso(antes_de))).fetchone()
        desde = datetime.fromisoformat(fila["desde"]) if fila["desde"] else None
        return fila["m"], desde

    def precios_actuales(self, modelo: str, pais: str, horas: int = 48) -> list[sqlite3.Row]:
        limite = _iso(datetime.now(timezone.utc) - timedelta(hours=horas))
        return self.c.execute(
            "SELECT * FROM ofertas WHERE modelo=? AND pais=? AND ultima_vez>=? "
            "AND (stock IS NULL OR stock=1) AND combo=0 ORDER BY precio", (modelo, pais, limite)).fetchall()

    def mediana(self, modelo: str, pais: str) -> float | None:
        precios = [r["precio"] for r in self.precios_actuales(modelo, pais) if r["precio"]]
        return statistics.median(precios) if len(precios) >= 3 else None

    def mejor(self, modelo: str, pais: str) -> sqlite3.Row | None:
        for r in self.precios_actuales(modelo, pais):
            if not r["sospechoso"]:
                return r
        return None

    def ofertas_recientes(self, pais: str | None = None, horas: int = 48) -> list[sqlite3.Row]:
        limite = _iso(datetime.now(timezone.utc) - timedelta(hours=horas))
        q = "SELECT * FROM ofertas WHERE ultima_vez>=? AND modelo IS NOT NULL"
        args: list = [limite]
        if pais:
            q += " AND pais=?"
            args.append(pais)
        return self.c.execute(q, args).fetchall()

    # ------------------------------------------------------------ posts

    def guardar_post(self, p: Post, modelos: list[str]) -> dict:
        fila = self.c.execute("SELECT votos, notificado FROM posts WHERE fuente=? AND id=?",
                              (p.fuente, p.id)).fetchone()
        ahora = _iso(datetime.now(timezone.utc))
        if fila is None:
            self.c.execute("INSERT INTO posts VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
                           (p.fuente, p.id, p.titulo, p.url, _iso(p.publicado), ahora, p.votos,
                            p.url_tienda, p.precio, p.moneda, json.dumps(modelos)))
            return {"nuevo": True, "notificado": False}
        self.c.execute("UPDATE posts SET votos=? WHERE fuente=? AND id=?", (p.votos, p.fuente, p.id))
        return {"nuevo": False, "notificado": bool(fila["notificado"])}

    def marcar_post_notificado(self, fuente: str, id_: str):
        self.c.execute("UPDATE posts SET notificado=1 WHERE fuente=? AND id=?", (fuente, id_))

    # ------------------------------------------------------------ alertas

    def ultima_alerta(self, clave: str) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM alertas WHERE clave=? ORDER BY ts DESC LIMIT 1",
                              (clave,)).fetchone()

    def registrar_alerta(self, tipo: str, clave: str, precio: float | None, sono: bool,
                         destino: str, texto: str):
        self.c.execute("INSERT INTO alertas(ts,tipo,clave,precio,sono,destino,texto) VALUES(?,?,?,?,?,?,?)",
                       (_iso(datetime.now(timezone.utc)), tipo, clave, precio, int(sono), destino, texto))

    def sonaron_desde(self, desde: datetime, destino: str) -> int:
        return self.c.execute("SELECT COUNT(*) FROM alertas WHERE sono=1 AND destino=? AND ts>=?",
                              (destino, _iso(desde))).fetchone()[0]

    # ------------------------------------------------------------ varios

    def registrar_tienda(self, tienda: str, ok: bool, productos: int, error: str | None, segundos: float):
        self.c.execute("INSERT INTO corridas_tienda VALUES(?,?,?,?,?,?)",
                       (_iso(datetime.now(timezone.utc)), tienda, int(ok), productos, error, segundos))

    def guardar_cotizacion(self, mep: float | None, aud_usd: float | None):
        """Guarda lo que se pudo bajar (la que falló queda NULL)."""
        self.c.execute("INSERT INTO cotizaciones VALUES(?,?,?)",
                       (_iso(datetime.now(timezone.utc)), mep, aud_usd))

    def ultima_cotizacion(self, cual: str = "mep") -> sqlite3.Row | None:
        """La última fila con esa cotización ('mep' o 'aud_usd')."""
        assert cual in ("mep", "aud_usd")
        return self.c.execute(f"SELECT * FROM cotizaciones WHERE {cual} IS NOT NULL "
                              "ORDER BY ts DESC LIMIT 1").fetchone()

    def vigentes(self, pais: str, categoria: str, desde: datetime) -> list[sqlite3.Row]:
        """Ofertas con stock (o stock desconocido) vistas desde 'desde', sin sospechosas ni combos."""
        return self.c.execute(
            "SELECT * FROM ofertas WHERE pais=? AND categoria=? AND ultima_vez>=? AND modelo IS NOT NULL "
            "AND sospechoso=0 AND combo=0 AND (stock IS NULL OR stock=1) ORDER BY precio",
            (pais, categoria, _iso(desde))).fetchall()

    def get(self, clave: str, defecto: str | None = None) -> str | None:
        fila = self.c.execute("SELECT valor FROM estado WHERE clave=?", (clave,)).fetchone()
        return fila["valor"] if fila else defecto

    def set(self, clave: str, valor: str):
        self.c.execute("INSERT INTO estado VALUES(?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                       (clave, valor))

    def commit(self):
        self.c.commit()
