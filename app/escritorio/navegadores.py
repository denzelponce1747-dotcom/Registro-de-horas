"""Navegadores instalados y ventana del programa.

La interfaz se abre en una ventana propia, sin pestañas ni barra de
direcciones, con el modo «aplicación» (--app) de los navegadores basados en
Chromium: Chrome, Edge, Brave, Vivaldi y Chromium. Firefox y Opera no tienen
ese modo, así que no se ofrecen. Edge viene con Windows 10 y 11: siempre hay al
menos uno.

Cada navegador usa un perfil propio dentro de los datos del programa. Así no se
mezcla con el de la persona (sus pestañas, extensiones y sesiones quedan
intactas) y se sabe cuándo se cerró la ventana: el proceso del navegador
termina con ella.

Es el mismo módulo que usa Licitaciones SICOP, probado en varias
computadoras.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

log = logging.getLogger("majerie.ventana")

# (clave, nombre, ejecutable, rutas relativas a Archivos de programa o a
# LOCALAPPDATA, prefijo del ProgId con que Windows lo registra)
CONOCIDOS = (
    ("chrome", "Google Chrome", "chrome.exe", (r"Google\Chrome\Application\chrome.exe",), "ChromeHTML"),
    ("edge", "Microsoft Edge", "msedge.exe", (r"Microsoft\Edge\Application\msedge.exe",), "MSEdgeHTM"),
    ("brave", "Brave", "brave.exe", (r"BraveSoftware\Brave-Browser\Application\brave.exe",), "BraveHTML"),
    ("vivaldi", "Vivaldi", "vivaldi.exe", (r"Vivaldi\Application\vivaldi.exe",), "VivaldiHTM"),
    ("chromium", "Chromium", "chrome.exe", (r"Chromium\Application\chrome.exe",), "ChromiumHTM"),
)

# Ejecutables de navegadores basados en Chromium que aceptan --app y
# --user-data-dir (además de los conocidos, los que aparezcan en el registro
# con alguno de estos nombres).
#
#
#
EJECUTABLES_CHROMIUM = {"chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "chromium.exe", "thorium.exe"}
# Si el predeterminado no es compatible, se propone el primero de estos.
ORDEN_RESPALDO = ("edge", "chrome", "brave", "vivaldi", "chromium")


# -- Registro de Windows -------------------------------------------------------
#
def _registro(raiz, clave, valor=None):
    try:
        import winreg

        with winreg.OpenKey(raiz, clave) as k:
            return winreg.QueryValueEx(k, valor or "")[0]
    except (ImportError, OSError):
        return None


def _subclaves(raiz, clave):
    try:
        import winreg

        with winreg.OpenKey(raiz, clave) as k:
            i = 0
            while True:
                try:
                    yield winreg.EnumKey(k, i)
                except OSError:
                    return
                i += 1
    except (ImportError, OSError):
        return


def _ruta_de_orden(orden):
    """Ruta del .exe en una orden del registro: «"C:\\…\\brave.exe" --flag»."""
    if not orden:
        return None
    orden = str(orden).strip()
    m = re.match(r'"([^"]+)"', orden) or re.match(r"(\S+\.exe)", orden, re.I)
    ruta = m.group(1) if m else orden
    return ruta if os.path.isfile(ruta) else None


def _raices():
    try:
        import winreg

        return (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    except ImportError:
        return ()


def progid_predeterminado():
    """ProgId del navegador predeterminado de Windows («BraveHTML»…), o ''."""
    try:
        import winreg

        clave = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        # La elección de la persona; sin ella, Windows usa Edge.
        return _registro(winreg.HKEY_CURRENT_USER, clave, "ProgId") or ""
    except ImportError:
        return ""


# -- Detección -----------------------------------------------------------------
#
def _ubicar_conocido(relativas):
    bases = [os.environ.get(v) for v in
             ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA")]
    for base in filter(None, bases):
        for relativa in relativas:
            ruta = os.path.join(base, relativa)
            if os.path.isfile(ruta):
                return ruta
    return None


def detectar():
    """Navegadores compatibles instalados: [{clave, nombre, ruta, predeterminado}]."""
    encontrados = {}
    for clave, nombre, exe, relativas, _ in CONOCIDOS:
        ruta = _ubicar_conocido(relativas)
        if ruta:
            encontrados[clave] = {"clave": clave, "nombre": nombre, "ruta": ruta}

    # Los que se registraron en Windows como navegador (instalados en otra
    # carpeta, o basados en Chromium con otro nombre).
    for raiz in _raices():
        base = r"SOFTWARE\Clients\StartMenuInternet"
        for sub in list(_subclaves(raiz, base)):
            ruta = _ruta_de_orden(_registro(raiz, f"{base}\\{sub}\\shell\\open\\command"))
            if not ruta:
                continue
            exe = os.path.basename(ruta).lower()
            if exe not in EJECUTABLES_CHROMIUM:
                continue
            normalizada = os.path.normcase(os.path.abspath(ruta))
            if any(os.path.normcase(os.path.abspath(n["ruta"])) == normalizada
                   for n in encontrados.values()):
                continue
            clave = next((c for c, _, e, rel, _ in CONOCIDOS
                          if e == exe and any(normalizada.endswith(os.path.normcase(r)) for r in rel)),
                         None)
            if clave and clave in encontrados:
                continue
            nombre = _registro(raiz, f"{base}\\{sub}") or sub
            clave = clave or "reg-" + re.sub(r"[^a-z0-9]+", "-", sub.lower()).strip("-")
            encontrados[clave] = {"clave": clave, "nombre": str(nombre), "ruta": ruta}

    progid = progid_predeterminado().lower()
    lista = []
    for clave, nombre, _, _, prefijo in CONOCIDOS:
        if clave in encontrados:
            encontrados[clave]["predeterminado"] = bool(progid) and progid.startswith(prefijo.lower())
            lista.append(encontrados.pop(clave))
    for resto in encontrados.values():
        resto["predeterminado"] = False
        lista.append(resto)
    return lista


def sugerido(lista):
    """El que conviene proponer: el predeterminado de Windows si es compatible."""
    for n in lista:
        if n.get("predeterminado"):
            return n
    for clave in ORDEN_RESPALDO:
        for n in lista:
            if n["clave"] == clave:
                return n
    return lista[0] if lista else None


def resolver(config, lista=None):
    """Navegador guardado en la configuración, si sigue instalado; si no, None."""
    clave = config["navegador"]
    if not clave:
        return None
    if clave == "otro":
        ruta = config["navegador_ruta"]
        if ruta and os.path.isfile(ruta):
            return {"clave": "otro", "nombre": Path(ruta).stem, "ruta": ruta}
        return None
    for n in lista if lista is not None else detectar():
        if n["clave"] == clave:
            return n
    return None


def es_ejecutable_valido(ruta):
    return bool(ruta) and os.path.isfile(ruta) and ruta.lower().endswith(".exe")


# -- Ventana -------------------------------------------------------------------
#
def _actualizar_json(ruta, cambios):
    """Mezcla `cambios` (diccionarios anidados) en un archivo JSON del perfil."""
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if not isinstance(datos, dict):
            datos = {}
    except (OSError, ValueError):
        datos = {}

    def mezclar(destino, origen):
        cambio = False
        for clave, valor in origen.items():
            if isinstance(valor, dict):
                if not isinstance(destino.get(clave), dict):
                    destino[clave] = {}
                    cambio = True
                cambio = mezclar(destino[clave], valor) or cambio
            elif destino.get(clave) != valor:
                destino[clave] = valor
                cambio = True
        return cambio

    if not mezclar(datos, cambios):
        return
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f)
    except OSError:
        pass


def _preparar_perfil(perfil):
    """Que la ventana se vea como una aplicación y no como un navegador recién estrenado.

    - El navegador no sigue corriendo escondido al cerrar la ventana.
    - Brave no muestra su aviso de estadísticas anónimas (P3A) en cada perfil nuevo.
    - Si la computadora se apagó de golpe, no aparece «¿Restaurar páginas?».
    """
    _actualizar_json(os.path.join(perfil, "Local State"), {
        "background_mode": {"enabled": False},
        "brave": {"p3a": {"enabled": False, "notice_acknowledged": True},
                  "stats": {"reporting_enabled": False}},
    })
    _actualizar_json(os.path.join(perfil, "Default", "Preferences"), {
        "profile": {"exit_type": "Normal", "exited_cleanly": True}})


# Tamaño de la ventana según la pantalla.
def _area_de_trabajo():
    """(x, y, ancho, alto) del escritorio sin la barra de tareas, en píxeles lógicos."""
    try:
        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        r = RECT()
        if not user32.SystemParametersInfoW(48, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
            raise OSError
        try:
            escala = user32.GetDpiForSystem() / 96.0
        except AttributeError:
            escala = 1.0
        escala = escala if escala > 0 else 1.0
        return (r.left / escala, r.top / escala,
                (r.right - r.left) / escala, (r.bottom - r.top) / escala)
    except (AttributeError, OSError):
        return (0, 0, 1366, 728)


def geometria():
    """Tamaño y posición de una ventana cómoda, centrada en el escritorio."""
    x, y, ancho_area, alto_area = _area_de_trabajo()
    ancho = int(min(1380, ancho_area - 40))
    alto = int(min(940, alto_area - 12))
    return ancho, alto, int(x + (ancho_area - ancho) / 2), int(y + (alto_area - alto) / 2)


def argumentos(ruta, url, perfil):
    ancho, alto, x, y = geometria()
    return [
        ruta, f"--app={url}", f"--user-data-dir={perfil}",
        f"--window-size={ancho},{alto}", f"--window-position={x},{y}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-sync", "--disable-extensions", "--disable-default-apps",
        # Sin la barra de traducción y sin que Windows «congele» la ventana
        # cuando queda tapada por otra.
        "--disable-features=Translate,CalculateNativeWinOcclusion",
        "--disable-backgrounding-occluded-windows",
        # Sin el aviso de «el navegador no se cerró correctamente».
        "--hide-crash-restore-bubble", "--disable-session-crashed-bubble",
    ]


def abrir_ventana(url, navegador, carpeta_perfiles):
    """Abre la interfaz. Devuelve el proceso del navegador, o None si no hay cómo vigilarlo."""
    if navegador and es_ejecutable_valido(navegador.get("ruta")):
        carpeta = re.sub(r"[^a-z0-9-]+", "-", navegador["clave"].lower())
        perfil = os.path.join(str(carpeta_perfiles), carpeta)
        os.makedirs(perfil, exist_ok=True)
        _preparar_perfil(perfil)
        try:
            # Deja que la ventana nueva pase al frente aunque el programa
            # se haya abierto desde otra ventana.
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except (AttributeError, OSError):
            pass
        log.info("Ventana con %s (%s)", navegador["nombre"], navegador["ruta"])
        try:
            return subprocess.Popen(
                argumentos(navegador["ruta"], url, perfil),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError:
            log.warning("No se pudo abrir %s", navegador["ruta"], exc_info=True)
    # Sin navegador compatible (o si falló): una pestaña del navegador
    # predeterminado. No se puede saber cuándo se cierra.
    log.info("Abriendo en el navegador predeterminado: %s", url)
    webbrowser.open(url)
    return None


if __name__ == "__main__":
    for n in detectar():
        print(n, file=sys.stderr)
