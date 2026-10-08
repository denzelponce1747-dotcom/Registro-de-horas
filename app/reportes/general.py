"""Reporte general de horas. Puerto de `src/lib/export/general-report.ts`.

Hoja **Resumen** con los indicadores del periodo, hoja **Detalle** con todos
los registros y una hoja **por colaborador** con el bloque de vacaciones, sus
ausencias del periodo y el control diario.
"""

from __future__ import annotations

from openpyxl import Workbook

from ..lib.ajustes import ajustes_de, periodo_del_colaborador
from ..lib.almuerzo import formatear_almuerzo_corto
from ..lib.ausencias import ETIQUETAS_ESTADO, ETIQUETAS_TIPO
from ..lib.diario import construir_filas_diarias
from ..lib.estadisticas import (
    monto_del_registro,
    resumir,
    saldos_de_colaboradores,
    totales_facturacion,
    vacaciones_de,
)
from ..lib.proyectos import buscar_proyecto
from ..lib.tarifas import formatear_montos, formatear_tarifa, resolver_tarifa
from ..lib.tiempo import formatear_fecha, formatear_numero, hoy_iso, redondear
from ..lib.usuarios import colaboradores_de, nombre_de_usuario
from .estilos import (
    ESTILO_TOTAL,
    Hoja,
    XL,
    color_diferencia,
    dinero,
    etiqueta,
    fecha as celda_fecha,
    fila_encabezado,
    fila_leyenda,
    fila_seccion,
    fila_subtitulo,
    fila_titulo,
    fila_vacia,
    nombre_hoja,
    numero,
    relleno,
    texto,
    total,
    total_numero,
    volcar,
)

ANCHO_RESUMEN = 9
ANCHO_DETALLE = 12
ANCHO_DIARIO = 10


def _colaboradores_del_reporte(contexto: dict) -> list:
    """Colaboradores que entran en el reporte, en orden alfabético."""
    colaboradores = colaboradores_de(contexto["users"])
    solo = contexto.get("onlyUserId")
    if solo:
        colaboradores = [u for u in colaboradores if u.id == solo]
    con_registros = [
        u
        for u in colaboradores
        if any(r.userId == u.id for r in contexto["entries"])
    ]
    return sorted(con_registros, key=lambda u: u.name)


def _leyenda_periodo(contexto: dict) -> str:
    periodo = contexto["period"]
    return (
        f"Periodo del {formatear_fecha(periodo.firstWorkday)} al "
        f"{formatear_fecha(periodo.lastWorkday)} · {contexto['filtersLabel']}"
    )


