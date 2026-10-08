"""Todas las mutaciones del sistema. Puerto de `src/server/actions.ts`.

Cada función comprueba el perfil de quien actúa, valida lo que llega y deja
la base en su nuevo estado. Devuelven siempre un diccionario con `ok`, para
que las pantallas decidan si muestran un aviso de éxito o de error, tal como
hacía la versión original con `ActionResult`.

Ahora varias computadoras guardan sobre los mismos datos (SharePoint). Por
eso las aprobaciones comprueban que lo aprobado siga pendiente: la otra
persona administradora pudo resolverlo un minuto antes desde su equipo.
Cada cambio deja además una línea en el historial (`app/historial.py`).
"""

from __future__ import annotations

import json
import re
from datetime import date

from .auth import (
    cifrar_contrasena,
    es_identidad_admin,
    problema_contrasena,
    verificar_contrasena,
)
from .db import consultar, consultar_una, ejecutar, transaccion
from .historial import anotar
from .lib.ajustes import AJUSTES_BASE
from .lib.almuerzo import ajustar_al_paso
from .lib.aprobaciones import motivo_aprobacion, requiere_aprobacion
from .lib.ausencias import ETIQUETAS_TIPO, admite_horas_acumuladas
from .lib.tarifas import formatear_tarifa
from .lib.tiempo import a_minutos, formatear_fecha, hoy_iso, parsear_iso
from .lib.tipos import HEREDADA, MONEDAS
from .lib.usuarios import crear_id, crear_id_usuario, normalizar_usuario, problema_usuario


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
# Largo máximo de las observaciones de un registro o de una ausencia.
LARGO_MAXIMO_NOTA = 2000


def bien(mensaje: str = "", pendiente: bool = False, historial: str = "") -> dict:
    if historial:
        anotar(historial)
    return {"ok": True, "message": mensaje, "pending": pendiente}


def mal(error: str) -> dict:
    return {"ok": False, "error": error}


def columnas_tarifa(tarifa):
    """Descompone una tarifa heredable en las tres columnas que guarda la base."""
    if tarifa is HEREDADA:
        return ("heredada", None, None)
    if tarifa is None:
        return ("sin-tarifa", None, None)
    return ("propia", tarifa.amount, tarifa.currency)


def problema_tarifa(tarifa) -> str | None:
    """Una tarifa propia necesita un valor positivo y una moneda conocida."""
    if tarifa is HEREDADA or tarifa is None:
        return None
    if tarifa.currency not in MONEDAS:
        return "Elija una moneda válida para la tarifa."
    if not tarifa.amount or tarifa.amount <= 0:
        return ("La tarifa por hora debe ser mayor que cero. Si no corresponde cobrar, "
                "elija «Sin tarifa asignada».")
    if tarifa.amount > 100_000_000:
        return "La tarifa es demasiado alta. Revise el valor."
    return None


def _o_none(valor):
    """Vacío se trata como «no lo cambies».

    Las sentencias UPDATE usan COALESCE para dejar intacto lo que no viene en
    los cambios, y COALESCE no distingue una cadena vacía de un valor: hay que
    convertirla a NULL antes.
    """
    if valor is None:
        return None
    limpio = str(valor).strip()
    return limpio or None


def _salta_aprobacion(usuario) -> bool:
    """El administrador salta la ventana: sus cambios se aplican ya."""
    return usuario.role == "administrador"


def _registro_propio(usuario, registro_id: str):
    """Comprueba que el registro exista y que quien actúa pueda tocarlo."""
    fila = consultar_una(
        "SELECT id, user_id, entry_date, start_time, end_time, project_id, status, pending_action "
        "FROM time_entries WHERE id = ?",
        (registro_id,),
    )
    if not fila:
        return None
    if usuario.role != "administrador" and fila["user_id"] != usuario.id:
        return None
    return fila


_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _problema_jornada(fecha: str, inicio: str, fin: str) -> str | None:
    if not parsear_iso(fecha):
        return "Indique una fecha válida."
    if not _HORA.match(inicio or "") or not _HORA.match(fin or ""):
        return "Indique las horas con el formato HH:MM."
    if a_minutos(fin) <= a_minutos(inicio):
        return "La hora de finalización debe ser posterior a la de inicio."
    return None


def _problema_proyecto(usuario, proyecto_id: str, permitir: str = "") -> str | None:
    """El proyecto debe existir, estar activo y ser visible para la persona.

    `permitir` deja pasar el proyecto que el registro ya tenía, aunque ahora
    esté inactivo: editar las observaciones de un registro viejo no debería
    obligar a cambiarle el proyecto.
    """
    fila = consultar_una("SELECT id, owner_id, active FROM projects WHERE id = ?", (proyecto_id,))
    if not fila:
        return "Elija un proyecto de la lista."
    if usuario.role != "administrador" and fila["owner_id"] not in (None, usuario.id):
        return "Ese proyecto no está disponible para usted."
    if not fila["active"] and proyecto_id != permitir:
        return "Ese proyecto está inactivo. Elija otro."
    return None


def _traslape(usuario_id: str, fecha: str, inicio: str, fin: str, excepto: str = ""):
    """Otra actividad de la misma persona que se cruza con este horario."""
    desde, hasta = a_minutos(inicio), a_minutos(fin)
    for fila in consultar(
        "SELECT id, start_time, end_time FROM time_entries "
        "WHERE user_id = ? AND entry_date = ? AND id <> ? AND pending_action <> 'eliminacion'",
        (usuario_id, fecha, excepto),
    ):
        if a_minutos(fila["start_time"]) < hasta and desde < a_minutos(fila["end_time"]):
            return fila
    return None


