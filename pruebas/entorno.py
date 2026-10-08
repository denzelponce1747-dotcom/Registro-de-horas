"""Datos de prueba aislados.

Se importa antes que `app`: las rutas de datos se fijan al importar
`app.config`, así que las variables de entorno van primero.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = Path(tempfile.mkdtemp(prefix="majerie-pruebas-"))
os.environ["MAJERIE_DATOS"] = str(CARPETA)
os.environ["MAJERIE_BASE"] = str(CARPETA / "majerie.db")
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.auth import cifrar_contrasena  # noqa: E402
from app.config import Configuracion  # noqa: E402
from app.lib.feriados import obtener_feriado  # noqa: E402

CLAVE_ADMIN = "Admin12345"
CLAVE_ANA = "Prueba12345"
_SEMILLA = CARPETA / "semilla.db"


def dia_habil(fecha: date) -> bool:
    return fecha.weekday() < 5 and not obtener_feriado(fecha.isoformat())


def habiles_hacia_atras(desde: date, cuantos: int) -> date:
    """El día hábil que queda `cuantos` días hábiles antes de `desde`."""
    actual = desde
    while cuantos > 0:
        actual -= timedelta(days=1)
        if dia_habil(actual):
            cuantos -= 1
    return actual


def _sembrar() -> None:
    from app.vistas.ajustes import _base_nueva

    _SEMILLA.write_bytes(_base_nueva("admin", cifrar_contrasena(CLAVE_ADMIN)))
    hoy = date.today()
    inicio = hoy - timedelta(days=45)
    c = sqlite3.connect(_SEMILLA)
    c.execute(
        "INSERT INTO users (id, username, name, email, role, password_hash, active) "
        "VALUES ('col-ana','ana','Ana Rojas','ana@example.com','colaborador',?,1)",
        (cifrar_contrasena(CLAVE_ANA),),
    )
    c.execute(
        "INSERT INTO collaborator_settings (user_id, period_from, period_to, carried_balance_hours) "
        "VALUES ('col-ana', ?, ?, 2)",
        (inicio.isoformat(), date(hoy.year + 1, 12, 31).isoformat()),
    )
    c.execute("INSERT INTO projects (id, code, name) VALUES ('p1','ADM','Administración')")
    # Un permiso pagado con horas, hace unos días.
    permiso = habiles_hacia_atras(hoy, 6)
    numero = 0
    dia = inicio
    while dia < hoy:
        if dia_habil(dia) and dia != permiso:
            numero += 1
            fin = "17:30" if dia.day % 3 == 0 else "17:00"
            c.execute(
                "INSERT INTO time_entries (id,user_id,entry_date,start_time,end_time,project_id,"
                "project_name,notes) VALUES (?,?,?,?,?,?,?,?)",
                (f"te{numero}", "col-ana", dia.isoformat(), "08:00", fin, "p1", "Administración",
                 "Trabajo"),
            )
        dia += timedelta(days=1)
    lejos = hoy + timedelta(days=60)
    c.executemany(
        "INSERT INTO absences (id,user_id,kind,from_date,to_date,days,accumulated_hours,notes,"
        "status,decided_by,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("a-permiso", "col-ana", "permiso-personal", permiso.isoformat(), permiso.isoformat(),
             1, 8.5, "Trámite", "aprobada", "María Quesada", permiso.isoformat()),
            ("a-pend-vac", "col-ana", "vacaciones", lejos.isoformat(),
             (lejos + timedelta(days=1)).isoformat(), 2, 0, "Familia", "pendiente", "", None),
            ("a-pend-perm", "col-ana", "permiso-personal", (lejos + timedelta(days=10)).isoformat(),
             (lejos + timedelta(days=10)).isoformat(), 0.5, 4, "Cita", "pendiente", "", None),
        ],
    )
    c.commit()
    c.close()


def base_nueva() -> Path:
    """Copia limpia de la base de prueba, lista para usarse."""
    if not _SEMILLA.is_file():
        _sembrar()
    destino = CARPETA / "majerie.db"
    for sufijo in ("", "-wal", "-shm"):
        Path(str(destino) + sufijo).unlink(missing_ok=True)
    shutil.copy(_SEMILLA, destino)
    return destino


def aplicacion(almacen=None):
    """Aplicación de prueba sobre una base limpia, con su configuración aparte."""
    from app import crear_app

    base_nueva()
    configuracion = CARPETA / "configuracion.json"
    configuracion.unlink(missing_ok=True)
    app = crear_app(Configuracion(configuracion), almacen, None)
    app.config["TESTING"] = True
    return app


def entrar(cliente, usuario: str, clave: str, identidad: str = "María Quesada") -> None:
    respuesta = cliente.post("/ingresar", data={"username": usuario, "password": clave})
    assert respuesta.status_code == 302, respuesta.get_data(as_text=True)[:400]
    if usuario == "admin":
        cliente.post("/identidad", data={"identidad": identidad})
