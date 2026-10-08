"""Proyectos. Puerto de `src/lib/projects.ts`."""

from __future__ import annotations


def buscar_proyecto(proyectos: list, proyecto_id: str):
    for proyecto in proyectos:
        if proyecto.id == proyecto_id:
            return proyecto
    return None


def etiqueta_proyecto(proyectos: list, proyecto_id: str, respaldo: str) -> str:
    """Nombre visible de un proyecto, con respaldo en el nombre guardado."""
    proyecto = buscar_proyecto(proyectos, proyecto_id)
    return proyecto.name if proyecto else respaldo


def proyectos_visibles(proyectos: list, usuario) -> list:
    """La administración los ve todos; el colaborador ve los de la empresa
    y los suyos."""
    if not usuario:
        return []
    if usuario.role == "administrador":
        return list(proyectos)
    return [p for p in proyectos if not p.ownerId or p.ownerId == usuario.id]


def proyectos_editables(proyectos: list, usuario) -> list:
    """Proyectos que un colaborador puede editar: únicamente los propios."""
    if not usuario:
        return []
    if usuario.role == "administrador":
        return list(proyectos)
    return [p for p in proyectos if p.ownerId == usuario.id]


def etiqueta_propietario(proyecto, nombre_propietario: str) -> str:
    return nombre_propietario if proyecto.ownerId else "Proyecto de la empresa"
