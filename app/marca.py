"""Logotipo e iconografía.

El logotipo es el oficial de MAJERIE S.R.L, vectorizado con exactitud a
partir del PNG que entregó la empresa (`app/marca_trazado.py`): cada letra
es el contorno real, no una imitación. Así se ve nítido a cualquier tamaño,
toma el color del texto —negro en el tema claro, blanco en el oscuro— y no
depende de ningún archivo de imagen.

Para la entrada animada, el contorno se revela con una máscara de trazos que
siguen el recorrido de cada letra, como si se escribiera con la misma pluma
del logotipo: la forma final es siempre la exacta.

Los iconos reproducen los de Lucide que usaba la versión original, con el
mismo trazo de 24×24 y sin depender de ninguna biblioteca externa.
"""

from __future__ import annotations

import itertools

from markupsafe import Markup

from .marca_trazado import ANCHO, ARRIBA, CONTORNO, TRAZO


# Nombre de la empresa tal como se escribe.
MARCA_DENOMINATIVA = "MAJERIE S.R.L"

# Caja del dibujo, con margen para que el trazo no se corte en los bordes.
_MARGEN = TRAZO / 2
_CAJA = (
    -_MARGEN,
    ARRIBA - _MARGEN,
    ANCHO + 2 * _MARGEN,
    100 - ARRIBA + 2.5 + 2 * _MARGEN,
)
_TRAZADO = "".join(CONTORNO)

# Recorrido de la pluma por cada letra, en el orden en que se escribe. Los
# trazos solo revelan el contorno exacto: no tienen que ser perfectos.
# «punto:x:y» es el punto de «S.R.L».
_PLUMA = (
    ("M", ["M5.15 102 V-2 L53.7 93 L102.8 -2 V102"]),
    ("A", ["M156.4 102 L198.9 4 L241.4 102"]),
    ("J", ["M325 -2 V76 C325 91 313 96.5 300 96.5 C293 96.5 288 94.5 281.5 90.5"]),
    ("E", ["M383 5.1 H448.5", "M444.4 48.9 H390.6 V94.9 H448.5"]),
    ("R", ["M494.5 5.1 H539 C555 5.1 560 17 560 28.8 C560 42 550 53.4 538 53.4 H502 V102",
           "M540 54 L564 102"]),
    ("I", ["M619.9 -2 V102"]),
    ("E", ["M677.9 5.1 H743.4", "M739.3 48.9 H685.5 V94.9 H743.4"]),
    ("S", ["M908 10 C897 3 889 0.6 878 0.6 C861 0.6 852.5 10 852.5 23 C852.5 37 865 43.5 879 46.6 C896 50.3 906.5 56 906.5 72 C906.5 89 892 96.4 876 96.4 C866 96.4 858 93.5 848.5 88.5"]),
    # S.R.L
    (".", ["punto:961.75:92.1"]),
    ("R", ["M1018.1 5.1 H1062.6 C1078.6 5.1 1083.6 17 1083.6 28.8 C1083.6 42 1073.6 53.4 1061.6 53.4 H1025.6 V102",
           "M1063.6 54 L1087.6 102"]),
    (".", ["punto:1142:91.85"]),
    ("L", ["M1205.6 -2 V94.9 H1264.4"]),
)

_ids = itertools.count(1)


def _caja() -> str:
    x, y, ancho, alto = _CAJA
    return f"{x:.2f} {y:.2f} {ancho:.2f} {alto:.2f}"


