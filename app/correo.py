"""Avisos por correo cuando la administración resuelve una solicitud.

La persona que pidió vacaciones, un permiso pagado con horas acumuladas o
cualquier otra ausencia recibe un correo en cuanto la administración la
aprueba o la rechaza, sin tener que entrar al sistema a revisar.

Cómo está armado:

- **Ajustes compartidos.** El servidor SMTP, el remitente y qué se avisa
  viven en la tabla `meta` de la base (clave `correo`): los ven las dos
  personas de la administración, desde cualquier computadora.
- **La contraseña, solo en la computadora.** Se guarda en la configuración
  local protegida con DPAPI (la misma protección que la sesión de
  Microsoft). Nunca sube a SharePoint, así que las computadoras de los
  colaboradores no la tienen. Cada computadora de administración la escribe
  una vez.
- **Se envía después de guardar.** Una petición que cambia datos puede
  repetirse si otra computadora guardó al mismo tiempo (ver
  `nube/escrituras.py`). Por eso las vistas solo *programan* el aviso
  (`programar`) y `AvisosTrasGuardar` lo envía cuando el cambio ya quedó en
  SharePoint: nunca sale un aviso de algo que no se guardó, ni dos veces.
- **Nunca interrumpe.** Si el correo falla, la aprobación ya está hecha; la
  pantalla siguiente muestra el motivo para que la administración lo sepa.
"""

from __future__ import annotations

import base64
import json
import logging
import smtplib
import ssl
import threading
from collections import deque
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape

log = logging.getLogger("majerie.correo")

# Clave de la tabla `meta` con los ajustes compartidos.
CLAVE_META = "correo"
# Clave de la configuración local con la contraseña protegida.
CLAVE_LOCAL = "correo_contrasena"
# Clave del entorno WSGI con los avisos programados en la petición.
CLAVE_ENTORNO = "majerie.avisos_correo"

SEGURIDADES = {
    "starttls": "STARTTLS (587)",
    "ssl": "SSL/TLS (465)",
    "ninguna": "Sin cifrado",
}

AJUSTES_POR_OMISION = {
    "activo": False,
    "servidor": "",
    "puerto": 587,
    "seguridad": "starttls",
    "usuario": "",
    "remitente": "",
    "nombre_remitente": "MAJERIE S.R.L · Registro de Horas",
    # Qué se avisa a la persona.
    "avisar_ausencias": True,
    "avisar_registros": False,
    # Copia oculta opcional (por ejemplo, el correo de la administración).
    "copia": "",
}

# Proveedores frecuentes, para llenar el formulario con un clic.
PROVEEDORES = [
    {"nombre": "Microsoft 365 / Outlook", "servidor": "smtp.office365.com", "puerto": 587,
     "seguridad": "starttls"},
    {"nombre": "Gmail / Google Workspace", "servidor": "smtp.gmail.com", "puerto": 587,
     "seguridad": "starttls"},
]

ESPERA_SEGUNDOS = 20


class ErrorCorreo(Exception):
    """Un envío que no salió, con un motivo que la administración entiende."""


# ---------------------------------------------------------------------------
# Ajustes compartidos (tabla meta)
# ---------------------------------------------------------------------------
def leer_ajustes() -> dict:
    from .db import consultar_una

    ajustes = dict(AJUSTES_POR_OMISION)
    try:
        fila = consultar_una("SELECT valor FROM meta WHERE clave = ?", (CLAVE_META,))
        guardados = json.loads(fila["valor"]) if fila else {}
    except Exception:
        guardados = {}
    if isinstance(guardados, dict):
        ajustes.update({k: v for k, v in guardados.items() if k in AJUSTES_POR_OMISION})
    return ajustes


def _correo_valido(texto: str) -> bool:
    texto = (texto or "").strip()
    if not texto or " " in texto or texto.count("@") != 1:
        return False
    usuario, dominio = texto.split("@")
    return bool(usuario) and "." in dominio and not dominio.startswith(".")


