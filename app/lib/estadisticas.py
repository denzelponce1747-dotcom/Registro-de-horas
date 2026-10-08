"""Cálculos del dashboard y de los reportes. Puerto de `src/lib/stats.ts`."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .ajustes import ajustes_de, periodo_del_colaborador, saldo_vacaciones
from .almuerzo import almuerzo_de
from .ausencias import totales_ausencias
from .feriados import obtener_feriado
from .proyectos import buscar_proyecto
from .tarifas import formatear_montos, resolver_tarifa, sumar_monto
from .tiempo import (
    cada_fecha,
    es_fin_de_semana,
    horas_brutas_entre,
    hoy_iso,
    redondear,
)
from .usuarios import colaboradores_de, nombre_de_usuario


def con_horas(registros: list, almuerzos: dict) -> list:
    """Agrega las horas trabajadas a cada registro.

    El almuerzo se guarda una vez por jornada, así que se reparte entre las
    actividades de ese día en proporción a su duración.
    """
    bruto_por_dia = {}
    brutos = []

    for registro in registros:
        valor = horas_brutas_entre(registro.start, registro.end)
        clave = f"{registro.userId}|{registro.date}"
        bruto_por_dia[clave] = bruto_por_dia.get(clave, 0) + valor
        brutos.append(valor)

    resultado = []
    for indice, registro in enumerate(registros):
        clave = f"{registro.userId}|{registro.date}"
        bruto_dia = bruto_por_dia.get(clave, 0)
        horas_almuerzo = almuerzo_de(almuerzos, registro.userId, registro.date) / 60
        parte = brutos[indice] / bruto_dia * horas_almuerzo if bruto_dia > 0 else 0
        # Parte del almuerzo del día que le toca a esta actividad.
        resultado.append(
            replace(
                registro,
                grossHours=brutos[indice],
                hours=redondear(max(0.0, brutos[indice] - parte)),
            )
        )

    return resultado


def horas_netas_del_dia(registros: list, minutos_almuerzo: int) -> float:
    """Horas netas de una jornada completa, ya descontado el almuerzo del día."""
    bruto = sum(r.grossHours for r in registros)
    return redondear(max(0.0, bruto - minutos_almuerzo / 60))


@dataclass
class Resumen:
    collaborators: int = 0
    totalEntries: int = 0
    totalHours: float = 0.0
    averageHours: float = 0.0
    pendingEntries: int = 0


def resumir(registros: list) -> Resumen:
    total_horas = 0.0
    pendientes = 0
    colaboradores = set()

    for registro in registros:
        colaboradores.add(registro.userId)
        total_horas += registro.hours
        if registro.status == "pendiente":
            pendientes += 1

    return Resumen(
        collaborators=len(colaboradores),
        totalEntries=len(registros),
        totalHours=redondear(total_horas),
        averageHours=redondear(total_horas / len(registros)) if registros else 0.0,
        pendingEntries=pendientes,
    )


def horas_por_colaborador(registros: list, usuarios: list) -> list:
    """Horas aprobadas y pendientes acumuladas por persona."""
    mapa = {}

    for registro in registros:
        nombre = nombre_de_usuario(usuarios, registro.userId)
        actual = mapa.setdefault(
            registro.userId,
            {
                "name": nombre,
                "shortName": nombre.replace("Colaborador ", "Col. "),
                "hours": 0.0,
                "pending": 0.0,
            },
        )
        if registro.status == "pendiente":
            actual["pending"] += registro.hours
        else:
            actual["hours"] += registro.hours

    salida = [
        {
            **item,
            "hours": redondear(item["hours"]),
            "pending": redondear(item["pending"]),
        }
        for item in mapa.values()
    ]
    return sorted(salida, key=lambda item: item["name"])


def horas_por_proyecto(registros: list) -> list:
    mapa = {}
    for registro in registros:
        mapa[registro.projectName] = mapa.get(registro.projectName, 0) + registro.hours
    salida = [
        {"name": nombre, "hours": redondear(horas)} for nombre, horas in mapa.items()
    ]
    return sorted(salida, key=lambda item: -item["hours"])


def distribucion_por_estado(registros: list) -> list:
    """Reparto de las horas entre aprobadas y pendientes de aprobación."""
    aprobadas = 0.0
    pendientes = 0.0
    for registro in registros:
        if registro.status == "pendiente":
            pendientes += registro.hours
        else:
            aprobadas += registro.hours
    return [
        {"name": "Horas aprobadas", "key": "hours", "value": redondear(aprobadas)},
        {
            "name": "Pendientes de aprobación",
            "key": "pending",
            "value": redondear(pendientes),
        },
    ]


def monto_del_registro(registro, proyectos: list, ajustes: dict,
                       tarifas_proyecto: dict | None = None):
    """Monto de un registro. None cuando no hay tarifa asignada."""
    tarifa, _origen = resolver_tarifa(
        registro,
        buscar_proyecto(proyectos, registro.projectId),
        ajustes.get(registro.userId),
        tarifas_proyecto,
    )
    if not tarifa:
        return None
    return {
        "amount": redondear(registro.hours * tarifa.amount),
        "currency": tarifa.currency,
    }


@dataclass
class TotalesFacturacion:
    amounts: dict = field(default_factory=dict)
    # Horas de registros sin tarifa: no generan monto.
    hoursWithoutRate: float = 0.0
    label: str = "Sin tarifa"


def totales_facturacion(
    registros: list, proyectos: list, ajustes: dict,
    tarifas_proyecto: dict | None = None,
) -> TotalesFacturacion:
    """Montos por moneda: las monedas no se suman entre sí ni se convierten."""
    montos = {}
    horas_sin_tarifa = 0.0

    for registro in registros:
        valor = monto_del_registro(registro, proyectos, ajustes, tarifas_proyecto)
        if valor:
            sumar_monto(montos, valor["currency"], valor["amount"])
        else:
            horas_sin_tarifa += registro.hours

    return TotalesFacturacion(
        amounts=montos,
        hoursWithoutRate=redondear(horas_sin_tarifa),
        label=formatear_montos(montos),
    )


def horas_deber_de(registros: list, horas_deber_diarias: float) -> float:
    """Horas deber contando solo los días con jornada registrada.

    Es la regla del sistema original. Se conserva para poder comparar, pero
    la que manda ahora es `horas_deber_del_periodo`: con esta, quien no
    registra nada no debe nada, y el saldo siempre daba cero.
    """
    dias = set()
    for registro in registros:
        if es_fin_de_semana(registro.date) or obtener_feriado(registro.date):
            continue
        dias.add(registro.date)
    return redondear(len(dias) * horas_deber_diarias)


def dias_laborales_del_periodo(desde: str, hasta: str, ausencias: list | None = None,
                               usuario_id: str = "", hoy: str | None = None) -> list:
    """Días del periodo que sí exigen trabajo.

    Quedan fuera los fines de semana, los feriados de Costa Rica y los días
    cubiertos por una ausencia aprobada. El periodo se recorta a hoy: lo que
    todavía no se ha trabajado no puede deberse.
    """
    hoy = hoy or hoy_iso()
    if not desde:
        return []
    fin = min(hasta, hoy) if hasta else hoy
    if fin < desde:
        return []

    aprobadas = [
        a
        for a in (ausencias or [])
        if a.status == "aprobada" and (not usuario_id or a.userId == usuario_id)
    ]

    dias = []
    for fecha in cada_fecha(desde, fin):
        if es_fin_de_semana(fecha) or obtener_feriado(fecha):
            continue
        if any(a.from_date <= fecha <= a.to_date for a in aprobadas):
            continue
        dias.append(fecha)
    return dias


def horas_deber_del_periodo(desde: str, hasta: str, horas_deber_diarias: float,
                            ausencias: list | None = None, usuario_id: str = "",
                            hoy: str | None = None) -> float:
    """Horas que la persona debía haber trabajado en su periodo.

    Cuenta **todos** los días laborales transcurridos, se haya registrado algo
    o no. Es lo que hace que las horas acumuladas reflejen la realidad: quien
    lleva medio año sin anotar arrastra un saldo negativo grande, en vez del
    cero que salía cuando solo contaban los días con registro.
    """
    dias = dias_laborales_del_periodo(desde, hasta, ausencias, usuario_id, hoy)
    return redondear(len(dias) * horas_deber_diarias)


@dataclass
class SaldoHoras:
    # Horas trabajadas en el tramo.
    worked: float
    # Horas deber del tramo.
    target: float
    # worked - target.
    difference: float
    # Horas acumuladas gastadas en permisos que empiezan en el tramo.
    spent: float
    # Saldo real al final del tramo: saldo previo + todo lo trabajado desde
    # el inicio del periodo - todo lo debido - todo lo gastado.
    accumulated: float


def gastadas_entre(ausencias: list, usuario_id: str, desde: str, hasta: str) -> float:
    """Horas acumuladas usadas en permisos aprobados que empiezan en el tramo."""
    return redondear(sum(
        a.accumulatedHours
        for a in ausencias
        if a.userId == usuario_id and a.status == "aprobada" and a.kind != "vacaciones"
        and desde <= a.from_date <= hasta
    ))


def saldo_horas(registros: list, ausencias: list, config, usuario_id: str, *,
                desde: str | None = None, hasta: str | None = None,
                hoy: str | None = None) -> SaldoHoras:
    """El saldo de horas de una persona, con una sola regla para todo el sistema.

    Todo se cuenta **dentro del periodo de su ficha** y hasta hoy: las horas
    trabajadas, las horas deber y las horas gastadas en permisos. Antes las
    trabajadas contaban todo el historial mientras el deber contaba solo el
    periodo, y al pasar al año siguiente el saldo se inflaba con las horas
    del año anterior, que ya estaban en el «saldo previo».

    `desde` y `hasta` recortan el tramo que se informa (un reporte de una
    quincena), pero el acumulado siempre corre desde el inicio del periodo:
    es el saldo real al final de ese tramo.
    """
    hoy = hoy or hoy_iso()
    periodo = periodo_del_colaborador(config)
    inicio = periodo.firstWorkday or "0000-01-01"
    fin = min(periodo.lastWorkday or hoy, hoy)
    tramo_desde = max(desde or inicio, inicio)
    tramo_hasta = min(hasta or fin, fin)

    propios = [r for r in registros if r.userId == usuario_id]

    def trabajadas_entre(a: str, b: str) -> float:
        return redondear(sum(r.hours for r in propios if a <= r.date <= b)) if a <= b else 0.0

    def deber_entre(a: str, b: str) -> float:
        if a > b:
            return 0.0
        return horas_deber_del_periodo(a, b, config.dailyTargetHours, ausencias, usuario_id, hoy)

    trabajadas = trabajadas_entre(tramo_desde, tramo_hasta)
    deber = deber_entre(tramo_desde, tramo_hasta)
    gastadas = (gastadas_entre(ausencias, usuario_id, tramo_desde, tramo_hasta)
                if tramo_desde <= tramo_hasta else 0.0)

    acumulado = redondear(
        config.carriedBalanceHours
        + trabajadas_entre(inicio, tramo_hasta)
        - deber_entre(inicio, tramo_hasta)
        - (gastadas_entre(ausencias, usuario_id, inicio, tramo_hasta) if inicio <= tramo_hasta else 0)
    )
    return SaldoHoras(
        worked=trabajadas,
        target=deber,
        difference=redondear(trabajadas - deber),
        spent=gastadas,
        accumulated=acumulado,
    )


def vacaciones_de(config, ausencias: list, usuario_id: str, hoy: str | None = None):
    """(saldo de vacaciones, totales de ausencias) de una persona, hoy."""
    periodo = periodo_del_colaborador(config)
    totales = totales_ausencias(
        [a for a in ausencias if a.userId == usuario_id],
        hoy,
        vacaciones_desde=getattr(config, "vacationSince", "") or "",
        periodo=(periodo.firstWorkday or "0000-01-01", periodo.lastWorkday or "9999-12-31"),
    )
    saldo = saldo_vacaciones(
        config, totales.vacationTaken, totales.vacationScheduled, totales.vacationPending
    )
    return saldo, totales


@dataclass
class SaldoColaborador:
    userId: str
    name: str
    shortName: str
    entries: int
    worked: float
    target: float
    # worked - target, dentro del tramo informado.
    difference: float
    # Horas acumuladas gastadas en permisos.
    accumulatedSpent: float
    # Saldo real de horas acumuladas.
    accumulated: float
    vacation: object
    pendingEntries: int
    pendingAbsences: int
    billing: TotalesFacturacion


def saldos_de_colaboradores(
    registros: list,
    ausencias: list,
    ajustes: dict,
    proyectos: list,
    usuarios: list,
    hoy: str | None = None,
    tarifas_proyecto: dict | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> list:
    """Saldo de cada colaborador. `registros` debe traer TODOS sus registros:
    el acumulado corre desde el inicio de su periodo. `desde`/`hasta`
    recortan solo lo que se informa como trabajado y deber."""
    hoy = hoy or hoy_iso()
    salida = []

    for usuario in colaboradores_de(usuarios):
        propios = [r for r in registros if r.userId == usuario.id]
        ausencias_propias = [a for a in ausencias if a.userId == usuario.id]
        config = ajustes_de(ajustes, usuario.id)
        # Una sola regla de saldo para todo el sistema (ver `saldo_horas`).
        #
        saldo = saldo_horas(propios, ausencias_propias, config, usuario.id,
                            desde=desde, hasta=hasta, hoy=hoy)
        vacaciones, totales = vacaciones_de(config, ausencias_propias, usuario.id, hoy)

        salida.append(
            SaldoColaborador(
                userId=usuario.id,
                name=usuario.name,
                shortName=usuario.name.replace("Colaborador ", "Col. "),
                entries=len(propios),
                worked=saldo.worked,
                target=saldo.target,
                difference=saldo.difference,
                accumulatedSpent=saldo.spent,
                accumulated=saldo.accumulated,
                vacation=vacaciones,
                pendingEntries=sum(1 for r in propios if r.status == "pendiente"),
                pendingAbsences=totales.pendingRequests,
                billing=totales_facturacion(
                    propios, proyectos, ajustes, tarifas_proyecto
                ),
            )
        )

    return sorted(salida, key=lambda item: item.name)


FILTROS_VACIOS = {
    "userId": "",
    "project": "",
    "status": "",
    "from": "",
    "to": "",
    "search": "",
}


def filtrar_registros(registros: list, filtros: dict) -> list:
    busqueda = (filtros.get("search") or "").strip().lower()
    salida = []

    for registro in registros:
        if filtros.get("userId") and registro.userId != filtros["userId"]:
            continue
        if filtros.get("project") and registro.projectId != filtros["project"]:
            continue
        if filtros.get("status") and registro.status != filtros["status"]:
            continue
        if filtros.get("from") and registro.date < filtros["from"]:
            continue
        if filtros.get("to") and registro.date > filtros["to"]:
            continue
        texto = f"{registro.projectName} {registro.notes}".lower()
        if busqueda and busqueda not in texto:
            continue
        salida.append(registro)

    return salida


def contar_filtros_activos(filtros: dict) -> int:
    return sum(1 for valor in filtros.values() if valor)


def ordenar_por_fecha_desc(registros: list) -> list:
    """Fecha descendente y, dentro del día, por hora de inicio descendente."""
    return sorted(registros, key=lambda r: (r.date, r.start), reverse=True)


def ordenar_por_fecha_asc(registros: list) -> list:
    return sorted(registros, key=lambda r: (r.date, r.start))
