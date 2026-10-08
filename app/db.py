"""Acceso a la base de datos.

La base es la copia de trabajo local de los datos que viven en SharePoint
(`app/nube/almacen.py`). La interfaz es la misma que usaba el sistema
original —`consultar`, `consultar_una`, `ejecutar`, `transaccion`— para que
la capa de datos se lea igual.

Dos detalles importan por SharePoint:

- **Diario clásico, no WAL.** Con WAL, lo último guardado puede quedar en un
  archivo aparte (`-wal`) y no en la base; al subirla faltaría. Con el
  diario clásico, al confirmar, todo está en el archivo principal.
- **Una conexión por petición, cerrada al terminar.** El almacén reemplaza
  el archivo cuando llega una versión de otra computadora, y Windows no deja
  reemplazar un archivo abierto.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from flask import current_app, g, has_app_context

from . import config


def ruta_base():
    """La base de la aplicación en curso (cada computadora simulada en las
    pruebas tiene la suya); fuera de una petición, la de siempre."""
    if has_app_context():
        return current_app.config.get("RUTA_BASE") or config.ARCHIVO_BASE
    return config.ARCHIVO_BASE


def _abrir(ruta=None) -> sqlite3.Connection:
    from pathlib import Path

    destino = Path(ruta or ruta_base())
    destino.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(destino, timeout=15)
    conexion.row_factory = sqlite3.Row
    # Diario clásico (el de SQLite por omisión): todo lo confirmado queda en
    # el archivo principal, listo para subirse.
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA busy_timeout = 8000")
    return conexion


def conexion() -> sqlite3.Connection:
    """Conexión de la petición en curso, reutilizada mientras dura."""
    if "conexion_db" not in g:
        g.conexion_db = _abrir()
    return g.conexion_db


def cerrar(_error=None) -> None:
    conexion_actual = g.pop("conexion_db", None)
    if conexion_actual is not None:
        conexion_actual.close()


@contextmanager
def conexion_suelta(ruta=None):
    """Conexión fuera de una petición web (pruebas, preparación)."""
    conexion_nueva = _abrir(ruta)
    try:
        yield conexion_nueva
        conexion_nueva.commit()
    finally:
        conexion_nueva.close()


def consultar(sql: str, parametros=()) -> list[sqlite3.Row]:
    return conexion().execute(sql, parametros).fetchall()


def consultar_una(sql: str, parametros=()) -> sqlite3.Row | None:
    """Primera fila del resultado, o None si la consulta no devolvió nada."""
    return conexion().execute(sql, parametros).fetchone()


def ejecutar(sql: str, parametros=()) -> int:
    """Ejecuta una sentencia y confirma; devuelve las filas afectadas."""
    conexion_actual = conexion()
    cursor = conexion_actual.execute(sql, parametros)
    conexion_actual.commit()
    return cursor.rowcount


@contextmanager
def transaccion():
    """Varias sentencias que se aplican o se deshacen juntas."""
    conexion_actual = conexion()
    try:
        yield conexion_actual
        conexion_actual.commit()
    except Exception:
        conexion_actual.rollback()
        raise


def aplicar_esquema(conexion_destino: sqlite3.Connection) -> None:
    """Crea las tablas si no existen y pone la base al día. Es idempotente."""
    from .migraciones import aplicar_esquema as crear, migrar

    crear(conexion_destino)
    migrar(conexion_destino)
    conexion_destino.commit()


def registrar(aplicacion) -> None:
    """Engancha el cierre de la conexión al final de cada petición."""
    aplicacion.teardown_appcontext(cerrar)
