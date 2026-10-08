"""Tiempo de almuerzo. Puerto de `src/lib/lunch.ts`.

Se registra manualmente, una sola vez por jornada y no dentro de cada
actividad: así una persona con varias actividades en el mismo día no tiene
que repartir el almuerzo a mano. Al calcular las horas, el almuerzo del día
se prorratea entre las actividades de esa fecha.
"""

from __future__ import annotations

import math

# El almuerzo se registra en pasos de 5 minutos.
PASO_MINUTOS = 5
# Cuatro horas: más que eso no es un almuerzo.
MAXIMO_MINUTOS = 240

# Lo que propone el formulario la primera vez.
MINUTOS_POR_OMISION = 60

# Botones de acceso rápido del formulario.
ATAJOS = [0, 30, 45, 60, 90]


def clave_almuerzo(usuario_id: str, fecha: str) -> str:
    """Clave con la que se guarda el almuerzo de una persona en una fecha."""
    return f"{usuario_id}|{fecha}"


def ajustar_al_paso(minutos) -> int:
    """Ajusta cualquier valor al múltiplo de 5 minutos más cercano."""
    try:
        valor = float(minutos)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(valor):
        return 0
    acotado = min(MAXIMO_MINUTOS, max(0, valor))
    return int(math.floor(acotado / PASO_MINUTOS + 0.5)) * PASO_MINUTOS


def formatear_almuerzo(minutos: int) -> str:
    """60 -> "1h"; 90 -> "1h 30m"; 45 -> "45m"; 0 -> "Sin almuerzo" """
    minutos = int(minutos or 0)
    if not minutos:
        return "Sin almuerzo"
    horas, resto = divmod(minutos, 60)
    if not horas:
        return f"{resto}m"
    return f"{horas}h {resto:02d}m" if resto else f"{horas}h"


def formatear_almuerzo_corto(minutos: int) -> str:
    """60 -> "1h"; 0 -> "—". Versión compacta para tablas."""
    return formatear_almuerzo(minutos) if minutos else "—"


def almuerzo_de(almuerzos: dict, usuario_id: str, fecha: str) -> int:
    """Minutos de almuerzo de una persona en una fecha."""
    return int(almuerzos.get(clave_almuerzo(usuario_id, fecha), 0) or 0)
