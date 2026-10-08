"""Ingreso, identidad y contraseña propia.

Reúne lo que en el sistema original eran `app/page.tsx`, `app/ingresar`,
`app/identidad` y `app/cuenta`.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from ..acciones import cambiar_contrasena_propia, elegir_identidad
from ..acciones import ingresar as comprobar_credenciales
from ..auth import (
    borrar_cookie_sesion,
    exigir_sesion,
    identidad_actual,
    poner_cookie_sesion,
    sesion_larga,
    usuario_de_sesion,
)
from ..seguridad import anotar_acierto, anotar_fallo, espera_restante, texto_espera

sesion = Blueprint("sesion", __name__)


@sesion.get("/")
def raiz():
    """La raíz solo decide a dónde llevar a quien llega."""
    usuario = usuario_de_sesion()
    if not usuario:
        return redirect(url_for("sesion.ingresar"))
    # La administración pasa primero por la elección de identidad.
    if usuario.role == "administrador":
        destino = "panel.dashboard" if identidad_actual() else "sesion.identidad"
        return redirect(url_for(destino))
    return redirect(url_for("registro.registro"))


@sesion.route("/ingresar", methods=["GET", "POST"])
def ingresar():
    # «Mantener la sesión iniciada en esta computadora» viene marcado de
    # entrada: es la computadora de la persona y el programa solo atiende
    # dentro de ella.
    if request.method != "POST":
        if usuario_de_sesion():
            return redirect(url_for("sesion.raiz"))
        return render_template("ingresar.html", error=None, username="", recordar=True)

    recordar = request.form.get("recordar") == "1"

    espera = espera_restante()
    if espera:
        return render_template(
            "ingresar.html", error=texto_espera(espera), username="", recordar=recordar
        ), 429

    nombre = request.form.get("username", "")
    resultado = comprobar_credenciales(nombre, request.form.get("password", ""))

    if not resultado["ok"]:
        anotar_fallo()
        return render_template(
            "ingresar.html", error=resultado["error"], username=nombre, recordar=recordar
        ), 401

    anotar_acierto()
    # La administración elige primero con qué identidad trabaja; el
    # colaborador va directo a registrar.
    destino = (
        "sesion.identidad"
        if resultado["role"] == "administrador"
        else "registro.registro"
    )
    respuesta = make_response(redirect(url_for(destino)))
    return poner_cookie_sesion(respuesta, resultado["id"], larga=recordar)


@sesion.route("/identidad", methods=["GET", "POST"])
@exigir_sesion
def identidad():
    usuario = usuario_de_sesion()
    # Solo la administración elige identidad.
    if usuario.role != "administrador":
        return redirect(url_for("registro.registro"))

    if request.method != "POST":
        return render_template("identidad.html", error=None)

    elegida = request.form.get("identidad", "")
    resultado = elegir_identidad(usuario, elegida)
    if not resultado["ok"]:
        return render_template("identidad.html", error=resultado["error"]), 400

    respuesta = make_response(redirect(url_for("panel.dashboard")))
    return poner_cookie_sesion(respuesta, usuario.id, resultado["identity"], larga=sesion_larga())


@sesion.route("/cuenta", methods=["GET", "POST"])
@exigir_sesion
def cuenta():
    """Cada persona cambia su propia contraseña sin pasar por la administración."""
    usuario = usuario_de_sesion()
    volver = url_for(
        "panel.dashboard" if usuario.role == "administrador" else "registro.registro"
    )

    if request.method != "POST":
        return render_template("cuenta.html", error=None, volver=volver)

    actual = request.form.get("actual", "")
    nueva = request.form.get("nueva", "")
    repetir = request.form.get("repetir", "")

    if nueva != repetir:
        return render_template(
            "cuenta.html", error="Las dos contraseñas nuevas no coinciden.", volver=volver
        ), 400

    resultado = cambiar_contrasena_propia(usuario, actual, nueva)
    if not resultado["ok"]:
        return render_template("cuenta.html", error=resultado["error"], volver=volver), 400

    flash("Contraseña actualizada. Úsela la próxima vez que ingrese.", "exito")
    return redirect(volver)


@sesion.post("/salir")
def salir():
    respuesta = make_response(redirect(url_for("sesion.ingresar")))
    return borrar_cookie_sesion(respuesta)
