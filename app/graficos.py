"""Gráficos del dashboard.

La versión desplegada usaba Recharts. Aquí los mismos tres gráficos se dibujan
como SVG en el servidor: no hacen falta bibliotecas y el sistema sigue
funcionando sin conexión.

Los colores no van escritos en el SVG sino en la hoja de estilo (clases
`g-…`), para que sigan el tema claro u oscuro. La paleta es la validada para
daltonismo y contraste del sistema original: violeta para las horas
aprobadas y naranja para las pendientes de aprobación.

Al aparecer, las barras crecen una detrás de otra y el anillo se dibuja como
un trazo de pluma (`estilo.css`, sección Gráficos).
"""

from __future__ import annotations

from html import escape

from markupsafe import Markup

from .lib.tiempo import formatear_numero

SERIES = {"hours": "var(--acento)", "pending": "var(--pendiente)"}
SERIES_ETIQUETAS = {
    "hours": "Horas aprobadas",
    "pending": "Pendientes de aprobación",
}
_CLASE = {"hours": "g-aprobadas", "pending": "g-pendientes"}


def _sin_datos(alto: int = 260) -> Markup:
    return Markup(
        f'<div class="grafico-vacio" style="height:{alto}px">Todavía no hay horas registradas.</div>'
    )


# Barras horizontales apiladas: aprobadas + pendientes de cada persona.
def barras_apiladas(datos: list, alto: int = 280) -> Markup:
    """Horas aprobadas y pendientes por colaborador, en barras horizontales."""
    if not datos:
        return _sin_datos(alto)

    maximo = max(fila["hours"] + fila["pending"] for fila in datos) or 1
    alto_fila = 42
    ancho_etiqueta = 150
    ancho_total = 720
    ancho_util = ancho_total - ancho_etiqueta - 90
    alto_total = max(alto, len(datos) * alto_fila + 20)

    piezas = []
    for indice, fila in enumerate(datos):
        y = indice * alto_fila + 10
        aprobadas = fila["hours"] / maximo * ancho_util
        pendientes = fila["pending"] / maximo * ancho_util
        total = fila["hours"] + fila["pending"]
        nombre = fila["shortName"]
        corto = nombre if len(nombre) <= 20 else nombre[:19] + "…"

        piezas.append(
            f'<text class="g-etiqueta" x="{ancho_etiqueta - 12}" y="{y + 17}" text-anchor="end" font-size="12">'
            f"{escape(corto)}</text>"
        )
        if aprobadas > 0:
            piezas.append(
                f'<rect class="g-barra g-aprobadas" x="{ancho_etiqueta}" y="{y + 4}" width="'
                f'{aprobadas:.2f}" height="20" rx="3" style="--i:{indice}"><title>'
                f'{escape(fila["name"])}: {formatear_numero(fila["hours"])} h aprobadas</title></rect>'
            )

        if pendientes > 0:
            piezas.append(
                f'<rect class="g-barra g-pendientes" x="{ancho_etiqueta + aprobadas:.2f}" y="'
                f'{y + 4}" width="{pendientes:.2f}" height="20" rx="3" style="--i:'
                f'{indice + 0.5}"><title>'
                f'{escape(fila["name"])}: {formatear_numero(fila["pending"])} h por aprobar</title></rect>'
            )

        piezas.append(
            f'<text class="g-valor" x="{ancho_etiqueta + aprobadas + pendientes + 10:.2f}" y="'
            f'{y + 19}" font-size="12" font-variant-numeric="tabular-nums" style="--i:'
            f'{indice}">{formatear_numero(total)} h</text>'
        )

    return Markup(
        f'<svg class="grafico" viewBox="0 0 {ancho_total} {alto_total}" width="100%" height="'
        f'{alto_total}" role="img" aria-label="Horas por colaborador">'
        f'{"".join(piezas)}</svg>'
    )