def _hoja_resumen(contexto: dict) -> Hoja:
    registros = contexto["entries"]
    periodo = contexto["period"]
    resumen = resumir(registros)
    # El saldo acumulado se calcula con todos los registros (no solo los
    # filtrados), pero las horas, la diferencia y el monto del bloque
    # corresponden a los registros del reporte.
    saldos = [
        item
        for item in saldos_de_colaboradores(
            contexto.get("allEntries") or registros,
            contexto["absences"],
            contexto["settings"],
            contexto["projects"],
            contexto["users"],
            tarifas_proyecto=contexto.get("projectRates"),
            desde=periodo.firstWorkday,
            hasta=periodo.lastWorkday,
        )
        if any(r.userId == item.userId for r in registros)
    ]
    for item in saldos:
        propios = [r for r in registros if r.userId == item.userId]
        item.entries = len(propios)
        item.worked = redondear(sum(r.hours for r in propios))
        item.difference = redondear(item.worked - item.target)
        item.billing = totales_facturacion(
            propios, contexto["projects"], contexto["settings"], contexto.get("projectRates")
        )

    deber = redondear(sum(item.target for item in saldos))
    diferencia = redondear(resumen.totalHours - deber)
    facturacion = totales_facturacion(
        registros, contexto["projects"], contexto["settings"],
        contexto.get("projectRates"),
    )

    def indicador(nombre, valor, formato=None):
        return [
            etiqueta(nombre),
            numero(valor, formato=formato) if formato else numero(valor),
        ] + relleno(ANCHO_RESUMEN - 2)

    filas = [
        fila_titulo("MAJERIE S.R.L", ANCHO_RESUMEN),
        fila_subtitulo("Reporte general de horas", ANCHO_RESUMEN),
        fila_leyenda(_leyenda_periodo(contexto), ANCHO_RESUMEN),
        fila_vacia(ANCHO_RESUMEN),
        fila_seccion("Indicadores del periodo", ANCHO_RESUMEN),
        indicador("Colaboradores con registros", resumen.collaborators, "0"),
        indicador("Total de registros", resumen.totalEntries, "0"),
        indicador("Registros pendientes de aprobación", resumen.pendingEntries, "0"),
        indicador("Horas trabajadas", resumen.totalHours),
        indicador("Horas deber", redondear(deber)),
        [
            etiqueta("Diferencia del periodo"),
            numero(diferencia, color=color_diferencia(diferencia)),
        ]
        + relleno(ANCHO_RESUMEN - 2),
        [etiqueta("Monto facturable"), texto(facturacion.label, columnas=3)]
        + relleno(ANCHO_RESUMEN - 2),
        indicador("Horas sin tarifa asignada", facturacion.hoursWithoutRate),
        fila_vacia(ANCHO_RESUMEN),
        fila_seccion("Horas acumuladas y vacaciones por colaborador", ANCHO_RESUMEN),
        fila_encabezado(
            [
                "Colaborador",
                "Registros",
                "Horas trabajadas",
                "Horas deber",
                "Diferencia",
                "Horas acumuladas",
                "Vacaciones disponibles (días)",
                "Vacaciones aprobadas (días)",
                "Monto facturable",
            ]
        ),
    ]

    for item in saldos:
        filas.append(
            [
                texto(item.name, negrita=True),
                numero(item.entries, formato="0"),
                numero(item.worked),
                numero(item.target),
                numero(item.difference, color=color_diferencia(item.difference)),
                numero(item.accumulated, color=color_diferencia(item.accumulated)),
                numero(item.vacation.available),
                numero(item.vacation.taken + item.vacation.scheduled),
                texto(formatear_montos(item.billing.amounts)),
            ]
        )

    filas.append(
        [
            total("Total"),
            total_numero(resumen.totalEntries, formato="0"),
            total_numero(resumen.totalHours),
            total_numero(redondear(deber)),
            total_numero(diferencia, color=color_diferencia(diferencia)),
            total(),
            total(),
            total(),
            total(facturacion.label),
        ]
    )

    return Hoja(
        nombre="Resumen",
        filas=filas,
        columnas=[
            {"width": 30}, {"width": 11}, {"width": 17}, {"width": 13},
            {"width": 12}, {"width": 18}, {"width": 26}, {"width": 26},
            {"width": 26},
        ],
    )


