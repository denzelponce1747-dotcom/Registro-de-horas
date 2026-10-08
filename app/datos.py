"""Carga de datos. Puerto de `src/server/data.ts`.

Arma la «instantánea» con todo lo que la interfaz necesita para el usuario de
la sesión. La administración ve al equipo completo; cada colaborador,
únicamente lo suyo y los proyectos de la empresa. El filtrado se hace en la
consulta, no en la interfaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .db import consultar, consultar_una
from .lib.ajustes import AJUSTES_BASE
from .lib.tipos import (
    AjustesColaborador,
    Ausencia,
    HEREDADA,
    Periodo,
    Proyecto,
    Registro,
    Tarifa,
    Usuario,
)
from .lib.usuarios import iniciales_de

COLUMNAS_USUARIO = "id, username, name, email, role, active"


# ---------------------------------------------------------------------------
# De fila de la base a objeto del dominio
# ---------------------------------------------------------------------------
def a_usuario(fila) -> Usuario:
    return Usuario(
        id=fila["id"],
        username=fila["username"],
        name=fila["name"],
        email=fila["email"],
        role=fila["role"],
        active=bool(fila["active"]),
        initials=iniciales_de(fila["name"]),
    )


def a_tarifa(monto, moneda) -> Tarifa | None:
    """`None` en el importe significa «sin tarifa asignada»."""
    if monto is None or moneda is None:
        return None
    return Tarifa(amount=float(monto), currency=moneda)


def a_tarifa_heredable(modo: str, monto, moneda):
    """La tarifa heredable distingue tres estados; el modo los desambigua."""
    if modo == "heredada":
        return HEREDADA
    if modo == "sin-tarifa":
        return None
    return a_tarifa(monto, moneda)


def a_proyecto(fila) -> Proyecto:
    return Proyecto(
        id=fila["id"],
        code=fila["code"],
        name=fila["name"],
        leader=fila["leader"],
        ownerId=fila["owner_id"] or "",
        rate=a_tarifa(fila["rate_amount"], fila["rate_currency"]),
        active=bool(fila["active"]),
    )


def a_registro(fila) -> Registro:
    return Registro(
        id=fila["id"],
        userId=fila["user_id"],
        date=fila["entry_date"],
        start=fila["start_time"],
        end=fila["end_time"],
        projectId=fila["project_id"],
        projectName=fila["project_name"],
        notes=fila["notes"],
        status=fila["status"],
        pendingAction=fila["pending_action"],
        pendingReason=fila["pending_reason"],
        rate=a_tarifa_heredable(
            fila["rate_mode"], fila["rate_amount"], fila["rate_currency"]
        ),
        createdAt=fila["created_at"],
        updatedAt=fila["updated_at"],
    )


def a_ausencia(fila) -> Ausencia:
    return Ausencia(
        id=fila["id"],
        userId=fila["user_id"],
        kind=fila["kind"],
        from_date=fila["from_date"],
        to_date=fila["to_date"],
        days=float(fila["days"]),
        accumulatedHours=float(fila["accumulated_hours"]),
        notes=fila["notes"],
        status=fila["status"],
        decidedBy=fila["decided_by"],
        decidedAt=fila["decided_at"] or "",
        decisionNote=fila["decision_note"],
        createdAt=fila["created_at"],
    )


def a_ajustes(fila) -> AjustesColaborador:
    return AjustesColaborador(
        dailyTargetHours=float(fila["daily_target_hours"]),
        carriedBalanceHours=float(fila["carried_balance_hours"]),
        carriedVacationDays=float(fila["carried_vacation_days"]),
        annualVacationDays=float(fila["annual_vacation_days"]),
        rate=a_tarifa_heredable(
            fila["rate_mode"], fila["rate_amount"], fila["rate_currency"]
        ),
        periodFrom=fila["period_from"],
        periodTo=fila["period_to"],
        vacationSince=(fila["vacation_since"] or "") if "vacation_since" in fila.keys() else "",
    )


# ---------------------------------------------------------------------------
# Instantánea
# ---------------------------------------------------------------------------
@dataclass
class Instantanea:
    """Todo lo que la interfaz necesita para el usuario de la sesión."""

    users: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    lunches: dict = field(default_factory=dict)
    absences: list = field(default_factory=list)
    projects: list = field(default_factory=list)
    collaboratorSettings: dict = field(default_factory=dict)
    # «usuario|proyecto» -> tarifa heredable de esa persona en ese proyecto.
    projectRates: dict = field(default_factory=dict)
    period: Periodo = None


def cargar_periodo() -> Periodo:
    fila = consultar_una("SELECT period_from, period_to FROM app_settings WHERE id = 1")
    anio = date.today().year
    return Periodo(
        firstWorkday=fila["period_from"] if fila else f"{anio}-01-01",
        lastWorkday=fila["period_to"] if fila else f"{anio}-12-31",
    )


def cargar_instantanea(usuario) -> Instantanea:
    es_admin = usuario.role == "administrador"
    alcance = () if es_admin else (usuario.id,)
    solo_mios = "" if es_admin else "WHERE user_id = ?"

    if es_admin:
        filas_usuarios = consultar(f"SELECT {COLUMNAS_USUARIO} FROM users ORDER BY name")
        filas_proyectos = consultar("SELECT * FROM projects ORDER BY code")
        filas_ajustes = consultar("SELECT * FROM collaborator_settings")
        filas_tarifas = consultar("SELECT * FROM collaborator_project_rates")
    else:
        filas_usuarios = consultar(
            f"SELECT {COLUMNAS_USUARIO} FROM users WHERE id = ?", (usuario.id,)
        )
        filas_proyectos = consultar(
            "SELECT * FROM projects WHERE owner_id IS NULL OR owner_id = ? ORDER BY code",
            (usuario.id,),
        )
        filas_ajustes = consultar(
            "SELECT * FROM collaborator_settings WHERE user_id = ?", (usuario.id,)
        )
        filas_tarifas = consultar(
            "SELECT * FROM collaborator_project_rates WHERE user_id = ?", (usuario.id,)
        )

    filas_registros = consultar(
        f"SELECT * FROM time_entries {solo_mios} ORDER BY entry_date DESC, start_time DESC",
        # Todos los registros: el saldo corre desde el inicio del periodo.
        alcance,
    )
    filas_almuerzos = consultar(
        f"SELECT user_id, lunch_date, minutes FROM lunches {solo_mios}", alcance
    )
    filas_ausencias = consultar(
        f"SELECT * FROM absences {solo_mios} ORDER BY from_date DESC", alcance
    )

    periodo = cargar_periodo()

    almuerzos = {
        f"{fila['user_id']}|{fila['lunch_date']}": int(fila["minutes"])
        for fila in filas_almuerzos
    }

    ajustes = {fila["user_id"]: a_ajustes(fila) for fila in filas_ajustes}
    # Un colaborador sin ficha propia hereda los parámetros base y el
    # periodo de la empresa.
    for fila in filas_usuarios:
        if fila["role"] == "colaborador" and fila["id"] not in ajustes:
            ajustes[fila["id"]] = AjustesColaborador(
                dailyTargetHours=AJUSTES_BASE.dailyTargetHours,
                carriedBalanceHours=AJUSTES_BASE.carriedBalanceHours,
                carriedVacationDays=AJUSTES_BASE.carriedVacationDays,
                annualVacationDays=AJUSTES_BASE.annualVacationDays,
                rate=HEREDADA,
                periodFrom=periodo.firstWorkday,
                periodTo=periodo.lastWorkday,
            )

    tarifas_proyecto = {
        f"{fila['user_id']}|{fila['project_id']}": a_tarifa_heredable(
            fila["rate_mode"], fila["rate_amount"], fila["rate_currency"]
        )
        for fila in filas_tarifas
    }

    return Instantanea(
        users=[a_usuario(fila) for fila in filas_usuarios],
        entries=[a_registro(fila) for fila in filas_registros],
        lunches=almuerzos,
        absences=[a_ausencia(fila) for fila in filas_ausencias],
        projects=[a_proyecto(fila) for fila in filas_proyectos],
        collaboratorSettings=ajustes,
        projectRates=tarifas_proyecto,
        period=periodo,
    )
