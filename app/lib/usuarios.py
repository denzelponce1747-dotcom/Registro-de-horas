"""Usuarios. Puerto de `src/lib/users.ts`."""

from __future__ import annotations

import random
import re
import time
import unicodedata


def colaboradores_de(usuarios: list) -> list:
    return [u for u in usuarios if u.role == "colaborador"]


def administradores_de(usuarios: list) -> list:
    return [u for u in usuarios if u.role == "administrador"]


def obtener_usuario(usuarios: list, identificador: str):
    for usuario in usuarios:
        if usuario.id == identificador:
            return usuario
    return None


def nombre_de_usuario(usuarios: list, identificador: str) -> str:
    usuario = obtener_usuario(usuarios, identificador)
    return usuario.name if usuario else "Sin asignar"


def iniciales_de(nombre: str) -> str:
    """Iniciales para el avatar: María Quesada -> MQ; Colaborador 3 -> C3."""
    limpio = (nombre or "").strip()
    if not limpio:
        return "??"
    # «Colaborador 3» -> «C3»: la inicial y el número.
    numerado = re.match(r"^(\w)\w*\s+(\d+)$", limpio, re.UNICODE)
    if numerado:
        return f"{numerado.group(1).upper()}{numerado.group(2)}"

    palabras = [p for p in re.split(r"\s+", limpio) if p]
    iniciales = "".join(p[0].upper() for p in palabras[:2])
    return iniciales or "??"


def sugerir_usuario(nombre: str) -> str:
    """Primera inicial más el primer apellido, sin tildes y en minúsculas."""
    sin_tildes = "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", nombre or "")
        if unicodedata.category(caracter) != "Mn"
    )
    limpio = re.sub(r"[^a-z0-9\s]", " ", sin_tildes.lower()).strip()
    if not limpio:
        return ""

    palabras = [p for p in re.split(r"\s+", limpio) if p]
    if len(palabras) == 1:
        return palabras[0]
    return f"{palabras[0][0]}{palabras[1]}"


def problema_usuario(username: str) -> str | None:
    """Reglas del nombre de usuario: sin espacios ni mayúsculas."""
    if len(username) < 3:
        return "El nombre de usuario debe tener al menos 3 caracteres."
    if not re.fullmatch(r"[a-z0-9._-]+", username):
        return "Use solo minúsculas, números, puntos, guiones o guiones bajos."
    return None


def normalizar_usuario(username: str) -> str:
    return (username or "").strip().lower()


def _sufijo_aleatorio(largo: int = 5) -> str:
    alfabeto = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(random.choice(alfabeto) for _ in range(largo))


def _base36(numero: int) -> str:
    digitos = "0123456789abcdefghijklmnopqrstuvwxyz"
    if numero == 0:
        return "0"
    salida = ""
    while numero:
        numero, resto = divmod(numero, 36)
        salida = digitos[resto] + salida
    return salida


def crear_id_usuario(role: str) -> str:
    """Identificador interno, independiente del nombre de usuario."""
    prefijo = "adm" if role == "administrador" else "col"
    return f"{prefijo}-{_base36(int(time.time() * 1000))}-{_sufijo_aleatorio()}"


def crear_id(prefijo: str) -> str:
    """Identificador de cualquier otra entidad: registro, ausencia, proyecto."""
    return f"{prefijo}-{_base36(int(time.time() * 1000))}-{_sufijo_aleatorio()}"
