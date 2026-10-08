"""Protección de datos de Windows (DPAPI).

La sesión de Microsoft de esta computadora se guarda en disco para no pedir
la contraseña cada vez. Va cifrada con `CryptProtectData`: Windows la ata a
la cuenta de Windows de la persona, así que otra persona —u otra
computadora a la que se copie el archivo— no puede leerla.

Fuera de Windows (solo en pruebas) se guarda tal cual.
"""

from __future__ import annotations

import ctypes
import sys

_ES_WINDOWS = sys.platform == "win32"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _a_blob(datos: bytes) -> tuple[_Blob, ctypes.Array]:
    memoria = ctypes.create_string_buffer(datos, len(datos))
    return _Blob(len(datos), ctypes.cast(memoria, ctypes.POINTER(ctypes.c_char))), memoria


def _de_blob(blob: _Blob) -> bytes:
    datos = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return datos


_ENTROPIA = b"MAJERIE Registro de Horas \xb7 cuenta de Microsoft"
_SIN_INTERFAZ = 1


def proteger(datos: bytes) -> bytes:
    if not _ES_WINDOWS:
        return datos
    entrada, _m1 = _a_blob(datos)
    entropia, _m2 = _a_blob(_ENTROPIA)
    salida = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(entrada), "MAJERIE", ctypes.byref(entropia), None, None,
        _SIN_INTERFAZ, ctypes.byref(salida),
    )
    if not ok:
        raise OSError("Windows no pudo proteger la sesión de Microsoft.")
    return _de_blob(salida)


def desproteger(datos: bytes) -> bytes:
    if not _ES_WINDOWS:
        return datos
    entrada, _m1 = _a_blob(datos)
    entropia, _m2 = _a_blob(_ENTROPIA)
    salida = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(entrada), None, ctypes.byref(entropia), None, None,
        _SIN_INTERFAZ, ctypes.byref(salida),
    )
    if not ok:
        raise OSError("La sesión de Microsoft guardada no se puede leer en esta cuenta.")
    return _de_blob(salida)