def _nombre_de(usuario_id: str) -> str:
    fila = consultar_una("SELECT name FROM users WHERE id = ?", (usuario_id,))
    return fila["name"] if fila else "una persona"


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------
def ingresar(usuario_texto: str, contrasena: str) -> dict:
    nombre = normalizar_usuario(usuario_texto)
    if not nombre or not contrasena:
        return mal("Indique el usuario y la contraseña.")

    fila = consultar_una(
        "SELECT id, role, password_hash, active FROM users WHERE username = ?",
        (nombre,),
    )
    # Con un usuario que no existe se verifica igual contra una huella de
    # relleno: así la respuesta tarda lo mismo y no delata qué usuarios
    # existen.
    huella = (
        fila["password_hash"]
        if fila
        else "scrypt$16384$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAA"
    )
    valida = verificar_contrasena(contrasena, huella)

    if not fila or not valida or not fila["active"]:
        return mal("Usuario o contraseña incorrectos.")

    return {"ok": True, "id": fila["id"], "role": fila["role"]}


def elegir_identidad(usuario, identidad: str) -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración elige identidad.")
    if not es_identidad_admin(identidad):
        return mal("Identidad no válida.")
    return {"ok": True, "identity": identidad}


def cambiar_contrasena_propia(usuario, actual: str, nueva: str) -> dict:
    """Cambio de contraseña de la propia cuenta."""
    if not usuario:
        return mal("Sesión no iniciada.")

    problema = problema_contrasena(nueva)
    if problema:
        return mal(problema)
    if nueva == actual:
        return mal("La contraseña nueva debe ser distinta de la actual.")

    fila = consultar_una("SELECT password_hash FROM users WHERE id = ?", (usuario.id,))
    if not fila or not verificar_contrasena(actual, fila["password_hash"]):
        return mal("La contraseña actual no es correcta.")

    ejecutar(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (cifrar_contrasena(nueva), usuario.id),
    )
    return bien("Contraseña actualizada.", historial="Cambió su propia contraseña")


