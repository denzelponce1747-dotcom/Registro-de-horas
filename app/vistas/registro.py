"""Pantallas del perfil Colaborador: horas, ausencias y proyectos propios."""

from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import acciones
from ..auth import exigir_perfil, usuario_de_sesion
from ..datos import cargar_instantanea
from ..lib.ajustes import ajustes_de
from ..lib.almuerzo import ATAJOS, MINUTOS_POR_OMISION, almuerzo_de
from ..lib.aprobaciones import requiere_aprobacion
from ..lib.ausencias import (
    admite_horas_acumuladas,
    dias_habiles_entre,
    ordenar_ausencias,
)
from ..lib.diario import construir_filas_diarias
from ..lib.estadisticas import (
    con_horas,
    horas_netas_del_dia,
    ordenar_por_fecha_desc,
    resumir,
    saldo_horas,
    vacaciones_de,
)
from ..lib.feriados import obtener_feriado, tabla_de
from ..lib.proyectos import (
    buscar_proyecto,
    proyectos_editables,
    proyectos_visibles,
)
from ..lib.tiempo import (
    anio_de,
    cada_fecha,
    es_fin_de_semana,
    fin_de_semana_iso,
    formatear_mes,
    hoy_iso,
    inicio_de_semana,
    redondear,
)
from .comun import avisar, contexto_base, numero_o_none

registro = Blueprint("registro", __name__)


def _mis_datos():
    """Instantánea del colaborador con los cálculos que comparten sus pantallas."""
    usuario = usuario_de_sesion()
    instantanea = cargar_instantanea(usuario)
    # Las horas netas se calculan una sola vez, con el almuerzo prorrateado.
    mis_registros = con_horas(
        [r for r in instantanea.entries if r.userId == usuario.id], instantanea.lunches
    )
    mis_ausencias = [a for a in instantanea.absences if a.userId == usuario.id]
    config = ajustes_de(instantanea.collaboratorSettings, usuario.id)

    return usuario, instantanea, mis_registros, mis_ausencias, config


# ---------------------------------------------------------------------------
# Registro de horas
# ---------------------------------------------------------------------------
@registro.route("/registro", endpoint="registro", methods=["GET", "POST"])
@exigir_perfil("colaborador")
def registro_horas():
    usuario = usuario_de_sesion()
    # Cada formulario de la pantalla manda su `accion`.
    if request.method == "POST":
        return _resolver_accion_horas(usuario)

    _, instantanea, mis_registros, mis_ausencias, config = _mis_datos()

    vista = request.args.get("vista", "dia")
    if vista not in ("dia", "semana", "historial"):
        vista = "dia"
    fecha = request.args.get("fecha") or hoy_iso()

    resumen = resumir(mis_registros)
    saldo = saldo_horas(mis_registros, mis_ausencias, config, usuario.id)
    vacaciones, totales = vacaciones_de(config, mis_ausencias, usuario.id)

    mis_proyectos = proyectos_visibles(instantanea.projects, usuario)
    editando = request.args.get("editar", "")

    contexto = dict(
        vista=vista,
        fecha=fecha,
        registros=mis_registros,
        proyectos=mis_proyectos,
        ausencias=mis_ausencias,
        config=config,
        resumen=resumen,
        saldo=saldo,
        deber=saldo.target,
        acumuladas=saldo.accumulated,
        vacaciones=vacaciones,
        totales=totales,
        pendientes=resumen.pendingEntries + totales.pendingRequests,
        editando=editando,
        creando=request.args.get("nueva") == "1",
        atajos_almuerzo=ATAJOS,
        almuerzo_por_omision=MINUTOS_POR_OMISION,
    )

    if vista == "dia":
        contexto.update(_contexto_dia(usuario, instantanea, mis_registros,
                                      mis_ausencias, config, fecha))
    elif vista == "semana":
        contexto.update(_contexto_semana(usuario, instantanea, mis_registros,
                                         mis_ausencias, config, fecha))
    else:
        contexto.update(_contexto_historial(mis_registros, mis_proyectos,
                                            instantanea.lunches, usuario))

    return render_template("registro.html", **contexto_base(instantanea, contexto))


