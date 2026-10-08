"""El sobre en que viaja la base de datos a SharePoint.

En SharePoint no se guarda la base tal cual, sino comprimida y sellada:

1. **Comprimida.** Una base SQLite con texto se reduce a la cuarta parte, y
   eso acorta cada subida y cada descarga.
2. **Ilegible fuera del programa.** Cualquiera con acceso a la carpeta podría
   descargar una base SQLite y abrirla con cualquier visor: vería las horas,
   las tarifas y las citas médicas de todo el equipo. Cifrada, es solo ruido.
   Ojo: la llave viaja dentro del programa, así que esto protege de la
   curiosidad, no de alguien decidido a desarmar el `.exe`. La seguridad de
   verdad la dan los permisos de la carpeta en SharePoint.
3. **Sellada.** Un sello (HMAC-SHA256) cubre todo el archivo. Si se dañó al
   viajar, si quedó cortado o si alguien lo tocó, el programa lo nota y no
   lo usa, en vez de abrir una base corrupta.

El cifrado es BLAKE2b en modo contador —un generador de flujo con llave,
construcción estándar— y el sello va sobre el texto ya cifrado
(cifrar-y-después-sellar). Todo con la biblioteca estándar de Python: nada
que instalar ni que compilar.

    MJRH | versión | largo cabecera | cabecera JSON | nonce | cifrado | sello
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import struct
import zlib

MAGIA = b"MJRH"
VERSION_FORMATO = 1

# Llave maestra del programa. De ella se derivan, con propósitos distintos,
# la del cifrado y la del sello. Cambiarla deja ilegibles los datos ya
# guardados en SharePoint.
_MAESTRA = bytes.fromhex(
    "4e1d9a6c2b7f03e85cb1a24d97f6e0137a5c8d2e41b9f06a3d7c58e2b19f4a60"
)


def _derivar(proposito: bytes) -> bytes:
    return hashlib.blake2b(proposito, key=_MAESTRA, digest_size=32,
                           person=b"majerie-horas").digest()


_LLAVE_CIFRADO = _derivar(b"cifrado")
_LLAVE_SELLO = _derivar(b"sello")


class ArchivoIlegible(Exception):
    """El archivo no es un sobre válido: dañado, cortado o de otro programa."""


def _flujo(nonce: bytes, largo: int) -> bytes:
    """Bytes pseudoaleatorios para enmascarar `largo` bytes."""
    bloques = []
    for contador in range((largo + 63) // 64):
        bloques.append(
            hashlib.blake2b(
                contador.to_bytes(8, "little"),
                key=_LLAVE_CIFRADO,
                salt=nonce,
                digest_size=64,
            ).digest()
        )
    return b"".join(bloques)[:largo]


def _xor(datos: bytes, mascara: bytes) -> bytes:
    # Con enteros grandes es mucho más rápido que byte a byte en Python
    # puro.
    largo = len(datos)
    resultado = int.from_bytes(datos, "little") ^ int.from_bytes(mascara, "little")
    return resultado.to_bytes(largo, "little")


def sellar(contenido: bytes, cabecera: dict | None = None) -> bytes:
    """Comprime, cifra y sella `contenido`. La cabecera queda legible."""
    cabecera = dict(cabecera or {})
    cabecera["largo"] = len(contenido)
    texto_cabecera = json.dumps(cabecera, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    comprimido = zlib.compress(contenido, 6)
    nonce = secrets.token_bytes(16)
    cifrado = _xor(comprimido, _flujo(nonce, len(comprimido)))

    cuerpo = (
        MAGIA
        + struct.pack("<BI", VERSION_FORMATO, len(texto_cabecera))
        + texto_cabecera
        + nonce
        + cifrado
    )
    sello = hmac.new(_LLAVE_SELLO, cuerpo, hashlib.sha256).digest()
    return cuerpo + sello


def leer_cabecera(sobre: bytes) -> dict:
    """La cabecera legible, sin comprobar el sello ni descifrar."""
    if len(sobre) < 9 or sobre[:4] != MAGIA:
        raise ArchivoIlegible("No es un archivo de datos del Sistema de Registro de Horas.")
    version, largo = struct.unpack("<BI", sobre[4:9])
    if version != VERSION_FORMATO:
        raise ArchivoIlegible(
            "El archivo de datos lo escribió una versión más nueva del programa. "
            "Actualice el Sistema de Registro de Horas."
        )
    try:
        return json.loads(sobre[9 : 9 + largo].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as fallo:
        raise ArchivoIlegible("La cabecera del archivo de datos está dañada.") from fallo


def abrir(sobre: bytes) -> tuple[bytes, dict]:
    """Comprueba el sello, descifra y descomprime. Devuelve (contenido, cabecera)."""
    cabecera = leer_cabecera(sobre)
    if len(sobre) < 57:
        raise ArchivoIlegible("El archivo de datos está incompleto.")

    cuerpo, sello = sobre[:-32], sobre[-32:]
    esperado = hmac.new(_LLAVE_SELLO, cuerpo, hashlib.sha256).digest()
    if not hmac.compare_digest(sello, esperado):
        raise ArchivoIlegible(
            "El archivo de datos está dañado o fue modificado fuera del programa."
        )

    _, largo_cabecera = struct.unpack("<BI", sobre[4:9])
    inicio = 9 + largo_cabecera
    nonce = cuerpo[inicio : inicio + 16]
    cifrado = cuerpo[inicio + 16 :]
    comprimido = _xor(cifrado, _flujo(nonce, len(cifrado)))
    try:
        contenido = zlib.decompress(comprimido)
    except zlib.error as fallo:
        raise ArchivoIlegible("El archivo de datos no se pudo descomprimir.") from fallo

    if cabecera.get("largo") not in (None, len(contenido)):
        raise ArchivoIlegible("El archivo de datos quedó a medias.")
    return contenido, cabecera
