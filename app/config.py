"""Configuración y rutas del programa.

El sistema ya no es un servidor que una computadora deja encendido para todo
el equipo: cada persona abre el `.exe` en su propia computadora y los datos
viven en el SharePoint de la empresa. Este módulo decide dónde guarda cada
computadora lo suyo y lee y escribe su configuración.

Dos reglas mandan aquí:

1. **Nada del programa se guarda junto al `.exe`.** El ejecutable puede estar
   en el Escritorio, en Descargas o en una carpeta sincronizada; da igual.
   Todo lo que el programa necesita recordar vive en `LOCALAPPDATA`, que
   OneDrive no toca.
2. **La configuración es de la computadora, no de la persona.** El enlace de
   SharePoint, el navegador elegido y la cuenta de Microsoft conectada son de
   este equipo; los usuarios y las horas son de la empresa y viven en
   SharePoint.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from pathlib import Path

# ¿Corre dentro del `.exe` de PyInstaller?
EMPAQUETADO = getattr(sys, "frozen", False)

NOMBRE_APP = "Sistema de Registro de Horas"
EMPRESA = "MAJERIE S.R.L"
VERSION = "3.1.0"

# Identificador estable del programa (candado de instancia única…).
ID_APP = "majerie-registro-horas"


def _carpeta_datos() -> Path:
    """Carpeta privada de esta computadora.

    `MAJERIE_DATOS` permite apuntar a otra: es lo que usan las pruebas para
    no tocar jamás la configuración ni la cuenta de Microsoft reales.
    """
    propia = os.environ.get("MAJERIE_DATOS")
    if propia:
        return Path(propia)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "MAJERIE Registro de Horas"
    return Path.home() / ".majerie-registro-horas"


def _carpeta_recursos() -> Path:
    """Dónde están las plantillas, los estilos y el esquema.

    Dentro del `.exe` viven en la carpeta temporal que PyInstaller prepara.
    """
    if EMPAQUETADO:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "app"
    return Path(__file__).resolve().parent


CARPETA_DATOS = _carpeta_datos()
RECURSOS = _carpeta_recursos()

ARCHIVO_CONFIGURACION = CARPETA_DATOS / "configuracion.json"
ARCHIVO_REGISTRO = CARPETA_DATOS / "registro.log"
# Puerto y secreto del proceso que ya está abierto: así un segundo doble
# clic sabe adónde mandar la ventana.
ARCHIVO_INSTANCIA = CARPETA_DATOS / "instancia.json"
# La sesión de Microsoft 365 de esta computadora, cifrada con la cuenta de
# Windows.
ARCHIVO_CUENTA = CARPETA_DATOS / "cuenta-microsoft.bin"
# Perfil propio del navegador para la ventana del programa.
CARPETA_VENTANA = CARPETA_DATOS / "ventana"
# Copia de trabajo de los datos de SharePoint y lo que el almacén recuerda
# de la última sincronización.
CARPETA_NUBE = CARPETA_DATOS / "nube"
ARCHIVO_ESTADO_NUBE = CARPETA_NUBE / "estado.json"
# La base local. `MAJERIE_BASE` permite apuntar a otra (pruebas).
#
ARCHIVO_BASE = Path(os.environ.get("MAJERIE_BASE") or CARPETA_NUBE / "majerie.db")
# Dónde guardaba la base la versión anterior (la del servidor con ventana
# negra). Si existe, el asistente ofrece subirla a SharePoint tal cual.
#
BASE_VERSION_ANTERIOR = CARPETA_DATOS / "majerie.db"

ARCHIVO_ESQUEMA = RECURSOS / "esquema.sql"
CARPETA_PLANTILLAS = RECURSOS / "templates"
CARPETA_ESTATICOS = RECURSOS / "static"


# ---------------------------------------------------------------------------
# Configuración de la computadora
# ---------------------------------------------------------------------------
POR_OMISION: dict = {
    # Firma las cookies de sesión. Se crea la primera vez.
    "secreto_sesion": "",
    # Navegador con que se abre la ventana del programa: su identificador y
    # la ruta del ejecutable.
    "navegador": "",
    "navegador_ruta": "",
    # «auto», «claro» u «oscuro».
    "tema": "auto",
    # Puerto preferido del servidor interno.
    "puerto": 8642,
    # Reporte de Excel que se guarda solo, en la carpeta de SharePoint.
    "excel_automatico": False,
    # Enlace de la carpeta, sitio, unidad y carpeta resueltos, cuenta…
    "sharepoint": {},
}


class Configuracion:
    """Configuración de esta computadora, en un JSON pequeño.

    Se escribe siempre entero y de golpe —primero aparte y después se
    reemplaza—, para que un corte de luz nunca la deje a medias. Varias
    partes del programa la leen y la escriben desde hilos distintos; un
    candado las pone en fila.
    """

    def __init__(self, ruta: Path | None = None):
        self.ruta = Path(ruta or ARCHIVO_CONFIGURACION)
        self._candado = threading.RLock()
        self._valores = {}
        self.recargar()

    # -- Lectura -----------------------------------------------------------

    def recargar(self) -> None:
        with self._candado:
            try:
                datos = json.loads(self.ruta.read_text(encoding="utf-8"))
                if not isinstance(datos, dict):
                    datos = {}
            except (OSError, ValueError):
                datos = {}
            self._valores = datos

    def __getitem__(self, clave: str):
        with self._candado:
            if clave in self._valores:
                return self._valores[clave]
            valor = POR_OMISION.get(clave)
            return json.loads(json.dumps(valor)) if isinstance(valor, (dict, list)) else valor

    def get(self, clave: str, por_omision=None):
        valor = self[clave]
        return por_omision if valor is None else valor

    @property
    def sharepoint(self) -> dict:
        return dict(self["sharepoint"] or {})

    # -- Escritura ---------------------------------------------------------

    def guardar(self, **cambios) -> None:
        with self._candado:
            self._valores.update(cambios)
            self._escribir()

    def guardar_sharepoint(self, **cambios) -> None:
        """Mezcla cambios en la sección de SharePoint."""
        with self._candado:
            actual = dict(self._valores.get("sharepoint") or {})
            for clave, valor in cambios.items():
                if valor is None:
                    actual.pop(clave, None)
                else:
                    actual[clave] = valor
            self._valores["sharepoint"] = actual
            self._escribir()

    def olvidar_sharepoint(self) -> None:
        with self._candado:
            self._valores["sharepoint"] = {}
            self._escribir()

    def _escribir(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        provisional = self.ruta.with_name(self.ruta.name + ".nuevo")
        provisional.write_text(
            json.dumps(self._valores, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(provisional, self.ruta)

    # -- Secreto de las sesiones -------------------------------------------

    def asegurar_secreto(self) -> str:
        """El secreto de las sesiones, creándolo la primera vez."""
        with self._candado:
            secreto = self._valores.get("secreto_sesion") or ""
            if len(secreto) < 32:
                secreto = secrets.token_urlsafe(48)
                self.guardar(secreto_sesion=secreto)
            return secreto


_CONFIGURACION: Configuracion | None = None
_CANDADO_GLOBAL = threading.Lock()


def configuracion() -> Configuracion:
    """La configuración de la computadora, una sola para todo el proceso."""
    global _CONFIGURACION
    with _CANDADO_GLOBAL:
        if _CONFIGURACION is None:
            _CONFIGURACION = Configuracion()
        return _CONFIGURACION


def nombre_equipo() -> str:
    """Nombre de esta computadora, para decir desde dónde se hizo un cambio."""
    return (os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "").strip()


def en_carpeta_sincronizada(ruta: Path) -> bool:
    """¿Esta ruta está dentro de OneDrive u otra carpeta que se sincroniza?"""
    texto = str(ruta).lower()
    return any(marca in texto for marca in ("onedrive", "dropbox", "google drive", "icloud"))