def _hoja_detalle(contexto: dict) -> Hoja:
    registros = sorted(contexto["entries"], key=lambda r: (r.date, r.start))
    suma = redondear(sum(r.hours for r in registros))

    filas = [
        fila_titulo("MAJERIE S.R.L", ANCHO_DETALLE),
        fila_subtitulo("Detalle de registros", ANCHO_DETALLE),
        fila_leyenda(_leyenda_periodo(contexto), ANCHO_DETALLE),
        fila_vacia(ANCHO_DETALLE),
        fila_encabezado(
            [
                "Colaborador",
                "Fecha",
                "Ingreso",
                "Salida",
                "Almuerzo del día",
                "Horas",
                "Código",
                "Proyecto",
                "Líder de proyecto",
                "Tarifa aplicada",
                "Monto",
                "Observaciones",
            ]
        ),
    ]

    for item in registros:
        proyecto = buscar_proyecto(contexto["projects"], item.projectId)
        tarifa, _origen = resolver_tarifa(
            item, proyecto, contexto["settings"].get(item.userId),
            contexto.get("projectRates"),
        )
        monto = monto_del_registro(
            item, contexto["projects"], contexto["settings"],
            contexto.get("projectRates"),
        )
        pendiente = item.status == "pendiente"
        minutos = contexto["lunches"].get(f"{item.userId}|{item.date}", 0)

        filas.append(
            [
                texto(
                    nombre_de_usuario(contexto["users"], item.userId),
                    color=XL["pending"] if pendiente else None,
                    fondo=XL["pendingSoft"] if pendiente else None,
                ),
                celda_fecha(item.date),
                texto(item.start, alineacion="center"),
                texto(item.end, alineacion="center"),
                texto(formatear_almuerzo_corto(minutos), alineacion="center"),
                numero(item.hours, negrita=True),
                texto(proyecto.code if proyecto else "—", alineacion="center"),
                texto(item.projectName),
                texto(proyecto.leader if proyecto else "—"),
                texto(formatear_tarifa(tarifa), alineacion="right"),
                dinero(monto["amount"])
                if monto
                else texto("Sin tarifa", alineacion="right", color=XL["muted"]),
                texto(
                    f"{item.notes} · PENDIENTE DE APROBACIÓN" if pendiente else item.notes,
                    ajustar=True,
                    color=XL["pending"] if pendiente else XL["muted"],
                ),
            ]
        )

    filas.append(
        [total("Total")]
        + [total() for _ in range(4)]
        + [total_numero(suma)]
        + [total() for _ in range(6)]
    )

    return Hoja(
        nombre="Detalle",
        filas=filas,
        filas_fijas=5,
        columnas=[
            {"width": 18}, {"width": 12}, {"width": 10}, {"width": 10},
            {"width": 15}, {"width": 9}, {"width": 10}, {"width": 22},
            {"width": 22}, {"width": 20}, {"width": 18}, {"width": 14},
            {"width": 46},
        ],
    )