def guardar_ajustes(usuario, datos: dict) -> dict:
    """Valida y guarda los ajustes compartidos. Mismo formato que `acciones`."""
    from .acciones import bien, mal
    from .db import ejecutar

    if not usuario or usuario.role != "administrador":
        return mal("Solo la administración configura los avisos por correo.")

    ajustes = dict(AJUSTES_POR_OMISION)
    ajustes.update({
        "activo": bool(datos.get("activo")),
        "servidor": (datos.get("servidor") or "").strip(),
        "seguridad": datos.get("seguridad") if datos.get("seguridad") in SEGURIDADES else "starttls",
        "usuario": (datos.get("usuario") or "").strip(),
        "remitente": (datos.get("remitente") or "").strip(),
        "nombre_remitente": (datos.get("nombre_remitente") or "").strip()[:80]
        or AJUSTES_POR_OMISION["nombre_remitente"],
        "avisar_ausencias": bool(datos.get("avisar_ausencias")),
        "avisar_registros": bool(datos.get("avisar_registros")),
        "copia": (datos.get("copia") or "").strip(),
    })
    try:
        ajustes["puerto"] = int(datos.get("puerto") or 0)
    except (TypeError, ValueError):
        return mal("El puerto debe ser un número (normalmente 587).")
    if not 0 < ajustes["puerto"] < 65536:
        return mal("El puerto debe estar entre 1 y 65535 (normalmente 587).")
    if ajustes["servidor"] and (" " in ajustes["servidor"] or "/" in ajustes["servidor"]):
        return mal("Escriba solo el nombre del servidor, por ejemplo smtp.office365.com.")
    if ajustes["remitente"] and not _correo_valido(ajustes["remitente"]):
        return mal("El correo del remitente no es válido.")
    if ajustes["copia"] and not _correo_valido(ajustes["copia"]):
        return mal("El correo de la copia no es válido.")
    if ajustes["activo"]:
        if not ajustes["servidor"]:
            return mal("Para activar los avisos indique el servidor de correo (SMTP).")
        if not (ajustes["remitente"] or _correo_valido(ajustes["usuario"])):
            return mal("Indique el correo desde el que salen los avisos (remitente).")

    ejecutar(
        "INSERT INTO meta (clave, valor) VALUES (?, ?) "
        "ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor",
        (CLAVE_META, json.dumps(ajustes, ensure_ascii=False)),
    )
    estado = "activó" if ajustes["activo"] else "guardó (desactivados)"
    return bien("Ajustes de correo guardados.",
                historial=f"Configuró los avisos por correo: los {estado}")


def remitente_de(ajustes: dict) -> str:
    return ajustes.get("remitente") or ajustes.get("usuario") or ""


# ---------------------------------------------------------------------------
# Contraseña de esta computadora (DPAPI)
# ---------------------------------------------------------------------------
def _configuracion():
    from flask import current_app, has_app_context

    from .config import configuracion

    if has_app_context():
        return current_app.config.get("CONFIGURACION") or configuracion()
    return configuracion()


def contrasena_local() -> str:
    from .nube.dpapi import desproteger

    guardada = _configuracion().get(CLAVE_LOCAL, "")
    if not guardada:
        return ""
    try:
        return desproteger(base64.b64decode(guardada)).decode("utf-8")
    except Exception:
        log.warning("No se pudo leer la contraseña del correo de esta computadora.")
        return ""


def guardar_contrasena_local(contrasena: str) -> None:
    from .nube.dpapi import proteger

    protegida = base64.b64encode(proteger(contrasena.encode("utf-8"))).decode("ascii")
    _configuracion().guardar(**{CLAVE_LOCAL: protegida})