def logo(alto: str = "16px", grosor: float | None = None, animado: bool = False,
         color: str = "currentColor", clase: str = "") -> Markup:
    """Logotipo de MAJERIE S.R.L.

    `alto` es la altura de la caja; el ancho sale solo (el logotipo es muy
    alargado, 12:1). `grosor` se acepta por compatibilidad y no se usa: el
    grosor es el del logotipo oficial. Con `animado`, se escribe letra por
    letra al aparecer.
    """
    del grosor
    etiqueta = 'role="img" aria-label="MAJERIE S.R.L"'
    estilo = f'style="height:{alto};width:auto;color:{color};display:block"'
    if not animado:
        return Markup(
            f'<svg viewBox="{_caja()}" {etiqueta} class="logo {clase}" {estilo}><path d="'
            f'{_TRAZADO}" fill="currentColor"/></svg>'
        )

    ident = f"pluma-{next(_ids)}"
    trazos = []
    for indice, (_letra, recorridos) in enumerate(_PLUMA):
        for recorrido in recorridos:
            if recorrido.startswith("punto:"):
                _, x, y = recorrido.split(":")
                trazos.append(
                    f'<circle cx="{x}" cy="{y}" r="13" fill="#fff" class="pluma-punto" style="--glifo:'
                    f'{indice}"/>'
                )
            else:
                trazos.append(
                    f'<path d="{recorrido}" pathLength="1" class="pluma-trazo" style="--glifo:'
                    f'{indice}"/>'
                )
    return Markup(
        f'<svg viewBox="{_caja()}" {etiqueta} class="logo logo-dibujo {clase}" {estilo}><defs><mask id="'
        f'{ident}" maskUnits="userSpaceOnUse" x="{_CAJA[0]:.2f}" y="'
        f'{_CAJA[1]:.2f}" width="{_CAJA[2]:.2f}" height="{_CAJA[3]:.2f}">'
        '<g fill="none" stroke="#fff" stroke-width="24" stroke-linecap="butt" stroke-linejoin="miter">'
        f'{"".join(trazos)}</g></mask></defs><path d="'
        f'{_TRAZADO}" fill="currentColor" mask="url(#{ident})"/></svg>'
    )


# La «M» sola: la pieza del contorno que empieza más a la izquierda.
_M = CONTORNO[min(range(len(CONTORNO)), key=lambda i: float(CONTORNO[i][1:].split(" ")[0]))]


def marca_compacta(tamano: str = "24px", clase: str = "") -> Markup:
    """La «M» del logotipo, cuadrada, para espacios reducidos."""
    return Markup(
        f'<svg viewBox="-16 -20 140 140" role="img" aria-label="MAJERIE" class="{clase}" style="height:'
        f'{tamano};width:{tamano}"><path d="{_M}" fill="currentColor"/></svg>'
    )


def trazado_logo() -> dict:
    """Datos del logotipo para quien lo dibuje por su cuenta (recursos, manual)."""
    return {"caja": _CAJA, "trazado": _TRAZADO, "m": _M}


# ---------------------------------------------------------------------------
# Iconos (Lucide, 24×24)
# ---------------------------------------------------------------------------

