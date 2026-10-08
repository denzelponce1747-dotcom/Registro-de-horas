"""Sistema de Registro de Horas · MAJERIE S.R.L — lo que corre al abrir el `.exe`.

Arranca el servidor interno y abre el sistema en una ventana propia del
navegador elegido (modo aplicación). No muestra consola: el programa
termina solo cuando se cierra la ventana. La primera vez pregunta con qué
navegador abrirse. Si ya estaba abierto, un segundo doble clic solo abre
otra ventana.

Los datos viven en el SharePoint de la empresa (`app/nube/`); esta
computadora guarda su configuración y una copia de trabajo en
`%LOCALAPPDATA%\\MAJERIE Registro de Horas`.

    python arranque.py                      uso normal
    python arranque.py --elegir-navegador   vuelve a preguntar el navegador
    python arranque.py --sin-ventana        solo el servidor (pruebas)
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

ESPERA_PRESENTACION = 25  # segundos máximos con la imagen de inicio
MUTEX = r"Local\MAJERIE-Registro-de-Horas"


def preparar_registro() -> None:
    """Sin consola, stdout y stderr no existen: todo va a un archivo."""
    from app.config import ARCHIVO_REGISTRO

    ARCHIVO_REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    try:
        if ARCHIVO_REGISTRO.is_file() and ARCHIVO_REGISTRO.stat().st_size > 2_000_000:
            os.replace(ARCHIVO_REGISTRO, ARCHIVO_REGISTRO.with_name("registro.anterior.log"))
    except OSError:
        pass
    archivo = open(ARCHIVO_REGISTRO, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = archivo
    logging.basicConfig(
        level=logging.INFO, handlers=[logging.StreamHandler(archivo)],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("waitress").setLevel(logging.WARNING)

    def sin_atrapar(tipo, valor, traza):
        logging.getLogger("majerie").critical("Error no controlado", exc_info=(tipo, valor, traza))

    sys.excepthook = sin_atrapar
    threading.excepthook = lambda a: sin_atrapar(a.exc_type, a.exc_value, a.exc_traceback)


def cerrar_presentacion() -> None:
    """Quita la imagen de inicio que muestra el .exe mientras se descomprime."""
    try:
        import pyi_splash

        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass


def tomar_mutex() -> bool:
    """True si esta es la primera copia. El mutex vive tanto como el proceso."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        manija = kernel32.CreateMutexW(None, False, MUTEX)
        ya_existia = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        tomar_mutex.manija = manija  # que no se libere antes de tiempo
        return not ya_existia
    except (AttributeError, OSError):
        return True


def instancia_activa(espera: float = 0.0) -> str | None:
    """Dirección del programa si ya está abierto, o None."""
    from app.config import ARCHIVO_INSTANCIA, ID_APP

    limite = time.monotonic() + espera
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while True:
        try:
            url = json.loads(ARCHIVO_INSTANCIA.read_text(encoding="utf-8"))["url"]
            with abridor.open(url + "estado", timeout=1.5) as respuesta:
                if json.load(respuesta).get("app") == ID_APP:
                    return url
        except Exception:
            pass
        if time.monotonic() >= limite:
            return None
        time.sleep(0.5)


def limpiar_temporales_viejos() -> None:
    """Borra las copias descomprimidas que dejaron cierres bruscos.

    El `.exe` se descomprime en una carpeta `_MEI…` temporal y la borra al
    cerrar. Si Windows lo mata (apagado de golpe, Administrador de tareas),
    la carpeta queda. Aquí se borran solo las de este programa —se
    reconocen por su contenido— que tengan más de una hora y no estén en uso.
    """
    propia = os.path.normcase(getattr(sys, "_MEIPASS", ""))
    base = Path(tempfile.gettempdir())
    try:
        candidatas = [c for c in base.glob("_MEI*") if c.is_dir()]
    except OSError:
        return
    for carpeta in candidatas:
        try:
            if os.path.normcase(str(carpeta)) == propia:
                continue
            if not (carpeta / "app" / "esquema.sql").is_file():
                continue
            if not (carpeta / "app" / "static" / "marca").is_dir():
                continue
            if time.time() - carpeta.stat().st_mtime < 3600:
                continue
            shutil.rmtree(carpeta, ignore_errors=True)
        except OSError:
            continue


def elegir_navegador(configuracion, lista, forzar: bool):
    """Navegador para la ventana. La primera vez (o si ya no está) pregunta."""
    from app.escritorio import dialogos, navegadores

    actual = navegadores.resolver(configuracion, lista)
    if actual and not forzar:
        return actual, True
    cerrar_presentacion()
    elegido = dialogos.elegir_navegador(lista, actual or navegadores.sugerido(lista))
    if elegido is None:
        return None, False
    if not elegido.get("ruta"):
        return None, True
    if elegido["clave"] == "otro":
        configuracion.guardar(navegador="otro", navegador_ruta=elegido["ruta"])
    else:
        configuracion.guardar(navegador=elegido["clave"])
    return elegido, True


