"""Las llamadas a Microsoft Graph, la API de SharePoint y OneDrive.

Solo lo que el programa usa: encontrar la carpeta a partir del enlace,
mirar un archivo, bajarlo, subirlo con control de versiones, listar y crear
carpetas y borrar. Cada respuesta de error se convierte en una excepción con
nombre (`SinPermiso`, `CambioConcurrente`…) y un texto que una persona
entiende.

Graph frena a quien pide demasiado rápido (429) y a veces está ocupado
(503). En esos casos dice cuánto esperar (`Retry-After`) y aquí se respeta.
"""

from __future__ import annotations

import email.utils
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .microsoft import ErrorMicrosoft, NecesitaIniciarSesion, SinConexion

URL_GRAPH = os.environ.get("MAJERIE_GRAPH_URL", "https://graph.microsoft.com/v1.0").rstrip("/")

ESPERA_RED = 30
REINTENTOS = 4
ESPERA_MAXIMA = 30


class ErrorGraph(ErrorMicrosoft):
    """Graph contestó con un error que no tiene nombre propio."""

    def __init__(self, mensaje: str, estado: int = 0, codigo: str = "", detalle: str = ""):
        super().__init__(mensaje, codigo=codigo, detalle=detalle)
        self.estado = estado


class SinPermiso(ErrorGraph):
    pass


class NoEncontrado(ErrorGraph):
    pass


class YaExiste(ErrorGraph):
    pass


class CambioConcurrente(ErrorGraph):
    """412: el archivo cambió desde que se leyó (otra computadora guardó)."""


class Bloqueado(ErrorGraph):
    """423: el archivo está abierto o retenido en SharePoint."""


