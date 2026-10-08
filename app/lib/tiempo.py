"""Fechas, horas y formatos. Puerto directo de `src/lib/time.ts`.

Todo el sistema maneja las fechas como ISO corto (AAAA-MM-DD) y las horas
como "HH:mm", igual que la versión original: así el dato que viaja entre la
base, la pantalla y los reportes es siempre el mismo texto.
"""

from __future__ import annotations

import math
from datetime import date as _date, timedelta

MESES_CORTOS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]

MESES_LARGOS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "setiembre", "octubre", "noviembre", "diciembre",
]

DIAS_SEMANA = [
    "domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado",
]

DIAS_SEMANA_CORTOS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"]


def redondear(valor: float, decimales: int = 2) -> float:
    """Redondeo idéntico al `Math.round(x * 100) / 100` de JavaScript.

    El `round` de Python usa redondeo bancario (0,5 al par más cercano), que
    daría totales distintos a los del sistema original. Aquí se replica el
    comportamiento de JavaScript: la mitad siempre sube.
    """
    if valor is None:
        return 0.0
    factor = 10 ** decimales
    return math.floor(valor * factor + 0.5) / factor


def _dia_semana_js(fecha: _date) -> int:
    """Domingo = 0, como `Date.getDay()` en JavaScript."""
    return (fecha.weekday() + 1) % 7


def a_minutos(hora: str) -> float:
    """Convierte "HH:mm" a minutos desde medianoche."""
    try:
        horas, minutos = hora.split(":")[:2]
        return int(horas) * 60 + int(minutos)
    except (ValueError, AttributeError):
        return math.nan


def a_texto_hora(minutos: int) -> str:
    """Convierte minutos desde medianoche a "HH:mm"."""
    h, m = divmod(int(minutos), 60)
    return f"{h:02d}:{m:02d}"


def minutos_entre(inicio: str, fin: str) -> float:
    """Minutos transcurridos entre dos horas del mismo día."""
    desde = a_minutos(inicio)
    hasta = a_minutos(fin)
    if math.isnan(desde) or math.isnan(hasta) or hasta <= desde:
        return 0
    return hasta - desde


def horas_brutas_entre(inicio: str, fin: str) -> float:
    """Jornada bruta en horas decimales, sin descontar el almuerzo."""
    return redondear(minutos_entre(inicio, fin) / 60)


def horas_entre(inicio: str, fin: str, minutos_descanso: int = 0) -> float:
    """Horas efectivamente trabajadas, ya descontado el descanso."""
    bruto = minutos_entre(inicio, fin)
    if bruto <= 0:
        return 0.0
    neto = bruto - max(0, minutos_descanso)
    return 0.0 if neto <= 0 else redondear(neto / 60)


# Signo menos tipográfico (U+2212), el mismo que usa `Intl.NumberFormat`.
MENOS = "−"


def formatear_numero(valor: float, decimales: int = 2) -> str:
    """Número con coma decimal (es-CR), sin unidad."""
    texto = f"{redondear(valor or 0, decimales):.{decimales}f}".replace(".", ",")
    if texto.startswith("-"):
        # «-0,00» se muestra como «0,00».
        texto = texto[1:] if set(texto[1:]) <= {"0", ","} else MENOS + texto[1:]
    return texto


def formatear_monto(valor: float) -> str:
    """19786.75 -> "19.786,75" (separador de miles con punto)."""
    entero, decimales = f"{abs(redondear(valor or 0)):.2f}".split(".")
    signo = MENOS if (valor or 0) < 0 and (entero, decimales) != ("0", "00") else ""
    grupos = f"{int(entero):,}".replace(",", ".")
    return f"{signo}{grupos},{decimales}"


def valor_entrada(valor) -> str:
    """Un número para un campo `type=number`: con punto (lo exige el
    navegador, que lo muestra con coma en español) y sin ceros sobrantes.

    6.0 -> "6"; 8.5 -> "8.5"; 32000.0 -> "32000"; None -> "".
    """
    if valor is None or valor == "":
        return ""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return ""
    if numero == 0:
        return "0"
    return f"{numero:.4f}".rstrip("0").rstrip(".")


def formatear_tamano(octetos: int) -> str:
    """24064 -> "23,5 KB"; 1572864 -> "1,5 MB"."""
    octetos = int(octetos or 0)
    if octetos < 1024:
        return f"{octetos} B"
    if octetos < 1024 * 1024:
        return f"{formatear_numero(octetos / 1024, 1)} KB"
    return f"{formatear_numero(octetos / (1024 * 1024), 1)} MB"