_TRAZOS = {
    "sol": (
        '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/>'
        '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>'
        '<path d="M2 12h2"/><path d="M20 12h2"/>'
        '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>'
    ),
    "luna": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "nube": '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    "nube-apagada": (
        '<path d="m2 2 20 20"/><path d="M5.782 5.782A7 7 0 0 0 9 19h8.5a4.5 4.5 0 0 0 1.307-.193"/>'
        '<path d="M21.532 16.5A4.5 4.5 0 0 0 17.5 10h-1.79A7.008 7.008 0 0 0 10 5.07"/>'
    ),
    "refrescar": (
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
        '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>'
    ),
    "enlace": (
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
    ),
    "carpeta": (
        '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'
    ),
    "abrir-afuera": (
        '<path d="M15 3h6v6"/><path d="M10 14 21 3"/>'
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
    ),
    "copiar": (
        '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
        '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'
    ),
    "ayuda": (
        '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        '<path d="M12 17h.01"/>'
    ),
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "libro": (
        '<path d="M12 7v14"/>'
        '<path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>'
    ),
    "subir": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/>'
        '<line x1="12" x2="12" y1="3" y2="15"/>'
    ),
    "archivo": (
        '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/>'
        '<path d="M10 12h4"/>'
    ),
    "ventana": (
        '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 4v4"/>'
        '<path d="M2 8h20"/><path d="M6 4v4"/>'
    ),
    "monitor": (
        '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/>'
        '<line x1="12" x2="12" y1="17" y2="21"/>'
    ),
    "persona": '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
    "visto-circulo": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>',
    "desenchufar": (
        '<path d="m19 5 3-3"/><path d="m2 22 3-3"/>'
        '<path d="M6.3 20.3a2.4 2.4 0 0 0 3.4 0L12 18l-6-6-2.3 2.3a2.4 2.4 0 0 0 0 3.4Z"/>'
        '<path d="M7.5 13.5 10 11"/><path d="M10.5 16.5 13 14"/>'
        '<path d="m12 6 6 6 2.3-2.3a2.4 2.4 0 0 0 0-3.4l-2.6-2.6a2.4 2.4 0 0 0-3.4 0Z"/>'
    ),
    "flecha-arriba-derecha": '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
    "lista": (
        '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/>'
        '<path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>'
    ),
    "calendario-dias": (
        '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/>'
        '<path d="M3 10h18"/><path d="M8 14h.01"/>'
        '<path d="M12 14h.01"/><path d="M16 14h.01"/><path d="M8 18h.01"/>'
        '<path d="M12 18h.01"/><path d="M16 18h.01"/>'
    ),
    "calendario-rango": (
        '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M17 14h-6"/><path d="M13 18H7"/>'
        '<path d="M7 14h.01"/><path d="M17 18h.01"/><path d="M8 2v4"/>'
        '<path d="M16 2v4"/><path d="M3 10h18"/>'
    ),
    "calendario-reloj": (
        '<path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M16 2v4"/>'
        '<path d="M8 2v4"/><path d="M3 10h5"/>'
        '<circle cx="16" cy="16" r="6"/><path d="M16 14v2l1 1"/>'
    ),
    "historial": (
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>'
        '<path d="M12 7v5l4 2"/>'
    ),
    "reloj-arena": (
        '<path d="M5 22h14"/><path d="M5 2h14"/>'
        '<path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/>'
        '<path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>'
    ),
    "palmera": (
        '<path d="M13 8c0-2.76-2.46-5-5.5-5S2 5.24 2 8h2l1-1 1 1h4"/>'
        '<path d="M13 7.14A5.82 5.82 0 0 1 16.5 6c3.04 0 5.5 2.24 5.5 5h-3l-1-1-1 1h-3"/>'
        '<path d="M5.89 9.71c-2.15 2.15-2.3 5.06-.35 7.01l4.24-4.24.7-.7.71-.71 2.12-2.12c-1.95-1.96-4.86-1.8-7.02.35z"/>'
        '<path d="M11 15.5c.5 2.5-.17 4.5-1 6.5h4c2-5.5-.5-12-1-14"/>'
    ),
    "escudo-alerta": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="M12 8v4"/>'
        '<path d="M12 16h.01"/>'
    ),
    "escudo-visto": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'
        '<path d="m9 12 2 2 4-4"/>'
    ),
    "personas": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "portapapeles-lista": (
        '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
        '<path d="M12 11h4"/><path d="M12 16h4"/>'
        '<path d="M8 11h.01"/><path d="M8 16h.01"/>'
    ),
    "portapapeles-visto": (
        '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/>'
        '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
        '<path d="m9 14 2 2 4-4"/>'
    ),
    "reloj": (
        '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'
    ),
    "diana": (
        '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/>'
        '<circle cx="12" cy="12" r="2"/>'
    ),
    "billete": (
        '<rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="12" cy="12" r="2"/>'
        '<path d="M6 12h.01M18 12h.01"/>'
    ),
    "descargar": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/>'
        '<line x1="12" x2="12" y1="15" y2="3"/>'
    ),
    "hoja-calculo": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M8 13h2"/><path d="M14 13h2"/>'
        '<path d="M8 17h2"/><path d="M14 17h2"/>'
    ),
    "doble-visto": (
        '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/>'
    ),
    "visto": '<path d="M20 6 9 17l-5-5"/>',
    "izquierda": '<path d="m15 18-6-6 6-6"/>',
    "derecha": '<path d="m9 18 6-6-6-6"/>',
    "flecha-derecha": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "flecha-izquierda": '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
    "mas": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "lapiz": (
        '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>'
        '<path d="m15 5 4 4"/>'
    ),
    "papelera": (
        '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
        '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/>'
        '<line x1="14" x2="14" y1="11" y2="17"/>'
    ),
    "cerrar": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "llave": (
        '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"/>'
        '<circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>'
    ),
    "candado": (
        '<circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>'
        '<path d="M15.6 11.6 22 7v9a2 2 0 0 1-2 2h-7"/>'
        '<rect width="10" height="8" x="2" y="14" rx="2"/>'
        '<path d="M4 14V9a4 4 0 0 1 8 0v5"/>'
    ),
    "salir": (
        '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/>'
        '<line x1="21" x2="9" y1="12" y2="12"/>'
    ),
    "usuario-config": (
        '<circle cx="18" cy="15" r="3"/><circle cx="9" cy="7" r="4"/>'
        '<path d="M10 15H6a4 4 0 0 0-4 4v2"/><path d="m21.7 16.4-.9-.3"/>'
        '<path d="m15.2 13.9-.9-.3"/><path d="m16.6 18.7.3-.9"/>'
        '<path d="m19.1 12.2.3-.9"/><path d="m19.6 18.7-.4-1"/>'
        '<path d="m16.8 12.3-.4-1"/><path d="m14.3 16.6 1-.4"/>'
        '<path d="m20.7 13.8 1-.4"/>'
    ),
    "engranaje": (
        '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    "carpetas": (
        '<path d="M4 10a2 2 0 0 1-2-2V5c0-1.1.9-2 2-2h3.93a2 2 0 0 1 1.66.9l.82 1.2a2 2 0 0 0 1.66.9H18a2 2 0 0 1 2 2v1"/><path d="M2 12h20"/>'
        '<path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7"/>'
        '<path d="M9 16h6"/>'
    ),
    "busqueda-vacia": (
        '<path d="m13.5 8.5-5 5"/><path d="m8.5 8.5 5 5"/>'
        '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'
    ),
    "filtro": '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "sandwich": (
        '<path d="M3 11v3a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-3"/>'
        '<path d="M12 19H4a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-3.83"/>'
        '<path d="m3 11 7.77-6.04a2 2 0 0 1 2.46 0L21 11H3Z"/>'
    ),
    "aviso": (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/>'
        '<path d="M12 17h.01"/>'
    ),
    "puerta": (
        '<path d="M13 4h3a2 2 0 0 1 2 2v14"/><path d="M2 20h3"/>'
        '<path d="M13 20h9"/>'
        '<path d="M10 12v.01"/>'
        '<path d="M13 2.5a.5.5 0 0 0-.7-.46l-6 2A.5.5 0 0 0 6 4.5V20a.5.5 0 0 0 .7.46l6-2A.5.5 0 0 0 13 18z"/>'
    ),
}

def icono(nombre: str, tamano: str = "16px", grosor: float = 1.8,
          clase: str = "") -> Markup:
    """Icono en línea, del mismo trazo que los de la versión original."""
    trazos = _TRAZOS.get(nombre)
    if not trazos:
        return Markup("")
    return Markup(
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="'
        f'{grosor}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="'
        f'{clase}" style="height:'
        f'{tamano};width:{tamano};flex-shrink:0">{trazos}</svg>'
    )


def logo_microsoft(tamano: str = "16px") -> Markup:
    """Los cuatro cuadros de Microsoft, para el botón de «Entrar con Microsoft»."""
    return Markup(
        f'<svg viewBox="0 0 21 21" aria-hidden="true" style="height:{tamano};width:{tamano};flex-shrink:0"><rect x="1" y="1" width="9" height="9" fill="#f25022"/><rect x="11" y="1" width="9" height="9" fill="#7fba00"/><rect x="1" y="11" width="9" height="9" fill="#00a4ef"/><rect x="11" y="11" width="9" height="9" fill="#ffb900"/></svg>'
    )