# ---------------------------------------------------------------------------
# Registros de horas
# ---------------------------------------------------------------------------
def agregar_registro(usuario, registro: dict) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")
    if usuario.role != "administrador" and registro["userId"] != usuario.id:
        return mal("No puede registrar horas de otra persona.")
    notas = (registro.get("notes") or "").strip()
    if not notas:
        return mal("Las observaciones son obligatorias.")
    if len(notas) > LARGO_MAXIMO_NOTA:
        return mal(f"Las observaciones no pueden pasar de {LARGO_MAXIMO_NOTA} caracteres.")

    problema = (_problema_jornada(registro["date"], registro["start"], registro["end"])
                or _problema_proyecto(usuario, registro["projectId"]))
    if problema:
        return mal(problema)

    choque = _traslape(registro["userId"], registro["date"], registro["start"], registro["end"])
    if choque:
        return mal(
            "Ese horario se cruza con otra actividad del mismo día ("
            f"{choque['start_time']} – {choque['end_time']})."
        )

    hoy = hoy_iso()
    pendiente = not _salta_aprobacion(usuario) and requiere_aprobacion(registro["date"], hoy)
    motivo = motivo_aprobacion(registro["date"], "creacion", hoy) if pendiente else ""

    ejecutar(
        """INSERT INTO time_entries
             (id, user_id, entry_date, start_time, end_time, project_id,
              project_name, notes, status, pending_action, pending_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            crear_id("entry"),
            registro["userId"],
            registro["date"],
            registro["start"],
            registro["end"],
            registro["projectId"],
            registro["projectName"],
            notas,
            "pendiente" if pendiente else "aprobado",
            "creacion" if pendiente else "",
            motivo,
        ),
    )

    detalle = (f"actividad del {formatear_fecha(registro['date'])} ("
               f"{registro['start']}–{registro['end']}, {registro['projectName']})")
    return bien(
        motivo if pendiente else "Registro guardado.",
        pendiente,
        historial=("Envió a aprobación una " if pendiente else "Registró una ") + detalle,
    )


def actualizar_registro(usuario, registro_id: str, cambios: dict) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")

    existente = _registro_propio(usuario, registro_id)
    if not existente:
        return mal("El registro no existe.")
    if "notes" in cambios:
        notas = (cambios["notes"] or "").strip()
        if not notas:
            return mal("Las observaciones son obligatorias.")
        if len(notas) > LARGO_MAXIMO_NOTA:
            return mal(f"Las observaciones no pueden pasar de {LARGO_MAXIMO_NOTA} caracteres.")
    if existente["pending_action"] == "eliminacion":
        return mal("Ese registro tiene una eliminación pendiente de aprobación.")

    fecha_nueva = _o_none(cambios.get("date")) or existente["entry_date"]
    inicio = _o_none(cambios.get("start")) or existente["start_time"]
    fin = _o_none(cambios.get("end")) or existente["end_time"]
    proyecto = _o_none(cambios.get("projectId")) or existente["project_id"]

    problema = (_problema_jornada(fecha_nueva, inicio, fin)
                or _problema_proyecto(usuario, proyecto, permitir=existente["project_id"]))
    if problema:
        return mal(problema)

    choque = _traslape(existente["user_id"], fecha_nueva, inicio, fin, excepto=registro_id)
    if choque:
        return mal(
            "Ese horario se cruza con otra actividad del mismo día ("
            f"{choque['start_time']} – {choque['end_time']})."
        )

    hoy = hoy_iso()
    # Mover un registro a una fecha vieja también requiere aprobación.
    mas_antigua = min(fecha_nueva, existente["entry_date"])
    pendiente = not _salta_aprobacion(usuario) and requiere_aprobacion(mas_antigua, hoy)
    # Editar un alta que todavía espera aprobación la sigue tratando como
    # alta.
    accion = "creacion" if existente["pending_action"] == "creacion" else "edicion"
    motivo = motivo_aprobacion(mas_antigua, accion, hoy) if pendiente else ""

    ejecutar(
        """UPDATE time_entries SET
             entry_date = COALESCE(?, entry_date),
             start_time = COALESCE(?, start_time),
             end_time = COALESCE(?, end_time),
             project_id = COALESCE(?, project_id),
             project_name = COALESCE(?, project_name),
             notes = COALESCE(?, notes),
             status = ?, pending_action = ?, pending_reason = ?,
             updated_at = datetime('now')
           WHERE id = ?""",
        (
            _o_none(cambios.get("date")),
            _o_none(cambios.get("start")),
            _o_none(cambios.get("end")),
            _o_none(cambios.get("projectId")),
            _o_none(cambios.get("projectName")),
            _o_none(cambios.get("notes")),
            "pendiente" if pendiente else "aprobado",
            accion if pendiente else "",
            motivo,
            registro_id,
        ),
    )

    detalle = f"actividad del {formatear_fecha(fecha_nueva)} ({inicio}–{fin})"
    return bien(
        motivo if pendiente else "Registro actualizado.",
        pendiente,
        historial=("Envió a aprobación un cambio en la " if pendiente else "Modificó la ") + detalle,
    )


def eliminar_registro(usuario, registro_id: str) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")

    existente = _registro_propio(usuario, registro_id)
    if not existente:
        return mal("El registro no existe.")

    hoy = hoy_iso()
    detalle = (f"actividad del {formatear_fecha(existente['entry_date'])} ("
               f"{existente['start_time']}–{existente['end_time']})")
    # Retirar un alta que todavía no se aprobó no necesita aprobación: el
    # registro nunca llegó a contar.
    retirar_alta = existente["pending_action"] == "creacion"
    pendiente = (not retirar_alta and not _salta_aprobacion(usuario)
                 and requiere_aprobacion(existente["entry_date"], hoy))

    if not pendiente:
        ejecutar("DELETE FROM time_entries WHERE id = ?", (registro_id,))
        return bien("Registro eliminado.", historial=f"Eliminó la {detalle}")

    motivo = motivo_aprobacion(existente["entry_date"], "eliminacion", hoy)
    ejecutar(
        """UPDATE time_entries
              SET status = 'pendiente', pending_action = 'eliminacion',
                  pending_reason = ?, updated_at = datetime('now')
            WHERE id = ?""",
        (motivo, registro_id),
    )
    return bien(motivo, True, historial=f"Pidió eliminar la {detalle}")


def _registro_pendiente(registro_id: str):
    return consultar_una(
        "SELECT user_id, entry_date, start_time, end_time, status, pending_action "
        "FROM time_entries WHERE id = ?",
        (registro_id,),
    )


def aprobar_registro(usuario, registro_id: str) -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración aprueba.")

    fila = _registro_pendiente(registro_id)
    if not fila:
        return mal("El registro ya no existe: lo retiraron o ya se resolvió.")
    if fila["status"] != "pendiente":
        return mal("Ese cambio ya estaba resuelto (quizás desde otra computadora).")

    detalle = (f"de {_nombre_de(fila['user_id'])} del {formatear_fecha(fila['entry_date'])} ("
               f"{fila['start_time']}–{fila['end_time']})")
    if fila["pending_action"] == "eliminacion":
        ejecutar("DELETE FROM time_entries WHERE id = ?", (registro_id,))
    else:
        ejecutar(
            """UPDATE time_entries
                  SET status = 'aprobado', pending_action = '', pending_reason = '',
                      updated_at = datetime('now')
                WHERE id = ?""",
            (registro_id,),
        )
    return bien("Cambio aprobado.", historial=f"Aprobó el registro {detalle}")


def rechazar_registro(usuario, registro_id: str) -> dict:
    """Rechazar un alta descarta el registro.

    Rechazar una modificación o una eliminación lo devuelve al estado aprobado.
    """
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración resuelve.")

    fila = _registro_pendiente(registro_id)
    if not fila:
        return mal("El registro ya no existe: lo retiraron o ya se resolvió.")
    if fila["status"] != "pendiente":
        return mal("Ese cambio ya estaba resuelto (quizás desde otra computadora).")

    detalle = (f"de {_nombre_de(fila['user_id'])} del {formatear_fecha(fila['entry_date'])} ("
               f"{fila['start_time']}–{fila['end_time']})")
    if fila["pending_action"] == "creacion":
        ejecutar("DELETE FROM time_entries WHERE id = ?", (registro_id,))
    else:
        ejecutar(
            """UPDATE time_entries
                  SET status = 'aprobado', pending_action = '', pending_reason = '',
                      updated_at = datetime('now')
                WHERE id = ?""",
            (registro_id,),
        )
    return bien("Cambio rechazado.", historial=f"Rechazó el registro {detalle}")


# ---------------------------------------------------------------------------
# Almuerzo
# ---------------------------------------------------------------------------
def fijar_almuerzo(usuario, usuario_id: str, fecha: str, minutos) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")
    if usuario.role != "administrador" and usuario_id != usuario.id:
        return mal("No puede cambiar el almuerzo de otra persona.")
    if not parsear_iso(fecha):
        return mal("Indique una fecha válida.")

    minutos = ajustar_al_paso(minutos)
    ejecutar(
        """INSERT INTO lunches (user_id, lunch_date, minutes)
           VALUES (?, ?, ?)
           ON CONFLICT (user_id, lunch_date) DO UPDATE SET minutes = excluded.minutes""",
        (usuario_id, fecha, minutos),
    )
    return bien(
        "Almuerzo actualizado.",
        historial=f"Fijó el almuerzo del {formatear_fecha(fecha)} en {minutos} minutos",
    )


# ---------------------------------------------------------------------------
# Ausencias
# ---------------------------------------------------------------------------
def solicitar_ausencia(usuario, ausencia: dict) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")
    if usuario.role != "administrador" and ausencia["userId"] != usuario.id:
        return mal("No puede solicitar ausencias de otra persona.")
    if ausencia.get("kind") not in ETIQUETAS_TIPO:
        return mal("Elija el tipo de ausencia.")
    notas = (ausencia.get("notes") or "").strip()
    if not notas:
        return mal("Explique el motivo de la ausencia.")
    if len(notas) > LARGO_MAXIMO_NOTA:
        return mal(f"Las observaciones no pueden pasar de {LARGO_MAXIMO_NOTA} caracteres.")

    desde = parsear_iso(ausencia.get("from_date"))
    hasta = parsear_iso(ausencia.get("to_date"))
    if not desde or not hasta:
        return mal("Indique las fechas de la ausencia.")
    if hasta < desde:
        return mal("La fecha final no puede ser anterior a la inicial.")
    dias = ausencia.get("days")
    if dias is None or dias <= 0:
        return mal("Indique al menos medio día.")
    if dias > (hasta - desde).days + 1:
        return mal("Pidió más días de los que tiene el rango de fechas.")
    if round(dias * 2) != dias * 2:
        return mal("Los días se piden en días completos o medios días (0,5).")
    # Solo el permiso personal puede pagarse con horas acumuladas: en
    # cualquier otro tipo se ignora lo que llegue.
    #
    horas = float(ausencia.get("accumulatedHours") or 0)
    if not admite_horas_acumuladas(ausencia["kind"]):
        horas = 0.0
    if horas < 0:
        return mal("Las horas acumuladas no pueden ser negativas.")

    choque = consultar_una(
        """SELECT kind, from_date, to_date FROM absences
            WHERE user_id = ? AND status <> 'rechazada'
              AND from_date <= ? AND to_date >= ?""",
        (ausencia["userId"], hasta.isoformat(), desde.isoformat()),
    )
    if choque:
        return mal(
            f"Ya hay una solicitud de {ETIQUETAS_TIPO[choque['kind']].lower()} que se cruza con esas fechas ("
            f"{formatear_fecha(choque['from_date'])} – "
            f"{formatear_fecha(choque['to_date'])})."
        )

    ejecutar(
        """INSERT INTO absences
             (id, user_id, kind, from_date, to_date, days, accumulated_hours,
              notes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            crear_id("abs"),
            ausencia["userId"],
            ausencia["kind"],
            desde.isoformat(),
            hasta.isoformat(),
            dias,
            horas,
            notas,
            date.today().isoformat(),
        ),
    )
    return bien(
        "Solicitud enviada a la administración.",
        historial=f"Solicitó {ETIQUETAS_TIPO[ausencia['kind']].lower()} del "
        f"{formatear_fecha(desde.isoformat())} al {formatear_fecha(hasta.isoformat())}",
    )


