"""Pantallas del perfil Administrador: dashboard, aprobaciones y configuración."""

from __future__ import annotations

import io
from datetime import date

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .. import acciones
from ..auth import exigir_perfil, sugerir_contrasena, usuario_de_sesion
from ..datos import cargar_instantanea
from ..graficos import barras_apiladas, barras_proyecto, leyenda, rosco_estado
from ..lib.ajustes import (
    DIAS_VACACIONES_ANUALES,
    ajustes_de,
    periodo_del_colaborador,
)
from ..lib.almuerzo import almuerzo_de
from ..lib.ausencias import ordenar_ausencias
from ..lib.estadisticas import (
    FILTROS_VACIOS,
    con_horas,
    distribucion_por_estado,
    filtrar_registros,
    horas_por_colaborador,
    horas_por_proyecto,
    monto_del_registro,
    ordenar_por_fecha_desc,
    resumir,
    saldos_de_colaboradores,
    totales_facturacion,
    vacaciones_de,
)
from ..lib.proyectos import buscar_proyecto
from ..lib.tarifas import formatear_tarifa, modo_tarifa, resolver_tarifa
from ..lib.tiempo import anio_de, hoy_iso, parsear_iso, redondear
from ..lib.tipos import Periodo, Tarifa
from ..lib.usuarios import colaboradores_de, iniciales_de, nombre_de_usuario, sugerir_usuario
from ..reportes.general import reporte_general
from ..reportes.por_colaborador import reporte_por_colaborador
from .comun import avisar, contexto_base, leer_tarifa, numero_o_none, texto_o_none

panel = Blueprint("panel", __name__)

TAMANO_PAGINA = 25


def _filtros_de_la_peticion() -> dict:
    filtros = dict(FILTROS_VACIOS)
    for clave in filtros:
        filtros[clave] = request.args.get(clave, "").strip()
    return filtros


def _pagina() -> int:
    try:
        return max(1, min(int(request.args.get("pagina", 1) or 1), 10000))
    except (TypeError, ValueError):
        return 1


def _etiqueta_filtros(filtros: dict, usuarios: list, proyectos: list) -> str:
    """Texto con los filtros aplicados, que encabeza los reportes."""
    partes = []
    if filtros["userId"]:
        partes.append(nombre_de_usuario(usuarios, filtros["userId"]))
    if filtros["project"]:
        proyecto = buscar_proyecto(proyectos, filtros["project"])
        if proyecto:
            partes.append(f"{proyecto.code} {proyecto.name}")
    if filtros["status"]:
        partes.append(
            "Solo pendientes de aprobación"
            if filtros["status"] == "pendiente"
            else "Solo aprobados"
        )
    if filtros["from"]:
        partes.append(f"desde {filtros['from']}")
    if filtros["to"]:
        partes.append(f"hasta {filtros['to']}")
    if filtros["search"]:
        partes.append(f"texto «{filtros['search']}»")
    return f"Filtros: {' · '.join(partes)}" if partes else "Sin filtros aplicados"


def _fecha_o_vacio(clave: str) -> str:
    valor = request.args.get(clave, "").strip()
    return valor if parsear_iso(valor) else ""


def _contexto_reporte(usuario):
    """Datos que comparten el dashboard y la generación de los dos reportes."""
    instantanea = cargar_instantanea(usuario)
    todos = con_horas(instantanea.entries, instantanea.lunches)
    filtros = _filtros_de_la_peticion()
    filtrados = filtrar_registros(todos, filtros)

    reporte_usuario = request.args.get("reporte_de", "").strip()
    if reporte_usuario and not any(u.id == reporte_usuario for u in instantanea.users):
        reporte_usuario = ""
    periodo = (
        periodo_del_colaborador(
            ajustes_de(instantanea.collaboratorSettings, reporte_usuario)
        )
        if reporte_usuario
        else instantanea.period
    )

    # Fechas libres: si se indican, reemplazan los límites del periodo
    # (si solo se indica una, la otra se toma del periodo). Si vienen al
    # revés, se intercambian.
    desde_libre = _fecha_o_vacio("periodo_desde")
    hasta_libre = _fecha_o_vacio("periodo_hasta")
    if desde_libre and hasta_libre and hasta_libre < desde_libre:
        desde_libre, hasta_libre = hasta_libre, desde_libre
    if desde_libre or hasta_libre:
        periodo = Periodo(
            firstWorkday=desde_libre or periodo.firstWorkday,
            lastWorkday=hasta_libre or periodo.lastWorkday,
        )

    # Registros que entran al reporte: los filtrados, del colaborador
    # elegido (si hay uno) y dentro del periodo.
    #
    registros_reporte = [
        r for r in filtrados
        if (not reporte_usuario or r.userId == reporte_usuario)
        and periodo.firstWorkday <= r.date <= periodo.lastWorkday
    ]

    return {
        "instantanea": instantanea,
        "todos": todos,
        "filtros": filtros,
        "filtrados": filtrados,
        "reporte_usuario": reporte_usuario,
        "periodo_reporte": periodo,
        "registros_reporte": registros_reporte,
        "periodo_desde": desde_libre,
        "periodo_hasta": hasta_libre,
        "etiqueta_filtros": _etiqueta_filtros(
            filtros, instantanea.users, instantanea.projects
        ),
    }


