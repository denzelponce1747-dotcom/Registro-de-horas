"""Compila el ejecutable de Windows y arma la carpeta que se entrega.

    python -m pip install -r requirements-empaque.txt
    python empaquetar.py             compila y arma la entrega
    python empaquetar.py --version   solo dice la versión

Deja en `dist/`:

- `Sistema de Registro de Horas/` con el .exe, el Manual de Usuario (PDF y
  HTML) y el LÉAME, lista para copiar a cada computadora;
- `Sistema-de-Registro-de-Horas-<versión>.zip` con esa misma carpeta.

Si la variable de entorno `MAJERIE_CLIENTE_ID` trae el identificador de la
aplicación registrada en Microsoft Entra ID, queda dentro del programa
(`app/microsoft.json`) y nadie tiene que escribirlo en Ajustes. Sin ella,
el programa lo pide la primera vez, como hasta ahora.

Solo funciona en Windows: PyInstaller compila para el sistema en que corre.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
NOMBRE = "Sistema de Registro de Horas"
EMPRESA = "MAJERIE S.R.L"


def version() -> str:
    texto = (RAIZ / "app" / "config.py").read_text(encoding="utf-8")
    encontrada = re.search(r'^VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', texto, re.M)
    if not encontrada:
        sys.exit("No se encontró VERSION en app/config.py")
    return ".".join(encontrada.groups())


def escribir_version(numero: str) -> Path:
    """La ficha de versión que Windows muestra en Propiedades › Detalles."""
    partes = tuple(int(p) for p in numero.split(".")) + (0,)
    ficha = f"""# Generado por empaquetar.py
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={partes},
    prodvers={partes},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040A04B0', [
        StringStruct('CompanyName', '{EMPRESA}'),
        StringStruct('FileDescription', '{NOMBRE}'),
        StringStruct('FileVersion', '{numero}'),
        StringStruct('InternalName', '{NOMBRE}'),
        StringStruct('LegalCopyright', '{EMPRESA}'),
        StringStruct('OriginalFilename', '{NOMBRE}.exe'),
        StringStruct('ProductName', '{NOMBRE}'),
        StringStruct('ProductVersion', '{numero}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1034, 1200])])
  ]
)
"""
    destino = RAIZ / "build" / "version.txt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(ficha, encoding="utf-8")
    return destino


def compilar() -> Path:
    import PyInstaller.__main__

    PyInstaller.__main__.run([
        str(RAIZ / "empaque" / "sistema.spec"),
        "--noconfirm",
        "--clean",
        "--distpath", str(RAIZ / "dist"),
        "--workpath", str(RAIZ / "build" / "pyinstaller"),
    ])
    exe = RAIZ / "dist" / f"{NOMBRE}.exe"
    if not exe.is_file():
        sys.exit("PyInstaller no dejó el ejecutable.")
    return exe


def armar_entrega(exe: Path, numero: str) -> Path:
    carpeta = RAIZ / "dist" / NOMBRE
    shutil.rmtree(carpeta, ignore_errors=True)
    carpeta.mkdir(parents=True)
    shutil.copy2(exe, carpeta / exe.name)
    shutil.copy2(RAIZ / "app" / "manuales" / "Manual de Usuario.pdf", carpeta)
    html = RAIZ / "manual" / "Manual de Usuario.html"
    if html.is_file():
        shutil.copy2(html, carpeta)
    shutil.copy2(RAIZ / "empaque" / "LÉAME.txt", carpeta)

    archivo = RAIZ / "dist" / f"Sistema-de-Registro-de-Horas-{numero}.zip"
    archivo.unlink(missing_ok=True)
    with zipfile.ZipFile(archivo, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zip_:
        for ruta in sorted(carpeta.rglob("*")):
            zip_.write(ruta, ruta.relative_to(carpeta.parent).as_posix())
    return archivo


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(version())
        return 0
    if sys.platform != "win32":
        sys.exit("El ejecutable se compila en Windows (PyInstaller compila para el sistema en que corre).")
    numero = version()
    print(f"Compilando {NOMBRE} {numero}…", flush=True)
    escribir_version(numero)

    cliente = (os.environ.get("MAJERIE_CLIENTE_ID") or "").strip()
    microsoft = RAIZ / "app" / "microsoft.json"
    if cliente:
        microsoft.write_text(json.dumps({"cliente_id": cliente}), encoding="utf-8")
    try:
        exe = compilar()
    finally:
        if cliente:
            microsoft.unlink(missing_ok=True)

    archivo = armar_entrega(exe, numero)
    print(f"Listo: {archivo}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