def olvidar_contrasena_local() -> None:
    _configuracion().guardar(**{CLAVE_LOCAL: ""})


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------
def _motivo(fallo: Exception) -> str:
    """Explica un fallo de SMTP con palabras de todos los días."""
    if isinstance(fallo, smtplib.SMTPAuthenticationError):
        return ("El servidor rechazó el usuario o la contraseña. En Microsoft 365 y Gmail "
                "suele hacer falta una «contraseña de aplicación» y tener habilitado el "
                "envío por SMTP en la cuenta.")
    if isinstance(fallo, smtplib.SMTPRecipientsRefused):
        return "El servidor rechazó la dirección de destino."
    if isinstance(fallo, smtplib.SMTPSenderRefused):
        return "El servidor no permite enviar con ese remitente: use el mismo correo del usuario."
    if isinstance(fallo, smtplib.SMTPNotSupportedError):
        return ("El servidor no admite esa forma de conexión o de ingreso: revise la seguridad "
                "y el puerto.")
    if isinstance(fallo, (ssl.SSLError, smtplib.SMTPServerDisconnected)):
        return ("No se pudo establecer la conexión segura: revise que la seguridad coincida "
                "con el puerto (587 con STARTTLS, 465 con SSL).")
    if isinstance(fallo, TimeoutError):
        return "El servidor de correo no respondió a tiempo."
    if isinstance(fallo, OSError):
        return ("No se pudo conectar con el servidor de correo. Revise el nombre del "
                "servidor, el puerto y la conexión a internet.")
    return str(fallo) or fallo.__class__.__name__


def enviar(ajustes: dict, contrasena: str, para: list[str], asunto: str, texto: str,
           html: str | None = None) -> None:
    """Envía un correo. Lanza `ErrorCorreo` con un motivo claro si falla."""
    destinatarios = [d for d in (para or []) if _correo_valido(d)]
    if not destinatarios:
        raise ErrorCorreo("No hay una dirección de correo válida a la cual enviar.")
    servidor = (ajustes.get("servidor") or "").strip()
    if not servidor:
        raise ErrorCorreo("Falta el servidor de correo en Configuración › Avisos por correo.")
    remitente = remitente_de(ajustes)
    if not _correo_valido(remitente):
        raise ErrorCorreo("Falta el correo del remitente en Configuración › Avisos por correo.")

    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = formataddr((ajustes.get("nombre_remitente") or "", remitente))
    mensaje["To"] = ", ".join(destinatarios)
    mensaje["Message-ID"] = make_msgid(domain=remitente.split("@")[-1])
    mensaje.set_content(texto)
    if html:
        mensaje.add_alternative(html, subtype="html")
    copia = (ajustes.get("copia") or "").strip()
    todos = destinatarios + ([copia] if _correo_valido(copia) and copia not in destinatarios else [])

    puerto = int(ajustes.get("puerto") or 587)
    seguridad = ajustes.get("seguridad") or "starttls"
    usuario = (ajustes.get("usuario") or "").strip()
    if usuario and not contrasena:
        raise ErrorCorreo(
            "Esta computadora no tiene guardada la contraseña del correo. "
            "Escríbala en Configuración › Avisos por correo."
        )
    contexto = ssl.create_default_context()
    # La etapa en que falla dice más que el error mismo: un servidor que
    # corta la conexión al ingresar casi siempre rechazó la contraseña.
    etapa = "conectar"
    try:
        if seguridad == "ssl":
            conexion = smtplib.SMTP_SSL(servidor, puerto, timeout=ESPERA_SEGUNDOS, context=contexto)
        else:
            conexion = smtplib.SMTP(servidor, puerto, timeout=ESPERA_SEGUNDOS)
        with conexion:
            conexion.ehlo()
            if seguridad == "starttls":
                etapa = "cifrar"
                conexion.starttls(context=contexto)
                conexion.ehlo()
            if usuario:
                etapa = "ingresar"
                conexion.login(usuario, contrasena)
            etapa = "enviar"
            conexion.send_message(mensaje, from_addr=remitente, to_addrs=todos)
    except Exception as fallo:
        if etapa == "ingresar" and not isinstance(fallo, (smtplib.SMTPNotSupportedError, TimeoutError)):
            fallo = smtplib.SMTPAuthenticationError(535, str(fallo))
        raise ErrorCorreo(_motivo(fallo)) from fallo