# Dashboard ----------------------------------------------------------------


@panel.get("/dashboard")
@exigir_perfil("administrador")
def dashboard():
    usuario = usuario_de_sesion()
    datos = _contexto_reporte(usuario)
    instantanea = datos["instantanea"]
    todos = datos["todos"]

    colaboradores = colaboradores_de(instantanea.users)
    activos = [c for c in colaboradores if c.active]
    resumen = resumir(todos)
    saldos = saldos_de_colaboradores(
        todos,
        instantanea.absences,
        instantanea.collaboratorSettings,
        instantanea.projects,
        instantanea.users,
        tarifas_proyecto=instantanea.projectRates,
    )

    # Totales del equipo para las tarjetas de arriba.
    #
    trabajadas = redondear(sum(item.worked for item in saldos))
    deber = redondear(sum(item.target for item in saldos))
    acumuladas = redondear(sum(item.accumulated for item in saldos))
    vacaciones_libres = redondear(sum(item.vacation.available for item in saldos))
    ausencias_pendientes = sum(
        1 for a in instantanea.absences if a.status == "pendiente"
    )
    facturacion = totales_facturacion(
        todos, instantanea.projects, instantanea.collaboratorSettings,
        instantanea.projectRates,
    )

    pagina = _pagina()
    ordenados = ordenar_por_fecha_desc(datos["filtrados"])
    visibles = ordenados[: pagina * TAMANO_PAGINA]
    argumentos = {k: v for k, v in request.args.to_dict().items() if k != "pagina" and v}

    contexto = dict(
        colaboradores=colaboradores,
        activos=activos,
        resumen=resumen,
        trabajadas=trabajadas,
        saldos=saldos,
        deber=deber,
        acumuladas=acumuladas,
        vacaciones_libres=vacaciones_libres,
        pendientes=resumen.pendingEntries + ausencias_pendientes,
        ausencias_pendientes=ausencias_pendientes,
        facturacion=facturacion,
        filtros=datos["filtros"],
        filtrados=ordenados,
        visibles=visibles,
        hay_mas=len(ordenados) > len(visibles),
        pagina=pagina,
        reporte_usuario=datos["reporte_usuario"],
        periodo_reporte=datos["periodo_reporte"],
        registros_reporte=datos["registros_reporte"],
        periodo_desde=datos["periodo_desde"],
        periodo_hasta=datos["periodo_hasta"],
        grafico_colaboradores=barras_apiladas(
            horas_por_colaborador(todos, instantanea.users)
        ),
        grafico_estado=rosco_estado(distribucion_por_estado(todos)),
        grafico_proyectos=barras_proyecto(horas_por_proyecto(todos)),
        leyenda_estado=leyenda(["hours", "pending"]),
        detalle_registro=lambda item: _detalle_registro(item, instantanea),
        almuerzos=instantanea.lunches,
        argumentos=argumentos,
        iniciales_de=iniciales_de,
    )
    return render_template("dashboard.html", **contexto_base(instantanea, contexto))


def _detalle_registro(item, instantanea):
    """Proyecto, tarifa aplicada y monto de un registro, para el detalle."""
    proyecto = buscar_proyecto(instantanea.projects, item.projectId)
    tarifa, _origen = resolver_tarifa(
        item, proyecto, instantanea.collaboratorSettings.get(item.userId),
        instantanea.projectRates,
    )
    monto = monto_del_registro(
        item, instantanea.projects, instantanea.collaboratorSettings,
        instantanea.projectRates,
    )
    return {
        "proyecto": proyecto,
        "tarifa": tarifa,
        "monto": monto,
        "colaborador": nombre_de_usuario(instantanea.users, item.userId),
        "almuerzo": almuerzo_de(instantanea.lunches, item.userId, item.date),
    }


