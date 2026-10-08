"""La copia de trabajo de los datos y su sincronización con SharePoint.

Todos los datos del sistema —usuarios, horas, ausencias, proyectos y
tarifas— son **una base SQLite** que vive en la carpeta de SharePoint de la
empresa, dentro de un sobre comprimido y sellado (`cifrado.py`). Cada
computadora trabaja sobre una copia local de esa base:

- **Para leer**, usa su copia. Un vigilante mira cada pocos segundos si en
  SharePoint hay una versión más nueva —basta con comparar la etiqueta de
  versión (`eTag`) del archivo— y, si la hay, la trae.
- **Para guardar**, primero trae la última versión, aplica el cambio y sube
  la base entera con la condición «solo si nadie la cambió desde que la
  traje» (`If-Match`). Si otra computadora se adelantó, SharePoint contesta
  412: se deshace el cambio local, se trae la versión nueva y se vuelve a
  aplicar encima. Así dos personas que guardan a la vez nunca se pisan.

Al conectar se comprueba que SharePoint respete esa condición. Si no la
respetara, el programa se pone en fila con un «candado»: una carpeta que
solo puede existir una vez y que marca quién está guardando.

Todo acceso al archivo local pasa por `candado`: así nadie lo lee mientras
se reemplaza por una versión recién traída.
"""

from __future__ import annotations

import json
import logging
import os
import random
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..config import (
    ARCHIVO_BASE,
    ARCHIVO_ESTADO_NUBE,
    VERSION,
    nombre_equipo,
)
from . import cifrado
from .enlaces import Enlace, interpretar
from .graph import (
    Bloqueado,
    CambioConcurrente,
    ErrorGraph,
    Graph,
    NoEncontrado,
    SinPermiso,
    YaExiste,
)
from .microsoft import ErrorMicrosoft, NecesitaIniciarSesion, SinConexion

log = logging.getLogger("majerie.nube")

CARPETA_SISTEMA = "Sistema de Registro de Horas"
ARCHIVO_DATOS = "datos.majerie"
ARCHIVO_LEAME = "LEAME - no mover ni editar estos archivos.txt"
ARCHIVO_EXCEL = "Registro de Horas MAJERIE (se actualiza solo).xlsx"
CARPETA_RESPALDOS = "Respaldos"
CANDADO_REMOTO = ".guardando-no-borrar"

# Cada cuánto mira el vigilante si hay algo nuevo en SharePoint (segundos).
INTERVALO_SONDEO = 20.0
# Veces que se repite un guardado si otra computadora se adelanta.
INTENTOS_GUARDADO = 6
# Respaldos diarios que se conservan en SharePoint.
RESPALDOS_QUE_SE_CONSERVAN = 30
# Un candado más viejo que esto quedó de una computadora que se apagó.
EDAD_CANDADO_ABANDONADO = 90.0

TEXTO_LEAME = """SISTEMA DE REGISTRO DE HORAS · MAJERIE S.R.L
=============================================

Esta carpeta la usa el Sistema de Registro de Horas. Aquí viven los datos
de todo el equipo: usuarios, horas, ausencias, proyectos y tarifas.

  datos.majerie          Los datos del sistema. Van comprimidos y sellados:
                         no se pueden abrir con otro programa.
  Registro de Horas ...  El Excel con todas las horas. Se actualiza solo
                         cada vez que alguien guarda algo. SOLO PARA LEER:
                         lo que se escriba encima se pierde.
  Respaldos\\             Una copia por día de los últimos 30 días.

NO MUEVA, RENOMBRE NI BORRE estos archivos. Si se borra datos.majerie por
error, recupérelo de la Papelera de reciclaje del sitio o restaure una copia
desde el programa (Ajustes → Copias de seguridad).

SharePoint guarda además el historial de versiones de cada archivo
(clic derecho → Historial de versiones).
"""


class SoloLectura(ErrorMicrosoft):
    """Ahora mismo no se puede guardar (sin conexión, sesión vencida…)."""


class FaltaConfigurar(ErrorMicrosoft):
    """Todavía no se eligió la carpeta de SharePoint."""


