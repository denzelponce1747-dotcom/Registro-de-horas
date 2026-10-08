"""Inicio de sesión con la cuenta de Microsoft 365 de la empresa.

Para leer y escribir en el SharePoint de la empresa, el programa necesita
que la persona entre con su cuenta de trabajo. Se usa el flujo que
Microsoft recomienda para las aplicaciones de escritorio —código de
autorización con PKCE y retorno a `http://localhost`—: la contraseña se
escribe en la página de Microsoft, nunca en este programa, y funciona igual
con verificación en dos pasos y con las políticas de acceso de la empresa.

Lo que queda guardado es el «token de actualización», cifrado con la
protección de datos de Windows (`dpapi.py`). Con él la sesión se renueva
sola durante meses; si Microsoft lo invalida —cambio de contraseña, cuenta
desactivada, política nueva— el programa pide volver a conectar.

La aplicación tiene que estar registrada en Microsoft Entra ID de la
empresa (una sola vez). Su identificador viaja en el programa
(`app/microsoft.json`, que deja `empaquetar.py`) o se escribe en Ajustes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import dpapi

URL_LOGIN = os.environ.get("MAJERIE_LOGIN_URL", "https://login.microsoftonline.com").rstrip("/")

# Lo que el programa pide en nombre de la persona:
# - offline_access: seguir conectado sin pedir la contraseña cada hora;
# - openid y profile: saber quién entró (nombre y correo);
# - User.Read: lo mínimo para iniciar sesión;
# - Files.ReadWrite.All y Sites.Read.All: la carpeta de SharePoint.
PERMISOS = ("offline_access", "openid", "profile", "User.Read",
            "Files.ReadWrite.All", "Sites.Read.All")

# Microsoft acepta cualquier puerto en `http://localhost` para las
# aplicaciones de escritorio, así que basta con registrar la dirección sin
# puerto: el programa usa el suyo.
#
RETORNO_REGISTRADO = "http://localhost"

ESPERA_RED = 25


class ErrorMicrosoft(Exception):
    """Un problema al hablar con Microsoft, con un texto para la persona."""

    def __init__(self, mensaje: str, codigo: str = "", detalle: str = ""):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.detalle = detalle


class NecesitaIniciarSesion(ErrorMicrosoft):
    """No hay sesión de Microsoft, o venció: hay que volver a conectar."""


class SinConexion(ErrorMicrosoft):
    """No hay internet, o Microsoft no contesta."""


# El identificador de la aplicación registrada en Entra ID viaja dentro del
# programa en `microsoft.json`; una variable de entorno lo reemplaza en
# pruebas.
def _leer_incluido() -> dict:
    from ..config import RECURSOS

    for ruta in (RECURSOS / "microsoft.json",):
        try:
            datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
            if isinstance(datos, dict):
                return datos
        except (OSError, ValueError):
            continue
    return {}


_INCLUIDO = _leer_incluido()
CLIENTE_ID_INCLUIDO = (os.environ.get("MAJERIE_CLIENTE_ID") or _INCLUIDO.get("cliente_id") or "").strip()

_FORMA_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def es_identificador(valor: str) -> bool:
    return bool(_FORMA_GUID.match((valor or "").strip()))


# -- Peticiones ---------------------------------------------------------------
#
# Con el proxy que tenga configurado Windows, como el navegador.
def _abridor():
    # Las respuestas de Microsoft nunca redirigen; no hace falta más.
    return urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies()))


def _post_formulario(url: str, campos: dict) -> dict:
    cuerpo = urllib.parse.urlencode(campos).encode("ascii")
    peticion = urllib.request.Request(
        url, data=cuerpo, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
    )
    try:
        with _abridor().open(peticion, timeout=ESPERA_RED) as respuesta:
            return json.loads(respuesta.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as fallo:
        try:
            datos = json.loads(fallo.read().decode("utf-8") or "{}")
        except ValueError:
            datos = {}
        raise _traducir_error(datos, fallo.code) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as fallo:
        raise SinConexion(
            "No hay conexión con Microsoft. Revise el internet de esta computadora.",
            detalle=str(fallo),
        ) from None


_MENSAJES_AADSTS = {
    "700016": (
        "El identificador de la aplicación no existe en el Microsoft 365 de la empresa. "
        "Revise que lo hayan copiado completo, o que se haya registrado en el mismo "
        "Microsoft 365 al que pertenece la carpeta."
    ),
    "50011": (
        "Falta registrar la dirección de retorno «http://localhost» en la aplicación "
        "(plataforma «Aplicaciones móviles y de escritorio»)."
    ),
    "7000218": (
        "La aplicación está registrada como aplicación web. En Entra ID, agregue la "
        "plataforma «Aplicaciones móviles y de escritorio» y active «Permitir flujos de "
        "clientes públicos»."
    ),
    "65001": (
        "La empresa todavía no autorizó esta aplicación. El administrador de Microsoft 365 "
        "debe conceder el consentimiento en Entra ID."
    ),
    "65004": "Se rechazó el permiso que pide el programa, así que no puede usar SharePoint.",
    "90094": (
        "Hace falta que un administrador de Microsoft 365 autorice esta aplicación para la "
        "empresa (consentimiento de administrador)."
    ),
    "50020": "Esa cuenta no pertenece al Microsoft 365 de la empresa. Entre con su cuenta de trabajo.",
    "53003": "Una política de acceso de la empresa bloqueó el ingreso desde esta computadora.",
    "50076": "Hace falta completar la verificación en dos pasos.",
    "50194": (
        "La aplicación está registrada solo para una organización y el programa no pudo "
        "identificar cuál. Escriba el inquilino en Ajustes."
    ),
    "700082": "La sesión de Microsoft venció por falta de uso. Vuelva a conectar.",
    "70008": "La sesión de Microsoft venció. Vuelva a conectar.",
    "50173": "La sesión de Microsoft ya no es válida (cambió la contraseña). Vuelva a conectar.",
    "50078": "Hace falta completar la verificación en dos pasos.",
}


def _traducir_error(datos: dict, estado: int = 0) -> ErrorMicrosoft:
    error = str(datos.get("error") or "")
    descripcion = str(datos.get("error_description") or "")
    codigos = [str(c) for c in datos.get("error_codes") or []]
    hallado = re.search(r"AADSTS(\d+)", descripcion)
    if hallado:
        codigos.insert(0, hallado.group(1))

    for codigo in codigos:
        if codigo in _MENSAJES_AADSTS:
            clase = (
                NecesitaIniciarSesion
                if codigo in ("700082", "70008", "50173", "50076", "50078")
                else ErrorMicrosoft
            )
            return clase(_MENSAJES_AADSTS[codigo], codigo=f"AADSTS{codigo}", detalle=descripcion)

    if error in ("invalid_grant", "interaction_required", "login_required", "consent_required"):
        return NecesitaIniciarSesion(
            "Hay que volver a conectar la cuenta de Microsoft.", codigo=error, detalle=descripcion
        )
    if error == "access_denied":
        return ErrorMicrosoft(
            "Se canceló el ingreso con Microsoft.", codigo=error, detalle=descripcion
        )
    primera = descripcion.split("\r\n")[0].split("\n")[0].strip()
    return ErrorMicrosoft(
        "Microsoft no aceptó el ingreso"
        + (f": {primera}" if primera else f" (error {estado or error})."),
        # La descripción completa queda para el registro.
        codigo=error or str(estado),
        detalle=descripcion,
    )


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _reclamos(id_token: str) -> dict:
    """Lo que dice el token de identidad. Viene directo de Microsoft por
    HTTPS como respuesta a nuestra propia petición, así que no hace falta
    verificar su firma para leer el nombre y el correo."""
    try:
        cuerpo = id_token.split(".")[1]
        cuerpo += "=" * (-len(cuerpo) % 4)
        return json.loads(base64.urlsafe_b64decode(cuerpo).decode("utf-8"))
    except (IndexError, ValueError, UnicodeDecodeError):
        return {}


# -- Inquilino ---------------------------------------------------------------
#
#
def descubrir_inquilino(anfitrion: str, probable: str) -> str:
    """El identificador del Microsoft 365 de la empresa a partir de la
    dirección de SharePoint.

    SharePoint contesta 401 a una petición con un token vacío y dice en la
    cabecera `WWW-Authenticate` a qué organización pertenece. Si eso falla,
    se usa `empresa.onmicrosoft.com`, que casi siempre es el mismo.
    """
    sondeo = os.environ.get("MAJERIE_SP_SONDEO") or f"https://{anfitrion}/_vti_bin/client.svc"
    peticion = urllib.request.Request(sondeo, headers={"Authorization": "Bearer"})
    try:
        with _abridor().open(peticion, timeout=12):
            pass
    except urllib.error.HTTPError as fallo:
        cabecera = fallo.headers.get("WWW-Authenticate", "")
        hallado = re.search(r'realm="([0-9a-fA-F-]{36})"', cabecera)
        if hallado:
            return hallado.group(1).lower()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        pass

    configuracion = f"{URL_LOGIN}/{probable}/v2.0/.well-known/openid-configuration"
    try:
        with _abridor().open(configuracion, timeout=12) as respuesta:
            emisor = json.loads(respuesta.read().decode("utf-8")).get("issuer", "")
            hallado = re.search(r"([0-9a-fA-F-]{36})", emisor)
            if hallado:
                return hallado.group(1).lower()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError):
        pass
    return probable


# -- La cuenta ---------------------------------------------------------------
#
#
class Cuenta:
    """La cuenta de Microsoft conectada en esta computadora."""

    def __init__(self, archivo: Path):
        self.archivo = Path(archivo)
        self._candado = threading.RLock()
        self._datos = {}
        self._token = ""
        self._vence = 0.0
        # Ingresos empezados y no terminados, por su `state`.
        self._pendientes = {}
        self._leer()

    # El archivo guarda el token de actualización y quién es la persona,
    # cifrados con DPAPI.
    def _leer(self) -> None:
        try:
            crudo = dpapi.desproteger(self.archivo.read_bytes())
            datos = json.loads(crudo.decode("utf-8"))
            self._datos = datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            self._datos = {}

    def _escribir(self) -> None:
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        provisional = self.archivo.with_name(self.archivo.name + ".nuevo")
        provisional.write_bytes(dpapi.proteger(json.dumps(self._datos).encode("utf-8")))
        os.replace(provisional, self.archivo)

    # -- Estado --

    @property
    def conectada(self) -> bool:
        with self._candado:
            return bool(self._datos.get("refresh_token"))

    def info(self) -> dict:
        with self._candado:
            cuenta = dict(self._datos.get("cuenta") or {})
            cuenta["conectada"] = bool(self._datos.get("refresh_token"))
            return cuenta

    def olvidar(self) -> None:
        with self._candado:
            self._datos = {}
            self._token = ""
            self._vence = 0.0
            try:
                self.archivo.unlink(missing_ok=True)
            except OSError:
                pass

    # -- Ingreso --
    #
    def url_de_ingreso(self, *, cliente_id: str, inquilino: str, retorno: str,
                       volver: str = "", pista: str = "") -> str:
        """Dirección de la página de Microsoft para entrar."""
        verificador = _b64url(secrets.token_bytes(48))
        estado = _b64url(secrets.token_bytes(24))
        nonce = _b64url(secrets.token_bytes(16))
        desafio = _b64url(hashlib.sha256(verificador.encode("ascii")).digest())

        with self._candado:
            ahora = time.time()
            # Los ingresos de hace más de 20 minutos ya no se van a completar.
            for clave in [c for c, v in self._pendientes.items() if ahora - v["creado"] > 1200]:
                self._pendientes.pop(clave, None)
            self._pendientes[estado] = {
                "verificador": verificador, "retorno": retorno, "nonce": nonce,
                "cliente_id": cliente_id, "inquilino": inquilino,
                "volver": volver, "creado": ahora,
            }

        parametros = {
            "client_id": cliente_id,
            "response_type": "code",
            "redirect_uri": retorno,
            "response_mode": "query",
            "scope": " ".join(PERMISOS),
            "state": estado,
            "nonce": nonce,
            "code_challenge": desafio,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        if pista:
            parametros["login_hint"] = pista
        return f"{URL_LOGIN}/{inquilino}/oauth2/v2.0/authorize?" + urllib.parse.urlencode(parametros)

    def es_retorno(self, estado: str) -> bool:
        with self._candado:
            return estado in self._pendientes

    def completar_ingreso(self, codigo: str, estado: str) -> dict:
        """Cambia el código que devolvió Microsoft por la sesión."""
        with self._candado:
            pendiente = self._pendientes.pop(estado, None)
        if not pendiente:
            raise ErrorMicrosoft(
                "Ese ingreso ya no es válido. Vuelva a pulsar «Conectar con Microsoft»."
            )

        respuesta = _post_formulario(
            f"{URL_LOGIN}/{pendiente['inquilino']}/oauth2/v2.0/token",
            {
                "client_id": pendiente["cliente_id"],
                "grant_type": "authorization_code",
                "code": codigo,
                "redirect_uri": pendiente["retorno"],
                "code_verifier": pendiente["verificador"],
                "scope": " ".join(PERMISOS),
            },
        )
        if not respuesta.get("refresh_token") or not respuesta.get("access_token"):
            raise ErrorMicrosoft("Microsoft no devolvió la sesión completa. Vuelva a intentar.")

        reclamos = _reclamos(respuesta.get("id_token", ""))
        if reclamos.get("nonce") not in (None, pendiente["nonce"]):
            raise ErrorMicrosoft("La respuesta de Microsoft no corresponde a este ingreso.")

        with self._candado:
            self._datos = {
                "refresh_token": respuesta["refresh_token"],
                "cliente_id": pendiente["cliente_id"],
                "inquilino": reclamos.get("tid") or pendiente["inquilino"],
                "cuenta": {
                    "nombre": reclamos.get("name", ""),
                    "correo": reclamos.get("preferred_username") or reclamos.get("email") or "",
                    "oid": reclamos.get("oid", ""),
                    "tid": reclamos.get("tid", ""),
                },
                "conectada_el": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._token = respuesta["access_token"]
            self._vence = time.time() + float(respuesta.get("expires_in", 3600))
            self._escribir()
        return {"volver": pendiente.get("volver", ""), **self.info()}

    # -- Tokens --

    def token(self, forzar: bool = False) -> str:
        """Un token de acceso vigente, renovándolo si hace falta."""
        with self._candado:
            if not forzar and self._token and time.time() < self._vence - 300:
                return self._token
            actualizacion = self._datos.get("refresh_token")
            if not actualizacion:
                raise NecesitaIniciarSesion("Conecte la cuenta de Microsoft de la empresa.")

            respuesta = _post_formulario(
                f"{URL_LOGIN}/{self._datos.get('inquilino') or 'organizations'}/oauth2/v2.0/token",
                {
                    "client_id": self._datos.get("cliente_id", ""),
                    "grant_type": "refresh_token",
                    "refresh_token": actualizacion,
                    "scope": " ".join(PERMISOS),
                },
            )
            if not respuesta.get("access_token"):
                raise NecesitaIniciarSesion("Hay que volver a conectar la cuenta de Microsoft.")

            self._token = respuesta["access_token"]
            self._vence = time.time() + float(respuesta.get("expires_in", 3600))
            # Microsoft puede entregar un token de actualización nuevo; el
            # anterior deja de servir al poco tiempo.
            if respuesta.get("refresh_token") and respuesta["refresh_token"] != actualizacion:
                self._datos["refresh_token"] = respuesta["refresh_token"]
                self._escribir()
            return self._token

    def invalidar_token(self) -> None:
        """Un 401 de Graph: el token en memoria no sirve, se pide otro."""
        with self._candado:
            self._token = ""
            self._vence = 0.0

    def error_de_retorno(self, estado: str, error: str, descripcion: str) -> ErrorMicrosoft:
        """Traduce el error que Microsoft devuelve en la dirección de retorno."""
        with self._candado:
            self._pendientes.pop(estado, None)
        return _traducir_error({"error": error, "error_description": descripcion})