# Reportes en Excel --------------------------------------------------------


@panel.get("/reportes/<tipo>.xlsx")
@exigir_perfil("administrador")
def descargar_reporte(tipo: str):
    usuario = usuario_de_sesion()
    datos = _contexto_reporte(usuario)
    instantanea = datos["instantanea"]

    if not datos["registros_reporte"]:
        flash(
            "No hay registros para exportar en ese periodo. Ajuste los filtros "
            "o las fechas para incluir al menos un registro.",
            "error",
        )
        return redirect(url_for("panel.dashboard", **request.args.to_dict()))

    contexto = {
        "entries": datos["registros_reporte"],
        # Todos los registros, para calcular saldos acumulados que no
        # dependen de los filtros.
        "allEntries": datos["todos"],
        "projects": instantanea.projects,
        "users": instantanea.users,
        "settings": instantanea.collaboratorSettings,
        "projectRates": instantanea.projectRates,
        "lunches": instantanea.lunches,
        "absences": instantanea.absences,
        "period": datos["periodo_reporte"],
        "filtersLabel": datos["etiqueta_filtros"],
        "onlyUserId": datos["reporte_usuario"] or None,
    }

    if tipo == "general":
        libro, nombre = reporte_general(contexto)
    elif tipo == "por-colaborador":
        libro, nombre = reporte_por_colaborador(contexto)
    else:
        flash("Ese reporte no existe.", "error")
        return redirect(url_for("panel.dashboard"))

    memoria = io.BytesIO()
    libro.save(memoria)
    memoria.seek(0)
    return send_file(
        memoria,
        mimetype=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        as_attachment=True,
        download_name=nombre,
    )


# Aprobaciones -------------------------------------------------------------


@panel.route("/aprobaciones", methods=["GET", "POST"])
@exigir_perfil("administrador")
def aprobaciones():
    usuario = usuario_de_sesion()

    if request.method == "POST":
        accion = request.form.get("accion", "")
        identificador = request.form.get("id", "")

        if accion == "aprobar-registro":
            avisar(acciones.aprobar_registro(usuario, identificador))
        elif accion == "rechazar-registro":
            avisar(acciones.rechazar_registro(usuario, identificador))
        elif accion == "eliminar-ausencia":
            avisar(acciones.retirar_ausencia(usuario, identificador))
        elif accion in ("aprobar-ausencia", "rechazar-ausencia"):
            estado = "aprobada" if accion == "aprobar-ausencia" else "rechazada"
            avisar(
                acciones.resolver_ausencia(
                    usuario, identificador, estado, request.form.get("nota", "")
                )
            )
        else:
            flash("Acción no reconocida.", "error")

        vista = request.form.get("vista", "horas")
        return redirect(url_for("panel.aprobaciones",
                                vista=vista if vista in ("horas", "ausencias", "historial") else "horas"))

    instantanea = cargar_instantanea(usuario)
    todos = con_horas(instantanea.entries, instantanea.lunches)

    registros_pendientes = ordenar_por_fecha_desc(
        [r for r in todos if r.status == "pendiente"]
    )
    ausencias_pendientes = ordenar_ausencias(
        [a for a in instantanea.absences if a.status == "pendiente"]
    )
    ausencias_resueltas = ordenar_ausencias(
        [a for a in instantanea.absences if a.status != "pendiente"]
    )

    vista = request.args.get("vista", "horas")
    if vista not in ("horas", "ausencias", "historial"):
        vista = "horas"

    contexto = dict(
        vista=vista,
        registros_pendientes=registros_pendientes,
        ausencias_pendientes=ausencias_pendientes,
        ausencias_resueltas=ausencias_resueltas,
        nombre_de=lambda uid: nombre_de_usuario(instantanea.users, uid),
        proyecto_de=lambda pid: buscar_proyecto(instantanea.projects, pid),
    )
    return render_template("aprobaciones.html", **contexto_base(instantanea, contexto))


# Configuración ------------------------------------------------------------