# ---------------------------------------------------------------------------
# Avisos programados durante una petición
# ---------------------------------------------------------------------------
def programar(aviso: dict) -> None:
    """Deja un aviso para enviarlo cuando el cambio ya esté guardado.

    `aviso` trae `para` (lista), `asunto`, `texto`, `html` y `quien` (el
    nombre de la persona, para el mensaje en pantalla).
    """
    from flask import request

    caja = request.environ.get(CLAVE_ENTORNO)
    if caja is None:
        # Fuera de `AvisosTrasGuardar` (pruebas): se anota en el entorno.
        caja = request.environ.setdefault(CLAVE_ENTORNO, {"avisos": []})
    caja["avisos"].append(aviso)


class AvisosTrasGuardar:
    """Capa WSGI que envía los avisos cuando la petición terminó bien.

    Va por fuera de `Sincronizacion`: cuando la petición vuelve hasta aquí,
    el cambio ya está en SharePoint (o la aplicación trabaja sin nube). Cada
    intento repetido de la petición vacía la caja antes de correr (ver
    `nube/escrituras.py`), así que solo quedan los avisos del intento que se
    guardó. Si el guardado falló, la vista no llega a correr y no hay nada
    que enviar.
    """

    def __init__(self, wsgi, aplicacion):
        self.wsgi = wsgi
        self.aplicacion = aplicacion

    def __call__(self, entorno, iniciar):
        if entorno.get("REQUEST_METHOD", "GET").upper() != "POST":
            return self.wsgi(entorno, iniciar)
        caja = {"avisos": []}
        entorno[CLAVE_ENTORNO] = caja
        respuesta = self.wsgi(entorno, iniciar)
        if caja["avisos"]:
            try:
                with self.aplicacion.app_context():
                    enviar_programados(self.aplicacion, caja["avisos"])
            except Exception:
                log.exception("Fallo inesperado al enviar los avisos por correo")
        return respuesta


def enviar_programados(aplicacion, avisos: list[dict]) -> None:
    ajustes = leer_ajustes()
    contrasena = contrasena_local()
    for aviso in avisos:
        quien = aviso.get("quien") or ", ".join(aviso.get("para") or [])
        try:
            enviar(ajustes, contrasena, aviso.get("para") or [], aviso["asunto"],
                   aviso["texto"], aviso.get("html"))
            anotar_resultado(aplicacion, True, f"Se avisó por correo a {quien}.", aviso)
        except ErrorCorreo as fallo:
            log.warning("No salió el aviso a %s: %s", quien, fallo)
            anotar_resultado(aplicacion, False,
                             f"No se pudo avisar por correo a {quien}: {fallo}", aviso)


# Resultados de los últimos envíos de esta computadora: se muestran como
# aviso en la pantalla siguiente y en Configuración › Avisos por correo.
_CANDADO = threading.Lock()


def _bitacora(aplicacion) -> dict:
    with _CANDADO:
        return aplicacion.config.setdefault(
            "CORREO_BITACORA", {"por_mostrar": [], "recientes": deque(maxlen=20)}
        )


def anotar_resultado(aplicacion, ok: bool, mensaje: str, aviso: dict | None = None) -> None:
    bitacora = _bitacora(aplicacion)
    with _CANDADO:
        bitacora["por_mostrar"].append(("exito" if ok else "error", mensaje))
        bitacora["recientes"].appendleft({
            "ok": ok,
            "mensaje": mensaje,
            "asunto": (aviso or {}).get("asunto", ""),
            "momento": datetime.now().isoformat(timespec="seconds"),
        })


def resultados_por_mostrar(aplicacion) -> list[tuple[str, str]]:
    bitacora = _bitacora(aplicacion)
    with _CANDADO:
        salida = list(bitacora["por_mostrar"])
        bitacora["por_mostrar"].clear()
    return salida


def recientes(aplicacion) -> list[dict]:
    bitacora = _bitacora(aplicacion)
    with _CANDADO:
        return list(bitacora["recientes"])