def _contexto_dia(usuario, instantanea, registros, ausencias, config, fecha):
    from ..lib.ausencias import ausencias_en

    del_dia = sorted([r for r in registros if r.date == fecha], key=lambda r: r.start)
    minutos_almuerzo = almuerzo_de(instantanea.lunches, usuario.id, fecha)
    horas_netas = horas_netas_del_dia(del_dia, minutos_almuerzo)
    horas_brutas = redondear(sum(r.grossHours for r in del_dia))

    feriado = obtener_feriado(fecha)
    finde = es_fin_de_semana(fecha)
    ausencias_dia = [a for a in ausencias_en(ausencias, fecha) if a.userId == usuario.id]
    # El día genera horas deber con la misma regla que el saldo: hábil, sin
    # ausencia aprobada, dentro del periodo de la persona y ya transcurrido.
    #
    en_periodo = (config.periodFrom or fecha) <= fecha <= (config.periodTo or fecha)
    futuro = fecha > hoy_iso()
    con_deber = not finde and not feriado and not ausencias_dia and en_periodo and not futuro
    deber_dia = config.dailyTargetHours if con_deber else 0

    return {
        "registros_dia": del_dia,
        "minutos_almuerzo": minutos_almuerzo,
        "horas_netas": horas_netas,
        "horas_brutas": horas_brutas,
        "feriado": feriado,
        "es_finde": finde,
        "ausencias_dia": ausencias_dia,
        "deber_dia": deber_dia,
        "dia_futuro": futuro,
        "fuera_del_periodo": not en_periodo,
        "diferencia_dia": redondear(horas_netas - deber_dia),
        "requiere_aprobacion": requiere_aprobacion(fecha),
        "proyecto_de": lambda pid: buscar_proyecto(instantanea.projects, pid),
    }


def _contexto_semana(usuario, instantanea, registros, ausencias, config, fecha):
    desde = inicio_de_semana(fecha)
    hasta = fin_de_semana_iso(fecha)

    filas = construir_filas_diarias(
        [r for r in registros if desde <= r.date <= hasta],
        desde=desde,
        hasta=hasta,
        horas_deber=config.dailyTargetHours,
        saldo_previo=0,
        proyectos=instantanea.projects,
        almuerzos=instantanea.lunches,
        usuario_id=usuario.id,
        ausencias=ausencias,
        periodo_desde=config.periodFrom,
        periodo_hasta=config.periodTo,
    )

    return {
        "semana_desde": desde,
        "semana_hasta": hasta,
        "filas_semana": filas,
        "codigos_proyecto": {p.id: p.code for p in instantanea.projects},
        "horas_semana": redondear(sum(fila.hours for fila in filas)),
        "deber_semana": redondear(sum(fila.targetHours for fila in filas)),
        "diferencia_semana": redondear(
            sum(fila.difference for fila in filas)
        ),
    }


def _contexto_historial(registros, proyectos, almuerzos, usuario):
    ordenados = ordenar_por_fecha_desc(registros)
    # Agrupados por mes, del más reciente al más antiguo.
    grupos = []
    indice = {}
    for item in ordenados:
        clave = item.date[:7]
        if clave not in indice:
            indice[clave] = {
                "clave": clave,
                "etiqueta": formatear_mes(item.date),
                "registros": [],
                "horas": 0.0,
            }
            grupos.append(indice[clave])
        indice[clave]["registros"].append(item)
        indice[clave]["horas"] = redondear(indice[clave]["horas"] + item.hours)

    return {
        "grupos_historial": grupos,
        "proyecto_de": lambda pid: buscar_proyecto(proyectos, pid),
        "almuerzos": almuerzos,
    }


def _resolver_accion_horas(usuario):
    accion = request.form.get("accion", "")
    fecha = request.form.get("fecha") or hoy_iso()
    vista = request.form.get("vista", "dia")
    volver = url_for("registro.registro", vista=vista, fecha=fecha)

    if accion == "crear":
        proyecto_id = request.form.get("projectId", "")
        instantanea = cargar_instantanea(usuario)
        proyecto = buscar_proyecto(instantanea.projects, proyecto_id)
        resultado = acciones.agregar_registro(
            usuario,
            {
                "userId": usuario.id,
                "date": request.form.get("date", ""),
                "start": request.form.get("start", ""),
                "end": request.form.get("end", ""),
                "projectId": proyecto_id,
                "projectName": proyecto.name if proyecto else "",
                "notes": request.form.get("notes", ""),
            },
        )
        avisar(resultado)
        return redirect(
            url_for("registro.registro", vista=vista,
                    fecha=request.form.get("date") or fecha)
        )

    if accion == "editar":
        proyecto_id = request.form.get("projectId", "")
        instantanea = cargar_instantanea(usuario)
        proyecto = buscar_proyecto(instantanea.projects, proyecto_id)
        resultado = acciones.actualizar_registro(
            usuario,
            request.form.get("id", ""),
            {
                "date": request.form.get("date", ""),
                "start": request.form.get("start", ""),
                "end": request.form.get("end", ""),
                "projectId": proyecto_id,
                "projectName": proyecto.name if proyecto else "",
                "notes": request.form.get("notes", ""),
            },
        )
        avisar(resultado)
        return redirect(
            url_for("registro.registro", vista=vista,
                    fecha=request.form.get("date") or fecha)
        )

    if accion == "eliminar":
        avisar(acciones.eliminar_registro(usuario, request.form.get("id", "")))
        return redirect(volver)

    if accion == "almuerzo":
        avisar(
            acciones.fijar_almuerzo(
                usuario, usuario.id, fecha, numero_o_none(request.form.get("minutos")) or 0
            )
        )
        return redirect(volver)

    flash("Acción no reconocida.", "error")
    return redirect(volver)