class CuotaLlena(ErrorGraph):
    pass


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    """Las descargas redirigen a una dirección ya autorizada; esa dirección
    se pide a mano y **sin** el token, que ahí no corresponde."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _abridor(redirigir: bool = True):
    manejadores = [urllib.request.ProxyHandler(urllib.request.getproxies())]
    if not redirigir:
        manejadores.append(_SinRedireccion())
    return urllib.request.build_opener(*manejadores)


def _ruta_segura(nombre: str) -> str:
    return urllib.parse.quote(nombre, safe="")


class Respuesta:
    def __init__(self, estado: int, cabeceras, cuerpo: bytes):
        self.estado = estado
        self.cabeceras = cabeceras
        self.cuerpo = cuerpo

    def json(self) -> dict:
        try:
            return json.loads(self.cuerpo.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            return {}

    @property
    def fecha_servidor(self) -> float | None:
        valor = self.cabeceras.get("Date") if self.cabeceras else None
        try:
            return email.utils.parsedate_to_datetime(valor).timestamp() if valor else None
        except (TypeError, ValueError):
            return None


class Graph:
    """Cliente de Graph que actúa con la cuenta de Microsoft de la computadora."""

    def __init__(self, cuenta):
        self.cuenta = cuenta
        # Hora de SharePoint según la última respuesta: sirve para saber
        # cuánto hace que se guardó algo sin fiarse del reloj de esta PC.
        self.ultima_fecha_servidor = None

    # Todas las llamadas pasan por aquí: arma la petición, pone el token,
    # reintenta lo que se puede reintentar y traduce los errores.
    def pedir(self, metodo: str, ruta: str, *, cuerpo=None, cabeceras: dict | None = None,
              consulta: dict | None = None, absoluta: bool = False,
              con_token: bool = True, redirigir: bool = True,
              reintentos: int = REINTENTOS) -> Respuesta:
        url = ruta if absoluta else f"{URL_GRAPH}{ruta}"
        if consulta:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(consulta)

        datos = None
        encabezados = {"Accept": "application/json"}
        if isinstance(cuerpo, (dict, list)):
            datos = json.dumps(cuerpo).encode("utf-8")
            encabezados["Content-Type"] = "application/json"
        elif cuerpo is not None:
            datos = bytes(cuerpo)
            encabezados["Content-Type"] = "application/octet-stream"
        encabezados.update(cabeceras or {})

        renovado = False
        intento = 0
        while True:
            intento += 1
            if con_token:
                encabezados["Authorization"] = f"Bearer {self.cuenta.token(forzar=renovado)}"
            peticion = urllib.request.Request(url, data=datos, method=metodo, headers=encabezados)
            try:
                with _abridor(redirigir).open(peticion, timeout=ESPERA_RED) as crudo:
                    respuesta = Respuesta(crudo.status, crudo.headers, crudo.read())
            except urllib.error.HTTPError as fallo:
                respuesta = Respuesta(fallo.code, fallo.headers, fallo.read() or b"")
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as fallo:
                if intento < min(reintentos, 2) and metodo in ("GET", "HEAD"):
                    time.sleep(1.5 * intento)
                    continue
                raise SinConexion(
                    "No hay conexión con SharePoint. Revise el internet de esta computadora.",
                    detalle=str(fallo),
                ) from None

            fecha = respuesta.fecha_servidor
            if fecha:
                self.ultima_fecha_servidor = fecha

            if respuesta.estado == 401 and con_token and not renovado:
                # El token venció antes de tiempo: se pide uno nuevo una vez.
                self.cuenta.invalidar_token()
                renovado = True
                continue

            if respuesta.estado in (429, 503, 502, 504) and intento < reintentos:
                time.sleep(self._espera(respuesta, intento))
                continue

            if respuesta.estado >= 400 and not (300 <= respuesta.estado < 400):
                raise self._error(respuesta)
            return respuesta

    @staticmethod
    def _espera(respuesta: Respuesta, intento: int) -> float:
        valor = (respuesta.cabeceras or {}).get("Retry-After", "") if respuesta.cabeceras else ""
        try:
            segundos = float(valor)
        except (TypeError, ValueError):
            segundos = 2.0 ** intento
        return max(0.5, min(segundos, ESPERA_MAXIMA))

    @staticmethod
    def _error(respuesta: Respuesta) -> ErrorGraph:
        datos = respuesta.json().get("error") or {}
        codigo = str(datos.get("code") or "")
        detalle = str(datos.get("message") or "")
        estado = respuesta.estado

        if estado == 401:
            return NecesitaIniciarSesion(
                "La sesión de Microsoft ya no es válida. Vuelva a conectar.",
                codigo=codigo, detalle=detalle,
            )
        if estado == 403:
            return SinPermiso(
                "Su cuenta de Microsoft no tiene permiso para esa carpeta de SharePoint. "
                "Pida a quien la compartió permiso de edición.",
                estado, codigo, detalle,
            )
        if estado == 404:
            return NoEncontrado(
                "No se encontró en SharePoint. Puede que la hayan movido, renombrado o "
                "borrado, o que su cuenta no tenga acceso.",
                estado, codigo, detalle,
            )
        if estado == 409:
            return YaExiste("Ya existe un elemento con ese nombre.", estado, codigo, detalle)
        if estado == 412:
            return CambioConcurrente(
                "Otra computadora guardó cambios al mismo tiempo.", estado, codigo, detalle
            )
        if estado == 423:
            return Bloqueado(
                "SharePoint tiene el archivo bloqueado (abierto o retenido).",
                estado, codigo, detalle,
            )
        if estado == 507:
            return CuotaLlena(
                "El SharePoint de la empresa se quedó sin espacio.", estado, codigo, detalle
            )
        if estado in (429, 503, 502, 504):
            return ErrorGraph(
                "SharePoint está muy ocupado en este momento. Vuelva a intentar en un minuto.",
                estado, codigo, detalle,
            )
        return ErrorGraph(
            f"SharePoint contestó con un error ({estado}"
            + (f", {codigo}" if codigo else "") + ").",
            estado, codigo, detalle,
        )

    # -- Carpetas y archivos ------------------------------------------------
    #
    def resolver_enlace(self, codificado: str) -> dict:
        """El elemento al que apunta un enlace (`u!…` de `enlaces.codificar`).

        `redeemSharingLink` equivale a abrir el enlace en el navegador: si es
        de los de «Compartir», deja a la persona con acceso permanente.
        """
        return self.pedir(
            "GET", f"/shares/{codificado}/driveItem",
            cabeceras={"Prefer": "redeemSharingLink"},
        ).json()

    def sitio_por_ruta(self, anfitrion: str, ruta_sitio: str) -> dict:
        return self.pedir("GET", f"/sites/{anfitrion}:{urllib.parse.quote(ruta_sitio)}").json()

    def bibliotecas(self, sitio_id: str) -> list[dict]:
        return self.pedir("GET", f"/sites/{sitio_id}/drives").json().get("value", [])

    def por_ruta(self, drive: str, ruta_relativa: str) -> dict:
        ruta = urllib.parse.quote(ruta_relativa.strip("/"))
        return self.pedir("GET", f"/drives/{drive}/root:/{ruta}").json()

    def yo(self) -> dict:
        return self.pedir(
            "GET", "/me", consulta={"$select": "displayName,mail,userPrincipalName"}
        ).json()

    # Los elementos se identifican por la biblioteca (drive) y su id, que no
    # cambia aunque alguien los renombre o los mueva.
    def elemento(self, drive: str, item: str) -> dict:
        return self.pedir("GET", f"/drives/{drive}/items/{item}").json()

    def hijo(self, drive: str, padre: str, nombre: str) -> dict:
        """Un archivo o carpeta dentro de `padre`, por su nombre."""
        return self.pedir("GET", f"/drives/{drive}/items/{padre}:/{_ruta_segura(nombre)}").json()

    def hijos(self, drive: str, padre: str) -> list[dict]:
        resultado = []
        url = f"/drives/{drive}/items/{padre}/children"
        consulta = {"$top": "200"}
        absoluta = False
        while url:
            datos = self.pedir("GET", url, consulta=consulta, absoluta=absoluta).json()
            resultado.extend(datos.get("value", []))
            url = datos.get("@odata.nextLink", "")
            consulta = None
            absoluta = True
        return resultado

    def crear_carpeta(self, drive: str, padre: str, nombre: str, conflicto: str = "fail") -> dict:
        return self.pedir(
            "POST", f"/drives/{drive}/items/{padre}/children",
            cuerpo={"name": nombre, "folder": {},
                    "@microsoft.graph.conflictBehavior": conflicto},
        ).json()

    def borrar(self, drive: str, item: str, si_coincide: str | None = None) -> None:
        cabeceras = {"If-Match": si_coincide} if si_coincide else None
        self.pedir("DELETE", f"/drives/{drive}/items/{item}", cabeceras=cabeceras)

    # -- Contenido -----------------------------------------------------------
    #
    def descargar(self, drive: str, item: str, rango: str | None = None) -> tuple[bytes, dict]:
        """Contenido de un archivo y las cabeceras con que llegó."""
        respuesta = self.pedir(
            "GET", f"/drives/{drive}/items/{item}/content", redirigir=False
        )
        if respuesta.estado in (301, 302, 303, 307, 308):
            destino = respuesta.cabeceras.get("Location", "")
            cabeceras = {"Range": rango} if rango else None
            respuesta = self.pedir(
                "GET", destino, absoluta=True, con_token=False, cabeceras=cabeceras
            )
        return respuesta.cuerpo, dict(respuesta.cabeceras or {})

    def subir_nuevo(self, drive: str, padre: str, nombre: str, datos: bytes,
                    conflicto: str = "fail") -> dict:
        """Crea un archivo. Con `fail`, si ya existe se lanza `YaExiste`."""
        return self.pedir(
            "PUT", f"/drives/{drive}/items/{padre}:/{_ruta_segura(nombre)}:/content",
            cuerpo=datos, consulta={"@microsoft.graph.conflictBehavior": conflicto},
        ).json()

    def reemplazar(self, drive: str, item: str, datos: bytes,
                   si_coincide: str | None = None) -> dict:
        """Reemplaza el contenido. Con `si_coincide`, solo si nadie lo cambió."""
        cabeceras = {"If-Match": si_coincide} if si_coincide else None
        return self.pedir(
            "PUT", f"/drives/{drive}/items/{item}/content", cuerpo=datos, cabeceras=cabeceras,
            # Un 412 o un 423 se resuelven arriba (se vuelve a leer y se
            # repite); aquí solo se reintenta poco.
            reintentos=2,
        ).json()