def _corte_sugerido() -> str:
    """Fecha de corte que se propone para trasladar las vacaciones.

    Es el 1 de enero del año en curso: el traslado se hace cuando el año ya
    cerró, nunca con una fecha futura (ver `acciones.trasladar_vacaciones`).
    """
    return f"{date.today().year}-01-01"


@panel.route("/configuracion", methods=["GET", "POST"])
@exigir_perfil("administrador")
def configuracion():
    usuario = usuario_de_sesion()

    if request.method == "POST":
        return _resolver_accion_configuracion(usuario)

    instantanea = cargar_instantanea(usuario)
    todos = con_horas(instantanea.entries, instantanea.lunches)

    colaboradores = colaboradores_de(instantanea.users)
    fichas = []
    for persona in colaboradores:
        config = ajustes_de(instantanea.collaboratorSettings, persona.id)
        saldo, _totales = vacaciones_de(config, instantanea.absences, persona.id)
        fichas.append(
            {
                "usuario": persona,
                "config": config,
                "modo_tarifa": modo_tarifa(config.rate),
                "tarifa": config.rate if config.rate else None,
                "saldo": saldo,
                "registros": sum(1 for r in todos if r.userId == persona.id),
            }
        )

    vista = request.args.get("vista", "equipo")
    if vista not in ("equipo", "proyectos", "historial", "seguridad"):
        vista = "equipo"

    contexto = dict(
        fichas=fichas,
        colaboradores=colaboradores,
        proyectos=instantanea.projects,
        tarifas_proyecto=instantanea.projectRates,
        anio=anio_de(hoy_iso()),
        vacaciones_anuales=DIAS_VACACIONES_ANUALES,
        contrasena_sugerida=sugerir_contrasena(),
        usuario_sugerido=sugerir_usuario,
        modo_tarifa=modo_tarifa,
        formatear_tarifa=formatear_tarifa,
        corte_sugerido=_corte_sugerido(),
        vista=vista,
        editando=request.args.get("editar", ""),
        creando=request.args.get("nuevo", ""),
    )

    if vista == "historial":
        from ..historial import recientes

        busqueda = request.args.get("buscar", "").strip()
        contexto.update(historial=recientes(300, busqueda), busqueda=busqueda)
    elif vista == "seguridad":
        contexto.update(_contexto_seguridad())

    return render_template("configuracion.html", **contexto_base(instantanea, contexto))


def _contexto_seguridad() -> dict:
    import json

    from ..db import consultar_una

    fila = consultar_una("SELECT valor FROM meta WHERE clave = 'recuperacion'")
    try:
        cuentas = json.loads(fila["valor"]) if fila else []
    except (ValueError, TypeError):
        cuentas = []
    almacen = current_app.config.get("ALMACEN")
    cuenta = almacen.cuenta.info() if almacen is not None else {}
    return {
        "cuentas_recuperacion": cuentas,
        "cuenta_actual": cuenta,
        "cuenta_autorizada": any(c.get("oid") == cuenta.get("oid") for c in cuentas)
        if cuenta.get("oid") else False,
    }


