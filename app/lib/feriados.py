"""Feriados de ley de Costa Rica. Puerto de `src/lib/holidays.ts`.

Se usan para marcar los días que no generan horas deber. Se calculan para
cualquier año, de modo que el sistema siga siendo correcto sin tener que
tocarlo cada enero.
"""

from __future__ import annotations

from datetime import date, timedelta

# Feriados de fecha fija: (mes, día, nombre).
FIJOS: list[tuple[int, int, str]] = [
    (1, 1, "Año Nuevo"),
    (4, 11, "Día de Juan Santamaría"),
    (5, 1, "Día del Trabajador"),
    (7, 25, "Anexión del Partido de Nicoya"),
    (8, 2, "Día de la Virgen de los Ángeles"),
    (8, 15, "Día de la Madre"),
    (9, 15, "Día de la Independencia"),
    (12, 1, "Día de la Abolición del Ejército"),
    (12, 25, "Navidad"),
]


def _domingo_de_pascua(anio: int) -> date:
    """Algoritmo gregoriano anónimo (Meeus/Jones/Butcher).

    De ahí salen el Jueves y el Viernes Santo, que cambian cada año.
    """
    a = anio % 19
    b = anio // 100
    c = anio % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def _tabla_del_anio(anio: int) -> dict[str, str]:
    tabla = {}
    for mes, dia, nombre in FIJOS:
        tabla[f"{anio}-{mes:02d}-{dia:02d}"] = nombre

    pascua = _domingo_de_pascua(anio)
    tabla[(pascua - timedelta(days=3)).strftime("%Y-%m-%d")] = "Jueves Santo"
    tabla[(pascua - timedelta(days=2)).strftime("%Y-%m-%d")] = "Viernes Santo"
    return tabla


_cache: dict[int, dict[str, str]] = {}


def tabla_de(anio: int) -> dict[str, str]:
    if anio not in _cache:
        _cache[anio] = _tabla_del_anio(anio)
    return _cache[anio]


def obtener_feriado(fecha_iso: str) -> str | None:
    """Nombre del feriado que cae en esa fecha, o None."""
    if not fecha_iso:
        return None
    try:
        anio = int(str(fecha_iso)[:4])
    except (ValueError, TypeError):
        return None
    return tabla_de(anio).get(str(fecha_iso)[:10])
