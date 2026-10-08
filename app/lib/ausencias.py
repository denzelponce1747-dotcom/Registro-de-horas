"""Vacaciones y demás ausencias. Puerto de `src/lib/absences.ts`."""

from __future__ import annotations

from dataclasses import dataclass

from .feriados import obtener_feriado
from .tiempo import cada_fecha, es_fin_de_semana, hoy_iso, redondear

TIPOS_AUSENCIA = [
    {
        "value": "vacaciones",
        "label": "Vacaciones",
        "hint": "Se descuentan del saldo anual de días.",
    },
    {
        "value": "permiso-personal",
        "label": "Permiso personal",
        "hint": "Puede pagarse con horas acumuladas.",
    },
    {
        "value": "cita-medica",
        "label": "Cita médica",
        "hint": "Indique la hora y el centro médico en las observaciones.",
    },
    {
        "value": "incapacidad",
        "label": "Incapacidad",
        "hint": "Adjunte el número de boleta en las observaciones.",
    },
    {
        "value": "otra",
        "label": "Otra ausencia",
        "hint": "Describa el motivo en las observaciones.",
    },
]

ETIQUETAS_TIPO = {
    "vacaciones": "Vacaciones",
    "permiso-personal": "Permiso personal",
    "cita-medica": "Cita médica",
    "incapacidad": "Incapacidad",
    "otra": "Otra ausencia",
}

ETIQUETAS_ESTADO = {
    "pendiente": "Pendiente de aprobación",
    "aprobada": "Aprobada",
    "rechazada": "Rechazada",
}


def admite_horas_acumuladas(kind: str) -> bool:
    """Solo el permiso personal puede pagarse con horas acumuladas."""
    return kind == "permiso-personal"


def dias_habiles_entre(desde: str, hasta: str) -> int:
    """Días hábiles del rango, sin contar fines de semana ni feriados.

    Es la propuesta que se muestra al solicitar; la persona puede ajustarla
    (por ejemplo a medio día) y el administrador la valida.
    """
    if not desde or not hasta or hasta < desde:
        return 0
    return sum(
        1
        for fecha in cada_fecha(desde, hasta)
        if not es_fin_de_semana(fecha) and not obtener_feriado(fecha)
    )


def dias_disfrutados(ausencia, hoy: str) -> float:
    """Días de unas vacaciones aprobadas que ya pasaron (hoy incluido).

    Unas vacaciones en curso se reparten: los días hábiles transcurridos
    cuentan como disfrutados y el resto como «por disfrutar». Antes contaban
    enteras como disfrutadas desde el primer día.
    """
    if ausencia.from_date > hoy:
        return 0.0
    if ausencia.to_date <= hoy:
        return float(ausencia.days)
    transcurridos = dias_habiles_entre(ausencia.from_date, hoy)
    return float(min(ausencia.days, transcurridos))


@dataclass
class TotalesAusencias:
    # Vacaciones aprobadas que ya empezaron.
    vacationTaken: float = 0.0
    # Vacaciones aprobadas que todavía no empiezan.
    vacationScheduled: float = 0.0
    # Vacaciones solicitadas, pendientes de aprobación.
    vacationPending: float = 0.0
    # Horas acumuladas gastadas en permisos aprobados.
    accumulatedHoursUsed: float = 0.0
    # Días de otras ausencias aprobadas.
    otherAbsenceDays: float = 0.0
    # Solicitudes pendientes de cualquier tipo.
    pendingRequests: int = 0


def totales_ausencias(ausencias: list, hoy: str | None = None,
                      vacaciones_desde: str = "", periodo: tuple | None = None) -> TotalesAusencias:
    """Totales de las ausencias de una persona.

    - `vacaciones_desde`: corte del último traslado de saldo. Las vacaciones
      que empiezan antes ya están descontadas en «vacaciones del año
      anterior» y no se vuelven a contar.
    - `periodo` (desde, hasta): las horas acumuladas gastadas en permisos
      solo cuentan dentro del periodo de la persona, igual que sus horas
      trabajadas y sus horas deber.
    """
    hoy = hoy or hoy_iso()
    totales = TotalesAusencias()

    for ausencia in ausencias:
        if ausencia.status == "rechazada":
            continue

        es_vacacion = ausencia.kind == "vacaciones"
        if es_vacacion and vacaciones_desde and ausencia.from_date < vacaciones_desde:
            continue
        en_periodo = not periodo or periodo[0] <= ausencia.from_date <= periodo[1]

        if ausencia.status == "pendiente":
            totales.pendingRequests += 1
            if es_vacacion:
                totales.vacationPending += ausencia.days
            continue

        if es_vacacion:
            disfrutados = dias_disfrutados(ausencia, hoy)
            totales.vacationTaken += disfrutados
            totales.vacationScheduled += ausencia.days - disfrutados
        elif en_periodo:
            totales.otherAbsenceDays += ausencia.days
            totales.accumulatedHoursUsed += ausencia.accumulatedHours

    return TotalesAusencias(
        vacationTaken=redondear(totales.vacationTaken),
        vacationScheduled=redondear(totales.vacationScheduled),
        vacationPending=redondear(totales.vacationPending),
        accumulatedHoursUsed=redondear(totales.accumulatedHoursUsed),
        otherAbsenceDays=redondear(totales.otherAbsenceDays),
        pendingRequests=totales.pendingRequests,
    )


def ausencias_en(ausencias: list, fecha: str) -> list:
    """Ausencias aprobadas que cubren una fecha concreta."""
    return [
        a
        for a in ausencias
        if a.status == "aprobada" and a.from_date <= fecha <= a.to_date
    ]


def ordenar_ausencias(ausencias: list) -> list:
    """Primero las pendientes, luego las aprobadas y por último las rechazadas."""
    peso = {"pendiente": 0, "aprobada": 1, "rechazada": 2}
    return sorted(
        ausencias,
        key=lambda a: (peso.get(a.status, 3), _invertido(a.from_date)),
    )


def _invertido(texto: str):
    """Clave que ordena un texto de forma descendente dentro de un sorted."""
    return tuple(-ord(c) for c in texto or "")
