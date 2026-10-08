"""Los enlaces de carpeta que la gente copia de SharePoint.

Hay muchas maneras de «copiar el enlace de la carpeta», y todas deben
servir:

- El botón **Compartir / Copiar vínculo**:
  `https://empresa.sharepoint.com/:f:/s/Equipo/EqA1b2c3…?e=Xy12`
- La **barra de direcciones** mientras se mira la carpeta:
  `https://empresa.sharepoint.com/sites/Equipo/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2F…`
- La dirección **directa** de la carpeta:
  `https://empresa.sharepoint.com/sites/Equipo/Documentos%20compartidos/Horas`
- Una carpeta del **OneDrive de trabajo** de alguien:
  `https://empresa-my.sharepoint.com/personal/ana_empresa_cr/_layouts/15/onedrive.aspx?id=…`

Graph las resuelve todas con `/shares/u!…` (la dirección codificada en
base64url). Aquí solo se limpia lo que pega la persona y se convierte la
dirección de las vistas del navegador en la dirección real de la carpeta.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlsplit

# Dominios de SharePoint (comercial, gobierno y nubes nacionales).
_DOMINIOS = (".sharepoint.com", ".sharepoint.us", ".sharepoint.de", ".sharepoint.cn",
             ".sharepoint-df.com", ".sharepoint-mil.us")
# Páginas del navegador que muestran una carpeta pero no son la carpeta.
_PAGINAS_VISTA = ("/forms/allitems.aspx", "/_layouts/15/onedrive.aspx",
                  "/_layouts/15/viewlsts.aspx", "/forms/", "/_layouts/15/")


class EnlaceInvalido(ValueError):
    """Lo pegado no es un enlace de carpeta de SharePoint."""


@dataclass
class Enlace:
    original: str
    # La dirección que se le pasa a Graph (la compartida o la directa).
    para_api: str
    anfitrion: str
    # «compartido» o «directo».
    tipo: str

    @property
    def codificado(self) -> str:
        return codificar(self.para_api)

    @property
    def inquilino_probable(self) -> str:
        """`empresa.onmicrosoft.com` a partir de `empresa.sharepoint.com`."""
        nombre = self.anfitrion.split(".")[0]
        if nombre.endswith("-my"):
            nombre = nombre[:-3]
        return f"{nombre}.onmicrosoft.com"


def codificar(url: str) -> str:
    """`u!` + base64url sin relleno, como pide Graph para `/shares`."""
    crudo = base64.b64encode(url.encode("utf-8")).decode("ascii")
    return "u!" + crudo.rstrip("=").replace("/", "_").replace("+", "-")


def _extraer_url(texto: str) -> str:
    """La primera dirección `https://` de lo que se pegó."""
    texto = (texto or "").strip().strip("<>\"'“”‘’")
    encontrada = re.search(r"https?://[^\s<>\"'“”‘’]+", texto)
    if not encontrada:
        raise EnlaceInvalido(
            "Pegue el enlace completo de la carpeta: empieza con https:// y "
            "contiene «sharepoint.com»."
        )
    # Lo pegado desde un correo a veces arrastra la puntuación de la frase.
    return encontrada.group(0).rstrip(".,;)]}")


def interpretar(texto: str) -> Enlace:
    url = _extraer_url(texto)
    partes = urlsplit(url)
    anfitrion = (partes.hostname or "").lower()

    if partes.scheme != "https":
        raise EnlaceInvalido("El enlace de SharePoint debe empezar con https://")
    if not anfitrion.endswith(_DOMINIOS):
        if "onedrive.live.com" in anfitrion or anfitrion == "1drv.ms":
            raise EnlaceInvalido(
                "Ese es un enlace de OneDrive personal. Hace falta una carpeta del "
                "SharePoint de la empresa (su dirección contiene «sharepoint.com»)."
            )
        # Cualquier otro sitio.
        raise EnlaceInvalido(
            "Ese enlace no es de SharePoint. La dirección de la carpeta de la "
            "empresa contiene «sharepoint.com»."
        )

    ruta = partes.path or "/"

    # Enlace de «Copiar vínculo»: /:f:/ es carpeta; /:w:/, /:x:/… son archivos.
    if re.match(r"^/:[a-z]:/", ruta, re.I):
        if not ruta.lower().startswith("/:f:/"):
            raise EnlaceInvalido(
                "Ese enlace es de un archivo, no de una carpeta. En SharePoint, "
                "abra la carpeta que le dieron y copie su enlace."
            )
        return Enlace(original=url, para_api=url, anfitrion=anfitrion, tipo="compartido")

    # Barra de direcciones: la carpeta viaja en ?id= (o ?RootFolder= en las
    # bibliotecas antiguas). Si no está, la dirección ya es la de la
    # carpeta, salvo que sea una página de vista.
    consulta = parse_qs(partes.query)
    carpeta = (consulta.get("id") or consulta.get("RootFolder") or [""])[0]
    if carpeta.startswith("/"):
        ruta = carpeta
    elif any(pagina in ruta.lower() for pagina in _PAGINAS_VISTA):
        raise EnlaceInvalido(
            "Ese enlace abre una vista de la biblioteca, no una carpeta. Entre a "
            "la carpeta y copie el enlace con «Copiar vínculo»."
        )
    else:
        ruta = unquote(ruta)

    ruta = "/" + ruta.strip("/")
    if ruta == "/" or ruta.lower().startswith("/_layouts"):
        raise EnlaceInvalido(
            "Ese enlace no apunta a una carpeta. Abra la carpeta en SharePoint "
            "y copie su enlace."
        )

    directa = f"https://{anfitrion}{quote(ruta, safe='/-_.~()')}"
    return Enlace(original=url, para_api=directa, anfitrion=anfitrion, tipo="directo")