def _resolver_accion_configuracion(usuario):
    accion = request.form.get("accion", "")
    formulario = request.form
    vista = formulario.get("vista", "equipo")
    if vista not in ("equipo", "proyectos", "historial", "seguridad"):
        vista = "equipo"
    volver = url_for("panel.configuracion", vista=vista)

    if accion == "periodo":
        avisar(
            acciones.actualizar_periodo(
                usuario,
                {
                    "firstWorkday": texto_o_none(formulario.get("firstWorkday")),
                    "lastWorkday": texto_o_none(formulario.get("lastWorkday")),
                },
            )
        )

    elif accion == "crear-colaborador":
        resultado = avisar(
            acciones.agregar_colaborador(
                usuario,
                {
                    "name": formulario.get("name", ""),
                    "username": formulario.get("username", "")
                    or sugerir_usuario(formulario.get("name", "")),
                    "password": formulario.get("password", ""),
                    "email": formulario.get("email", ""),
                },
            )
        )
        if not resultado.get("ok"):
            # Si falló, se vuelve al formulario abierto para corregirlo.
            volver = url_for("panel.configuracion", vista="equipo", nuevo="colaborador")

    elif accion == "editar-colaborador":
        avisar(
            acciones.actualizar_colaborador(
                usuario,
                formulario.get("id", ""),
                {
                    "name": formulario.get("name", ""),
                    "email": formulario.get("email", ""),
                    "username": formulario.get("username", ""),
                    "active": formulario.get("active") == "1",
                },
            )
        )
        volver = url_for("panel.configuracion", vista="equipo", editar=formulario.get("id", ""))

    elif accion == "parametros-colaborador":
        cambios = {
            "dailyTargetHours": numero_o_none(formulario.get("dailyTargetHours")),
            "carriedBalanceHours": numero_o_none(
                formulario.get("carriedBalanceHours")
            ),
            "carriedVacationDays": numero_o_none(
                formulario.get("carriedVacationDays")
            ),
            "annualVacationDays": numero_o_none(formulario.get("annualVacationDays")),
            "periodFrom": texto_o_none(formulario.get("periodFrom")),
            "periodTo": texto_o_none(formulario.get("periodTo")),
            "rate": leer_tarifa(formulario, "tarifa"),
        }
        avisar(
            acciones.actualizar_ajustes_colaborador(
                usuario, formulario.get("id", ""), cambios
            )
        )
        volver = url_for("panel.configuracion", vista="equipo", editar=formulario.get("id", ""))

    elif accion == "trasladar-vacaciones":
        avisar(
            acciones.trasladar_vacaciones(
                usuario, formulario.get("id", ""), texto_o_none(formulario.get("corte"))
            )
        )
        volver = url_for("panel.configuracion", vista="equipo", editar=formulario.get("id", ""))

    elif accion == "restablecer-contrasena":
        avisar(
            acciones.restablecer_contrasena(
                usuario, formulario.get("id", ""), formulario.get("password", "")
            )
        )

    elif accion == "eliminar-colaborador":
        avisar(acciones.eliminar_colaborador(usuario, formulario.get("id", "")))

    elif accion == "crear-proyecto":
        resultado = avisar(
            acciones.agregar_proyecto(
                usuario,
                {
                    "code": formulario.get("code", ""),
                    "name": formulario.get("name", ""),
                    "leader": formulario.get("leader", ""),
                    "ownerId": formulario.get("ownerId", ""),
                    "rate": _tarifa_de_proyecto(formulario),
                    "active": True,
                },
            )
        )
        if not resultado.get("ok"):
            volver = url_for("panel.configuracion", vista="proyectos", nuevo="proyecto")

    elif accion == "editar-proyecto":
        avisar(
            acciones.actualizar_proyecto(
                usuario,
                formulario.get("id", ""),
                {
                    "code": formulario.get("code", ""),
                    "name": formulario.get("name", ""),
                    "leader": formulario.get("leader", ""),
                    "ownerId": formulario.get("ownerId", ""),
                    "active": formulario.get("active") == "1",
                    "rate": _tarifa_de_proyecto(formulario),
                },
            )
        )

    elif accion == "tarifa-persona-proyecto":
        avisar(
            acciones.fijar_tarifa_de_proyecto(
                usuario,
                formulario.get("usuario_id", ""),
                formulario.get("proyecto_id", ""),
                leer_tarifa(formulario, "tarifa"),
            )
        )
        volver = url_for("panel.configuracion", vista="proyectos",
                         editar=formulario.get("proyecto_id", ""))

    elif accion == "eliminar-proyecto":
        avisar(acciones.eliminar_proyecto(usuario, formulario.get("id", "")))

    elif accion in ("autorizar-recuperacion", "quitar-recuperacion"):
        almacen = current_app.config.get("ALMACEN")
        cuenta = almacen.cuenta.info() if almacen is not None else {}
        if accion == "quitar-recuperacion":
            cuenta = {"oid": formulario.get("oid", ""), "correo": formulario.get("correo", "")}
        avisar(acciones.autorizar_recuperacion(
            usuario, cuenta, autorizar=accion == "autorizar-recuperacion"))

    # Cualquier otra cosa es un formulario desconocido.
    else:
        flash("Acción no reconocida.", "error")

    return redirect(volver)


def _tarifa_de_proyecto(formulario):
    """Tarifa de un proyecto.

    A diferencia de la del colaborador, solo distingue «con valor» y «sin
    tarifa asignada»: un proyecto no hereda de ningún nivel superior.
    """
    tarifa = leer_tarifa(formulario, "tarifa")
    return tarifa if isinstance(tarifa, Tarifa) else None
