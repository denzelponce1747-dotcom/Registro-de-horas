"""Tipos del dominio. Puerto de `src/lib/types.ts`.

Se usan dataclasses en lugar de interfaces de TypeScript, con los mismos
nombres de campo que la versión original para que la lógica sea comparable
línea a línea.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

# Roles posibles de una cuenta.
ROLES = ("colaborador", "administrador")

# Monedas admitidas en las tarifas.
MONEDAS = ("CRC", "USD", "EUR", "CHF")


# ---------------------------------------------------------------------------
# Tarifas
# ---------------------------------------------------------------------------
class _Heredada:
    """Marca «hereda del nivel superior».

    En TypeScript la tarifa heredable distingue tres estados con `undefined`,
    `null` y un objeto. Python no tiene `undefined`, así que el estado
    «heredada» se representa con este centinela y «sin tarifa» con `None`.
    """

    _instancia = None

    def __new__(cls):
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
        return cls._instancia

    def __repr__(self) -> str:
        return "HEREDADA"

    def __bool__(self) -> bool:
        return False


HEREDADA = _Heredada()


@dataclass
class Tarifa:
    """Tarifa por hora. `None` en lugar del objeto significa «sin tarifa»."""

    amount: float
    currency: str

    def como_dict(self) -> dict[str, Any]:
        return {"amount": self.amount, "currency": self.currency}


@dataclass
class Usuario:
    id: str
    username: str
    name: str
    role: str
    initials: str
    email: str = ""
    active: bool = True


@dataclass
class Proyecto:
    id: str
    code: str
    name: str
    leader: str = ""
    # Vacío = proyecto de la empresa, visible para todo el equipo.
    ownerId: str = ""
    # None = sin tarifa asignada.
    rate: Tarifa | None = None
    active: bool = True


@dataclass
class Registro:
    """Registro de horas (`TimeEntry`)."""

    id: str
    userId: str
    date: str
    start: str
    end: str
    projectId: str
    projectName: str
    notes: str
    status: str = "aprobado"
    pendingAction: str = ""
    pendingReason: str = ""
    # HEREDADA, None (sin tarifa) o una Tarifa propia del registro.
    rate: Any = HEREDADA
    createdAt: str = ""
    updatedAt: str = ""
    # Calculadas al leer: jornada bruta y horas netas (ya sin almuerzo).
    grossHours: float = 0.0
    hours: float = 0.0


@dataclass
class Ausencia:
    """Ausencia solicitada (`Absence`).

    `from` y `to` son palabras reservadas en Python, así que los extremos del
    rango se llaman `from_date` y `to_date`, igual que en la base de datos.
    """

    id: str
    userId: str
    # vacaciones | permiso-personal | cita-medica | incapacidad | otra
    kind: str
    from_date: str
    to_date: str
    # Días hábiles que cubre (admite medios días).
    days: float
    # Horas acumuladas con que se paga la ausencia (solo permiso
    # personal).
    accumulatedHours: float = 0.0
    notes: str = ""
    # pendiente | aprobada | rechazada
    status: str = "pendiente"
    # Quién resolvió, cuándo y con qué nota.
    decidedBy: str = ""
    decidedAt: str = ""
    decisionNote: str = ""
    createdAt: str = ""


@dataclass
class AjustesColaborador:
    """Parámetros de jornada, vacaciones, tarifa y periodo (`CollaboratorSettings`)."""

    # Horas deber por día hábil.
    dailyTargetHours: float = 8.5
    # Saldo de horas que arrastra de antes del periodo.
    carriedBalanceHours: float = 0.0
    # Días de vacaciones que arrastra del año anterior.
    carriedVacationDays: float = 0.0
    # Días de vacaciones que corresponden en el año.
    annualVacationDays: float = 20.0
    # HEREDADA, None (sin tarifa) o una Tarifa propia.
    rate: Any = HEREDADA
    # Periodo del reporte de la persona.
    periodFrom: str = ""
    periodTo: str = ""
    # Desde cuándo cuentan sus vacaciones (vacío = desde siempre). Lo mueve
    # «Trasladar el saldo al año siguiente».
    vacationSince: str = ""


@dataclass
class Periodo:
    """Periodo por omisión que hereda un colaborador nuevo (`PeriodSettings`)."""

    firstWorkday: str
    lastWorkday: str


def copia(objeto, **cambios):
    """Copia una dataclass cambiando solo los campos indicados."""
    return replace(objeto, **cambios)