def puerto_libre(preferido: int) -> int:
    """El puerto preferido si está libre; si no, el siguiente que lo esté."""
    for candidato in [preferido, *range(preferido + 1, preferido + 40)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prueba:
            try:
                prueba.bind(("127.0.0.1", candidato))
                return candidato
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prueba:
        prueba.bind(("127.0.0.1", 0))
        return prueba.getsockname()[1]


def crear_servidor(aplicacion, puerto: int):
    """Waitress escuchando SOLO en esta computadora (IPv4 y, si hay, IPv6)."""
    from waitress.server import create_server

    direcciones = [f"127.0.0.1:{puerto}"]
    if socket.has_ipv6:
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as prueba:
                prueba.bind(("::1", puerto))
            direcciones.append(f"[::1]:{puerto}")
        except OSError:
            pass
    return create_server(aplicacion, listen=" ".join(direcciones), threads=6,
                         ident="MAJERIE", channel_timeout=120)


def vigilar_navegador(proceso, vida) -> None:
    inicio = time.monotonic()
    proceso.wait()
    # Si el proceso termina enseguida, el navegador ya estaba abierto y le
    # pasó la ventana a otro proceso: entonces no se sabe cuándo se cierra.
    if time.monotonic() - inicio > 8:
        logging.getLogger("majerie").info("El navegador se cerró.")
        vida.adios(None)


def main() -> int:
    analizador = argparse.ArgumentParser(description="Sistema de Registro de Horas")
    analizador.add_argument("--sin-ventana", action="store_true", help="solo el servidor")
    analizador.add_argument("--elegir-navegador", action="store_true",
                            help="vuelve a preguntar con qué navegador abrirse")
    analizador.add_argument("--puerto", type=int, default=None)
    argumentos, _resto = analizador.parse_known_args()

    preparar_registro()
    log = logging.getLogger("majerie")

    from app.config import (
        ARCHIVO_CUENTA,
        ARCHIVO_INSTANCIA,
        CARPETA_VENTANA,
        NOMBRE_APP,
        VERSION,
        configuracion,
    )
    from app.escritorio import dialogos, navegadores

    dialogos.preparar_dpi()
    log.info("%s %s — inicio", NOMBRE_APP, VERSION)
    ajustes = configuracion()

    # Si ya está abierto, solo se abre otra ventana del que ya corre.
    if not argumentos.sin_ventana and not tomar_mutex():
        url = instancia_activa(espera=30)
        if url:
            navegadores.abrir_ventana(url, navegadores.resolver(ajustes), CARPETA_VENTANA)
        cerrar_presentacion()
        return 0

    threading.Thread(target=limpiar_temporales_viejos, name="limpieza", daemon=True).start()

    # El navegador se elige antes de levantar nada.
    navegador = None
    if not argumentos.sin_ventana:
        navegador, seguir = elegir_navegador(ajustes, navegadores.detectar(),
                                             argumentos.elegir_navegador)
        if not seguir:
            log.info("Se cerró la bienvenida sin elegir navegador.")
            return 0

    # La aplicación, con los datos de SharePoint y su ciclo de vida.
    from app import crear_app
    from app.escritorio.vida import Vida
    from app.nube.almacen import Almacen
    from app.nube.microsoft import Cuenta

    cuenta = Cuenta(ARCHIVO_CUENTA)
    almacen = Almacen(ajustes, cuenta)
    almacen.preparar()
    vida = Vida()
    aplicacion = crear_app(ajustes, almacen, vida)

    puerto = puerto_libre(argumentos.puerto or int(ajustes["puerto"] or 8642))
    try:
        servidor = crear_servidor(aplicacion, puerto)
    except OSError as fallo:
        cerrar_presentacion()
        dialogos.avisar_error(
            NOMBRE_APP, f"No se pudo iniciar el sistema en esta computadora.\n\n{fallo}"
        )
        return 1

    url = f"http://localhost:{puerto}/"
    ARCHIVO_INSTANCIA.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")
    threading.Thread(target=servidor.run, name="servidor", daemon=True).start()
    almacen.arrancar_vigilante()
    log.info("Sistema en %s", url)

    inicio = time.monotonic()
    if argumentos.sin_ventana:
        cerrar_presentacion()
        print(url, flush=True)
    else:
        proceso = navegadores.abrir_ventana(url, navegador, CARPETA_VENTANA)
        if proceso is not None:
            threading.Thread(target=vigilar_navegador, args=(proceso, vida),
                             name="navegador", daemon=True).start()

    presentacion = True
    try:
        while argumentos.sin_ventana or not vida.debe_cerrar():
            if presentacion and (vida.primer_latido.is_set()
                                 or time.monotonic() - inicio > ESPERA_PRESENTACION):
                cerrar_presentacion()
                presentacion = False
            time.sleep(0.4)
    except KeyboardInterrupt:
        pass

    log.info("Se cerró la última ventana; terminando.")
    cerrar_presentacion()
    almacen.detener_vigilante()
    # El Excel de SharePoint puede estar a medio subir: se le da un momento.
    excel = aplicacion.config.get("EXCEL")
    if excel is not None:
        try:
            excel.terminar(espera=8)
        except Exception:
            pass
    try:
        servidor.close()
    except Exception:
        pass
    try:
        if json.loads(ARCHIVO_INSTANCIA.read_text(encoding="utf-8")).get("pid") == os.getpid():
            ARCHIVO_INSTANCIA.unlink()
    except (OSError, ValueError):
        pass
    logging.shutdown()
    # Salida inmediata: los hilos del servidor y del navegador no tienen
    # nada más que hacer.
    os._exit(0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.getLogger("majerie").exception("Fallo al arrancar")
        try:
            from app.escritorio.dialogos import avisar_error

            avisar_error(
                "Sistema de Registro de Horas",
                "El sistema no pudo arrancar. El detalle quedó en el registro:\n"
                "%LOCALAPPDATA%\\MAJERIE Registro de Horas\\registro.log",
            )
        except Exception:
            pass
        sys.exit(1)