def retirar_ausencia(usuario, ausencia_id: str) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")

    fila = consultar_una(
        "SELECT user_id, kind, status, from_date, to_date FROM absences WHERE id = ?",
        (ausencia_id,),
    )
    if not fila:
        return mal("La solicitud ya no existe.")
    # La persona retira sus propias solicitudes; la administración puede
    # eliminar cualquiera.
    #
    if usuario.role != "administrador":
        if fila["user_id"] != usuario.id:
            return mal("No puede retirar solicitudes de otra persona.")
        # Unas vacaciones ya aprobadas y empezadas solo las elimina la
        # administración.
        if fila["status"] != "pendiente" and fila["from_date"] <= hoy_iso():
            return mal(
                "Estas vacaciones ya empezaron. Pida a la administración que las elimine."
            )


    ejecutar("DELETE FROM absences WHERE id = ?", (ausencia_id,))
    quien = "" if fila["user_id"] == usuario.id else f" de {_nombre_de(fila['user_id'])}"
    return bien(
        "Ausencia eliminada.",
        historial=f"Eliminó {ETIQUETAS_TIPO[fila['kind']].lower()}{quien} del "
        f"{formatear_fecha(fila['from_date'])} al {formatear_fecha(fila['to_date'])}",
    )


def resolver_ausencia(usuario, ausencia_id: str, estado: str, nota: str = "") -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración resuelve.")
    if estado not in ("aprobada", "rechazada"):
        return mal("Estado no válido.")

    fila = consultar_una(
        "SELECT user_id, kind, status, decided_by, from_date, to_date FROM absences WHERE id = ?",
        (ausencia_id,),
    )
    if not fila:
        return mal("La solicitud ya no existe: la retiraron o la eliminaron.")
    if fila["status"] != "pendiente":
        resolvio = f" por {fila['decided_by']}" if fila["decided_by"] else ""
        return mal(f"Esa solicitud ya fue resuelta{resolvio}.")

    ejecutar(
        """UPDATE absences
              SET status = ?, decided_by = ?, decided_at = ?, decision_note = ?
            WHERE id = ? AND status = 'pendiente'""",
        (estado, usuario.actingAs, date.today().isoformat(), (nota or "").strip()[:500],
         ausencia_id),
    )
    verbo = "Aprobó" if estado == "aprobada" else "Rechazó"
    return bien(
        "Ausencia aprobada." if estado == "aprobada" else "Ausencia rechazada.",
        historial=f"{verbo} {ETIQUETAS_TIPO[fila['kind']].lower()} de "
        f"{_nombre_de(fila['user_id'])} del {formatear_fecha(fila['from_date'])} al "
        f"{formatear_fecha(fila['to_date'])}",
    )