def barras_proyecto(datos: list, alto: int = 300) -> Markup:
    """Distribución del tiempo registrado entre proyectos y tareas."""
    if not datos:
        return _sin_datos(alto)

    visibles = datos[:12]
    maximo = max(fila["hours"] for fila in visibles) or 1
    ancho_total = 720
    margen_izq = 40
    margen_inf = 64
    alto_total = alto
    alto_util = alto_total - margen_inf - 20
    paso = (ancho_total - margen_izq - 20) / len(visibles)
    ancho_barra = min(52, paso * 0.62)

    piezas = [
        f'<line class="g-rejilla" x1="{margen_izq}" y1="{alto_util + 20}" x2="'
        f'{ancho_total - 20}" y2="{alto_util + 20}" stroke-width="1" />'
    ]
    # Rejilla horizontal punteada, con su valor a la izquierda.
    #
    for fraccion in (0.25, 0.5, 0.75, 1.0):
        y = 20 + alto_util * (1 - fraccion)
        piezas.append(
            f'<line class="g-rejilla" x1="{margen_izq}" y1="{y:.1f}" x2="{ancho_total - 20}" y2="'
            f'{y:.1f}" stroke-width="1" stroke-dasharray="3 4" />'
        )
        piezas.append(
            f'<text x="{margen_izq - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="10">'
            f"{formatear_numero(maximo * fraccion, 0)}</text>"
        )

    for indice, fila in enumerate(visibles):
        centro = margen_izq + paso * indice + paso / 2
        altura = fila["hours"] / maximo * alto_util
        y = 20 + alto_util - altura
        nombre = fila["name"]
        corto = nombre if len(nombre) <= 14 else nombre[:13] + "…"

        piezas.append(
            f'<rect class="g-columna g-aprobadas" x="{centro - ancho_barra / 2:.1f}" y="'
            f'{y:.1f}" width="{ancho_barra:.1f}" height="{altura:.1f}" rx="4" style="--i:'
            f'{indice}"><title>'
            f"{escape(nombre)}: {formatear_numero(fila['hours'])} h</title></rect>"
        )

        piezas.append(
            f'<text class="g-valor" x="{centro:.1f}" y="{y - 7:.1f}" text-anchor="middle" font-size="11" font-variant-numeric="tabular-nums" style="--i:'
            f'{indice}">'
            f'{formatear_numero(fila["hours"])}</text>'
        )
        piezas.append(
            f'<text x="{centro:.1f}" y="{alto_util + 38}" text-anchor="middle" font-size="11">'
            f"{escape(corto)}</text>"
        )

    return Markup(
        f'<svg class="grafico" viewBox="0 0 {ancho_total} {alto_total}" width="100%" height="'
        f'{alto_total}" role="img" aria-label="Horas por proyecto">'
        f'{"".join(piezas)}</svg>'
    )


def rosco_estado(datos: list, alto: int = 260) -> Markup:
    """Participación de las horas aprobadas y las que esperan aprobación."""
    total = sum(fila["value"] for fila in datos)
    if total <= 0:
        return _sin_datos(alto)

    centro = alto / 2
    radio = alto * 0.34
    grosor = alto * 0.13
    piezas = [
        f'<circle class="g-fondo-arco" cx="{centro}" cy="{centro}" r="{radio}" stroke-width="'
        f'{grosor}" />'
    ]
    # Cada tramo es un círculo con un guion del largo de su porción. Con
    # `pathLength="100"` los largos son porcentajes y el desfase acumulado
    # los pone uno detrás de otro.
    #
    acumulado = 0.0
    orden = 0
    for fila in datos:
        if fila["value"] <= 0:
            continue
        porcion = fila["value"] / total * 100
        titulo = f"{fila['name']}: {formatear_numero(fila['value'])} h"
        piezas.append(
            f'<circle class="g-arco g-arco-{"aprobadas" if fila["key"] == "hours" else "pendientes"}" cx="'
            f'{centro}" cy="{centro}" r="{radio}" stroke-width="{grosor}" pathLength="100" stroke-dasharray="'
            f'{porcion:.3f} {100 - porcion:.3f}" stroke-dashoffset="'
            f'{-acumulado:.3f}" transform="rotate(-90 '
            f'{centro} {centro})" style="--i:{orden}"><title>'
            f"{escape(titulo)}</title></circle>"
        )
        acumulado += porcion
        orden += 1

    aprobadas = next((f["value"] for f in datos if f["key"] == "hours"), 0)
    porcentaje = round(aprobadas / total * 100) if total else 0

    piezas.append(
        f'<text class="g-centro" x="{centro}" y="{centro - 2}" text-anchor="middle" font-size="24" font-variant-numeric="tabular-nums">'
        f"{porcentaje}%</text>"
    )
    piezas.append(
        f'<text x="{centro}" y="{centro + 18}" text-anchor="middle" font-size="11">aprobadas</text>'
    )


    return Markup(
        f'<svg class="grafico" viewBox="0 0 {alto} {alto}" width="100%" height="{alto}" role="img" aria-label="Estado de los registros">'
        f'{"".join(piezas)}</svg>'
    )


def leyenda(claves: list) -> Markup:
    """Leyenda de colores compartida por los gráficos."""
    piezas = [
        f'<span><i style="background:{SERIES[clave]}"></i>{SERIES_ETIQUETAS[clave]}</span>'
        for clave in claves
    ]
    return Markup('<div class="leyenda">' + "".join(piezas) + "</div>")
