"""Reporte de horas por colaborador.

Puerto de `src/lib/export/collaborator-report.ts`: una hoja por colaborador
con fecha, número de proyecto, proyecto, líder, reporte de la actividad,
horas, tarifa aplicada y monto, más una hoja **Proyectos** con las horas y los
montos por moneda.
"""

from __future__ import annotations

from openpyxl import Workbook

from ..lib.ajustes import ajustes_de, periodo_del_colaborador
from ..lib.proyectos import buscar_proyecto
from ..lib.estadisticas import monto_del_registro, totales_facturacion
from ..lib.tarifas import formatear_montos, formatear_tarifa, resolver_tarifa
from ..lib.tiempo import formatear_fecha, formatear_numero, redondear
from ..lib.usuarios import colaboradores_de, nombre_de_usuario
from .estilos import (
    Hoja,
    XL,
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

ANCHO = 8

COLUMNAS = [
    {"width": 12}, {"width": 16}, {"width": 34}, {"width": 22},
    {"width": 58}, {"width": 10}, {"width": 18}, {"width": 16},
]


def _hoja_colaborador(usuario_id: str, contexto: dict) -> Hoja:
    propios = sorted(
        [r for r in contexto["entries"] if r.userId == usuario_id],
        key=lambda r: (r.date, r.start),
    )
    # Totales del colaborador para la leyenda y la fila final.
    horas = redondear(sum(r.hours for r in propios))
    facturacion = totales_facturacion(
        propios, contexto["projects"], contexto["settings"],
        contexto.get("projectRates"),
    )
    # Si el reporte no trae periodo (no debería pasar), se usa el periodo
    # individual del colaborador.
    periodo = contexto.get("period") or periodo_del_colaborador(
        ajustes_de(contexto["settings"], usuario_id)
    )
    nombre = nombre_de_usuario(contexto["users"], usuario_id)

    filas = [
        fila_titulo("MAJERIE S.R.L", ANCHO),
        fila_subtitulo(f"Reporte de horas por colaborador · {nombre}", ANCHO),
        fila_leyenda(
            f"Periodo del {formatear_fecha(periodo.firstWorkday)} al "
            f"{formatear_fecha(periodo.lastWorkday)} · {len(propios)} registros · "
            f"{formatear_numero(horas)} horas · {facturacion.label} · {contexto['filtersLabel']}",
            ANCHO,
        ),
        fila_vacia(ANCHO),
        fila_encabezado(
            [
                "Fecha",
                "N.º de proyecto",
                "Proyecto",
                "Líder de proyecto",
                "Reporte",
                "Horas",
                "Tarifa aplicada",
                "Monto",
            ]
        ),
    ]

    for item in propios:
        proyecto = buscar_proyecto(contexto["projects"], item.projectId)
        tarifa, _origen = resolver_tarifa(
            item, proyecto, contexto["settings"].get(usuario_id),
            contexto.get("projectRates"),
        )
        monto = monto_del_registro(
            item, contexto["projects"], contexto["settings"],
            contexto.get("projectRates"),
        )
        pendiente = item.status == "pendiente"

        filas.append(
            [
                celda_fecha(item.date),
                texto(proyecto.code if proyecto else "—", alineacion="center"),
                texto(item.projectName),
                texto(proyecto.leader if proyecto else "—"),
                texto(
                    f"{item.notes} · PENDIENTE DE APROBACIÓN" if pendiente else item.notes,
                    ajustar=True,
                    color=XL["pending"] if pendiente else None,
                ),
                numero(item.hours),
                texto(formatear_tarifa(tarifa), alineacion="right"),
                dinero(monto["amount"])
                if monto
                else texto("Sin tarifa", alineacion="right", color=XL["muted"]),
            ]
        )

    filas.append(
        [total("Total")]
        + [total() for _ in range(4)]
        + [total_numero(horas), total(), total(facturacion.label)]
    )

    return Hoja(nombre=nombre_hoja(nombre), filas=filas, filas_fijas=5, columnas=COLUMNAS)


def _hoja_proyectos(contexto: dict) -> Hoja:
    registros = contexto["entries"]
    resumen = []
    # Solo los proyectos con registros en el reporte.
    for proyecto in contexto["projects"]:
        propios = [r for r in registros if r.projectId == proyecto.id]
        if not propios:
            continue
        resumen.append(
            {
                "proyecto": proyecto,
                "registros": len(propios),
                "horas": redondear(sum(r.hours for r in propios)),
                "facturacion": totales_facturacion(
                    propios, contexto["projects"], contexto["settings"],
                    contexto.get("projectRates"),
                ),
            }
        )

    resumen.sort(key=lambda fila: -fila["horas"])
    horas_totales = redondear(sum(fila["horas"] for fila in resumen))
    facturacion_total = totales_facturacion(
        registros, contexto["projects"], contexto["settings"],
        contexto.get("projectRates"),
    )

    filas = [
        fila_titulo("MAJERIE S.R.L", ANCHO),
        fila_subtitulo("Resumen por proyecto", ANCHO),
        fila_leyenda(contexto["filtersLabel"], ANCHO),
        fila_vacia(ANCHO),
        fila_seccion("Horas y montos acumulados por proyecto", ANCHO),
        fila_encabezado(
            [
                "N.º de proyecto",
                "Proyecto",
                "Líder de proyecto",
                "Pertenece a",
                "Tarifa del proyecto",
                "Registros",
                "Horas",
                "Monto",
            ]
        ),
    ]

    for fila in resumen:
        proyecto = fila["proyecto"]
        filas.append(
            [
                texto(proyecto.code, alineacion="center"),
                texto(proyecto.name, negrita=True),
                texto(proyecto.leader),
                texto(
                    nombre_de_usuario(contexto["users"], proyecto.ownerId)
                    if proyecto.ownerId
                    else "Proyecto de la empresa"
                ),
                texto(formatear_tarifa(proyecto.rate), alineacion="right"),
                numero(fila["registros"], formato="0"),
                numero(fila["horas"]),
                texto(
                    formatear_montos(fila["facturacion"].amounts), alineacion="right"
                ),
            ]
        )

    filas.append(
        [total("Total")]
        + [total() for _ in range(4)]
        + [
            total_numero(sum(fila["registros"] for fila in resumen), formato="0"),
            total_numero(horas_totales),
            total(facturacion_total.label),
        ]
    )
    filas.append(fila_vacia(ANCHO))
    filas.append(
        [
            etiqueta(
                "Las tarifas y las monedas las define el perfil Administrador.",
                columnas=ANCHO,
                color=XL["muted"],
            )
        ]
        + relleno(ANCHO - 1)
    )

    return Hoja(
        nombre="Proyectos",
        filas=filas,
        columnas=[
            {"width": 16}, {"width": 26}, {"width": 22}, {"width": 22},
            {"width": 18}, {"width": 11}, {"width": 10}, {"width": 22},
        ],
    )


def reporte_por_colaborador(contexto: dict):
    """Devuelve (libro, nombre de archivo) del reporte por colaborador."""
    solo = contexto.get("onlyUserId")
    colaboradores = [
        usuario
        for usuario in colaboradores_de(contexto["users"])
        if (not solo or usuario.id == solo)
        and any(r.userId == usuario.id for r in contexto["entries"])
    ]
    colaboradores.sort(key=lambda usuario: usuario.name)

    libro = Workbook()
    libro.remove(libro.active)

    for usuario in colaboradores:
        volcar(libro, _hoja_colaborador(usuario.id, contexto))
    volcar(libro, _hoja_proyectos(contexto))

    sufijo = ""
    if solo:
        nombre = nombre_hoja(nombre_de_usuario(contexto["users"], solo))
        sufijo = "-" + nombre.lower().replace(" ", "-")

    return libro, f"reporte-horas-por-colaborador{sufijo}.xlsx"
