"""Cada petición que cambia datos se guarda en SharePoint.

Envuelve la aplicación WSGI. Las lecturas pasan directo, solo tomando el
candado del almacén mientras usan la base. Las peticiones que cambian algo
(los formularios POST) se ejecutan dentro de `Almacen.guardar`:

1. se trae la última versión de SharePoint,
2. corre la petición de verdad, como siempre,
3. si cambió algo, se sube con la condición «si nadie la cambió»,
4. si otra computadora se adelantó, se deshace y se repite desde el paso 1.

Para poder repetirla, el cuerpo de la petición se lee una vez y se guarda.
La respuesta solo sale hacia el navegador cuando el cambio ya está en
SharePoint: si la persona ve «Registro guardado», es que se guardó de verdad.

Si no se puede guardar (sin internet, sesión de Microsoft vencida…), la
petición se repite con una marca y la aplicación la corta con un aviso claro
en vez de ejecutarla.
"""

from __future__ import annotations

import io
import logging

from .almacen import SoloLectura
from .cifrado import ArchivoIlegible
from .microsoft import ErrorMicrosoft

log = logging.getLogger("majerie.nube")

# Rutas que no leen ni escriben la base: pasan sin más (archivos, el estado
# de la sincronización, el cierre de la ventana…).
LIBRES = ("/static/", "/estado", "/adios", "/favicon.ico", "/marca/",
          "/ajustes/navegador/buscar")

# Formularios que solo tocan cosas de esta computadora (la sesión, el tema,
# el navegador…): se ejecutan sin traer ni subir nada. Si de todos modos
# cambian la base, se sube igual (ver `_por_si_acaso`).
#
SIN_SUBIDA = ("/ingresar", "/identidad", "/salir", "/bienvenida", "/conexion/",
              "/ajustes/tema", "/ajustes/navegador", "/ajustes/excel",
              "/ajustes/avanzado", "/ajustes/carpeta", "/ajustes/desconectar",
              "/ajustes/sincronizar", "/ajustes/respaldos/restaurar")

# Clave del entorno WSGI con el aviso que debe ver la persona cuando un
# cambio no se pudo guardar.
MARCA_AVISO = "majerie.aviso_nube"


class _Captura:
    def __init__(self):
        self.estado = "500 INTERNAL SERVER ERROR"
        self.cabeceras = []

    def __call__(self, estado, cabeceras, exc_info=None):
        self.estado = estado
        self.cabeceras = list(cabeceras)
        return lambda _datos: None


class Sincronizacion:
    def __init__(self, wsgi, obtener_almacen):
        self.wsgi = wsgi
        self.obtener_almacen = obtener_almacen

    def _correr(self, entorno) -> tuple[str, list, bytes]:
        captura = _Captura()
        respuesta = self.wsgi(entorno, captura)
        try:
            cuerpo = b"".join(respuesta)
        finally:
            cerrar = getattr(respuesta, "close", None)
            if cerrar:
                cerrar()
        return captura.estado, captura.cabeceras, cuerpo

    @staticmethod
    def _entregar(iniciar, estado, cabeceras, cuerpo):
        iniciar(estado, cabeceras)
        return [cuerpo]

    def __call__(self, entorno, iniciar):
        almacen = self.obtener_almacen()
        ruta = entorno.get("PATH_INFO", "") or "/"
        if almacen is None or ruta.startswith(LIBRES):
            return self.wsgi(entorno, iniciar)

        metodo = entorno.get("REQUEST_METHOD", "GET").upper()
        if metodo in ("GET", "HEAD", "OPTIONS"):
            with almacen.candado:
                return self._entregar(iniciar, *self._correr(entorno))

        try:
            largo = int(entorno.get("CONTENT_LENGTH") or 0)
        except ValueError:
            largo = 0
        cuerpo = entorno["wsgi.input"].read(largo) if largo > 0 else b""

        def copia_del_entorno(**extra):
            nuevo = dict(entorno)
            nuevo["wsgi.input"] = io.BytesIO(cuerpo)
            nuevo["CONTENT_LENGTH"] = str(len(cuerpo))
            nuevo.update(extra)
            return nuevo

        if ruta.startswith(SIN_SUBIDA):
            with almacen.candado:
                return self._entregar(iniciar, *self._por_si_acaso(almacen, copia_del_entorno()))

        resultado = {}

        def ejecutar():
            resultado["respuesta"] = self._correr(copia_del_entorno())
            return resultado["respuesta"]

        try:
            almacen.guardar(ejecutar)
        except (SoloLectura, ErrorMicrosoft, ArchivoIlegible) as fallo:
            mensaje = getattr(fallo, "mensaje", "") or str(fallo)
            log.info("No se guardó %s %s: %s", metodo, ruta, mensaje)
            with almacen.candado:
                return self._entregar(
                    iniciar, *self._correr(copia_del_entorno(**{MARCA_AVISO: mensaje}))
                )
        return self._entregar(iniciar, *resultado["respuesta"])

    def _por_si_acaso(self, almacen, entorno):
        """Un formulario «de los que no guardan» que igual cambió la base:
        se sube, para que el cambio no quede solo en esta computadora."""
        from .almacen import contador_cambios

        antes = contador_cambios(almacen.ruta_base)
        subidas = almacen.subidas
        respuesta = self._correr(entorno)
        if almacen.configurado and almacen.subidas == subidas:
            if contador_cambios(almacen.ruta_base) != antes:
                log.warning("%s cambió la base sin pasar por el guardado.", entorno.get("PATH_INFO"))
                try:
                    almacen.guardar(lambda: None, forzar_subida=True)
                except Exception:
                    log.exception("No se pudo subir el cambio imprevisto")
        return respuesta
