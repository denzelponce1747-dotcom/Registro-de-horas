"""El selector de navegador de la primera vez.

Es una ventana de Windows (tkinter, que viaja dentro del `.exe`) porque
todavía no hay navegador elegido en el que mostrar nada. Sigue la marca de
MAJERIE: blanco, el logotipo, tinta negra y una sola acción clara.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading

log = logging.getLogger("majerie.ventana")

_un_cuadro = threading.Lock()


class Ocupado(Exception):
    """Ya hay un cuadro abierto."""

TINTA = "#0B0B0C"
TINTA_SUAVE = "#27272A"
GRIS = "#62626B"
GRIS_CLARO = "#A1A1AA"
BORDE = "#E4E4E7"
FONDO = "#FFFFFF"


def preparar_dpi() -> None:
    """Nitidez en pantallas con escala: sin esto Windows estira la ventana."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _al_frente(raiz) -> None:
    """Pone la ventana delante de todo, aunque otro programa tenga el foco.

    Windows no deja que un proceso en segundo plano se adelante; uniéndose un
    momento a la entrada del hilo que tiene el foco, sí lo permite.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(raiz.winfo_id()) or raiz.winfo_id()
        primero = user32.GetForegroundWindow()
        propio = ctypes.windll.kernel32.GetCurrentThreadId()
        ajeno = user32.GetWindowThreadProcessId(primero, None) if primero else 0
        unidos = bool(ajeno and ajeno != propio and user32.AttachThreadInput(ajeno, propio, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if unidos:
                user32.AttachThreadInput(ajeno, propio, False)
    except (AttributeError, OSError):
        pass


def _recurso(*partes: str) -> str:
    from ..config import CARPETA_ESTATICOS

    return str(CARPETA_ESTATICOS.joinpath(*partes))


def _raiz_invisible():
    """Dueña de los cuadros: invisible, al frente, centrada en la pantalla."""
    import tkinter as tk

    raiz = tk.Tk()
    raiz.attributes("-alpha", 0.0)
    raiz.attributes("-topmost", True)
    try:
        raiz.iconbitmap(_recurso("iconos", "majerie.ico"))
    except Exception:
        pass
    ancho, alto = raiz.winfo_screenwidth(), raiz.winfo_screenheight()
    raiz.geometry(f"1x1+{ancho // 2}+{alto // 3}")
    raiz.update_idletasks()
    raiz.deiconify()
    raiz.update()
    _al_frente(raiz)
    return raiz


def elegir_ejecutable(titulo: str) -> str:
    """Ruta de un .exe, o '' si se canceló. Lanza Ocupado si ya hay un cuadro."""
    from tkinter import filedialog

    if not _un_cuadro.acquire(blocking=False):
        raise Ocupado()
    try:
        raiz = _raiz_invisible()
        try:
            elegida = filedialog.askopenfilename(
                parent=raiz, title=titulo,
                initialdir=os.environ.get("ProgramFiles") or None,
                filetypes=[("Programas", "*.exe")])
            return os.path.normpath(elegida) if elegida else ""
        finally:
            raiz.destroy()
    finally:
        _un_cuadro.release()


def _etiqueta(navegador: dict) -> str:
    if navegador.get("predeterminado"):
        return f"{navegador['nombre']}   ·   su navegador predeterminado"
    return navegador["nombre"]


def elegir_navegador(lista: list[dict], actual: dict | None = None) -> dict | None:
    """Ventana de bienvenida con la lista de navegadores.

    Devuelve el navegador elegido ({clave, nombre, ruta}) o None si se cerró
    la ventana sin elegir.
    """
    import tkinter as tk
    from tkinter import ttk

    opciones = list(lista)
    resultado = {"valor": None}

    raiz = tk.Tk()
    raiz.title("Sistema de Registro de Horas · MAJERIE S.R.L")
    raiz.configure(bg=FONDO)
    raiz.resizable(False, False)
    try:
        raiz.iconbitmap(_recurso("iconos", "majerie.ico"))
    except Exception:
        pass
    # Las medidas se piensan a 96 ppp y se escalan con la pantalla.
    escala = float(raiz.tk.call("tk", "scaling"))
    px = lambda v: int(round(v * escala / 1.3333))  # noqa: E731

    estilo = ttk.Style(raiz)
    try:
        estilo.theme_use("vista")
    except tk.TclError:
        pass
    estilo.configure("Marca.TCombobox", padding=px(7))

    # Franja de tinta arriba, como en la aplicación.
    tk.Frame(raiz, bg=TINTA, height=px(3)).pack(fill="x")

    cuerpo = tk.Frame(raiz, bg=FONDO, padx=px(40), pady=px(28))
    cuerpo.pack(fill="both", expand=True)

    # El logotipo en la resolución que corresponde a la escala de la pantalla.
    factor = escala / 1.3333
    nombre_logo = ("logo-dialogo@2x.png" if factor >= 1.75
                   else "logo-dialogo@1.5x.png" if factor >= 1.2
                   else "logo-dialogo.png")
    try:
        logo = tk.PhotoImage(file=_recurso("marca", nombre_logo))
        tk.Label(cuerpo, image=logo, bg=FONDO).pack(pady=(px(6), px(6)))
        raiz._logo = logo  # que no lo recoja el recolector de basura
    except tk.TclError:
        tk.Label(cuerpo, text="M A J E R I E   S . R . L", bg=FONDO, fg=TINTA,
                 font=("Segoe UI Light", 16)).pack(pady=(px(6), px(6)))

    tk.Label(cuerpo, text="SISTEMA DE REGISTRO DE HORAS", bg=FONDO, fg=GRIS_CLARO,
             font=("Segoe UI Semibold", 8)).pack(pady=(0, px(22)))

    tk.Frame(cuerpo, bg=BORDE, height=1).pack(fill="x", pady=(0, px(22)))

    tk.Label(cuerpo, text="¿Con qué navegador abrimos el sistema?", bg=FONDO, fg=TINTA,
             font=("Segoe UI Semibold", 14)).pack(anchor="w")
    tk.Label(
        cuerpo, bg=FONDO, fg=GRIS, font=("Segoe UI", 10), justify="left",
        wraplength=px(440),
        text=("El sistema se abre en su propia ventana, como una aplicación: sin pestañas "
              "ni barra de direcciones. Elija el navegador que prefiera; solo se pregunta "
              "esta vez."),
    ).pack(anchor="w", pady=(px(6), px(18)))

    tk.Label(cuerpo, text="Navegador", bg=FONDO, fg=TINTA,
             font=("Segoe UI Semibold", 9)).pack(anchor="w")
    variable = tk.StringVar()
    combo = ttk.Combobox(cuerpo, textvariable=variable, state="readonly",
                         font=("Segoe UI", 11), style="Marca.TCombobox")
    combo.pack(fill="x", pady=(px(5), px(8)))

    def refrescar(seleccion=None):
        combo["values"] = [_etiqueta(n) for n in opciones]
        if opciones:
            # El elegido antes, o el predeterminado de Windows, o el primero.
            indice = next((i for i, n in enumerate(opciones)
                           if seleccion and n["ruta"] == seleccion["ruta"]), None)
            if indice is None:
                indice = next((i for i, n in enumerate(opciones) if n.get("predeterminado")), 0)
            combo.current(indice)
            combo.selection_clear()

    def buscar_otro(_evento=None):
        from tkinter import filedialog, messagebox

        ruta = filedialog.askopenfilename(
            parent=raiz, title="Elegir el programa del navegador",
            initialdir=os.environ.get("ProgramFiles") or None,
            filetypes=[("Programas", "*.exe")])
        if not ruta:
            return
        ruta = os.path.normpath(ruta)
        if os.path.basename(ruta).lower() in ("firefox.exe", "iexplore.exe", "opera.exe", "launcher.exe"):
            # No tienen el modo «aplicación».
            messagebox.showwarning(
                "Navegador no compatible",
                "Ese navegador no puede abrir el sistema en una ventana propia.\n\n"
                "Elija Google Chrome, Microsoft Edge, Brave, Vivaldi u otro basado en Chromium.",
                parent=raiz)
            return
        nuevo = {"clave": "otro", "nombre": os.path.splitext(os.path.basename(ruta))[0].capitalize(),
                 "ruta": ruta, "predeterminado": False}
        opciones[:] = [n for n in opciones if n["clave"] != "otro"] + [nuevo]
        refrescar(nuevo)

    enlace = tk.Label(cuerpo, text="¿Usa otro navegador? Buscar el programa…", bg=FONDO,
                      fg=TINTA_SUAVE, cursor="hand2", font=("Segoe UI", 9, "underline"))
    enlace.pack(anchor="w", pady=(0, px(22)))
    enlace.bind("<Button-1>", buscar_otro)

    def continuar(_evento=None):
        indice = combo.current()
        if 0 <= indice < len(opciones):
            resultado["valor"] = opciones[indice]
            raiz.destroy()

    boton = tk.Label(cuerpo, text="Abrir el sistema   →", bg=TINTA, fg="white",
                     font=("Segoe UI Semibold", 11), pady=px(12), cursor="hand2")
    boton.pack(fill="x")
    boton.bind("<Button-1>", continuar)
    boton.bind("<Enter>", lambda _e: boton.configure(bg=TINTA_SUAVE))
    boton.bind("<Leave>", lambda _e: boton.configure(bg=TINTA))

    tk.Label(cuerpo, text="Puede cambiarlo cuando quiera en Ajustes.", bg=FONDO, fg=GRIS_CLARO,
             font=("Segoe UI", 9)).pack(pady=(px(12), 0))

    if not opciones:
        combo.configure(state="disabled")
        tk.Label(cuerpo, bg=FONDO, fg="#B42318", font=("Segoe UI", 9), wraplength=px(440),
                 justify="left",
                 text="No se encontró ningún navegador compatible. Use «Buscar el programa…» "
                      "o continúe para abrir el sistema en una pestaña del navegador.",
                 ).pack(anchor="w", pady=(px(8), 0))

        def sin_navegador(_evento=None):
            resultado["valor"] = {"clave": "", "nombre": "", "ruta": ""}
            raiz.destroy()

        boton.bind("<Button-1>", sin_navegador)
        raiz.bind("<Return>", sin_navegador)
    else:
        refrescar(actual)
        raiz.bind("<Return>", continuar)
    raiz.bind("<Escape>", lambda _e: raiz.destroy())

    raiz.update_idletasks()
    ancho, alto = raiz.winfo_reqwidth(), raiz.winfo_reqheight()
    x = (raiz.winfo_screenwidth() - ancho) // 2
    y = max((raiz.winfo_screenheight() - alto) // 2 - px(30), 0)
    raiz.geometry(f"{ancho}x{alto}+{x}+{y}")
    combo.bind("<<ComboboxSelected>>", lambda _e: (combo.selection_clear(), raiz.focus_set()))
    raiz.after(80, lambda: (_al_frente(raiz), raiz.focus_force()))
    raiz.mainloop()
    return resultado["valor"]


def avisar_error(titulo: str, mensaje: str) -> None:
    """Un aviso de Windows para cuando el programa no puede arrancar."""
    try:
        ctypes.windll.user32.MessageBoxW(None, mensaje, titulo, 0x10 | 0x40000)
    except (AttributeError, OSError):
        log.error("%s: %s", titulo, mensaje)
