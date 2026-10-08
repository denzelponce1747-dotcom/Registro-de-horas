"""Piezas que comparten las pantallas: avisos, contexto y lectura de formularios."""

from __future__ import annotations

from flask import flash

from ..lib.tipos import HEREDADA, Tarifa


def avisar(resultado: dict) -> dict:
    """Convierte el resultado de una acción en el aviso que verá la persona.

    Es el equivalente de las notificaciones que el sistema original mostraba
    con `toast`: éxito, éxito con envío a aprobación, o error.
    """
    if not resultado.get("ok"):
        flash(resultado.get("error", "No fue posible completar la operación."), "error")
        return resultado

    mensaje = resultado.get("message") or "Cambio guardado."
    flash(mensaje, "pendiente" if resultado.get("pending") else "exito")
    return resultado


def contexto_base(instantanea, extra: dict) -> dict:
    """Agrega a cada pantalla lo que la barra superior necesita."""
    pendientes_totales = sum(
        1 for r in instantanea.entries if r.status == "pendiente"
    ) + sum(1 for a in instantanea.absences if a.status == "pendiente")

    contexto = {
        "instantanea": instantanea,
        "pendientes_totales": pendientes_totales,
        "periodo": instantanea.period,
    }
    contexto.update(extra)
    return contexto


def numero_o_none(valor):
    """Lee un número de un formulario; None si el campo venía vacío."""
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return float(str(valor).replace(",", "."))
    except ValueError:
        return None


def texto_o_none(valor):
    limpio = (valor or "").strip()
    return limpio or None


def leer_tarifa(formulario, prefijo: str):
    """Reconstruye una tarifa heredable a partir del editor de tarifa.

    Devuelve el centinela HEREDADA, `None` («sin tarifa asignada») o una
    `Tarifa` con su valor y su moneda.
    """
    modo = formulario.get(f"{prefijo}_modo", "heredada")
    if modo == "heredada":
        return HEREDADA
    if modo == "sin-tarifa":
        return None

    monto = numero_o_none(formulario.get(f"{prefijo}_monto")) or 0
    moneda = formulario.get(f"{prefijo}_moneda") or "CRC"
    return Tarifa(amount=monto, currency=moneda)
