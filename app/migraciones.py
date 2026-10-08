"""Versiones del esquema de la base.

La base viaja entre computadoras que pueden tener versiones distintas del
programa. `PRAGMA user_version` dice con qué esquema se escribió:

- **0**: el de la versión con servidor y ventana negra.
- **1**: esta versión. Agrega el corte de vacaciones de cada persona, el
  historial de cambios y la tabla `meta`.

Cada paso es idempotente: se puede correr dos veces sin romper nada. Una
base con un esquema MÁS NUEVO que el del programa no se toca: el almacén la
deja en solo lectura y pide actualizar.
"""

from __future__ import annotations

import sqlite3

from .config import ARCHIVO_ESQUEMA

ESQUEMA_ACTUAL = 1


def _columnas(conexion: sqlite3.Connection, tabla: str) -> set[str]:
    return {fila[1] for fila in conexion.execute(f"PRAGMA table_info({tabla})")}


def _tablas(conexion: sqlite3.Connection) -> set[str]:
    return {
        fila[0]
        for fila in conexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def aplicar_esquema(conexion: sqlite3.Connection) -> None:
    """Crea las tablas que falten (para una base nueva)."""
    conexion.executescript(ARCHIVO_ESQUEMA.read_text(encoding="utf-8"))


def _a_version_1(conexion: sqlite3.Connection) -> None:
    # Corte de vacaciones por persona: lo mueve «Trasladar el saldo al año
    # siguiente». Las bases de la versión anterior no lo tienen.
    #
    if "vacation_since" not in _columnas(conexion, "collaborator_settings"):
        conexion.execute("ALTER TABLE collaborator_settings ADD COLUMN vacation_since TEXT")

    conexion.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
          clave TEXT PRIMARY KEY,
          valor TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS historial (
          id      INTEGER PRIMARY KEY AUTOINCREMENT,
          momento TEXT NOT NULL,
          usuario TEXT NOT NULL DEFAULT '',
          cuenta  TEXT NOT NULL DEFAULT '',
          equipo  TEXT NOT NULL DEFAULT '',
          accion  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS absences_user_from_idx ON absences (user_id, from_date);
        """
    )


def migrar(conexion: sqlite3.Connection) -> int:
    """Pone la base al día. Devuelve el esquema con que quedó.

    No escribe nada si la base ya está al día, para no tocar el contador de
    cambios de SQLite sin necesidad.
    """
    version = conexion.execute("PRAGMA user_version").fetchone()[0]
    if version >= ESQUEMA_ACTUAL:
        return version

    if "users" not in _tablas(conexion):
        aplicar_esquema(conexion)

    if version < 1:
        _a_version_1(conexion)

    conexion.execute(f"PRAGMA user_version = {ESQUEMA_ACTUAL}")
    return ESQUEMA_ACTUAL