def formatear_momento(iso: str) -> str:
    """Un instante de SharePoint (ISO en UTC) en la hora de esta computadora:
    «hoy a las 11:33», «ayer a las 16:02» o «5 oct 2026, 11:33»."""
    from datetime import datetime, timezone

    if not iso:
        return ""
    try:
        momento = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    local = momento.astimezone()
    hoy = _date.today()
    hora = f"{local.hour:02d}:{local.minute:02d}"
    if local.date() == hoy:
        return f"hoy a las {hora}"
    if local.date() == hoy - timedelta(days=1):
        return f"ayer a las {hora}"
    return f"{formatear_fecha(local.date().isoformat())}, {hora}"


def formatear_horas(valor: float) -> str:
    """8.5 -> "8,50 h" """
    return f"{formatear_numero(valor)} h"


def formatear_horas_reloj(valor: float) -> str:
    """8.5 -> "8h 30m" """
    total = int(redondear(valor * 60, 0))
    h, m = divmod(total, 60)
    return f"{h}h" if m == 0 else f"{h}h {m:02d}m"


def a_iso(fecha: _date) -> str:
    return fecha.strftime("%Y-%m-%d")


def hoy_iso() -> str:
    return a_iso(_date.today())


def parsear_iso(iso: str) -> _date | None:
    """Parsea "AAAA-MM-DD" como fecha local; None si no es válida."""
    if not iso:
        return None
    try:
        anio, mes, dia = (int(parte) for parte in str(iso)[:10].split("-"))
        return _date(anio, mes, dia)
    except (ValueError, TypeError):
        return None


def formatear_fecha(iso: str) -> str:
    """"2026-08-06" -> "06 ago 2026" """
    fecha = parsear_iso(iso)
    if not fecha:
        return iso or ""
    return f"{fecha.day:02d} {MESES_CORTOS[fecha.month - 1]} {fecha.year}"


def formatear_fecha_larga(iso: str) -> str:
    """"2026-08-06" -> "jueves, 6 de agosto de 2026" """
    fecha = parsear_iso(iso)
    if not fecha:
        return iso or ""
    return (
        f"{DIAS_SEMANA[_dia_semana_js(fecha)]}, {fecha.day} de "
        f"{MESES_LARGOS[fecha.month - 1]} de {fecha.year}"
    )


def dia_semana_corto(iso: str) -> str:
    fecha = parsear_iso(iso)
    return "" if not fecha else DIAS_SEMANA_CORTOS[_dia_semana_js(fecha)]


def formatear_dia_semana(iso: str) -> str:
    """"2026-08-06" -> "jueves 6" """
    fecha = parsear_iso(iso)
    if not fecha:
        return iso or ""
    return f"{DIAS_SEMANA[_dia_semana_js(fecha)]} {fecha.day}"


def es_fin_de_semana(iso: str) -> bool:
    fecha = parsear_iso(iso)
    if not fecha:
        return False
    dia = _dia_semana_js(fecha)
    return dia == 0 or dia == 6


def dias_entre(desde: str, hasta: str) -> int:
    """Días completos entre dos fechas ISO; negativo si `hasta` es anterior."""
    a = parsear_iso(desde)
    b = parsear_iso(hasta)
    if not a or not b:
        return 0
    return (b - a).days


def sumar_dias(iso: str, dias: int) -> str:
    fecha = parsear_iso(iso)
    if not fecha:
        return iso
    return a_iso(fecha + timedelta(days=dias))


def inicio_de_semana(iso: str) -> str:
    """Lunes de la semana a la que pertenece la fecha."""
    fecha = parsear_iso(iso)
    if not fecha:
        return iso
    return sumar_dias(iso, -fecha.weekday())


def fin_de_semana_iso(iso: str) -> str:
    """Domingo de la semana a la que pertenece la fecha."""
    return sumar_dias(inicio_de_semana(iso), 6)


def formatear_rango(desde: str, hasta: str) -> str:
    """"06 ago 2026 – 12 ago 2026" """
    return f"{formatear_fecha(desde)} – {formatear_fecha(hasta)}"


def anio_de(iso: str) -> int:
    try:
        return int(str(iso)[:4])
    except (ValueError, TypeError):
        return 0


def cada_fecha(desde: str, hasta: str) -> list[str]:
    """Todas las fechas ISO entre dos extremos, ambos incluidos."""
    inicio = parsear_iso(desde)
    fin = parsear_iso(hasta)
    if not inicio or not fin:
        return []

    fechas = []
    cursor = inicio
    # Tope de seguridad: ningún rango del sistema supera dos años.
    guarda = 0
    while cursor <= fin and guarda < 800:
        fechas.append(a_iso(cursor))
        cursor += timedelta(days=1)
        guarda += 1
    return fechas


def formatear_mes(iso: str) -> str:
    """"2026-08-06" -> "ago 2026" """
    fecha = parsear_iso(iso)
    if not fecha:
        return iso or ""
    return f"{MESES_CORTOS[fecha.month - 1]} {fecha.year}"
