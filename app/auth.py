"""Contraseñas, sesiones e identidades.

Reúne lo que en el sistema original estaba en `src/lib/auth/password.ts`,
`src/lib/auth/session.ts` y `src/lib/auth/identities.ts`. El formato de la
huella de la contraseña y el de la cookie de sesión son idénticos a los de la
versión desplegada, de modo que una base exportada de allá sigue sirviendo
aquí sin que nadie tenga que cambiar su contraseña.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata
from functools import wraps

from flask import current_app, g, redirect, request, url_for

from .db import consultar_una


# ---------------------------------------------------------------------------
# Identidades de la administración
# ---------------------------------------------------------------------------
# La cuenta de administración la comparten dos personas; al entrar, cada una
# elige con qué nombre actúa.
IDENTIDADES_ADMIN = ("María Quesada", "Jérémie Surbeck")


def es_identidad_admin(valor: str) -> bool:
    return valor in IDENTIDADES_ADMIN


def iniciales_identidad(identidad: str) -> str:
    palabras = [p for p in re.split(r"\s+", (identidad or "").strip()) if p]
    return "".join(p[0].upper() for p in palabras[:2]) or "?"


# ---------------------------------------------------------------------------
# Contraseñas
# ---------------------------------------------------------------------------
# Parámetros de scrypt: los mismos que la versión desplegada.
_N = 16384
_R = 8
_P = 1
_LARGO_CLAVE = 64
# Memoria que necesita scrypt con esos parámetros, con margen; el valor por
# omisión de OpenSSL se queda corto.
_MAXMEM = 128 * _N * _R * 2

LARGO_MINIMO_CONTRASENA = 10


def cifrar_contrasena(contrasena: str) -> str:
    """Deriva la huella con scrypt.

    El formato guarda los parámetros para poder endurecerlos en el futuro sin
    invalidar las contraseñas existentes: `scrypt$N$r$p$sal$huella`, ambas
    partes en base64.
    """
    sal = secrets.token_bytes(16)
    clave = hashlib.scrypt(
        unicodedata.normalize("NFKC", contrasena).encode("utf-8"),
        salt=sal,
        n=_N,
        r=_R,
        p=_P,
        dklen=_LARGO_CLAVE,
        maxmem=_MAXMEM,
    )
    sal_b64 = base64.b64encode(sal).decode("ascii")
    clave_b64 = base64.b64encode(clave).decode("ascii")
    return f"scrypt${_N}${_R}${_P}${sal_b64}${clave_b64}"


def verificar_contrasena(contrasena: str, guardada: str) -> bool:
    """Comparación en tiempo constante para no filtrar información por el reloj."""
    partes = (guardada or "").split("$")
    if len(partes) != 6 or partes[0] != "scrypt":
        return False

    _, n, r, p, sal_b64, clave_b64 = partes
    try:
        sal = base64.b64decode(sal_b64)
        esperada = base64.b64decode(clave_b64)
        obtenida = hashlib.scrypt(
            unicodedata.normalize("NFKC", contrasena).encode("utf-8"),
            salt=sal,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(esperada),
            maxmem=128 * int(n) * int(r) * 2,
        )
    except (ValueError, TypeError, MemoryError):
        return False

    return hmac.compare_digest(obtenida, esperada)


def problema_contrasena(contrasena: str) -> str | None:
    """Reglas mínimas para las contraseñas que crea el administrador."""
    if len(contrasena) < LARGO_MINIMO_CONTRASENA:
        return f"La contraseña debe tener al menos {LARGO_MINIMO_CONTRASENA} caracteres."
    if not re.search("[a-z]", contrasena) or not re.search("[A-Z]", contrasena):
        return "La contraseña debe combinar mayúsculas y minúsculas."
    if not re.search("[0-9]", contrasena):
        return "La contraseña debe incluir al menos un número."
    return None


_PALABRAS = [
    "Cedro", "Roble", "Laurel", "Guaria", "Manglar", "Volcan", "Sendero",
    "Ceiba", "Coral", "Pampa", "Quebrada", "Higueron", "Palmar", "Tucan",
]


def sugerir_contrasena() -> str:
    """Contraseña inicial legible que el administrador puede dictar por teléfono."""
    escoger = lambda: secrets.choice(_PALABRAS)
    return f"{escoger()}-{escoger()}-{100 + secrets.randbelow(900)}"


# ---------------------------------------------------------------------------
# Sesiones
COOKIE_SESION = "majerie_session"
# Doce horas: una jornada.
DURACION_SESION_SEGUNDOS = 12 * 60 * 60
# Treinta días cuando la persona marca «Mantener la sesión iniciada en esta
# computadora». Es su propia computadora; el programa solo atiende dentro de
# ella.
DURACION_SESION_LARGA = 30 * 24 * 60 * 60


def _secreto() -> bytes:
    valor = current_app.config.get("SECRETO_SESION", "")
    if not valor or len(valor) < 32:
        raise RuntimeError(
            "Falta SESSION_SECRET (mínimo 32 caracteres). Sin ella no se pueden firmar las sesiones."
        )

    return valor.encode("utf-8")


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _desde_b64url(texto: str) -> bytes:
    relleno = "=" * (-len(texto) % 4)
    return base64.urlsafe_b64decode(texto + relleno)


def _firmar(datos: str) -> str:
    return _b64url(hmac.new(_secreto(), datos.encode("utf-8"), hashlib.sha256).digest())


def codificar_sesion(usuario_id: str, identidad: str = "", larga: bool = False) -> str:
    carga = {
        "uid": usuario_id,
        "identity": identidad,
        "exp": int(time.time()) + (DURACION_SESION_LARGA if larga else DURACION_SESION_SEGUNDOS),
        "larga": bool(larga),
    }
    cuerpo = _b64url(json.dumps(carga, separators=(",", ":")).encode("utf-8"))
    return f"{cuerpo}.{_firmar(cuerpo)}"


def decodificar_sesion(token: str):
    if not token or "." not in token:
        return None
    cuerpo, _, firma = token.partition(".")
    if not cuerpo or not firma:
        return None

    if not hmac.compare_digest(_firmar(cuerpo), firma):
        return None

    try:
        carga = json.loads(_desde_b64url(cuerpo).decode("utf-8"))
    except (ValueError, TypeError):
        return None

    if not carga.get("uid") or float(carga.get("exp", 0)) < time.time():
        return None
    return carga


class UsuarioSesion:
    """Usuario de la sesión, con la identidad con la que está actuando."""

    def __init__(self, fila, identidad: str = ""):
        self.id = fila["id"]
        self.username = fila["username"]
        self.name = fila["name"]
        self.email = fila["email"]
        self.role = fila["role"]
        self.active = bool(fila["active"])
        # La administración actúa con la identidad elegida al entrar.
        self.actingAs = (
            identidad if self.role == "administrador" and identidad else self.name
        )
        self.initials = iniciales_identidad(self.actingAs)


def usuario_de_sesion():
    """Usuario de la sesión, releído de la base en cada petición.

    Si la cuenta se elimina o se desactiva, la sesión deja de valer de
    inmediato.
    """
    if "usuario_sesion" in g:
        return g.usuario_sesion

    token = request.cookies.get(COOKIE_SESION)
    carga = decodificar_sesion(token) if token else None
    if not carga:
        g.usuario_sesion = None
        return None

    fila = consultar_una(
        "SELECT id, username, name, email, role, active FROM users WHERE id = ?",
        (carga["uid"],),
    )
    if not fila or not fila["active"]:
        g.usuario_sesion = None
        return None

    g.usuario_sesion = UsuarioSesion(fila, carga.get("identity", ""))
    return g.usuario_sesion


def identidad_actual() -> str:
    """Identidad elegida por la administración, sin forzar la redirección."""
    token = request.cookies.get(COOKIE_SESION)
    carga = decodificar_sesion(token) if token else None
    return (carga or {}).get("identity", "")


def sesion_larga() -> bool:
    """¿La sesión en curso pidió quedar iniciada en esta computadora?"""
    token = request.cookies.get(COOKIE_SESION)
    carga = decodificar_sesion(token) if token else None
    return bool((carga or {}).get("larga"))


def poner_cookie_sesion(respuesta, usuario_id: str, identidad: str = "", larga: bool = False):
    from .seguridad import peticion_segura

    respuesta.set_cookie(
        COOKIE_SESION,
        codificar_sesion(usuario_id, identidad, larga),
        httponly=True,
        samesite="Lax",
        secure=peticion_segura(),
        path="/",
        max_age=DURACION_SESION_LARGA if larga else DURACION_SESION_SEGUNDOS,
    )
    return respuesta


def borrar_cookie_sesion(respuesta):
    respuesta.delete_cookie(COOKIE_SESION, path="/")
    return respuesta


# ---------------------------------------------------------------------------
# Decoradores de las vistas
# ---------------------------------------------------------------------------
def exigir_sesion(funcion):
    """Exige sesión iniciada; si no la hay, devuelve a la pantalla de ingreso."""

    @wraps(funcion)
    def envoltura(*args, **kwargs):
        usuario = usuario_de_sesion()
        if not usuario:
            return redirect(url_for("sesion.ingresar"))
        return funcion(*args, **kwargs)

    return envoltura


def exigir_perfil(role: str):
    """Exige el perfil indicado.

    La administración debe además haber elegido con cuál de las dos
    identidades está trabajando.
    """

    def decorador(funcion):
        @wraps(funcion)
        def envoltura(*args, **kwargs):
            usuario = usuario_de_sesion()
            if not usuario:
                return redirect(url_for("sesion.ingresar"))
            # Cada perfil vuelve a su pantalla de inicio.
            if usuario.role != role:
                destino = (
                    "panel.dashboard"
                    if usuario.role == "administrador"
                    else "registro.registro"
                )
                return redirect(url_for(destino))
            # Sin identidad elegida, la administración no puede seguir.
            if usuario.role == "administrador" and usuario.actingAs == usuario.name:
                return redirect(url_for("sesion.identidad"))

            return funcion(*args, **kwargs)

        return envoltura

    return decorador