# ---------------------------------------------------------------------------
# Ausencias
# ---------------------------------------------------------------------------
@registro.route("/ausencias", methods=["GET", "POST"])
@exigir_perfil("colaborador")
def ausencias():
    usuario = usuario_de_sesion()

    if request.method == "POST":
        accion = request.form.get("accion", "")

        if accion == "solicitar":
            desde = request.form.get("from_date", "")
            hasta = request.form.get("to_date", "") or desde
            dias = numero_o_none(request.form.get("days"))
            resultado = acciones.solicitar_ausencia(
                usuario,
                {
                    "userId": usuario.id,
                    "kind": request.form.get("kind", "vacaciones"),
                    "from_date": desde,
                    "to_date": hasta,
                    "days": dias if dias is not None else dias_habiles_entre(desde, hasta),
                    "accumulatedHours": numero_o_none(
                        request.form.get("accumulatedHours")
                    ) or 0,
                    "notes": request.form.get("notes", ""),
                },
            )
            avisar(resultado)

        elif accion == "retirar":
            avisar(acciones.retirar_ausencia(usuario, request.form.get("id", "")))

        return redirect(url_for("registro.ausencias"))

    _, instantanea, mis_registros, mis_ausencias, config = _mis_datos()

    vacaciones, totales = vacaciones_de(config, mis_ausencias, usuario.id)
    acumuladas = saldo_horas(mis_registros, mis_ausencias, config, usuario.id).accumulated

    hoy = hoy_iso()
    anio = anio_de(hoy)
    # Feriados de este año y del siguiente, para que el calendario descuente
    # los días que no son hábiles al proponer los días pedidos.
    feriados = sorted(list(tabla_de(anio)) + list(tabla_de(anio + 1)))

    contexto = dict(
        ausencias=ordenar_ausencias(mis_ausencias),
        # Se puede retirar lo pendiente y lo aprobado que todavía no
        # empieza.
        puede_retirar=lambda a: a.status == "pendiente" or a.from_date > hoy,
        totales=totales,
        vacaciones=vacaciones,
        acumuladas=acumuladas,
        anio=anio,
        hoy=hoy,
        dias_sugeridos=dias_habiles_entre(hoy, hoy),
        admite_horas=admite_horas_acumuladas,
        feriados_json=json.dumps(feriados),
    )
    return render_template("ausencias.html", **contexto_base(instantanea, contexto))


# ---------------------------------------------------------------------------
# Proyectos
# ---------------------------------------------------------------------------
@registro.route("/proyectos", methods=["GET", "POST"])
@exigir_perfil("colaborador")
def proyectos():
    usuario = usuario_de_sesion()

    if request.method == "POST":
        accion = request.form.get("accion", "")

        if accion == "crear":
            avisar(
                acciones.agregar_proyecto(
                    usuario,
                    {
                        "code": request.form.get("code", ""),
                        "name": request.form.get("name", ""),
                        "leader": request.form.get("leader", ""),
                        "ownerId": usuario.id,
                        "rate": None,
                        "active": True,
                    },
                )
            )

        elif accion == "editar":
            avisar(
                acciones.actualizar_proyecto(
                    usuario,
                    request.form.get("id", ""),
                    {
                        "code": request.form.get("code", ""),
                        "name": request.form.get("name", ""),
                        "leader": request.form.get("leader", ""),
                        "active": request.form.get("active") == "1",
                    },
                )
            )

        elif accion == "eliminar":
            avisar(acciones.eliminar_proyecto(usuario, request.form.get("id", "")))

        return redirect(url_for("registro.proyectos"))

    usuario, instantanea, mis_registros, _ausencias, _config = _mis_datos()

    visibles = proyectos_visibles(instantanea.projects, usuario)
    editables = {p.id for p in proyectos_editables(instantanea.projects, usuario)}

    horas_por_proyecto = {}
    for item in mis_registros:
        horas_por_proyecto[item.projectId] = redondear(
            horas_por_proyecto.get(item.projectId, 0) + item.hours
        )

    contexto = dict(
        proyectos=visibles,
        editables=editables,
        horas_por_proyecto=horas_por_proyecto,
        editando=request.args.get("editar", ""),
        creando=request.args.get("nuevo") == "1",
    )
    return render_template("proyectos.html", **contexto_base(instantanea, contexto))