# ---------------------------------------------------------------------------
# Contenido de los avisos
# ---------------------------------------------------------------------------
def _plantilla_html(titulo: str, saludo: str, parrafos: list[str], filas: list[tuple[str, str]],
                    pie: str) -> str:
    detalle = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#66666e;white-space:nowrap">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#0b0b0c;font-weight:600">{escape(v)}</td></tr>'
        for k, v in filas
    )
    cuerpo = "".join(f'<p style="margin:0 0 12px">{escape(p)}</p>' for p in parrafos)
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;background:#f6f6f3;font-family:Segoe UI,Arial,sans-serif;color:#3a3a40">
<div style="max-width:560px;margin:0 auto;padding:28px 16px">
  <p style="margin:0 0 18px;letter-spacing:.3em;font-size:12px;color:#0b0b0c">MAJERIE S.R.L</p>
  <div style="background:#ffffff;border:1px solid #e4e3de;border-radius:14px;padding:24px">
    <h1 style="margin:0 0 14px;font-size:19px;color:#0b0b0c">{escape(titulo)}</h1>
    <p style="margin:0 0 12px">{escape(saludo)}</p>
    {cuerpo}
    <table style="border-collapse:collapse;font-size:14px;margin:6px 0 4px">{detalle}</table>
  </div>
  <p style="margin:16px 4px 0;font-size:12px;color:#a0a0a8">{escape(pie)}</p>
