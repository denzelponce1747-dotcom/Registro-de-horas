"""Parámetros del colaborador y saldo de vacaciones. Puerto de `src/lib/settings.ts`."""

from __future__ import annotations

from dataclasses import dataclass

from .tiempo import redondear
from .tipos import AjustesColaborador, HEREDADA, Periodo

HORAS_DEBER_POR_OMISION = 8.5

# Días de vacaciones que corresponden por año.
DIAS_VACACIONES_ANUALES = 20

PERIODO_POR_OMISION = Periodo(firstWorkday="2026-01-01", lastWorkday="2026-12-31")

AJUSTES_BASE = AjustesColaborador(
    dailyTargetHours=HORAS_DEBER_POR_OMISION,
    carriedBalanceHours=0.0,
    carriedVacationDays=0.0,
    annualVacationDays=DIAS_VACACIONES_ANUALES,
    rate=HEREDADA,
    periodFrom=PERIODO_POR_OMISION.firstWorkday,
    periodTo=PERIODO_POR_OMISION.lastWorkday,
)


def ajustes_de(ajustes: dict, usuario_id: str) -> AjustesColaborador:
    return ajustes.get(usuario_id) or AJUSTES_BASE


@dataclass
class SaldoVacaciones:
    # Saldo de años anteriores.
    carried: float
    # Días que corresponden en el año.
    annual: float
    # Aprobados y ya disfrutados.
    taken: float
    # Aprobados, todavía por disfrutar.
    scheduled: float
    # Solicitados, pendientes de aprobación.
    pending: float
    # Lo que queda: saldo anterior + anuales - aprobados.
    available: float


def saldo_vacaciones(ajustes: AjustesColaborador, taken: float, scheduled: float,
                     pending: float) -> SaldoVacaciones:
    """Saldo de vacaciones en días.

    Los días aprobados se descuentan siempre del saldo; los pendientes se
    muestran aparte para que la persona sepa cuánto le quedaría si el
    administrador aprueba lo solicitado.
    """
    carried = ajustes.carriedVacationDays
    annual = ajustes.annualVacationDays

    return SaldoVacaciones(
        carried=carried,
        annual=annual,
        taken=redondear(taken),
        scheduled=redondear(scheduled),
        pending=redondear(pending),
        available=redondear(carried + annual - taken - scheduled),
    )


def trasladar_vacaciones(dias_disponibles: float) -> float:
    """Traslado de saldo al año siguiente.

    Los días no utilizados se acumulan como saldo del año anterior y la base
    vuelve a los 20 días.
    """
    return max(0.0, redondear(dias_disponibles))


def horas_de_vacaciones(dias: float, horas_deber_diarias: float) -> float:
    """Días de vacaciones convertidos a horas según la jornada."""
    return redondear(dias * horas_deber_diarias)


def periodo_del_colaborador(ajustes: AjustesColaborador) -> Periodo:
    """Periodo individual del reporte de un colaborador."""
    return Periodo(firstWorkday=ajustes.periodFrom, lastWorkday=ajustes.periodTo)
