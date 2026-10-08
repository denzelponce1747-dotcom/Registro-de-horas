"""Tarifario. Puerto de `src/lib/rates.ts`.

La tarifa se resuelve en cascada registro -> colaborador -> proyecto. En
cualquiera de los tres niveles se puede indicar «sin tarifa», y esa decisión
corta la cascada. Como pueden convivir varias monedas, los montos nunca se
suman entre monedas.
"""

from __future__ import annotations

from .tiempo import formatear_monto, redondear
from .tipos import HEREDADA, Tarifa

# Monedas que ofrece el selector.
MONEDAS = [
    {"value": "CRC", "label": "Colones (CRC)", "symbol": "₡"},
    {"value": "USD", "label": "Dólares (USD)", "symbol": "$"},
    {"value": "EUR", "label": "Euros (EUR)", "symbol": "€"},
    {"value": "CHF", "label": "Francos suizos (CHF)", "symbol": "CHF"},
]

# Moneda que propone el formulario.
MONEDA_POR_OMISION = "CRC"

# Valores del selector «Tarifa».
MODO_HEREDADA = "heredada"
MODO_PROPIA = "propia"
MODO_SIN_TARIFA = "sin-tarifa"

ETIQUETAS_ORIGEN = {
    "registro": "Tarifa del registro",
    "colaborador-proyecto": "Tarifa de la persona en este proyecto",
    "colaborador": "Tarifa del colaborador",
    "proyecto": "Tarifa del proyecto",
    "sin-tarifa": "Sin tarifa",
}


def clave_tarifa(usuario_id: str, proyecto_id: str) -> str:
    """Clave del tarifario por persona y proyecto."""
    return f"{usuario_id}|{proyecto_id}"


def simbolo_moneda(moneda: str) -> str:
    for item in MONEDAS:
        if item["value"] == moneda:
            return item["symbol"]
    return moneda


def modo_tarifa(tarifa) -> str:
    """Traduce la tarifa heredable al valor del selector."""
    if tarifa is HEREDADA:
        return MODO_HEREDADA
    if tarifa is None:
        return MODO_SIN_TARIFA
    return MODO_PROPIA


def resolver_tarifa(registro, proyecto, ajustes, tarifas_persona_proyecto=None):
    """Cascada registro -> persona en el proyecto -> colaborador -> proyecto.

    Gana siempre lo más específico. `tarifas_persona_proyecto` es el mapa
    `usuario|proyecto -> tarifa heredable`, que permite que dos personas
    cobren distinto en el mismo proyecto.

    Devuelve (tarifa, origen); la tarifa es None cuando no hay ninguna
    aplicable, sea porque se marcó «sin tarifa» o porque nunca se asignó.
    """
    tarifa_registro = getattr(registro, "rate", HEREDADA)
    if tarifa_registro is not HEREDADA:
        return tarifa_registro, "registro" if tarifa_registro else "sin-tarifa"

    if tarifas_persona_proyecto:
        propia = tarifas_persona_proyecto.get(
            clave_tarifa(
                getattr(registro, "userId", ""), getattr(registro, "projectId", "")
            ),
            HEREDADA,
        )
        if propia is not HEREDADA:
            return propia, "colaborador-proyecto" if propia else "sin-tarifa"

    tarifa_ajustes = getattr(ajustes, "rate", HEREDADA) if ajustes else HEREDADA
    if tarifa_ajustes is not HEREDADA:
        return tarifa_ajustes, "colaborador" if tarifa_ajustes else "sin-tarifa"

    tarifa_proyecto = getattr(proyecto, "rate", None) if proyecto else None
    return tarifa_proyecto, "proyecto" if tarifa_proyecto else "sin-tarifa"


def sumar_monto(totales: dict, moneda: str, monto: float) -> dict:
    """Acumula un monto en su moneda; las monedas nunca se mezclan."""
    totales[moneda] = redondear(totales.get(moneda, 0) + monto)
    return totales


def fusionar_montos(a: dict, b: dict) -> dict:
    fusion = dict(a)
    for moneda, monto in b.items():
        sumar_monto(fusion, moneda, monto)
    return fusion


def formatear_montos(totales: dict) -> str:
    """Devuelve algo como «1.250,00 CRC · 480,00 USD», o «Sin tarifa»."""
    partes = [
        f"{formatear_monto(monto)} {moneda}"
        for moneda, monto in totales.items()
        if monto != 0
    ]
    return " · ".join(partes) if partes else "Sin tarifa"


def formatear_tarifa(tarifa) -> str:
    if not tarifa:
        return "Sin tarifa"
    return f"{formatear_monto(tarifa.amount)} {tarifa.currency}/h"
