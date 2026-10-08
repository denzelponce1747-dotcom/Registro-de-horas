"""Defensas del servidor interno.

El programa sirve sus pantallas solo dentro de esta computadora
(`localhost`): nadie de la red ni de internet llega a él. Aun así, una
página maliciosa abierta en cualquier navegador de la computadora podría
intentar hablarle. Tres cerrojos lo impiden:

1. **Anfitrión.** Solo se atienden peticiones dirigidas a `localhost` o a
   `127.0.0.1`. Eso corta el «DNS rebinding», el truco de hacer pasar un
   dominio ajeno por la propia computadora.
2. **Origen.** Un formulario enviado desde otro sitio trae su `Origin`: se
   rechaza. Las cookies además van con `SameSite=Lax`.
3. **Freno de intentos** en el ingreso, por si alguien con acceso a la
   computadora prueba contraseñas.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from flask import abort, request


# Ocho intentos fallidos en quince minutos bloquean el ingreso diez minutos.
VENTANA_SEGUNDOS = 15 * 60
INTENTOS_MAXIMOS = 8
BLOQUEO_SEGUNDOS = 10 * 60

_intentos: dict[str, deque] = {}
_bloqueos: dict[str, float] = {}
_candado = threading.Lock()


def _clave() -> str:
    """Quien intenta: el nombre de usuario escrito (todo es local)."""
    return (request.form.get("username", "") or "").strip().lower() or "?"


def _limpiar(cola: deque, ahora: float) -> None:
    while cola and ahora - cola[0] > VENTANA_SEGUNDOS:
        cola.popleft()


def espera_restante() -> int:
    """Segundos que faltan para poder volver a intentar; 0 si se puede ya."""
    clave = _clave()
    ahora = time.time()
    with _candado:
        hasta = _bloqueos.get(clave, 0)
        if hasta > ahora:
            return int(hasta - ahora)
        if hasta:
            _bloqueos.pop(clave, None)
            _intentos.pop(clave, None)
    return 0


def anotar_fallo() -> None:
    clave = _clave()
    ahora = time.time()
    with _candado:
        cola = _intentos.setdefault(clave, deque())
        _limpiar(cola, ahora)
        cola.append(ahora)
        if len(cola) >= INTENTOS_MAXIMOS:
            _bloqueos[clave] = ahora + BLOQUEO_SEGUNDOS
            cola.clear()


def anotar_acierto() -> None:
    clave = _clave()
    with _candado:
        _intentos.pop(clave, None)
        _bloqueos.pop(clave, None)


def texto_espera(segundos: int) -> str:
    minutos = max(1, round(segundos / 60))
    if minutos == 1:
        return "Demasiados intentos fallidos. Espere un minuto y vuelva a probar."
    return f"Demasiados intentos fallidos. Espere {minutos} minutos y vuelva a probar."


# Nombres con que el navegador puede llegar al servidor interno. `[::1]` es
# `localhost` en IPv6.
ANFITRIONES = ("localhost", "127.0.0.1", "[::1]")


def _anfitrion_permitido(valor: str) -> bool:
    nombre = (valor or "").strip().lower()
    if nombre.startswith("["):
        nombre = nombre.split("]")[0] + "]"
    else:
        nombre = nombre.split(":")[0]
    return nombre in ANFITRIONES


def peticion_segura() -> bool:
    """El servidor interno va por HTTP: las cookies no se marcan «secure»."""
    return request.is_secure


def registrar_seguridad(aplicacion) -> None:
    @aplicacion.before_request
    def _anfitrion_y_origen():
        if aplicacion.config.get("TESTING") and not aplicacion.config.get("PROBAR_ANFITRION"):
            return None
        if not _anfitrion_permitido(request.host):
            abort(400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origen = request.headers.get("Origin", "")
            if origen and origen != "null":
                from urllib.parse import urlsplit

                if not _anfitrion_permitido(urlsplit(origen).netloc):
                    abort(403)
        return None

    @aplicacion.after_request
    def _encabezados(respuesta):
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        respuesta.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if respuesta.mimetype == "text/html":
            respuesta.headers.setdefault("Cache-Control", "no-store")
        return respuesta
