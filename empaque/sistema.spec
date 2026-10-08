# -*- mode: python ; coding: utf-8 -*-
#
# Receta de PyInstaller del Sistema de Registro de Horas.
#
# Un solo archivo, sin consola, con el ícono de MAJERIE y la imagen de
# inicio mientras arranca. No se usa directamente: `empaquetar.py` la llama
# después de dejar la información de versión en `build/version.txt`.

from pathlib import Path

RAIZ = Path(SPECPATH).parent
NOMBRE = "Sistema de Registro de Horas"

datos = [
    (str(RAIZ / "app" / "templates"), "app/templates"),
    (str(RAIZ / "app" / "static"), "app/static"),
    (str(RAIZ / "app" / "esquema.sql"), "app"),
    (str(RAIZ / "app" / "manuales"), "app/manuales"),
]
# Identificador de la aplicación de Microsoft, si se compiló con uno.
if (RAIZ / "app" / "microsoft.json").is_file():
    datos.append((str(RAIZ / "app" / "microsoft.json"), "app"))

a = Analysis(
    [str(RAIZ / "arranque.py")],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=datos,
    hiddenimports=["waitress", "waitress.server"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "numpy", "PIL", "IPython"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

presentacion = Splash(
    str(RAIZ / "empaque" / "presentacion.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    always_on_top=False,
)

exe = EXE(
    pyz,
    a.scripts,
    presentacion,
    presentacion.binaries,
    a.binaries,
    a.datas,
    [],
    name=NOMBRE,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(RAIZ / "app" / "static" / "iconos" / "majerie.ico"),
    version=str(RAIZ / "build" / "version.txt"),
)