# ---------------------------------------------------------------------------
# Proyectos
# ---------------------------------------------------------------------------
def _codigo_repetido(codigo: str, propietario, excepto: str = "") -> bool:
    fila = consultar_una(
        "SELECT id FROM projects WHERE lower(code) = lower(?) AND id <> ? "
        "AND (owner_id IS ? OR owner_id IS NULL)",
        (codigo, excepto, propietario),
    )
    return fila is not None


def agregar_proyecto(usuario, proyecto: dict) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")
    codigo = (proyecto.get("code") or "").strip()
    nombre = (proyecto.get("name") or "").strip()
    if not codigo or not nombre:
        return mal("Indique el código y el nombre del proyecto.")
    # El colaborador crea proyectos propios y sin tarifa; la administración
    # decide propietario y tarifa.
    es_admin = usuario.role == "administrador"
    propietario = (proyecto.get("ownerId") or None) if es_admin else usuario.id
    tarifa = proyecto.get("rate") if es_admin else None
    problema = problema_tarifa(tarifa)
    if problema:
        return mal(problema)
    if propietario and not consultar_una(
        "SELECT id FROM users WHERE id = ? AND role = 'colaborador'", (propietario,)
    ):
        return mal("La persona elegida ya no existe.")
    if _codigo_repetido(codigo, propietario):
        return mal(f"Ya existe un proyecto con el código «{codigo}».")

    ejecutar(
        """INSERT INTO projects
             (id, code, name, leader, owner_id, rate_amount, rate_currency, active)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            crear_id("prj"),
            codigo,
            nombre,
            (proyecto.get("leader") or "").strip(),
            propietario,
            tarifa.amount if tarifa else None,
            tarifa.currency if tarifa else None,
            1 if proyecto.get("active", True) else 0,
        ),
    )
    return bien("Proyecto creado.", historial=f"Creó el proyecto {codigo} · {nombre}")


def actualizar_proyecto(usuario, proyecto_id: str, cambios: dict) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")

    fila = consultar_una("SELECT owner_id, code, name FROM projects WHERE id = ?", (proyecto_id,))
    if not fila:
        return mal("El proyecto no existe.")

    es_admin = usuario.role == "administrador"
    if not es_admin and fila["owner_id"] != usuario.id:
        return mal("Solo puede modificar sus propios proyectos.")
    # Ni la tarifa ni el propietario los cambia un colaborador.
    if not es_admin and ("rate" in cambios or "ownerId" in cambios):
        return mal("Las tarifas las define la administración.")

    tarifa_dada = es_admin and "rate" in cambios
    propietario_dado = es_admin and "ownerId" in cambios
    tarifa = cambios.get("rate") if tarifa_dada else None
    problema = problema_tarifa(tarifa)
    if problema:
        return mal(problema)

    propietario = (cambios.get("ownerId") or None) if propietario_dado else fila["owner_id"]
    codigo = _o_none(cambios.get("code")) or fila["code"]
    if _codigo_repetido(codigo, propietario, excepto=proyecto_id):
        return mal(f"Ya existe un proyecto con el código «{codigo}».")

    ejecutar(
        """UPDATE projects SET
             code = COALESCE(?, code),
             name = COALESCE(?, name),
             leader = COALESCE(?, leader),
             active = COALESCE(?, active),
             owner_id = CASE WHEN ? THEN ? ELSE owner_id END,
             rate_amount = CASE WHEN ? THEN ? ELSE rate_amount END,
             rate_currency = CASE WHEN ? THEN ? ELSE rate_currency END
           WHERE id = ?""",
        (
            _o_none(cambios.get("code")),
            _o_none(cambios.get("name")),
            # El líder sí puede quedar vacío.
            cambios["leader"].strip() if "leader" in cambios else None,
            (1 if cambios["active"] else 0) if "active" in cambios else None,
            1 if propietario_dado else 0,
            (cambios.get("ownerId") or None) if propietario_dado else None,
            1 if tarifa_dada else 0,
            tarifa.amount if tarifa else None,
            1 if tarifa_dada else 0,
            tarifa.currency if tarifa else None,
            proyecto_id,
        ),
    )
    nombre = _o_none(cambios.get("name")) or fila["name"]
    extra = f" (tarifa: {formatear_tarifa(tarifa)})" if tarifa_dada else ""
    return bien("Proyecto actualizado.",
                historial=f"Modificó el proyecto {codigo} · {nombre}{extra}")


def eliminar_proyecto(usuario, proyecto_id: str) -> dict:
    if not usuario:
        return mal("Sesión no iniciada.")

    fila = consultar_una("SELECT owner_id, code, name FROM projects WHERE id = ?", (proyecto_id,))
    if not fila:
        return mal("El proyecto no existe.")
    if usuario.role != "administrador" and fila["owner_id"] != usuario.id:
        return mal("Solo puede eliminar sus propios proyectos.")

    ejecutar("DELETE FROM projects WHERE id = ?", (proyecto_id,))
    return bien("Proyecto eliminado.",
                historial=f"Eliminó el proyecto {fila['code']} · {fila['name']}")


def fijar_tarifa_de_proyecto(usuario, usuario_id: str, proyecto_id: str,
                             tarifa) -> dict:
    """Tarifa de una persona concreta en un proyecto concreto.

    Es el nivel más específico del tarifario después del propio registro:
    permite que dos colaboradores cobren distinto en el mismo proyecto.
    """
    if not usuario or usuario.role != "administrador":
        return mal("Las tarifas las define la administración.")
    if not usuario_id or not proyecto_id:
        return mal("Indique la persona y el proyecto.")
    problema = problema_tarifa(tarifa)
    if problema:
        return mal(problema)
    proyecto = consultar_una("SELECT code, name FROM projects WHERE id = ?", (proyecto_id,))
    if not proyecto or not consultar_una("SELECT id FROM users WHERE id = ?", (usuario_id,)):
        return mal("La persona o el proyecto ya no existen.")

    modo, monto, moneda = columnas_tarifa(tarifa)
    detalle = (f"Fijó la tarifa de {_nombre_de(usuario_id)} en el proyecto "
               f"{proyecto['code']}: "
               + ("la general" if modo == "heredada" else formatear_tarifa(tarifa)))

    if modo == "heredada":
        # «Heredada» es no tener tarifa propia en ese proyecto: se borra la
        # fila y vuelve a mandar la tarifa general.
        ejecutar(
            "DELETE FROM collaborator_project_rates "
            "WHERE user_id = ? AND project_id = ?",
            (usuario_id, proyecto_id),
        )
        return bien("Tarifa actualizada.", historial=detalle)

    ejecutar(
        """INSERT INTO collaborator_project_rates
             (user_id, project_id, rate_mode, rate_amount, rate_currency)
           VALUES (?,?,?,?,?)
           ON CONFLICT (user_id, project_id) DO UPDATE SET
             rate_mode = excluded.rate_mode,
             rate_amount = excluded.rate_amount,
             rate_currency = excluded.rate_currency""",
        (usuario_id, proyecto_id, modo, monto, moneda),
    )
    return bien("Tarifa actualizada.", historial=detalle)


# ---------------------------------------------------------------------------
# Equipo
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def agregar_colaborador(usuario, entrada: dict) -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración gestiona el equipo.")

    nombre = (entrada.get("name") or "").strip()
    username = normalizar_usuario(entrada.get("username", ""))
    correo = (entrada.get("email") or "").strip()
    if not nombre:
        return mal("Indique el nombre de la persona.")
    if len(nombre) > 120:
        return mal("El nombre es demasiado largo.")
    if correo and not _CORREO.match(correo):
        return mal("Revise el correo: no parece una dirección válida.")

    problema = problema_usuario(username)
    if problema:
        return mal(problema)
    problema = problema_contrasena(entrada.get("password", ""))
    if problema:
        return mal(problema)

    tomado = consultar_una("SELECT id FROM users WHERE username = ?", (username,))
    if tomado:
        return mal(f"El usuario «{username}» ya existe.")

    identificador = crear_id_usuario("colaborador")
    huella = cifrar_contrasena(entrada["password"])
    periodo = consultar_una("SELECT period_from, period_to FROM app_settings WHERE id = 1")
    anio = date.today().year
    # Quien entra a mitad de año no debe arrastrar horas deber de antes de su
    # ingreso: su periodo empieza hoy.
    #
    desde = max(
        periodo["period_from"] if periodo else f"{anio}-01-01",
        date.today().isoformat(),
    )

    with transaccion() as conexion:
        conexion.execute(
            """INSERT INTO users (id, username, name, email, role, password_hash, active)
               VALUES (?,?,?,?,'colaborador',?,1)""",
            (identificador, username, nombre, correo, huella),
        )
        conexion.execute(
            """INSERT INTO collaborator_settings
                 (user_id, daily_target_hours, annual_vacation_days,
                  period_from, period_to)
               VALUES (?,?,?,?,?)""",
            (
                identificador,
                AJUSTES_BASE.dailyTargetHours,
                AJUSTES_BASE.annualVacationDays,
                desde,
                max(periodo["period_to"] if periodo else f"{anio}-12-31", desde),
            ),
        )

    return bien(f"{nombre} ya puede ingresar con el usuario «{username}».",
                historial=f"Creó la cuenta de {nombre} (usuario «{username}»)")


def actualizar_colaborador(usuario, usuario_id: str, cambios: dict) -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración gestiona el equipo.")

    fila = consultar_una("SELECT name FROM users WHERE id = ? AND role = 'colaborador'",
                         (usuario_id,))
    if not fila:
        return mal("La persona ya no existe.")

    if "email" in cambios:
        correo = (cambios["email"] or "").strip()
        if correo and not _CORREO.match(correo):
            return mal("Revise el correo: no parece una dirección válida.")

    if "username" in cambios:
        username = normalizar_usuario(cambios["username"])
        problema = problema_usuario(username)
        if problema:
            return mal(problema)

        tomado = consultar_una(
            "SELECT id FROM users WHERE username = ? AND id <> ?", (username, usuario_id)
        )
        if tomado:
            return mal(f"El usuario «{username}» ya existe.")
        cambios["username"] = username

    ejecutar(
        """UPDATE users SET
             name = COALESCE(?, name),
             email = COALESCE(?, email),
             username = COALESCE(?, username),
             active = COALESCE(?, active)
           WHERE id = ?""",
        (
            _o_none(cambios.get("name")),
            # El correo sí puede quedar vacío: se borra con una cadena vacía,
            # que COALESCE respeta.
            cambios["email"].strip() if "email" in cambios else None,
            _o_none(cambios.get("username")),
            (1 if cambios["active"] else 0) if "active" in cambios else None,
            usuario_id,
        ),
    )
    return bien("Ficha actualizada.",
                historial=f"Actualizó la ficha de {_o_none(cambios.get('name')) or fila['name']}")


def restablecer_contrasena(usuario, usuario_id: str, contrasena: str) -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración cambia contraseñas.")

    problema = problema_contrasena(contrasena)
    if problema:
        return mal(problema)

    fila = consultar_una("SELECT name FROM users WHERE id = ?", (usuario_id,))
    if not fila:
        return mal("La persona no existe.")

    ejecutar(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (cifrar_contrasena(contrasena), usuario_id),
    )
    return bien(f"Contraseña nueva para {fila['name']}.",
                historial=f"Restableció la contraseña de {fila['name']}")


def eliminar_colaborador(usuario, usuario_id: str) -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración gestiona el equipo.")
    if usuario_id == usuario.id:
        return mal("No puede eliminar su propia cuenta.")

    fila = consultar_una("SELECT name FROM users WHERE id = ? AND role = 'colaborador'",
                         (usuario_id,))
    if not fila:
        return mal("La persona ya no existe.")

    ejecutar("DELETE FROM users WHERE id = ? AND role = 'colaborador'", (usuario_id,))
    return bien("Colaborador eliminado.",
                historial=f"Eliminó a {fila['name']} con sus registros y ausencias")


def _problema_parametros(cambios: dict, actual) -> str | None:
    horas = cambios.get("dailyTargetHours")
    if horas is not None and not (0 < horas <= 24):
        return "Las horas deber por día deben estar entre 0 y 24."
    base = cambios.get("annualVacationDays")
    if base is not None and not (0 <= base <= 366):
        return "La base anual de vacaciones debe estar entre 0 y 366 días."
    for clave in ("carriedVacationDays", "carriedBalanceHours"):
        valor = cambios.get(clave)
        if valor is not None and abs(valor) > 100000:
            return "Revise los saldos: el valor es demasiado grande."
    desde = cambios.get("periodFrom") or (actual["period_from"] if actual else None)
    hasta = cambios.get("periodTo") or (actual["period_to"] if actual else None)
    for valor in (cambios.get("periodFrom"), cambios.get("periodTo")):
        if valor and not parsear_iso(valor):
            return "Indique fechas válidas para el periodo."
    if desde and hasta and desde > hasta:
        return "El periodo termina antes de empezar. Revise las fechas."
    return None


def actualizar_ajustes_colaborador(usuario, usuario_id: str, cambios: dict) -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración cambia los parámetros.")

    actual = consultar_una(
        "SELECT s.period_from, s.period_to, u.name FROM collaborator_settings s "
        "JOIN users u ON u.id = s.user_id WHERE s.user_id = ?",
        (usuario_id,),
    )
    if not actual:
        return mal("La persona ya no existe.")
    problema = _problema_parametros(cambios, actual)
    if problema:
        return mal(problema)
    # La tarifa solo se toca si viene en los cambios: así guardar la jornada
    # no borra una tarifa propia.
    #
    tarifa_dada = "rate" in cambios
    problema = problema_tarifa(cambios.get("rate")) if tarifa_dada else None
    if problema:
        return mal(problema)
    modo, monto, moneda = columnas_tarifa(cambios.get("rate", HEREDADA))

    ejecutar(
        """UPDATE collaborator_settings SET
             daily_target_hours    = COALESCE(?, daily_target_hours),
             carried_balance_hours = COALESCE(?, carried_balance_hours),
             carried_vacation_days = COALESCE(?, carried_vacation_days),
             annual_vacation_days  = COALESCE(?, annual_vacation_days),
             period_from           = COALESCE(?, period_from),
             period_to             = COALESCE(?, period_to),
             rate_mode     = CASE WHEN ? THEN ? ELSE rate_mode END,
             rate_amount   = CASE WHEN ? THEN ? ELSE rate_amount END,
             rate_currency = CASE WHEN ? THEN ? ELSE rate_currency END
           WHERE user_id = ?""",
        (
            cambios.get("dailyTargetHours"),
            cambios.get("carriedBalanceHours"),
            cambios.get("carriedVacationDays"),
            cambios.get("annualVacationDays"),
            cambios.get("periodFrom"),
            cambios.get("periodTo"),
            1 if tarifa_dada else 0,
            modo,
            1 if tarifa_dada else 0,
            monto,
            1 if tarifa_dada else 0,
            moneda,
            usuario_id,
        ),
    )
    return bien("Parámetros actualizados.",
                historial=f"Cambió los parámetros de {actual['name']}")


def trasladar_vacaciones(usuario, usuario_id: str, corte: str | None = None) -> dict:
    """Cierra el año de vacaciones de una persona.

    Los días que le quedan pasan a «vacaciones del año anterior» y, desde la
    fecha de corte, solo cuentan las vacaciones nuevas. Antes el traslado
    copiaba el saldo pero las vacaciones ya descontadas se seguían
    descontando, y el saldo quedaba castigado dos veces.

    El saldo se calcula aquí, con los datos de este momento, y no con el
    número que mostraba la pantalla: otra computadora pudo aprobar unas
    vacaciones entretanto.
    """
    from .lib.ausencias import totales_ausencias
    from .datos import a_ausencia

    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración cambia los parámetros.")

    ficha = consultar_una(
        "SELECT s.*, u.name FROM collaborator_settings s JOIN users u ON u.id = s.user_id "
        "WHERE s.user_id = ?",
        (usuario_id,),
    )
    if not ficha:
        return mal("La persona ya no existe.")

    corte = corte or hoy_iso()
    if not parsear_iso(corte):
        return mal("Indique una fecha de corte válida.")
    desde_anterior = ficha["vacation_since"] or ""
    if desde_anterior and corte <= desde_anterior:
        return mal(f"Ya se hizo un traslado con corte el {formatear_fecha(desde_anterior)}.")
    # Vacaciones aprobadas que cuentan en este año: desde el corte anterior
    # hasta el nuevo. Se cuentan todas, aunque todavía no hayan empezado.
    #
    ausencias = [
        a_ausencia(fila) for fila in consultar(
            "SELECT * FROM absences WHERE user_id = ? AND kind = 'vacaciones' "
            "AND status = 'aprobada' AND from_date < ? AND from_date >= ?",
            (usuario_id, corte, desde_anterior),
        )
    ]
    usados = totales_ausencias(ausencias, hoy="9999-12-31")
    disponibles = round(
        float(ficha["carried_vacation_days"]) + float(ficha["annual_vacation_days"])
        - usados.vacationTaken, 2
    )
    disponibles = max(0.0, disponibles)

    ejecutar(
        "UPDATE collaborator_settings SET carried_vacation_days = ?, vacation_since = ? "
        "WHERE user_id = ?",
        (disponibles, corte, usuario_id),
    )
    texto_dias = f"{disponibles:g}".replace(".", ",")
    return bien(
        f"Se trasladaron {texto_dias} días de {ficha['name']} al año siguiente.",
        historial=f"Trasladó {texto_dias} días de vacaciones de {ficha['name']} (corte "
        f"{formatear_fecha(corte)})",
    )


def actualizar_periodo(usuario, cambios: dict) -> dict:
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración cambia el periodo.")

    actual = consultar_una("SELECT period_from, period_to FROM app_settings WHERE id = 1")
    problema = _problema_parametros(
        {"periodFrom": cambios.get("firstWorkday"), "periodTo": cambios.get("lastWorkday")},
        actual,
    )
    if problema:
        return mal(problema)
    # Una sola fila: se crea la primera vez y después se actualiza solo lo
    # que viene.
    #
    ejecutar(
        """INSERT INTO app_settings (id, period_from, period_to)
           VALUES (1, COALESCE(:desde, :hoy), COALESCE(:hasta, :hoy))
           ON CONFLICT (id) DO UPDATE SET
             period_from = COALESCE(:desde, app_settings.period_from),
             period_to   = COALESCE(:hasta, app_settings.period_to)""",
        {
            "desde": cambios.get("firstWorkday"),
            "hasta": cambios.get("lastWorkday"),
            "hoy": date.today().isoformat(),
        },
    )
    return bien("Periodo actualizado.", historial="Cambió el periodo por omisión del reporte")


# ---------------------------------------------------------------------------
# Recuperación del acceso de administración
# ---------------------------------------------------------------------------
def autorizar_recuperacion(usuario, cuenta: dict, autorizar: bool = True) -> dict:
    """Agrega (o quita) una cuenta de Microsoft de las que pueden recuperar
    el acceso de administración desde Ajustes."""
    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración decide quién recupera el acceso.")
    if not cuenta.get("oid"):
        return mal("Conecte primero una cuenta de Microsoft en esta computadora.")

    fila = consultar_una("SELECT valor FROM meta WHERE clave = 'recuperacion'")
    try:
        lista = json.loads(fila["valor"]) if fila else []
    except ValueError:
        lista = []
    lista = [c for c in lista if c.get("oid") != cuenta["oid"]]
    if autorizar:
        lista.append({"oid": cuenta["oid"], "correo": cuenta.get("correo", ""),
                      "nombre": cuenta.get("nombre", "")})
    ejecutar(
        "INSERT INTO meta (clave, valor) VALUES ('recuperacion', ?) "
        "ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor",
        (json.dumps(lista, ensure_ascii=False),),
    )
    correo = cuenta.get("correo") or cuenta.get("nombre") or "la cuenta"
    return bien(
        f"{correo} {'ya puede' if autorizar else 'ya no puede'} recuperar el acceso de administración.",
        historial=f"{'Autorizó' if autorizar else 'Quitó'} a {correo} para recuperar el acceso de administración",
    )
