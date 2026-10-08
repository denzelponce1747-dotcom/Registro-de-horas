"""El Excel de SharePoint, siempre al día sin que nadie lo genere a mano.

Cada vez que esta computadora guarda un cambio en SharePoint —alguien
registró horas, pidió vacaciones, la administración aprobó algo—, se vuelve
a armar el reporte general completo y se sube a la carpeta del sistema, con
el nombre «Registro de Horas MAJERIE (se actualiza solo).xlsx». Como vive en
SharePoint, se puede abrir desde el celular, desde la web o desde cualquier
computadora de la empresa, aunque nadie tenga el programa abierto.

Tres decisiones que importan:

1. **No se regenera en cada guardado.** Armar el libro entero cuesta. Se
   espera a que pase un rato sin cambios y se sube una sola vez.
2. **Lo sube la computadora que hizo el cambio.** Así no hay diez
   computadoras subiendo el mismo Excel a la vez.
3. **Si alguien lo tiene abierto y SharePoint lo bloquea, se reintenta**
   más tarde en vez de perder la actualización.

El Excel es **solo de lectura**: lo que alguien escriba encima se pierde en
la siguiente actualización. Por eso el archivo lo dice en su propio nombre.
"""

from __future__ import annotations

import io
import logging
import threading
import time

log = logging.getLogger("majerie.excel")


class _UsuarioTodoElEquipo:
    """La instantánea se carga con la mirada de la administración.

    No es una sesión de verdad: solo le dice a la capa de datos que cargue el
    equipo completo, no lo de una sola persona.
    """

    id = "adm-majerie"
    role = "administrador"


class ExcelAutomatico:
    # Segundos sin cambios antes de armar y subir el libro.
    ESPERA_TRAS_CAMBIO = 15.0
    # Si la subida falla (sin conexión, archivo bloqueado), se reintenta.
    ESPERA_TRAS_FALLO = 90.0
    # Al abrir el programa, se revisa que el Excel exista.
    ESPERA_INICIAL = 30.0

    def __init__(self, aplicacion, almacen, arrancar: bool = True):
        self.aplicacion = aplicacion
        self.almacen = almacen
        self._aviso = threading.Event()
        self._ocupado = threading.Lock()
        self._hilo = None
        self.estado = {"ultima_subida": 0.0, "ultimo_error": "", "pendiente": False, "url": ""}
        almacen.despues_de_guardar.append(self.marcar_cambio)
        if arrancar:
            self._hilo = threading.Thread(target=self._vigilar, name="excel-automatico", daemon=True)
            self._hilo.start()

    @property
    def activo(self) -> bool:
        return bool(self.aplicacion.config["CONFIGURACION"]["excel_automatico"])

    def marcar_cambio(self) -> None:
        """Hay algo nuevo que volcar al Excel."""
        self.estado["pendiente"] = True
        self._aviso.set()

    def _vigilar(self) -> None:
        # Si en el primer rato no hubo cambios, se revisa que el Excel exista.
        if not self._aviso.wait(self.ESPERA_INICIAL):
            self._crear_si_falta()
        while True:
            self._aviso.wait()
            # Se deja pasar un rato: varios cambios seguidos, una sola subida.
            time.sleep(self.ESPERA_TRAS_CAMBIO)
            self._aviso.clear()
            if not self.activo or not self.estado["pendiente"]:
                continue
            if not self.subir():
                time.sleep(self.ESPERA_TRAS_FALLO)
                self._aviso.set()

    def _crear_si_falta(self) -> None:
        almacen = self.almacen
        if not self.activo or not almacen.configurado or not almacen.hay_copia_local:
            return
        from .nube.almacen import ARCHIVO_EXCEL
        from .nube.graph import NoEncontrado

        sp = almacen.sp
        try:
            meta = almacen.graph.hijo(sp["drive_id"], sp["carpeta_sistema_id"], ARCHIVO_EXCEL)
            self.estado["url"] = meta.get("webUrl", "")
        except NoEncontrado:
            self.estado["pendiente"] = True
            self.subir()
        except Exception as fallo:
            log.info("No se pudo revisar el Excel: %s", fallo)

    def armar_libro(self) -> bytes:
        """El reporte general completo, en memoria."""
        from .datos import cargar_instantanea
        from .lib.estadisticas import con_horas
        from .reportes.general import reporte_general

        with self.almacen.candado, self.aplicacion.app_context():
            instantanea = cargar_instantanea(_UsuarioTodoElEquipo())
            registros = con_horas(instantanea.entries, instantanea.lunches)
            contexto = {
                "entries": registros,
                "allEntries": registros,
                "projects": instantanea.projects,
                "users": instantanea.users,
                "settings": instantanea.collaboratorSettings,
                # Mismo contexto que arma la pantalla de reportes, sin
                # filtros: todos los registros del sistema.
                "projectRates": instantanea.projectRates,
                "lunches": instantanea.lunches,
                "absences": instantanea.absences,
                "period": instantanea.period,
                "filtersLabel": "Todos los registros del sistema",
                "onlyUserId": None,
            }
            libro, _nombre = reporte_general(contexto)
        memoria = io.BytesIO()
        libro.save(memoria)
        return memoria.getvalue()

    def subir(self) -> bool:
        """Arma el libro y lo sube. False si hay que reintentar más tarde."""
        from .nube.graph import Bloqueado

        if not self._ocupado.acquire(blocking=False):
            return True
        try:
            almacen = self.almacen
            if not almacen.configurado or not almacen.hay_copia_local:
                return True
            self.estado["pendiente"] = False
            try:
                contenido = self.armar_libro()
                meta = almacen.subir_excel(contenido)
            except Bloqueado:
                self.estado["pendiente"] = True
                self.estado["ultimo_error"] = "SharePoint tenía el Excel abierto; se reintentará."
                return False
            except Exception as fallo:
                self.estado["pendiente"] = True
                self.estado["ultimo_error"] = f"{type(fallo).__name__}: {fallo}"
                log.info("No se pudo subir el Excel: %s", fallo)
                return False
            self.estado["ultima_subida"] = time.time()
            self.estado["ultimo_error"] = ""
            self.estado["url"] = meta.get("webUrl", "") or self.estado["url"]
            log.info("Excel actualizado en SharePoint.")
            return True
        finally:
            self._ocupado.release()

    def terminar(self, espera: float = 8.0) -> None:
        """Al cerrar el programa: se deja terminar la subida en curso y, si
        quedó una actualización pendiente, se sube."""
        if not self.activo:
            return
        limite = time.monotonic() + espera
        if self._ocupado.acquire(timeout=espera):
            self._ocupado.release()
        if not self.estado["pendiente"]:
            return
        hilo = threading.Thread(target=self.subir, daemon=True)
        hilo.start()
        hilo.join(max(0.0, limite - time.monotonic()))
