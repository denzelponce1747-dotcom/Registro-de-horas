"""Fábrica de la aplicación.

Arma el servidor interno: las pantallas de siempre (sesión, colaborador y
administración), las de Ajustes y la conexión con SharePoint, y lo que une
todo con los datos de la nube.

La aplicación funciona de dos maneras:

- **Con SharePoint** (lo normal): recibe un `Almacen` y cada cambio se
  guarda en la carpeta de la empresa (`app/nube/`).
- **Local**, sin almacén: la base es un archivo y nada más. La usan las
  pruebas de las reglas de negocio.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import config as cfg
from . import db as base_de_datos
from .seguridad import registrar_seguridad

# Rutas que se atienden aunque todavía no haya datos de SharePoint: el
# asistente de la primera vez, Ajustes, los estilos…
LIBRES_DE_NUBE = (
    "/static/", "/estado", "/adios", "/bienvenida", "/conexion",
    "/ajustes", "/conectando", "/favicon.ico", "/marca/", "/ayuda",
)


# Peticiones que no son pantallas: no muestran los avisos del correo.
SIN_AVISOS_CORREO = ("/static/", "/estado", "/adios", "/favicon.ico", "/marca/",
                     "/reportes/", "/ayuda/")


def crear_app(configuracion=None, almacen=None, vida=None) -> Flask:
    aplicacion = Flask(
        __name__,
        template_folder=str(cfg.CARPETA_PLANTILLAS),
        static_folder=str(cfg.CARPETA_ESTATICOS),
    )
    ajustes = configuracion or cfg.configuracion()

    aplicacion.config["CONFIGURACION"] = ajustes
    aplicacion.config["SECRETO_SESION"] = ajustes.asegurar_secreto()
    aplicacion.config["ALMACEN"] = almacen
    aplicacion.config["VIDA"] = vida
    aplicacion.config["RUTA_BASE"] = str(almacen.ruta_base if almacen is not None else cfg.ARCHIVO_BASE)

    aplicacion.secret_key = aplicacion.config["SECRETO_SESION"]
    aplicacion.config["SESSION_COOKIE_NAME"] = "majerie_avisos"
    aplicacion.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    aplicacion.jinja_env.trim_blocks = True
    aplicacion.jinja_env.lstrip_blocks = True

    base_de_datos.registrar(aplicacion)
    registrar_seguridad(aplicacion)
    _registrar_guia(aplicacion)
    _registrar_globales(aplicacion)

    from .vistas.ajustes import ajustes as pantallas_ajustes
    from .vistas.panel import panel
    from .vistas.registro import registro
    from .vistas.sesion import sesion

    aplicacion.register_blueprint(sesion)
    aplicacion.register_blueprint(registro)
    aplicacion.register_blueprint(panel)
    aplicacion.register_blueprint(pantallas_ajustes)

    if almacen is not None:
        from .nube.escrituras import Sincronizacion

        aplicacion.wsgi_app = Sincronizacion(
            aplicacion.wsgi_app, lambda: aplicacion.config["ALMACEN"]
        )
        from .excel_auto import ExcelAutomatico

        aplicacion.config["EXCEL"] = ExcelAutomatico(aplicacion, almacen)

    # Los avisos por correo salen cuando el cambio ya quedó guardado: esta
    # capa va por fuera de todo (ver `app/correo.py`).
    from .correo import AvisosTrasGuardar

    aplicacion.wsgi_app = AvisosTrasGuardar(aplicacion.wsgi_app, aplicacion)

    @aplicacion.get("/estado")
    def estado():
        """Lo que la pantalla consulta cada pocos segundos.

        Es también el latido de la ventana: mientras alguna lo pida, el
        programa sigue abierto.
        """
        if vida is not None:
            vida.latido(request.args.get("c", ""))
        nube = None
        if almacen is not None:
            if request.args.get("comprobar") and almacen.configurado:
                # «Comprobar ahora»: se espera la respuesta de SharePoint
                # para mostrar el resultado de inmediato.
                try:
                    almacen.comprobar(forzar=True)
                except Exception:
                    pass
            elif request.args.get("refrescar"):
                almacen.pedir_comprobacion()
            nube = almacen.estado()
            nube["puede_guardar"] = not nube["solo_lectura"]
        respuesta = jsonify({"app": cfg.ID_APP, "version": cfg.VERSION, "nube": nube})
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    @aplicacion.post("/adios")
    def adios():
        """La ventana se cierra (lo manda `navigator.sendBeacon`)."""
        if vida is not None:
            vida.adios(request.get_data(as_text=True)[:64] or request.args.get("c") or None)
        return "", 204

    @aplicacion.get("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="iconos/favicon-32.png"))

    @aplicacion.errorhandler(400)
    def _peticion_rara(_error):
        return (
            render_template(
                "aviso.html",
                titulo="Petición no válida",
                descripcion="El sistema solo atiende a su propia ventana.",
                nombre_icono="escudo-alerta",
                tono="alerta",
            ),
            400,
        )

    @aplicacion.errorhandler(404)
    def _no_encontrado(_error):
        return (
            render_template(
                "aviso.html",
                titulo="Esta dirección no existe",
                descripcion="Revise el enlace o vuelva al inicio del sistema.",
                nombre_icono="busqueda-vacia",
            ),
            404,
        )

    @aplicacion.errorhandler(500)
    def _fallo(_error):
        return (
            render_template(
                "aviso.html",
                titulo="Algo salió mal",
                descripcion=(
                    "No fue posible completar la operación. Vuelva a intentarlo; "
                    "si el problema sigue, avise a la administración."
                ),
                nombre_icono="aviso",
                tono="alerta",
            ),
            500,
        )

    return aplicacion


def _registrar_guia(aplicacion: Flask) -> None:
    """Lleva a la persona a donde corresponde según el estado de la nube."""
    from flask import flash

    from .nube.escrituras import MARCA_AVISO

    @aplicacion.before_request
    def _guia():
        almacen = aplicacion.config.get("ALMACEN")
        # Un cambio que no se pudo guardar en SharePoint (sin conexión, base
        # en solo lectura…) vuelve a la pantalla de donde vino con el
        # aviso, en vez de perderse en silencio.
        aviso = request.environ.get(MARCA_AVISO)
        if aviso and request.method not in ("GET", "HEAD"):
            flash(f"No se guardó. {aviso}", "error")
            destino = request.referrer or url_for("sesion.raiz")
            return redirect(destino)
        # Resultado de los avisos por correo que salieron tras el último
        # cambio: se muestra en la pantalla a la que se vuelve.
        if request.method == "GET" and not request.path.startswith(SIN_AVISOS_CORREO):
            from .correo import resultados_por_mostrar

            for categoria, mensaje in resultados_por_mostrar(aplicacion):
                flash(mensaje, categoria)
        # Microsoft devuelve el inicio de sesión a la raíz con `code` y
        # `state`: se atiende aquí, antes que nada.
        if almacen is not None and request.path == "/" and request.args.get("state"):
            if "code" in request.args or "error" in request.args:
                from .vistas.ajustes import atender_retorno_microsoft

                return atender_retorno_microsoft()

        if almacen is None or request.path.startswith(LIBRES_DE_NUBE):
            return None
        if not almacen.configurado:
            return redirect(url_for("ajustes.bienvenida"))
        if not almacen.hay_copia_local:
            return redirect(url_for("ajustes.conectando", volver=request.full_path))
        return None


def _registrar_globales(aplicacion: Flask) -> None:
    """Deja en las plantillas lo que usan en casi todas las pantallas."""
    from .auth import (
        IDENTIDADES_ADMIN,
        LARGO_MINIMO_CONTRASENA,
        iniciales_identidad,
        usuario_de_sesion,
    )
    from .lib import tiempo
    from .lib.almuerzo import formatear_almuerzo, formatear_almuerzo_corto
    from .lib.aprobaciones import ETIQUETAS_ACCION, VENTANA_APROBACION_DIAS
    from .lib.ausencias import ETIQUETAS_ESTADO, ETIQUETAS_TIPO, TIPOS_AUSENCIA
    from .lib.tarifas import MONEDAS, formatear_montos, formatear_tarifa
    from .marca import icono, logo, logo_microsoft, marca_compacta

    aplicacion.jinja_env.globals.update(
        logo=logo,
        logo_microsoft=logo_microsoft,
        marca_compacta=marca_compacta,
        icono=icono,
        iniciales_identidad=iniciales_identidad,
        IDENTIDADES=IDENTIDADES_ADMIN,
        LARGO_MINIMO=LARGO_MINIMO_CONTRASENA,
        MONEDAS=MONEDAS,
        TIPOS_AUSENCIA=TIPOS_AUSENCIA,
        ETIQUETAS_ACCION=ETIQUETAS_ACCION,
        ETIQUETAS_TIPO=ETIQUETAS_TIPO,
        ETIQUETAS_ESTADO=ETIQUETAS_ESTADO,
        VENTANA_APROBACION=VENTANA_APROBACION_DIAS,
        VERSION=cfg.VERSION,
        formatear_numero=tiempo.formatear_numero,
        formatear_horas=tiempo.formatear_horas,
        formatear_horas_reloj=tiempo.formatear_horas_reloj,
        formatear_monto=tiempo.formatear_monto,
        formatear_fecha=tiempo.formatear_fecha,
        formatear_fecha_larga=tiempo.formatear_fecha_larga,
        formatear_dia_semana=tiempo.formatear_dia_semana,
        formatear_rango=tiempo.formatear_rango,
        formatear_mes=tiempo.formatear_mes,
        formatear_momento=tiempo.formatear_momento,
        formatear_tamano=tiempo.formatear_tamano,
        valor_entrada=tiempo.valor_entrada,
        formatear_montos=formatear_montos,
        formatear_tarifa=formatear_tarifa,
        formatear_almuerzo=formatear_almuerzo,
        formatear_almuerzo_corto=formatear_almuerzo_corto,
        hoy_iso=tiempo.hoy_iso,
        sumar_dias=tiempo.sumar_dias,
    )

    @aplicacion.context_processor
    def _contexto():
        almacen = aplicacion.config.get("ALMACEN")
        ajustes = aplicacion.config["CONFIGURACION"]
        try:
            usuario = usuario_de_sesion()
        except Exception:
            usuario = None
        return {
            "usuario": usuario,
            "nube": almacen.estado() if almacen is not None else None,
            "tema": ajustes["tema"] or "auto",
        }

    def _version_estatica(nombre: str) -> str:
        """Dirección de un archivo estático con su fecha pegada detrás.

        Sin esto, la ventana se queda con la hoja de estilo vieja después de
        una actualización y la pantalla se ve rota hasta que alguien recarga.
        """
        ruta = Path(aplicacion.static_folder or "") / nombre
        marca = int(ruta.stat().st_mtime) if ruta.is_file() else 0
        return url_for("static", filename=nombre, v=marca)

    aplicacion.jinja_env.globals["estatico"] = _version_estatica