</div></body></html>"""


def _texto_plano(titulo: str, saludo: str, parrafos: list[str], filas: list[tuple[str, str]],
                 pie: str) -> str:
    lineas = [titulo, "", saludo, ""] + [p + "\n" for p in parrafos]
    lineas += [f"{k}: {v}" for k, v in filas]
    lineas += ["", "--", pie]
    return "\n".join(lineas)


PIE = ("Aviso automático del Sistema de Registro de Horas de MAJERIE S.R.L. "
       "Para ver el detalle, abra el sistema en su computadora.")


def aviso_de_ausencia(ausencia_id: str) -> dict | None:
    """Correo para la persona cuya ausencia se acaba de resolver.

    None si los avisos están apagados o la persona no tiene correo.
    """
    from types import SimpleNamespace

    from .datos import cargar_instantanea
    from .db import consultar_una
    from .lib.ajustes import ajustes_de
    from .lib.ausencias import ETIQUETAS_TIPO
    from .lib.estadisticas import con_horas, saldo_horas, vacaciones_de
    from .lib.tiempo import formatear_fecha, formatear_numero

    ajustes = leer_ajustes()
    if not ajustes["activo"] or not ajustes["avisar_ausencias"]:
        return None
    fila = consultar_una(
        "SELECT a.*, u.name, u.email FROM absences a JOIN users u ON u.id = a.user_id "
        "WHERE a.id = ?",
        (ausencia_id,),
    )
    if not fila or not _correo_valido(fila["email"]) or fila["status"] == "pendiente":
        return None

    aprobada = fila["status"] == "aprobada"
    tipo = ETIQUETAS_TIPO.get(fila["kind"], "Ausencia")
    dias = float(fila["days"])
    rango = (formatear_fecha(fila["from_date"]) if fila["from_date"] == fila["to_date"]
             else f"{formatear_fecha(fila['from_date'])} al {formatear_fecha(fila['to_date'])}")
    filas = [
        ("Tipo", tipo),
        ("Fechas", rango),
        ("Días", f"{formatear_numero(dias, 1)} {'día' if dias == 1 else 'días'}"),
    ]
    if float(fila["accumulated_hours"] or 0):
        filas.append(("Horas acumuladas", f"{formatear_numero(fila['accumulated_hours'])} h"))
    filas.append(("Estado", "Aprobada" if aprobada else "Rechazada"))
    if fila["decided_by"]:
        filas.append(("Resuelta por", fila["decided_by"]))
    if fila["decision_note"]:
        filas.append(("Nota", fila["decision_note"]))

    # Saldos actualizados, ya con esta resolución.
    try:
        persona = SimpleNamespace(id=fila["user_id"], role="colaborador")
        instantanea = cargar_instantanea(persona)
        config = ajustes_de(instantanea.collaboratorSettings, persona.id)
        propias = [a for a in instantanea.absences if a.userId == persona.id]
        if fila["kind"] == "vacaciones":
            saldo, _totales = vacaciones_de(config, propias, persona.id)
            filas.append(("Vacaciones disponibles", f"{formatear_numero(saldo.available, 1)} días"))
        if float(fila["accumulated_hours"] or 0):
            registros = con_horas(
                [r for r in instantanea.entries if r.userId == persona.id], instantanea.lunches
            )
            acumuladas = saldo_horas(registros, propias, config, persona.id)
            texto_saldo = f"{formatear_numero(acumuladas.accumulated)} h"
            if aprobada and acumuladas.upcomingSpent:
                texto_saldo += (f" (las {formatear_numero(fila['accumulated_hours'])} h del permiso "
                                "se descuentan el día en que empieza)")
            filas.append(("Horas acumuladas hoy", texto_saldo))
    except Exception:
        log.exception("No se pudo calcular el saldo para el aviso")

    nombre = fila["name"]
    if aprobada:
        titulo = f"Su solicitud de {tipo.lower()} fue aprobada"
        parrafos = ["La administración aprobó su solicitud. Estos son los datos:"]
    else:
        titulo = f"Su solicitud de {tipo.lower()} fue rechazada"
        parrafos = ["La administración rechazó su solicitud. Si tiene dudas, consúltelo con "
                    "la administración. Estos son los datos:"]
    saludo = f"Hola, {nombre}:"
    return {
        "para": [fila["email"].strip()],
        "quien": nombre,
        "asunto": f"{titulo} ({rango})",
        "texto": _texto_plano(titulo, saludo, parrafos, filas, PIE),
        "html": _plantilla_html(titulo, saludo, parrafos, filas, PIE),
    }


def aviso_de_registro(datos: dict, aprobado: bool) -> dict | None:
    """Correo cuando la administración resuelve un cambio de horas.

    `datos` trae lo que se leyó del registro antes de resolverlo
    (`user_id`, `entry_date`, `start_time`, `end_time`, `pending_action`).
    """
    from .db import consultar_una
    from .lib.aprobaciones import ETIQUETAS_ACCION
    from .lib.tiempo import formatear_fecha

    ajustes = leer_ajustes()
    if not ajustes["activo"] or not ajustes["avisar_registros"]:
        return None
    persona = consultar_una("SELECT name, email FROM users WHERE id = ?", (datos["user_id"],))
    if not persona or not _correo_valido(persona["email"]):
        return None
    accion = ETIQUETAS_ACCION.get(datos.get("pending_action") or "", "Cambio")
    estado = "aprobado" if aprobado else "rechazado"
    titulo = f"Su cambio de horas fue {estado}"
    filas = [
        ("Fecha", formatear_fecha(datos["entry_date"])),
        ("Horario", f"{datos['start_time']} – {datos['end_time']}"),
        ("Solicitud", accion),
        ("Estado", estado.capitalize()),
    ]
    parrafos = ["La administración resolvió un cambio en su registro de horas."]
    if not aprobado and datos.get("pending_action") == "creacion":
        parrafos.append("Como era un registro nuevo, se descartó y sus horas no cuentan en el saldo.")
    saludo = f"Hola, {persona['name']}:"
    return {
        "para": [persona["email"].strip()],
        "quien": persona["name"],
        "asunto": f"{titulo} ({formatear_fecha(datos['entry_date'])})",
        "texto": _texto_plano(titulo, saludo, parrafos, filas, PIE),
        "html": _plantilla_html(titulo, saludo, parrafos, filas, PIE),
    }


def aviso_de_prueba(para: str) -> dict:
    titulo = "Correo de prueba"
    parrafos = ["Si recibió este mensaje, los avisos por correo del Sistema de Registro de "
                "Horas quedaron bien configurados."]
    filas = [("Enviado", datetime.now().strftime("%d/%m/%Y %H:%M"))]
    saludo = "Hola:"
    return {
        "para": [para],
        "quien": para,
        "asunto": "Prueba de los avisos por correo · MAJERIE S.R.L",
        "texto": _texto_plano(titulo, saludo, parrafos, filas, PIE),
        "html": _plantilla_html(titulo, saludo, parrafos, filas, PIE),
    }
