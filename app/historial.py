"""Historial de cambios: quién cambió qué, cuándo y desde qué computadora.

Ahora cada persona guarda desde su propia computadora, así que conviene
poder responder «¿quién aprobó esto?» o «¿desde dónde se cambió esa
tarifa?». Cada acción que modifica datos deja una línea aquí, dentro de la
misma transacción que el cambio. Se conservan las últimas `MAXIMO` líneas
para que la base no engorde sin límite.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from flask import current_app, has_app_context

from .config import nombre_equipo

MAXIMO = 1500


def _quien() -> str:
    try:
        from .auth import usuario_de_sesion

        usuario = usuario_de_sesion()
    except Exception:
        usuario = None
    return usuario.actingAs if usuario else ""


def _cuenta_microsoft() -> str:
    if not has_app_context():
        return ""
    almacen = current_app.config.get("ALMACEN")
    return almacen.cuenta.info().get("correo", "") if almacen is not None else ""


def anotar(accion: str, usuario: str | None = None) -> None:
    """Deja constancia de una acción. Nunca interrumpe la acción misma."""
    from .db import conexion

    try:
        cx = conexion()
        cx.execute(
            "INSERT INTO historial (momento, usuario, cuenta, equipo, accion) VALUES (?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                usuario if usuario is not None else _quien(),
                _cuenta_microsoft(),
                nombre_equipo(),
                accion[:400],
            ),
        )
        cx.execute(
            "DELETE FROM historial WHERE id <= (SELECT MAX(id) FROM historial) - ?", (MAXIMO,)
        )
        cx.commit()
    except sqlite3.Error:
        return


def recientes(limite: int = 200, filtro: str = "") -> list[sqlite3.Row]:
    from .db import consultar

    try:
        if filtro:
            patron = f"%{filtro.strip()}%"
            return consultar(
                "SELECT * FROM historial WHERE accion LIKE ? OR usuario LIKE ? "
                "OR cuenta LIKE ? OR equipo LIKE ? ORDER BY id DESC LIMIT ?",
                (patron, patron, patron, patron, limite),
            )
        return consultar("SELECT * FROM historial ORDER BY id DESC LIMIT ?", (limite,))
    except sqlite3.Error:
        return []
