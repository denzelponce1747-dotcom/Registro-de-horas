"""Control día por día. Puerto de `src/lib/daily.ts`.

Es la vista que reproduce el reporte de horas que la empresa llevaba en
Excel: una fila por día natural, con las horas deber del día y el arrastre de
las horas acumuladas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .almuerzo import almuerzo_de
from .ausencias import ETIQUETAS_TIPO, ausencias_en
from .feriados import obtener_feriado
from .proyectos import buscar_proyecto
from .tiempo import (
    cada_fecha,
    dia_semana_corto,
    es_fin_de_semana,
    formatear_numero,
    hoy_iso,
    redondear,
)


@dataclass
class FilaDiaria:
    date: str
    weekday: str
    isWeekend: bool
    holiday: str | None
    # Tipos de las ausencias aprobadas que cubren el día.
    absence: str | None
    # Primera entrada y última salida del día.
    start: str | None
    end: str | None
    lunchMinutes: int
    lunchHours: float
    hours: float
    targetHours: float
    difference: float
    # Horas acumuladas al cierre del día.
    cumulative: float
    # Una línea por registro, para el reporte.
    report: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    pending: int = 0
    # Horas acumuladas pagadas con un permiso que empieza ese día.
    spentHours: float = 0.0
    # Hoy, todavía sin registros: sus horas deber entran en el saldo con la
    # primera actividad del día (o mañana, si no se registra nada).
    todayOpen: bool = False
    # Horas deber que tendría el día (aunque todavía no cuenten).
    dayTarget: float = 0.0


def linea_de_registro(registro, proyectos: list) -> str:
    """Texto que describe un registro dentro del reporte diario."""
    proyecto = buscar_proyecto(proyectos, registro.projectId)
    codigo = proyecto.code if proyecto else registro.projectName
    sufijo = " (pendiente de aprobación)" if registro.status == "pendiente" else ""
    detalle = registro.notes or "Sin detalle"
    return f"{codigo}, {formatear_numero(registro.hours)}h: {detalle}{sufijo}"


def construir_filas_diarias(
    registros: list,
    *,
    desde: str,
    hasta: str,
    horas_deber: float,
    saldo_previo: float = 0.0,
    proyectos: list,
    almuerzos: dict,
    usuario_id: str,
    ausencias: list | None = None,
    hoy: str | None = None,
    periodo_desde: str = "",
    periodo_hasta: str = "",
) -> list:
    """Agrupa los registros por fecha, calcula las horas deber de cada día
    laboral y arrastra las horas acumuladas.

    Los días fuera del periodo de la persona (`periodo_desde`…`periodo_hasta`)
    no generan horas deber ni mueven el acumulado, igual que en el saldo del
    dashboard. Las horas acumuladas que se pagan con un permiso se descuentan
    el día en que el permiso empieza: así el último acumulado coincide con el
    del dashboard. Hoy, mientras no haya registros, tampoco se debe nada
    todavía (ver `saldo_horas`).
    """
    ausencias = ausencias or []
    hoy = hoy or hoy_iso()
    gastadas_por_dia = {}
    for ausencia in ausencias:
        if (ausencia.userId == usuario_id and ausencia.status == "aprobada"
                and ausencia.kind != "vacaciones" and ausencia.accumulatedHours):
            gastadas_por_dia[ausencia.from_date] = (
                gastadas_por_dia.get(ausencia.from_date, 0.0) + ausencia.accumulatedHours
            )

    por_fecha = {}
    for registro in registros:
        por_fecha.setdefault(registro.date, []).append(registro)

    acumulado = saldo_previo
    filas = []

    for fecha in cada_fecha(desde, hasta):
        del_dia = sorted(por_fecha.get(fecha, []), key=lambda r: r.start)

        feriado = obtener_feriado(fecha)
        finde = es_fin_de_semana(fecha)
        ausencias_dia = [
            a for a in ausencias_en(ausencias, fecha) if a.userId == usuario_id
        ]
        trabajadas = redondear(sum(r.hours for r in del_dia))
        minutos_almuerzo = almuerzo_de(almuerzos, usuario_id, fecha)

        # Un día genera horas deber solo si es hábil, no está cubierto por
        # una ausencia aprobada, ya llegó y cae dentro del periodo de la
        # persona. Fuera del periodo no se descuenta nada: es lo que hace el
        # saldo del dashboard, y así el último acumulado de esta tabla
        # coincide con él.
        #
        fuera_del_periodo = (
            (periodo_desde and fecha < periodo_desde)
            or (periodo_hasta and fecha > periodo_hasta)
        )
        deber_del_dia = (
            0.0
            if finde or feriado or ausencias_dia or fecha > hoy or fuera_del_periodo
            else horas_deber
        )
        # Hoy sin registros: el día todavía no cuenta en el saldo.
        hoy_abierto = fecha == hoy and not del_dia and deber_del_dia > 0
        deber = 0.0 if hoy_abierto else deber_del_dia
        diferencia = redondear(trabajadas - deber)
        gastadas = 0.0 if fuera_del_periodo else redondear(gastadas_por_dia.get(fecha, 0.0))
        if not fuera_del_periodo:
            acumulado = redondear(acumulado + diferencia - gastadas)

        filas.append(
            FilaDiaria(
                date=fecha,
                weekday=dia_semana_corto(fecha),
                isWeekend=finde,
                holiday=feriado,
                absence=" · ".join(ETIQUETAS_TIPO[a.kind] for a in ausencias_dia)
                if ausencias_dia
                else None,
                start=del_dia[0].start if del_dia else None,
                end=del_dia[-1].end if del_dia else None,
                lunchMinutes=minutos_almuerzo,
                lunchHours=redondear(minutos_almuerzo / 60),
                hours=trabajadas,
                targetHours=deber,
                difference=diferencia,
                cumulative=acumulado,
                report=[linea_de_registro(r, proyectos) for r in del_dia],
                entries=del_dia,
                pending=sum(1 for r in del_dia if r.status == "pendiente"),
                spentHours=gastadas,
                todayOpen=hoy_abierto,
                dayTarget=deber_del_dia,
            )
        )

    return filas


def rango_de_registros(registros: list):
    """Rango que cubren los registros indicados, o None si no hay ninguno."""
    if not registros:
        return None
    desde = registros[0].date
    hasta = registros[0].date
    for registro in registros:
        if registro.date < desde:
            desde = registro.date
        if registro.date > hasta:
            hasta = registro.date
    return {"from": desde, "to": hasta}