def _ahora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _segundos_desde_iso(texto: str, referencia: float | None = None) -> float:
    try:
        momento = datetime.fromisoformat(texto.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return 0.0
    return (referencia or time.time()) - momento


def _soltar_conexion_de_la_peticion() -> None:
    """Cierra la conexión a la base que tenga abierta la petición en curso.

    Windows no deja reemplazar un archivo abierto. Si una pantalla ya leyó
    algo (por ejemplo, quién es la persona) y después pide traer o restaurar
    datos, su conexión estorbaría; la siguiente consulta la vuelve a abrir.
    """
    try:
        from flask import has_app_context

        if has_app_context():
            from ..db import cerrar

            cerrar()
    except Exception:
        pass


def _reemplazar(origen: Path, destino: Path) -> None:
    """`os.replace` con paciencia: un antivirus puede tener el archivo
    tomado unos milisegundos justo después de escribirlo."""
    for intento in range(20):
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            if intento == 19:
                raise
            time.sleep(0.1)


def contador_cambios(ruta: Path) -> bytes:
    """El «contador de cambios» que SQLite guarda en la cabecera del archivo.

    SQLite lo incrementa cada vez que una transacción modifica la base (en
    modo de diario clásico, que es el que se usa aquí). Comparar estos cuatro
    bytes antes y después de una petición dice si cambió algo, sin abrir la
    base.
    """
    try:
        with open(ruta, "rb") as archivo:
            cabecera = archivo.read(28)
        return cabecera[24:28]
    except OSError:
        return b""


class Almacen:
    """La copia local de los datos y su ida y vuelta con SharePoint."""

    def __init__(self, configuracion, cuenta, ruta_base: Path | None = None,
                 ruta_estado: Path | None = None):
        self.configuracion = configuracion
        self.cuenta = cuenta
        self.graph = Graph(cuenta)
        self.ruta_base = Path(ruta_base or ARCHIVO_BASE)
        self.ruta_estado = Path(ruta_estado or ARCHIVO_ESTADO_NUBE)
        # `candado` protege el archivo local; `_candado_estado`, los
        # diccionarios de estado.
        self.candado = threading.RLock()
        self._candado_estado = threading.Lock()
        self._persistente = self._leer_estado()
        self._vivo = {
            "en_linea": None,
            "ocupado": "",
            "error": "",
            "necesita_sesion": False,
            "falta_archivo": False,
            "solo_lectura": "",
            "ultima_comprobacion": 0.0,
            # Sube cada vez que llegan datos nuevos: la pantalla lo usa para
            # saber si tiene que recargarse.
            "version_datos": 0,
        }
        self._vigilante = None
        self._parar = threading.Event()
        self._despertar = threading.Event()
        self._respaldo_hecho = ""
        self.despues_de_guardar = []
        # Cuántas veces subió esta computadora (para `_por_si_acaso`).
        self.subidas = 0

    # -- Estado que sobrevive al cierre: etag, autor, si quedó algo a medias.
    #
    def _leer_estado(self) -> dict:
        try:
            datos = json.loads(self.ruta_estado.read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def _guardar_estado(self, **cambios) -> None:
        with self._candado_estado:
            self._persistente.update(cambios)
            self.ruta_estado.parent.mkdir(parents=True, exist_ok=True)
            provisional = self.ruta_estado.with_name(self.ruta_estado.name + ".nuevo")
            provisional.write_text(json.dumps(self._persistente, indent=2), encoding="utf-8")
            os.replace(provisional, self.ruta_estado)

    def _anotar(self, **cambios) -> None:
        with self._candado_estado:
            self._vivo.update(cambios)

    @property
    def sp(self) -> dict:
        return self.configuracion.sharepoint

    @property
    def configurado(self) -> bool:
        """Hay carpeta elegida y archivo de datos en ella."""
        sp = self.sp
        return bool(sp.get("drive_id") and sp.get("carpeta_sistema_id") and sp.get("archivo_id"))

    @property
    def hay_copia_local(self) -> bool:
        return self.ruta_base.is_file() and bool(self._persistente.get("etag"))

    def estado(self) -> dict:
        """Lo que la pantalla muestra en el indicador de la nube."""
        with self._candado_estado:
            vivo = dict(self._vivo)
            persistente = dict(self._persistente)
        sp = self.sp
        ahora = time.time()
        cuenta = self.cuenta.info()
        return {
            "configurado": self.configurado,
            "cuenta": cuenta.get("correo", ""),
            "nombre_cuenta": cuenta.get("nombre", ""),
            "cuenta_conectada": cuenta.get("conectada", False),
            "carpeta": sp.get("nombre_carpeta", ""),
            "carpeta_url": sp.get("web_url", ""),
            "sitio": sp.get("sitio", ""),
            "en_linea": vivo["en_linea"],
            "ocupado": vivo["ocupado"],
            "error": vivo["error"],
            "necesita_sesion": vivo["necesita_sesion"],
            "falta_archivo": vivo["falta_archivo"],
            "solo_lectura": vivo["solo_lectura"] or self._motivo_solo_lectura(vivo),
            "hace": round(ahora - vivo["ultima_comprobacion"]) if vivo["ultima_comprobacion"] else None,
            "version_datos": vivo["version_datos"],
            "autor": persistente.get("autor", ""),
            "modificado": persistente.get("modificado", ""),
            "subido": persistente.get("subido", ""),
            "copia_local": self.hay_copia_local,
            "modo": sp.get("modo_concurrencia", ""),
        }

    def _motivo_solo_lectura(self, vivo: dict) -> str:
        if not self.configurado:
            return "Falta conectar la carpeta de SharePoint."
        if vivo["necesita_sesion"]:
            return "La sesión de Microsoft venció. Vuelva a conectar la cuenta."
        if vivo["falta_archivo"]:
            return "El archivo de datos ya no está en SharePoint."
        if vivo["en_linea"] is False:
            return "Sin conexión con SharePoint. Los cambios se podrán guardar cuando vuelva."
        return ""

    def _registrar_fallo(self, fallo: Exception) -> None:
        if isinstance(fallo, NecesitaIniciarSesion):
            self._anotar(necesita_sesion=True, en_linea=True, error=str(fallo))
        elif isinstance(fallo, SinConexion):
            self._anotar(en_linea=False, error=str(fallo))
        elif isinstance(fallo, NoEncontrado):
            self._anotar(falta_archivo=True, en_linea=True, error=str(fallo))
        elif isinstance(fallo, cifrado.ArchivoIlegible):
            self._anotar(en_linea=True, error=(
                f"{fallo} Se sigue usando la última copia buena de esta computadora; "
                "la administración puede restaurar un respaldo desde Ajustes."
            ))
        else:
            self._anotar(error=str(fallo))

    # -- Vigilante: mira SharePoint cada `INTERVALO_SONDEO` segundos ---------
    #
    def arrancar_vigilante(self) -> None:
        if self._vigilante and self._vigilante.is_alive():
            return
        self._parar.clear()
        self._vigilante = threading.Thread(target=self._vigilar, name="nube", daemon=True)
        self._vigilante.start()

    def detener_vigilante(self) -> None:
        self._parar.set()
        self._despertar.set()

    def pedir_comprobacion(self) -> None:
        """Que el vigilante mire SharePoint ya, sin esperar su turno."""
        self._despertar.set()

    def _vigilar(self) -> None:
        primera = True
        while not self._parar.is_set():
            if self.configurado and self.cuenta.conectada:
                try:
                    self.comprobar(forzar=primera)
                    primera = False
                    self._respaldo_del_dia()
                except Exception as fallo:
                    log.info("Comprobación fallida: %s", fallo)
            self._despertar.wait(INTERVALO_SONDEO)
            self._despertar.clear()

    # -- Traer -----------------------------------------------------------------
    #
    def preparar(self) -> None:
        """Al arrancar: si un guardado quedó a medias, la copia local no vale."""
        if self._persistente.get("pendiente"):
            log.warning("El último guardado quedó a medias: se descarta la copia local.")
            self._descartar_copia_local()

    def _descartar_copia_local(self) -> None:
        with self.candado:
            _soltar_conexion_de_la_peticion()
            for ruta in (self.ruta_base, self.ruta_base.with_name(self.ruta_base.name + "-journal")):
                try:
                    ruta.unlink(missing_ok=True)
                except OSError:
                    pass
            self._guardar_estado(etag="", pendiente=False)

    def comprobar(self, forzar: bool = False) -> bool:
        """Trae la versión de SharePoint si es más nueva que la local.

        Devuelve True si llegó algo nuevo.
        """
        if not self.configurado:
            return False
        with self.candado:
            if not forzar and time.time() - self._vivo["ultima_comprobacion"] < 4:
                return False
            sp = self.sp
            self._anotar(ocupado="comprobando")
            try:
                meta = self.graph.elemento(sp["drive_id"], sp["archivo_id"])
            except Exception as fallo:
                self._anotar(ocupado="")
                self._registrar_fallo(fallo)
                raise
            self._anotar(
                en_linea=True, necesita_sesion=False, falta_archivo=False, error="",
                ultima_comprobacion=time.time(), ocupado="",
            )
            self._anotar_autor(meta)
            # Misma etiqueta de versión: la copia local ya es la última.
            if meta.get("eTag") == self._persistente.get("etag") and self.ruta_base.is_file():
                return False

            self._anotar(ocupado="descargando")
            try:
                self._traer(meta)
            except Exception as fallo:
                # Si lo que llegó no sirve, se sigue con la copia local, que
                # es la última buena.
                self._registrar_fallo(fallo)
                raise
            finally:
                self._anotar(ocupado="")
            with self._candado_estado:
                self._vivo["version_datos"] += 1
            return True

    def _anotar_autor(self, meta: dict) -> None:
        usuario = (meta.get("lastModifiedBy") or {}).get("user") or {}
        autor = usuario.get("displayName", "")
        modificado = meta.get("lastModifiedDateTime", "")
        if (autor, modificado) != (self._persistente.get("autor"), self._persistente.get("modificado")):
            self._guardar_estado(autor=autor, modificado=modificado)

    def _traer(self, meta: dict) -> None:
        sp = self.sp
        sobre, _cabeceras = self.graph.descargar(sp["drive_id"], sp["archivo_id"])
        contenido, cabecera = cifrado.abrir(sobre)
        self._colocar_base(contenido)
        # El eTag que vale es el de los metadatos que se pidieron antes de
        # descargar: si alguien guardó entre medio, la próxima comprobación
        # lo nota y vuelve a traer. Al revés (tomar un eTag más nuevo que el
        # contenido) se perdería ese cambio.
        #
        #
        self._guardar_estado(
            etag=meta.get("eTag", ""), ctag=meta.get("cTag", ""), descargado=_ahora_utc(),
            esquema=cabecera.get("esquema"), escritura=cabecera.get("escritura", ""),
            pendiente=False,
        )
        log.info("Datos traídos de SharePoint (%s bytes, escrito por %s en %s).",
                 len(contenido), cabecera.get("por", "?"), cabecera.get("equipo", "?"))

    def _colocar_base(self, contenido: bytes) -> None:
        """Deja `contenido` como la base local, comprobada y de una vez."""
        self.ruta_base.parent.mkdir(parents=True, exist_ok=True)
        provisional = self.ruta_base.with_name(self.ruta_base.name + ".nueva")
        provisional.write_bytes(contenido)
        conexion = sqlite3.connect(provisional)
        try:
            resultado = conexion.execute("PRAGMA quick_check").fetchone()
            if not resultado or resultado[0] != "ok":
                raise cifrado.ArchivoIlegible("La base que llegó de SharePoint está dañada.")
            conexion.execute("PRAGMA journal_mode = DELETE")
            from ..migraciones import ESQUEMA_ACTUAL, migrar

            esquema = migrar(conexion)
            conexion.commit()
        finally:
            conexion.close()
        _soltar_conexion_de_la_peticion()
        _reemplazar(provisional, self.ruta_base)
        # Una base escrita por una versión más nueva del programa se puede
        # leer, pero no guardar: se perderían datos que esta versión no conoce.
        self._anotar(solo_lectura=(
            "Otra computadora usa una versión más nueva del programa. Actualice el "
            "Sistema de Registro de Horas para poder guardar cambios."
            if esquema > ESQUEMA_ACTUAL else ""
        ))
        try:
            self.ruta_base.with_name(self.ruta_base.name + "-journal").unlink(missing_ok=True)
        except OSError:
            pass

    # -- Guardar ---------------------------------------------------------------
    #
    def puede_guardar(self) -> str:
        """Texto con el motivo si ahora no se puede guardar; vacío si sí."""
        if not self.configurado:
            return "Falta conectar la carpeta de SharePoint (Ajustes)."
        if not self.cuenta.conectada:
            return "Conecte la cuenta de Microsoft para poder guardar (Ajustes)."
        motivo = self._vivo.get("solo_lectura")
        return motivo or ""

    def guardar(self, ejecutar, forzar_subida: bool = False):
        """Ejecuta `ejecutar()` sobre la última versión y sube lo que cambió.

        `ejecutar` es la petición que modifica la base; puede correr varias
        veces si otra computadora guarda al mismo tiempo, siempre sobre los
        datos más nuevos. Devuelve lo que devuelva la última ejecución.
        Si `ejecutar` no cambió nada, no se sube nada (salvo `forzar_subida`).
        """
        motivo = self.puede_guardar()
        if motivo:
            raise SoloLectura(motivo)

        with self.candado:
            for intento in range(1, INTENTOS_GUARDADO + 1):
                with self._turno():
                    self.comprobar(forzar=True)
                    if not self.ruta_base.is_file():
                        raise SoloLectura("Todavía no hay datos de SharePoint en esta computadora.")
                    # La versión recién traída puede ser de un programa más nuevo.
                    if self._vivo.get("solo_lectura"):
                        raise SoloLectura(self._vivo["solo_lectura"])
                    respaldo = self.ruta_base.read_bytes()
                    antes = contador_cambios(self.ruta_base)
                    self._guardar_estado(pendiente=True)
                    try:
                        resultado = ejecutar()
                    except BaseException:
                        self._restaurar(respaldo)
                        raise
                    # Nada cambió (un formulario con errores, por ejemplo).
                    if not forzar_subida and contador_cambios(self.ruta_base) == antes:
                        self._guardar_estado(pendiente=False)
                        return resultado

                    try:
                        self._anotar(ocupado="guardando")
                        self._subir()
                    except CambioConcurrente:
                        log.info("Otra computadora guardó primero; se repite (intento %s).", intento)
                        self._restaurar(respaldo)
                        time.sleep(random.uniform(0.05, 0.35) * intento)
                        continue
                    except BaseException as fallo:
                        self._restaurar(respaldo)
                        self._registrar_fallo(fallo)
                        raise
                    finally:
                        self._anotar(ocupado="")
                # Ya está en SharePoint.
                self._guardar_estado(pendiente=False)
                for funcion in list(self.despues_de_guardar):
                    try:
                        funcion()
                    except Exception:
                        log.exception("Tarea posterior al guardado")
                return resultado

        raise ErrorGraph(
            "Hay demasiadas computadoras guardando al mismo tiempo. Vuelva a intentar en un momento."
        )

    def _restaurar(self, respaldo: bytes) -> None:
        provisional = self.ruta_base.with_name(self.ruta_base.name + ".restaurar")
        provisional.write_bytes(respaldo)
        _soltar_conexion_de_la_peticion()
        _reemplazar(provisional, self.ruta_base)
        self._guardar_estado(pendiente=False)

    def _sobre_local(self, escritura: str) -> bytes:
        conexion = sqlite3.connect(self.ruta_base)
        try:
            esquema = conexion.execute("PRAGMA user_version").fetchone()[0]
            contenido = conexion.serialize()
        finally:
            conexion.close()
        cuenta = self.cuenta.info()
        return cifrado.sellar(contenido, {
            "esquema": esquema,
            "app": VERSION,
            "escrito": _ahora_utc(),
            "equipo": nombre_equipo(),
            "por": cuenta.get("correo", ""),
            "escritura": escritura,
        })

    def _subir(self) -> None:
        """Sube la base local con la condición «si nadie la cambió»."""
        sp = self.sp
        escritura = secrets.token_hex(8)
        sobre = self._sobre_local(escritura)
        base = self._persistente.get("etag", "")
        try:
            meta = self.graph.reemplazar(sp["drive_id"], sp["archivo_id"], sobre, si_coincide=base)
        except CambioConcurrente:
            raise
        except (SinConexion, ErrorGraph) as fallo:
            # Se cortó la conexión a mitad de la subida: puede que haya
            # llegado igual. La marca `escritura` de la cabecera lo dice.
            #
            meta = self._confirmar_escritura(escritura, base)
            if not meta:
                raise fallo
        self._guardar_estado(
            etag=meta.get("eTag", ""), ctag=meta.get("cTag", ""), subido=_ahora_utc(),
            escritura=escritura,
        )
        self.subidas += 1
        self._anotar_autor(meta)
        self._anotar(en_linea=True, error="", ultima_comprobacion=time.time())

    def _confirmar_escritura(self, escritura: str, base: str) -> dict | None:
        sp = self.sp
        try:
            meta = self.graph.elemento(sp["drive_id"], sp["archivo_id"])
            if meta.get("eTag") == base:
                return None
            inicio, _ = self.graph.descargar(sp["drive_id"], sp["archivo_id"], rango="bytes=0-4095")
            if cifrado.leer_cabecera(inicio).get("escritura") == escritura:
                log.info("La subida llegó aunque se perdió la respuesta.")
                return meta
        except Exception:
            return None
        return None

    @contextmanager
    def _turno(self):
        """En modo candado, espera su turno para guardar; si no, nada."""
        if self.sp.get("modo_concurrencia") != "candado":
            yield
            return
        # El candado es una carpeta: crearla «si no existe» es atómico.
        sp = self.sp
        propio = None
        limite = time.time() + 45
        while propio is None:
            try:
                propio = self.graph.crear_carpeta(
                    sp["drive_id"], sp["carpeta_sistema_id"], CANDADO_REMOTO, "fail"
                )
            except YaExiste:
                try:
                    ajeno = self.graph.hijo(sp["drive_id"], sp["carpeta_sistema_id"], CANDADO_REMOTO)
                    edad = _segundos_desde_iso(
                        ajeno.get("createdDateTime", ""), self.graph.ultima_fecha_servidor
                    )
                    if edad > EDAD_CANDADO_ABANDONADO:
                        log.warning("Candado abandonado de %.0f s: se libera.", edad)
                        self.graph.borrar(sp["drive_id"], ajeno["id"])
                        continue
                except NoEncontrado:
                    continue
                if time.time() > limite:
                    raise ErrorGraph(
                        "Otra computadora está guardando y tarda demasiado. Vuelva a intentar."
                    )
                time.sleep(random.uniform(0.4, 0.9))
        try:
            yield
        finally:
            try:
                self.graph.borrar(sp["drive_id"], propio["id"])
            except Exception:
                log.warning("No se pudo quitar el candado de guardado.")

    # -- Elegir la carpeta -----------------------------------------------------
    #
    def interpretar_enlace(self, texto: str) -> Enlace:
        return interpretar(texto)

    def resolver_carpeta(self, enlace: Enlace) -> dict:
        """El elemento de SharePoint al que apunta el enlace (debe ser carpeta)."""
        try:
            elemento = self.graph.resolver_enlace(enlace.codificado)
        except (NoEncontrado, ErrorGraph) as primero:
            if isinstance(primero, (SinPermiso,)) or enlace.tipo != "directo":
                raise
            elemento = self._resolver_por_sitio(enlace)
            if not elemento:
                raise
        if "folder" not in elemento:
            raise ErrorGraph(
                "Ese enlace es de un archivo, no de una carpeta. Copie el enlace de la carpeta."
            )
        return elemento

    def _resolver_por_sitio(self, enlace: Enlace) -> dict | None:
        """Plan B para direcciones directas: sitio → biblioteca → carpeta."""
        from urllib.parse import unquote, urlsplit

        ruta = unquote(urlsplit(enlace.para_api).path)
        partes = [p for p in ruta.split("/") if p]
        # /sites/Equipo/Biblioteca/carpeta…
        if len(partes) < 3 or partes[0] not in ("sites", "teams", "personal"):
            return None
        ruta_sitio = "/" + "/".join(partes[:2])
        try:
            sitio = self.graph.sitio_por_ruta(enlace.anfitrion, ruta_sitio)
            for biblioteca in self.graph.bibliotecas(sitio["id"]):
                raiz = unquote(urlsplit(biblioteca.get("webUrl", "")).path).rstrip("/")
                if ruta == raiz or ruta.startswith(raiz + "/"):
                    resto = ruta[len(raiz):].strip("/")
                    if not resto:
                        return self.graph.pedir(
                            "GET", f"/drives/{biblioteca['id']}/root"
                        ).json()
                    return self.graph.por_ruta(biblioteca["id"], resto)
        except (ErrorGraph, SinConexion):
            return None
        return None

    def examinar(self, elemento: dict) -> dict:
        """¿Qué hay en la carpeta? Busca los datos del sistema en ella o en
        su subcarpeta «Sistema de Registro de Horas».

        Devuelve {drive, carpeta, sistema (o None), archivo (o None)}.
        """
        drive = (elemento.get("parentReference") or {}).get("driveId") or elemento.get("driveId", "")
        if not drive:
            drive = ((elemento.get("remoteItem") or {}).get("parentReference") or {}).get("driveId", "")
        carpeta = elemento["id"]

        def buscar(padre, nombre):
            try:
                return self.graph.hijo(drive, padre, nombre)
            except NoEncontrado:
                return None

        # ¿Eligieron directamente la carpeta del sistema?
        archivo = buscar(carpeta, ARCHIVO_DATOS)
        if archivo:
            return {"drive": drive, "carpeta": elemento, "sistema": elemento, "archivo": archivo}
        # Si no, la subcarpeta con el nombre del sistema.
        sistema = buscar(carpeta, CARPETA_SISTEMA)
        archivo = buscar(sistema["id"], ARCHIVO_DATOS) if sistema else None
        return {"drive": drive, "carpeta": elemento, "sistema": sistema, "archivo": archivo}

    def recordar_carpeta(self, enlace: Enlace, examen: dict) -> None:
        carpeta = examen["carpeta"]
        sistema = examen.get("sistema") or {}
        archivo = examen.get("archivo") or {}
        sitio = (carpeta.get("parentReference") or {}).get("siteId") or ""
        self.configuracion.guardar_sharepoint(
            enlace=enlace.original,
            anfitrion=enlace.anfitrion,
            drive_id=examen["drive"],
            carpeta_id=carpeta["id"],
            nombre_carpeta=carpeta.get("name", ""),
            web_url=carpeta.get("webUrl", ""),
            sitio=sitio,
            carpeta_sistema_id=sistema.get("id") or None,
            archivo_id=archivo.get("id") or None,
        )
        # Otra carpeta, otros datos: la copia local ya no corresponde.
        if self._persistente.get("archivo_id") != archivo.get("id"):
            self._descartar_copia_local()
            self._guardar_estado(archivo_id=archivo.get("id", ""))
        self._anotar(falta_archivo=False, error="", solo_lectura="")

    def desconectar(self) -> None:
        """Olvida la carpeta (la cuenta de Microsoft se olvida aparte)."""
        with self.candado:
            self.configuracion.olvidar_sharepoint()
            self._descartar_copia_local()
            self._guardar_estado(archivo_id="", autor="", modificado="")

    def asegurar_carpeta_sistema(self) -> dict:
        sp = self.sp
        if sp.get("carpeta_sistema_id"):
            try:
                return self.graph.elemento(sp["drive_id"], sp["carpeta_sistema_id"])
            except NoEncontrado:
                pass
        try:
            sistema = self.graph.crear_carpeta(sp["drive_id"], sp["carpeta_id"], CARPETA_SISTEMA, "fail")
        except YaExiste:
            sistema = self.graph.hijo(sp["drive_id"], sp["carpeta_id"], CARPETA_SISTEMA)
        self.configuracion.guardar_sharepoint(carpeta_sistema_id=sistema["id"])
        try:
            self.graph.subir_nuevo(
                sp["drive_id"], sistema["id"], ARCHIVO_LEAME,
                TEXTO_LEAME.replace("\n", "\r\n").encode("utf-8-sig"), conflicto="replace",
            )
        except ErrorGraph:
            pass
        return sistema

    def probar_concurrencia(self) -> str:
        """¿SharePoint respeta «If-Match»? Lo prueba con un archivo temporal.

        Devuelve «condicional» (lo respeta: basta con la condición) o
        «candado» (no lo respeta: hay que hacer fila).
        """
        sp = self.sp
        nombre = f".prueba-{secrets.token_hex(4)}.tmp"
        drive, padre = sp["drive_id"], sp["carpeta_sistema_id"]
        prueba = self.graph.subir_nuevo(drive, padre, nombre, b"1", conflicto="replace")
        modo = "candado"
        try:
            segunda = self.graph.reemplazar(drive, prueba["id"], b"22", si_coincide=prueba["eTag"])
            try:
                self.graph.reemplazar(drive, prueba["id"], b"333", si_coincide=prueba["eTag"])
            except CambioConcurrente:
                modo = "condicional"
            if not segunda.get("eTag"):
                modo = "candado"
        finally:
            try:
                self.graph.borrar(drive, prueba["id"])
            except ErrorGraph:
                pass
        self.configuracion.guardar_sharepoint(modo_concurrencia=modo, probado_con=VERSION)
        log.info("Modo de guardado con SharePoint: %s", modo)
        return modo

    def publicar_base_inicial(self, contenido: bytes) -> None:
        """Sube la primera base a una carpeta que no tenía datos.

        Si otra computadora la creó en ese mismo momento, gana la suya y aquí
        se usa esa (`YaExiste`).
        """
        sp = self.sp
        with self.candado:
            self._colocar_base(contenido)
            escritura = secrets.token_hex(8)
            sobre = self._sobre_local(escritura)
            meta = self.graph.subir_nuevo(
                sp["drive_id"], sp["carpeta_sistema_id"], ARCHIVO_DATOS, sobre, conflicto="fail"
            )
            self.configuracion.guardar_sharepoint(archivo_id=meta["id"])
            self._guardar_estado(
                archivo_id=meta["id"], etag=meta.get("eTag", ""), ctag=meta.get("cTag", ""),
                subido=_ahora_utc(), escritura=escritura, pendiente=False,
            )
            self.subidas += 1
            self._anotar_autor(meta)
            self._anotar(en_linea=True, error="", falta_archivo=False,
                         ultima_comprobacion=time.time())

    # -- Excel y respaldos -----------------------------------------------------
    #
    def subir_excel(self, contenido: bytes) -> dict:
        sp = self.sp
        return self.graph.subir_nuevo(
            sp["drive_id"], sp["carpeta_sistema_id"], ARCHIVO_EXCEL, contenido, conflicto="replace"
        )

    def _carpeta_respaldos(self) -> dict:
        sp = self.sp
        try:
            return self.graph.hijo(sp["drive_id"], sp["carpeta_sistema_id"], CARPETA_RESPALDOS)
        except NoEncontrado:
            try:
                return self.graph.crear_carpeta(
                    sp["drive_id"], sp["carpeta_sistema_id"], CARPETA_RESPALDOS, "fail"
                )
            except YaExiste:
                return self.graph.hijo(sp["drive_id"], sp["carpeta_sistema_id"], CARPETA_RESPALDOS)

    def _respaldo_del_dia(self) -> None:
        """Una copia por día en `Respaldos/`, la hace la primera computadora
        que abre el programa ese día. Se conservan las últimas 30."""
        hoy = datetime.now().strftime("%Y-%m-%d")
        if self._respaldo_hecho == hoy or not self.hay_copia_local:
            return
        sp = self.sp
        nombre = f"respaldo-{hoy}.majerie"
        try:
            carpeta = self._carpeta_respaldos()
            try:
                self.graph.hijo(sp["drive_id"], carpeta["id"], nombre)
            except NoEncontrado:
                with self.candado:
                    sobre = self._sobre_local(secrets.token_hex(8))
                try:
                    self.graph.subir_nuevo(sp["drive_id"], carpeta["id"], nombre, sobre, "fail")
                    log.info("Respaldo del día subido: %s", nombre)
                except YaExiste:
                    pass
                self._podar_respaldos(carpeta["id"])
            self._respaldo_hecho = hoy
        except (ErrorGraph, SinConexion, NecesitaIniciarSesion) as fallo:
            log.info("No se pudo hacer el respaldo del día: %s", fallo)

    def _podar_respaldos(self, carpeta_id: str) -> None:
        sp = self.sp
        copias = sorted(
            (h for h in self.graph.hijos(sp["drive_id"], carpeta_id)
             if h.get("name", "").startswith("respaldo-") and "file" in h),
            key=lambda h: h["name"], reverse=True,
        )
        for sobrante in copias[RESPALDOS_QUE_SE_CONSERVAN:]:
            try:
                self.graph.borrar(sp["drive_id"], sobrante["id"])
            except ErrorGraph:
                pass

    def respaldos(self) -> list[dict]:
        """Las copias guardadas en SharePoint, de la más nueva a la más vieja."""
        sp = self.sp
        carpeta = self._carpeta_respaldos()
        copias = [
            {"id": h["id"], "nombre": h["name"], "tamano": h.get("size", 0),
             "fecha": h.get("lastModifiedDateTime", ""),
             "autor": ((h.get("lastModifiedBy") or {}).get("user") or {}).get("displayName", "")}
            for h in self.graph.hijos(sp["drive_id"], carpeta["id"])
            if "file" in h and h.get("name", "").endswith(".majerie")
        ]
        return sorted(copias, key=lambda c: c["nombre"], reverse=True)

    def copia_actual(self) -> bytes:
        """La base local, en su sobre, para descargarla como respaldo."""
        with self.candado:
            return self._sobre_local(secrets.token_hex(8))

    def restaurar(self, sobre: bytes) -> None:
        """Reemplaza los datos de SharePoint por los de una copia.

        Antes guarda la versión actual en `Respaldos/` como
        «antes-de-restaurar-…», por si hubo un error.
        """
        contenido, _cabecera = cifrado.abrir(sobre)
        sp = self.sp
        with self.candado:
            self.comprobar(forzar=True)
            carpeta = self._carpeta_respaldos()
            marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            self.graph.subir_nuevo(
                sp["drive_id"], carpeta["id"], f"antes-de-restaurar-{marca}.majerie",
                self._sobre_local(secrets.token_hex(8)), "rename",
            )
            # La copia entra como un guardado más, con la misma condición.
            self.guardar(lambda: self._colocar_base(contenido), forzar_subida=True)

    def bajar_respaldo(self, item: str) -> bytes:
        sobre, _ = self.graph.descargar(self.sp["drive_id"], item)
        cifrado.abrir(sobre)  # comprueba que se pueda leer
        return sobre


__all__ = ["Almacen", "SoloLectura", "FaltaConfigurar", "Bloqueado", "contador_cambios",
           "CARPETA_SISTEMA", "ARCHIVO_DATOS", "ARCHIVO_EXCEL"]