def _hoja_colaborador(usuario_id: str, contexto: dict) -> Hoja:
    """Hoja con el detalle día por día y el bloque de vacaciones."""
    config = ajustes_de(contexto["settings"], usuario_id)
    individual = periodo_del_colaborador(config)
    reporte = contexto["period"]
    hoy = hoy_iso()
    todos_propios = [
        r for r in (contexto.get("allEntries") or contexto["entries"]) if r.userId == usuario_id
    ]
    ausencias_propias = [a for a in contexto["absences"] if a.userId == usuario_id]

    # El control diario se arma desde el inicio del periodo individual, para
    # que la columna «Horas acumuladas» arrastre el saldo correcto aunque el
    # reporte empiece más tarde; después se muestran solo los días que caen
    # en el tramo del reporte (y nunca después de hoy).
    #
    rango = {
        "from": max(reporte.firstWorkday, individual.firstWorkday),
        "to": min(reporte.lastWorkday, individual.lastWorkday, hoy),
    }
    if rango["to"] >= rango["from"]:
        completas = construir_filas_diarias(
            [r for r in todos_propios if individual.firstWorkday <= r.date <= rango["to"]],
            desde=individual.firstWorkday,
            hasta=rango["to"],
            horas_deber=config.dailyTargetHours,
            saldo_previo=config.carriedBalanceHours,
            proyectos=contexto["projects"],
            almuerzos=contexto["lunches"],
            usuario_id=usuario_id,
            ausencias=ausencias_propias,
            periodo_desde=individual.firstWorkday,
            periodo_hasta=individual.lastWorkday,
        )
        filas_diarias = [fila for fila in completas if fila.date >= rango["from"]]
        saldo_inicial = next(
            (redondear(fila.cumulative - fila.difference + fila.spentHours)
             for fila in filas_diarias), config.carriedBalanceHours
        )
    else:
        filas_diarias = []
        saldo_inicial = config.carriedBalanceHours

    trabajadas = redondear(sum(fila.hours for fila in filas_diarias))
    deber = redondear(sum(fila.targetHours for fila in filas_diarias))
    saldo, _totales = vacaciones_de(config, ausencias_propias, usuario_id, hoy)
    ausencias_del_tramo = [
        a for a in ausencias_propias
        if a.to_date >= reporte.firstWorkday and a.from_date <= reporte.lastWorkday
    ]

    def linea_vacaciones(nombre, dias):
        return [
            etiqueta(nombre, columnas=2),
            None,
            numero(dias),
            texto("días", color=XL["muted"]),
        ] + relleno(ANCHO_DIARIO - 4)

    nombre = nombre_de_usuario(contexto["users"], usuario_id)

    filas = [
        fila_titulo("MAJERIE S.R.L", ANCHO_DIARIO),
        fila_subtitulo(f"Reporte de horas de {nombre}", ANCHO_DIARIO),
        fila_leyenda(
            f"Jornada de {config.dailyTargetHours:.2f} h diarias · periodo individual del "
            f"{formatear_fecha(individual.firstWorkday)} al "
            f"{formatear_fecha(individual.lastWorkday)} · control del "
            f"{formatear_fecha(rango['from'])} al {formatear_fecha(rango['to'])}"
            if filas_diarias
            else f"Jornada de {config.dailyTargetHours:.2f} h diarias · el periodo del reporte "
            "no coincide con el periodo individual ("
            f"{formatear_fecha(individual.firstWorkday)} al "
            f"{formatear_fecha(individual.lastWorkday)})",
            ANCHO_DIARIO,
        ),
        fila_vacia(ANCHO_DIARIO),
        fila_seccion("Vacaciones (en días)", ANCHO_DIARIO),
        [
            etiqueta("Primer día laboral del periodo", columnas=2),
            None,
            celda_fecha(individual.firstWorkday),
        ]
        + relleno(ANCHO_DIARIO - 3),
        [
            etiqueta("Último día laboral del periodo", columnas=2),
            None,
            celda_fecha(individual.lastWorkday),
        ]
        + relleno(ANCHO_DIARIO - 3),
        linea_vacaciones("Días acumulados del año anterior", saldo.carried),
        linea_vacaciones("Base anual de vacaciones", saldo.annual),
        linea_vacaciones("Días aprobados y disfrutados", saldo.taken),
        linea_vacaciones("Días aprobados por disfrutar", saldo.scheduled),
        [
            etiqueta("Días de vacaciones disponibles", columnas=2,
                     fondo=XL["accentSoft"]),
            None,
            numero(saldo.available, negrita=True, fondo=XL["accentSoft"]),
            texto("días", color=XL["muted"], fondo=XL["accentSoft"]),
        ]
        + relleno(ANCHO_DIARIO - 4),
        fila_vacia(ANCHO_DIARIO),
        fila_seccion("Ausencias del periodo", ANCHO_DIARIO),
    ]

    if ausencias_del_tramo:
        for ausencia in ausencias_del_tramo:
            color_estado = (
                XL["positive"]
                if ausencia.status == "aprobada"
                else XL["negative"]
                if ausencia.status == "rechazada"
                else XL["pending"]
            )
            filas.append(
                [
                    texto(ETIQUETAS_TIPO[ausencia.kind], columnas=2),
                    None,
                    celda_fecha(ausencia.from_date),
                    celda_fecha(ausencia.to_date),
                    numero(ausencia.days),
                    texto(ETIQUETAS_ESTADO[ausencia.status], color=color_estado),
                    texto(ausencia.notes, columnas=4, ajustar=True, color=XL["muted"]),
                ]
                + relleno(3)
            )
    else:
        filas.append(
            [texto("Sin ausencias en el periodo del reporte", color=XL["muted"])]
            + relleno(ANCHO_DIARIO - 1)
        )

    filas.append(fila_vacia(ANCHO_DIARIO))
    filas.append(fila_seccion("Detalle diario", ANCHO_DIARIO))
    filas.append(
        fila_encabezado(
            [
                "Día",
                "Fecha",
                "Ingreso",
                "Salida",
                "Tiempo de almuerzo",
                "Horas",
                "Horas deber",
                "Diferencia",
                "Horas acumuladas",
                "Reporte de horas",
            ]
        )
    )

    for fila in filas_diarias:
        fondo = (
            XL["holiday"]
            if fila.holiday
            else XL["accentSoft"]
            if fila.absence
            else XL["weekend"]
            if fila.isWeekend
            else None
        )
        vacio = not fila.entries

        filas.append(
            [
                texto(fila.weekday, alineacion="center", fondo=fondo),
                celda_fecha(fila.date, fondo=fondo),
                texto(fila.start or "—", alineacion="center", fondo=fondo),
                texto(fila.end or "—", alineacion="center", fondo=fondo),
                texto("—", alineacion="center", fondo=fondo)
                if vacio
                else numero(fila.lunchHours, fondo=fondo),
                texto("—", alineacion="center", fondo=fondo)
                if vacio
                else numero(fila.hours, negrita=True, fondo=fondo),
                texto("—", alineacion="center", fondo=fondo)
                if vacio
                else numero(fila.targetHours, fondo=fondo),
                texto("—", alineacion="center", fondo=fondo)
                if vacio
                else numero(
                    fila.difference, color=color_diferencia(fila.difference), fondo=fondo
                ),
                numero(
                    fila.cumulative,
                    negrita=True,
                    color=color_diferencia(fila.cumulative),
                    fondo=fondo,
                ),
                texto(
                    (fila.holiday or fila.absence or "\n".join(fila.report))
                    + (f" · usa {formatear_numero(fila.spentHours)} h acumuladas"
                       if fila.spentHours else ""),
                    ajustar=True,
                    fondo=fondo,
                    negrita=bool(fila.holiday or fila.absence),
                    color=XL["positive"]
                    if fila.holiday
                    else XL["accent"]
                    if fila.absence
                    else None,
                ),
            ]
        )

    acumulado_final = filas_diarias[-1].cumulative if filas_diarias else saldo_inicial
    diferencia_total = redondear(trabajadas - deber)

    filas.append(
        [total("Total")]
        + [total() for _ in range(4)]
        + [
            total_numero(trabajadas),
            total_numero(deber),
            total_numero(diferencia_total, color=color_diferencia(diferencia_total)),
            total_numero(acumulado_final, color=color_diferencia(acumulado_final)),
            total(),
        ]
    )

    return Hoja(
        nombre=nombre_hoja(nombre),
        filas=filas,
        columnas=[
            {"width": 7}, {"width": 12}, {"width": 10}, {"width": 10},
            {"width": 18}, {"width": 9}, {"width": 12}, {"width": 12},
            {"width": 18}, {"width": 78},
        ],
    )


def reporte_general(contexto: dict):
    """Devuelve (libro, nombre de archivo) del reporte general de horas."""
    libro = Workbook()
    libro.remove(libro.active)

    volcar(libro, _hoja_resumen(contexto))
    volcar(libro, _hoja_detalle(contexto))
    for usuario in _colaboradores_del_reporte(contexto):
        volcar(libro, _hoja_colaborador(usuario.id, contexto))

    solo = contexto.get("onlyUserId")
    sufijo = ""
    if solo:
        nombre = nombre_hoja(nombre_de_usuario(contexto["users"], solo))
        sufijo = "-" + nombre.lower().replace(" ", "-")

    return libro, f"reporte-general-de-horas{sufijo}.xlsx"
