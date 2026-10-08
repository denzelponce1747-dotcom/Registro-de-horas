"""Arma el Manual de Usuario en HTML y en PDF a partir de `fuente.html`.

    python manual/generar.py                        HTML y PDF
    python manual/generar.py --solo-html            solo el HTML
    python manual/generar.py --navegador RUTA       Chrome/Edge/Chromium a usar

- `manual/Manual de Usuario.html`: un solo archivo, con las imágenes y la
  letra dentro; se abre con doble clic en cualquier navegador, sin internet.
- `app/manuales/Manual de Usuario.pdf`: el que abre el programa desde su menú
  y el que va en la carpeta de entrega. Lo imprime un navegador basado en
  Chromium en modo sin ventana (Chrome, Edge o Chromium).

Para cambiar el manual se edita `fuente.html` (y las imágenes de
`imagenes/`) y se vuelve a correr este archivo.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
FUENTE = AQUI / "fuente.html"
HTML = AQUI / "Manual de Usuario.html"
PDF = RAIZ / "app" / "manuales" / "Manual de Usuario.pdf"
FUENTES = RAIZ / "app" / "static" / "fuentes"

TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}


def _datos(ruta: Path, tipo: str) -> str:
    return f"data:{tipo};base64,{base64.b64encode(ruta.read_bytes()).decode('ascii')}"


def armar_html() -> str:
    texto = FUENTE.read_text(encoding="utf-8")

    def incrustar(encontrado: re.Match) -> str:
        ruta = AQUI / encontrado.group(1)
        if not ruta.is_file():
            sys.exit(f"Falta la imagen {ruta}")
        return f'src="{_datos(ruta, TIPOS[ruta.suffix.lower()])}"'

    texto = re.sub(r'src="(imagenes/[^"]+)"', incrustar, texto)
    fuentes = "\n".join(
        f'@font-face {{ font-family: "Inter Manual"; src: url("{_datos(FUENTES / nombre, "font/woff2")}") '
        f'format("woff2"); font-weight: 100 900; font-style: normal; }}'
        for nombre in ("inter-latin.woff2", "inter-extra.woff2")
    )
    return texto.replace("/*@@FUENTES@@*/", fuentes)


def buscar_navegador(indicado: str | None) -> str | None:
    candidatos = [indicado, os.environ.get("NAVEGADOR_PDF")]
    candidatos += [shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge")]
    programas = [os.environ.get(v, "") for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    for base in filter(None, programas):
        candidatos += [
            str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        ]
    candidatos += [str(p) for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")]
    return next((c for c in candidatos if c and Path(c).is_file()), None)


def imprimir_pdf(navegador: str, html: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="manual-") as perfil:
        subprocess.run(
            [navegador, "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
             f"--user-data-dir={perfil}", "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
             "--virtual-time-budget=8000", f"--print-to-pdf={destino}", html.as_uri()],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180,
        )
    if not destino.is_file() or destino.stat().st_size < 10_000:
        sys.exit("El navegador no generó el PDF.")


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--solo-html", action="store_true")
    argumentos.add_argument("--navegador")
    opciones = argumentos.parse_args()

    HTML.write_text(armar_html(), encoding="utf-8")
    print(f"HTML: {HTML} ({HTML.stat().st_size / 1_048_576:.1f} MB)")
    if opciones.solo_html:
        return 0

    navegador = buscar_navegador(opciones.navegador)
    if not navegador:
        sys.exit("No se encontró Chrome, Edge ni Chromium para imprimir el PDF (use --navegador).")
    imprimir_pdf(navegador, HTML, PDF)
    print(f"PDF:  {PDF} ({PDF.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
