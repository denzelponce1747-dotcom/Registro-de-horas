"""Ventana de aprobación de los registros. Puerto de `src/lib/approvals.ts`."""

from __future__ import annotations

from .tiempo import dias_entre, formatear_fecha, hoy_iso, sumar_dias

# Un registro de hasta cuatro días de antigüedad se guarda directamente.
# Crear, modificar o eliminar uno más antiguo queda pendiente hasta que una
# persona administradora lo apruebe.
#
# Ejemplo con hoy = 10 de agosto:
#   06 ago (4 días)  -> se guarda directo
#   05 ago (5 días)  -> requiere aprobación
#
# Las fechas futuras nunca requieren aprobación.
VENTANA_APROBACION_DIAS = 4

ETIQUETAS_ACCION = {
    "creacion": "Registro nuevo",
    "edicion": "Modificación",
    "eliminacion": "Eliminación",
}


def antiguedad_en_dias(fecha: str, hoy: str | None = None) -> int:
    """Días de antigüedad de una fecha respecto de hoy."""
    return dias_entre(fecha, hoy or hoy_iso())


def requiere_aprobacion(fecha: str, hoy: str | None = None) -> bool:
    """Requiere aprobación cuando pasa de la ventana de días configurada.

    Las fechas futuras no la requieren.
    """
    return antiguedad_en_dias(fecha, hoy) > VENTANA_APROBACION_DIAS


def motivo_aprobacion(fecha: str, accion: str, hoy: str | None = None) -> str:
    """Texto que explica por qué el cambio quedó pendiente."""
    edad = antiguedad_en_dias(fecha, hoy)
    return (
        f"{ETIQUETAS_ACCION[accion]} de una jornada del {formatear_fecha(fecha)}, con "
        f"{edad} días de antigüedad (más de {VENTANA_APROBACION_DIAS})."
    )


def piso_edicion_libre(hoy: str | None = None) -> str:
    """Fecha más antigua que se puede registrar o editar sin aprobación."""
    return sumar_dias(hoy or hoy_iso(), -VENTANA_APROBACION_DIAS)
