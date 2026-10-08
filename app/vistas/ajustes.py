"""Ajustes de esta computadora y conexión con SharePoint.

- `/bienvenida`: la guía de la primera vez. Se pega el enlace de la carpeta
  de SharePoint que dio la empresa, se conecta la cuenta de Microsoft y,
  según lo que haya en la carpeta, se entra directo, se empieza de cero o se
  suben los datos de la versión anterior.
- `/ajustes`: lo mismo a posteriori, más el navegador de la ventana, el tema,
  las copias de seguridad y la recuperación del acceso de administración.
- `/conectando`: espera mientras llegan los datos la primera vez.

Todo esto es de la computadora, no de la persona: se puede usar sin haber
iniciado sesión en el sistema.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .. import config as cfg
from ..auth import usuario_de_sesion

log = logging.getLogger("majerie.ajustes")

ajustes = Blueprint("ajustes", __name__)


def _almacen():
    return current_app.config.get("ALMACEN")


def _configuracion():
    return current_app.config["CONFIGURACION"]


def _volver_seguro(destino: str, por_omision: str) -> str:
    """Solo direcciones internas: nada de redirigir a sitios ajenos."""
    destino = (destino or "").strip()
    if destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return por_omision


def _retorno_microsoft() -> str:
    """`http://localhost:PUERTO`, la dirección registrada en Entra ID."""
    puerto = request.host.rsplit(":", 1)[-1] if ":" in request.host.split("]")[-1] else "80"
    return f"http://localhost:{puerto}"


def _cliente_id() -> str:
    from ..nube.microsoft import CLIENTE_ID_INCLUIDO

    return (_configuracion().sharepoint.get("cliente_id") or CLIENTE_ID_INCLUIDO or "").strip()


def _texto_error(fallo: Exception) -> str:
    return getattr(fallo, "mensaje", "") or str(fallo) or "Ocurrió un error inesperado."


# -- Cuenta de Microsoft -------------------------------------------------------
#
#
def atender_retorno_microsoft():
    """Microsoft vuelve a `http://localhost:PUERTO/?code=…&state=…`.

    Lo llama la guía de la aplicación cuando la raíz trae esos parámetros.
    """
    from ..nube.microsoft import ErrorMicrosoft

    almacen = _almacen()
    estado = request.args.get("state", "")
    if almacen is None or not almacen.cuenta.es_retorno(estado):
        flash("Ese ingreso con Microsoft ya no es válido. Vuelva a intentarlo.", "error")
        return redirect(url_for("ajustes.ajustes_inicio"))

    if request.args.get("error"):
        fallo = almacen.cuenta.error_de_retorno(
            estado, request.args.get("error", ""), request.args.get("error_description", "")
        )
        flash(_texto_error(fallo), "error")
        return redirect(url_for("ajustes.bienvenida") if not almacen.configurado
                        else url_for("ajustes.ajustes_inicio"))

    try:
        datos = almacen.cuenta.completar_ingreso(request.args.get("code", ""), estado)
    except ErrorMicrosoft as fallo:
        flash(_texto_error(fallo), "error")
        return redirect(url_for("ajustes.bienvenida") if not almacen.configurado
                        else url_for("ajustes.ajustes_inicio"))
    # Con la sesión nueva, se vuelve a mirar SharePoint enseguida.
    almacen._anotar(necesita_sesion=False, error="")
    almacen.pedir_comprobacion()
    nombre = datos.get("nombre") or datos.get("correo") or "su cuenta"
    flash(f"Cuenta de Microsoft conectada: {nombre}.", "exito")
    return redirect(_volver_seguro(datos.get("volver", ""), url_for("ajustes.ajustes_inicio")))


@ajustes.get("/conexion/microsoft")
def conectar_microsoft():
    """Manda a la página de Microsoft para entrar con la cuenta de trabajo."""
    almacen = _almacen()
    if almacen is None:
        return redirect(url_for("sesion.raiz"))

    volver = _volver_seguro(request.args.get("volver", ""), url_for("ajustes.ajustes_inicio"))
    cliente_id = _cliente_id()
    sp = _configuracion().sharepoint
    inquilino = sp.get("inquilino") or ""
    if not cliente_id:
        flash(
            "Falta el identificador de la aplicación de Microsoft. Escríbalo en «Opciones "
            "avanzadas» (se lo da el administrador de Microsoft 365).",
            "error",
        )
        return redirect(url_for("ajustes.bienvenida") if not almacen.configurado
                        else url_for("ajustes.ajustes_inicio", seccion="avanzado"))
    if not inquilino:
        flash("Primero pegue el enlace de la carpeta de SharePoint.", "error")
        return redirect(url_for("ajustes.bienvenida"))

    url = almacen.cuenta.url_de_ingreso(
        cliente_id=cliente_id,
        inquilino=inquilino,
        retorno=_retorno_microsoft(),
        volver=volver,
        pista=almacen.cuenta.info().get("correo", ""),
    )
    return redirect(url)


@ajustes.post("/conexion/salir")
def desconectar_microsoft():
    almacen = _almacen()
    if almacen is not None:
        almacen.cuenta.olvidar()
        almacen._anotar(necesita_sesion=False)
    flash("Se desconectó la cuenta de Microsoft de esta computadora.", "exito")
    return redirect(url_for("ajustes.ajustes_inicio"))


# -- Bienvenida ------------------------------------------------------------------
#
#
def _paso_actual(almacen) -> str:
    sp = _configuracion().sharepoint
    if almacen.configurado:
        return "listo"
    if not sp.get("enlace"):
        return "enlace"
    if not almacen.cuenta.conectada:
        return "cuenta"
    if not sp.get("drive_id"):
        return "carpeta"
    return "vacia"


@ajustes.route("/bienvenida", methods=["GET", "POST"])
def bienvenida():
    almacen = _almacen()
    if almacen is None:
        return redirect(url_for("sesion.raiz"))

    if request.method == "POST":
        return _recibir_enlace(almacen, volver=url_for("ajustes.carpeta"))

    paso = _paso_actual(almacen)
    if paso == "listo":
        return redirect(url_for("sesion.raiz"))
    if paso == "carpeta":
        return redirect(url_for("ajustes.carpeta"))

    sp = _configuracion().sharepoint
    return render_template(
        "bienvenida.html",
        paso=paso,
        enlace=sp.get("enlace", ""),
        cliente_id=sp.get("cliente_id", ""),
        cliente_incluido=bool(_cliente_id_incluido()),
        inquilino=sp.get("inquilino", ""),
        cuenta=almacen.cuenta.info(),
        hay_anterior=cfg.BASE_VERSION_ANTERIOR.is_file(),
        nombre_carpeta=sp.get("nombre_carpeta", ""),
        carpeta_url=sp.get("web_url", ""),
    )


def _cliente_id_incluido() -> str:
    from ..nube.microsoft import CLIENTE_ID_INCLUIDO

    return CLIENTE_ID_INCLUIDO


def _recibir_enlace(almacen, volver: str):
    """Guarda el enlace pegado y sigue con la cuenta de Microsoft."""
    from ..nube.enlaces import EnlaceInvalido, interpretar
    from ..nube.microsoft import descubrir_inquilino, es_identificador

    configuracion = _configuracion()
    texto = request.form.get("enlace", "")
    cliente_id = (request.form.get("cliente_id") or "").strip()
    inquilino = (request.form.get("inquilino") or "").strip()
    destino_error = request.form.get("desde") or url_for("ajustes.bienvenida")

    try:
        enlace = interpretar(texto)
    except EnlaceInvalido as fallo:
        flash(str(fallo), "error")
        return redirect(_volver_seguro(destino_error, url_for("ajustes.bienvenida")))

    if cliente_id and not es_identificador(cliente_id):
        flash("El identificador de la aplicación tiene la forma xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.",
              "error")
        return redirect(_volver_seguro(destino_error, url_for("ajustes.bienvenida")))

    if not inquilino:
        inquilino = descubrir_inquilino(enlace.anfitrion, enlace.inquilino_probable)

    anterior = configuracion.sharepoint
    cambio_de_empresa = anterior.get("inquilino") and anterior.get("inquilino") != inquilino
    configuracion.guardar_sharepoint(
        enlace=enlace.original,
        anfitrion=enlace.anfitrion,
        inquilino=inquilino,
        cliente_id=cliente_id or anterior.get("cliente_id") or None,
        # La carpeta se vuelve a buscar con el enlace nuevo.
        drive_id=None, carpeta_id=None, carpeta_sistema_id=None, archivo_id=None,
    )
    if cambio_de_empresa:
        almacen.cuenta.olvidar()

    cuenta = almacen.cuenta.info()
    if cuenta.get("conectada") and (not cuenta.get("tid") or cuenta.get("tid") == inquilino
                                    or "." in inquilino):
        return redirect(volver)
    return redirect(url_for("ajustes.conectar_microsoft", volver=volver))


@ajustes.get("/bienvenida/carpeta")
def carpeta():
    """Ya hay enlace y cuenta: se busca la carpeta y se mira qué tiene."""
    from ..nube.enlaces import EnlaceInvalido, interpretar
    from ..nube.microsoft import ErrorMicrosoft, NecesitaIniciarSesion

    almacen = _almacen()
    if almacen is None:
        return redirect(url_for("sesion.raiz"))
    sp = _configuracion().sharepoint
    if not sp.get("enlace"):
        return redirect(url_for("ajustes.bienvenida"))
    if not almacen.cuenta.conectada:
        return redirect(url_for("ajustes.conectar_microsoft", volver=url_for("ajustes.carpeta")))

    try:
        enlace = interpretar(sp["enlace"])
        elemento = almacen.resolver_carpeta(enlace)
        examen = almacen.examinar(elemento)
        almacen.recordar_carpeta(enlace, examen)
    except NecesitaIniciarSesion:
        return redirect(url_for("ajustes.conectar_microsoft", volver=url_for("ajustes.carpeta")))
    except (EnlaceInvalido, ErrorMicrosoft) as fallo:
        _configuracion().guardar_sharepoint(drive_id=None, carpeta_id=None)
        flash(_texto_error(fallo), "error")
        return redirect(url_for("ajustes.bienvenida"))

    if examen.get("archivo"):
        try:
            almacen.comprobar(forzar=True)
        except ErrorMicrosoft as fallo:
            flash(_texto_error(fallo), "error")
            return redirect(url_for("ajustes.conectando"))
        almacen.arrancar_vigilante()
        flash(
            f"Conectado a la carpeta «{examen['carpeta'].get('name', '')}». Ya puede ingresar "
            "con su usuario y contraseña.",
            "exito",
        )
        return redirect(url_for("sesion.ingresar"))
    # Carpeta sin datos: la bienvenida ofrece empezar.
    return redirect(url_for("ajustes.bienvenida"))


@ajustes.post("/bienvenida/empezar")
def empezar():
    """La carpeta está vacía: se crean los datos del sistema."""
    from ..auth import cifrar_contrasena, problema_contrasena
    from ..lib.usuarios import normalizar_usuario, problema_usuario
    from ..nube.microsoft import ErrorMicrosoft

    almacen = _almacen()
    if almacen is None or almacen.configurado:
        return redirect(url_for("sesion.raiz"))
    if not _configuracion().sharepoint.get("drive_id"):
        return redirect(url_for("ajustes.bienvenida"))

    origen = request.form.get("origen", "nueva")
    try:
        if origen == "anterior":
            contenido = _base_anterior()
        elif origen == "archivo":
            contenido = _base_de_archivo(request.files.get("archivo"))
        else:
            usuario = normalizar_usuario(request.form.get("usuario", "") or "majerie")
            contrasena = request.form.get("contrasena", "")
            problema = problema_usuario(usuario) or problema_contrasena(contrasena)
            if not problema and contrasena != request.form.get("repetir", ""):
                problema = "Las dos contraseñas no coinciden."
            if problema:
                flash(problema, "error")
                return redirect(url_for("ajustes.bienvenida", origen="nueva"))
            contenido = _base_nueva(usuario, cifrar_contrasena(contrasena))
    except ValueError as fallo:
        flash(str(fallo), "error")
        return redirect(url_for("ajustes.bienvenida"))
    # Quien crea el sistema puede recuperar el acceso de administración.
    contenido = _con_recuperacion(contenido, almacen.cuenta.info())

    try:
        almacen.asegurar_carpeta_sistema()
        almacen.probar_concurrencia()
        almacen.publicar_base_inicial(contenido)
    except ErrorMicrosoft as fallo:
        from ..nube.graph import YaExiste

        if isinstance(fallo, YaExiste):
            # Otra computadora creó los datos al mismo tiempo: se usan esos.
            return redirect(url_for("ajustes.carpeta"))
        flash(_texto_error(fallo), "error")
        return redirect(url_for("ajustes.bienvenida"))
    # La base vieja ya está arriba.
    if origen == "anterior":
        _apartar_base_anterior()
    almacen.arrancar_vigilante()
    flash(
        "Los datos del sistema ya viven en el SharePoint de la empresa. Ingrese con su "
        "usuario y contraseña de siempre."
        if origen != "nueva"
        else "El sistema quedó creado en el SharePoint de la empresa. Ingrese con la cuenta "
        "de administración que acaba de crear.",
        "exito",
    )
    return redirect(url_for("sesion.ingresar"))


def _base_vacia() -> sqlite3.Connection:
    from ..migraciones import aplicar_esquema, migrar

    conexion = sqlite3.connect(":memory:")
    conexion.row_factory = sqlite3.Row
    aplicar_esquema(conexion)
    migrar(conexion)
    anio = date.today().year
    conexion.execute(
        "INSERT INTO app_settings (id, period_from, period_to) VALUES (1, ?, ?) "
        "ON CONFLICT (id) DO NOTHING",
        (f"{anio}-01-01", f"{anio}-12-31"),
    )
    return conexion


def _base_nueva(usuario: str, huella: str) -> bytes:
    conexion = _base_vacia()
    conexion.execute(
        """INSERT INTO users (id, username, name, email, role, password_hash, active)
           VALUES ('adm-majerie', ?, 'Administración MaJerie', '', 'administrador', ?, 1)""",
        (usuario, huella),
    )
    conexion.execute(
        "INSERT INTO meta (clave, valor) VALUES ('creado', ?)",
        (datetime.now().isoformat(timespec="seconds"),),
    )
    conexion.commit()
    contenido = conexion.serialize()
    conexion.close()
    return contenido


def _normalizar_base(crudo: bytes) -> bytes:
    """Una base SQLite cualquiera, comprobada y al día con el esquema."""
    from ..migraciones import ESQUEMA_ACTUAL, migrar

    if not crudo.startswith(b"SQLite format 3\x00"):
        raise ValueError("El archivo no es una base de datos del sistema.")
    # Una base en modo WAL no se puede abrir desde memoria: se pasa al modo
    # de diario clásico cambiando los dos bytes de versión de la cabecera
    # (es lo que hace SQLite al cambiar de modo).
    if crudo[18:20] == b"\x02\x02":
        crudo = crudo[:18] + b"\x01\x01" + crudo[20:]
    conexion = sqlite3.connect(":memory:")
    try:
        conexion.deserialize(crudo)
        if conexion.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("La base de datos está dañada.")
        tablas = {f[0] for f in conexion.execute("SELECT name FROM sqlite_master")}
        if "users" not in tablas or "time_entries" not in tablas:
            raise ValueError("El archivo no es una base de datos del Sistema de Registro de Horas.")
        if migrar(conexion) > ESQUEMA_ACTUAL:
            raise ValueError("La copia es de una versión más nueva del programa.")
        conexion.execute("PRAGMA journal_mode = DELETE")
        conexion.commit()
        return conexion.serialize()
    except sqlite3.DatabaseError as fallo:
        raise ValueError(f"No se pudo leer la base: {fallo}") from fallo
    finally:
        conexion.close()


# La base de la versión anterior y sus dos acompañantes del modo WAL.
#
_ARCHIVOS_SQLITE = ("", "-wal", "-shm")


def _copiar_sqlite(origen: str, uri: bool = False) -> bytes:
    """Copia consistente (API de respaldo de SQLite) de una base, en memoria."""
    fuente = sqlite3.connect(origen, uri=uri)
    memoria = sqlite3.connect(":memory:")
    try:
        fuente.backup(memoria)
        return memoria.serialize()
    finally:
        memoria.close()
        fuente.close()


def _base_anterior() -> bytes:
    """Los datos de la versión anterior, sin modificar el original.

    Se leen en solo lectura, con lo pendiente en el `-wal` incluido. Si el
    programa viejo se cerró de golpe, SQLite necesitaría escribir para
    recuperar ese `-wal`: entonces se trabaja sobre una copia de los tres
    archivos.
    """
    original = cfg.BASE_VERSION_ANTERIOR
    if not original.is_file():
        raise ValueError("No hay datos de la versión anterior en esta computadora.")
    try:
        crudo = _copiar_sqlite(original.as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        with tempfile.TemporaryDirectory(prefix="majerie-anterior-") as carpeta:
            for sufijo in _ARCHIVOS_SQLITE:
                archivo = original.with_name(original.name + sufijo)
                if archivo.is_file():
                    shutil.copy2(archivo, Path(carpeta) / archivo.name)
            try:
                crudo = _copiar_sqlite(str(Path(carpeta) / original.name))
            except sqlite3.Error as fallo:
                raise ValueError(f"No se pudieron leer los datos anteriores: {fallo}") from fallo
    return _normalizar_base(crudo)


def _base_de_archivo(archivo) -> bytes:
    from ..nube.cifrado import ArchivoIlegible, MAGIA, abrir

    if not archivo or not archivo.filename:
        raise ValueError("Elija el archivo de la copia de seguridad.")
    datos = archivo.read()
    if datos.startswith(MAGIA):
        try:
            datos, _cabecera = abrir(datos)
        except ArchivoIlegible as fallo:
            raise ValueError(str(fallo)) from fallo
    return _normalizar_base(datos)


def _con_recuperacion(contenido: bytes, cuenta: dict) -> bytes:
    """Anota la cuenta de Microsoft que creó el sistema como la que puede
    recuperar el acceso de administración si se pierde la contraseña."""
    if not cuenta.get("oid"):
        return contenido
    conexion = sqlite3.connect(":memory:")
    try:
        conexion.deserialize(contenido)
        fila = conexion.execute("SELECT valor FROM meta WHERE clave = 'recuperacion'").fetchone()
        lista = json.loads(fila[0]) if fila else []
        if not any(c.get("oid") == cuenta["oid"] for c in lista):
            lista.append({"oid": cuenta["oid"], "correo": cuenta.get("correo", ""),
                          "nombre": cuenta.get("nombre", "")})
        conexion.execute(
            "INSERT INTO meta (clave, valor) VALUES ('recuperacion', ?) "
            "ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor",
            (json.dumps(lista, ensure_ascii=False),),
        )
        conexion.commit()
        return conexion.serialize()
    finally:
        conexion.close()


def _apartar_base_anterior() -> None:
    """La base vieja ya está en SharePoint: se aparta para no ofrecerla otra
    vez, pero no se borra.

    Va a una carpeta propia junto con su `-wal` y su `-shm`: separados, lo
    pendiente del `-wal` quedaría huérfano.
    """
    original = cfg.BASE_VERSION_ANTERIOR
    destino = original.parent / f"version-anterior-subida-{date.today():%Y-%m-%d}"
    numero = 2
    while (destino / original.name).exists():
        destino = original.parent / f"version-anterior-subida-{date.today():%Y-%m-%d}-{numero}"
        numero += 1
    try:
        destino.mkdir(parents=True, exist_ok=True)
        # Primero la base: si no se puede mover (la versión vieja sigue
        # abierta), no se toca nada más.
        os.replace(original, destino / original.name)
    except OSError:
        log.warning("No se pudo apartar la base anterior (¿sigue abierta la versión vieja?).")
        return
    for sufijo in _ARCHIVOS_SQLITE[1:]:
        acompanante = original.with_name(original.name + sufijo)
        try:
            if acompanante.exists():
                os.replace(acompanante, destino / acompanante.name)
        except OSError:
            log.warning("No se pudo apartar %s.", acompanante.name)


@ajustes.get("/conectando")
def conectando():
    """Mientras llegan los datos de SharePoint por primera vez."""
    almacen = _almacen()
    if almacen is None or not almacen.configurado:
        return redirect(url_for("ajustes.bienvenida"))
    volver = _volver_seguro(request.args.get("volver", ""), url_for("sesion.raiz"))
    if almacen.hay_copia_local:
        return redirect(volver)
    almacen.arrancar_vigilante()
    almacen.pedir_comprobacion()
    return render_template("conectando.html", volver=volver)


# -- Ajustes ---------------------------------------------------------------------
#
#
@ajustes.get("/ajustes")
def ajustes_inicio():
    from ..escritorio import navegadores

    almacen = _almacen()
    configuracion = _configuracion()
    usuario = _usuario_o_nada()
    lista = navegadores.detectar()
    actual = navegadores.resolver(configuracion, lista)
    sp = configuracion.sharepoint

    return render_template(
        "ajustes.html",
        seccion=request.args.get("seccion", ""),
        navegadores_lista=lista,
        navegador_actual=actual,
        sp=sp,
        cliente_incluido=bool(_cliente_id_incluido()),
        cliente_id=_cliente_id(),
        cuenta=almacen.cuenta.info() if almacen is not None else {},
        es_admin=bool(usuario and usuario.role == "administrador"),
        puede_recuperar=_puede_recuperar(),
        carpeta_datos=str(cfg.CARPETA_DATOS),
        archivo_registro=str(cfg.ARCHIVO_REGISTRO),
        excel_automatico=configuracion["excel_automatico"],
        excel_url=(current_app.config.get("EXCEL").estado.get("url", "")
                   if current_app.config.get("EXCEL") is not None else ""),
        version=cfg.VERSION,
    )


def _usuario_o_nada():
    try:
        return usuario_de_sesion()
    except Exception:
        return None


@ajustes.post("/ajustes/carpeta")
def cambiar_carpeta():
    almacen = _almacen()
    if almacen is None:
        return redirect(url_for("ajustes.ajustes_inicio"))
    # Otra carpeta: se olvida la actual (y su copia local) y se sigue como
    # en la bienvenida.
    almacen.desconectar()
    return _recibir_enlace(almacen, volver=url_for("ajustes.carpeta"))


@ajustes.post("/ajustes/desconectar")
def desconectar():
    almacen = _almacen()
    if almacen is not None:
        almacen.desconectar()
    flash("Esta computadora ya no está conectada a la carpeta de SharePoint.", "exito")
    return redirect(url_for("ajustes.bienvenida"))


@ajustes.post("/ajustes/avanzado")
def avanzado():
    from ..nube.microsoft import es_identificador

    configuracion = _configuracion()
    cliente_id = (request.form.get("cliente_id") or "").strip()
    inquilino = (request.form.get("inquilino") or "").strip()
    if cliente_id and not es_identificador(cliente_id):
        flash("El identificador de la aplicación tiene la forma xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.",
              "error")
        return redirect(url_for("ajustes.ajustes_inicio", seccion="avanzado"))
    anterior = configuracion.sharepoint
    configuracion.guardar_sharepoint(
        cliente_id=cliente_id or None,
        inquilino=inquilino or anterior.get("inquilino") or None,
    )
    if (cliente_id or None) != anterior.get("cliente_id"):
        almacen = _almacen()
        if almacen is not None:
            almacen.cuenta.olvidar()
        flash("Identificador guardado. Vuelva a conectar la cuenta de Microsoft.", "exito")
    else:
        flash("Opciones guardadas.", "exito")
    return redirect(url_for("ajustes.ajustes_inicio", seccion="avanzado"))


@ajustes.post("/ajustes/sincronizar")
def sincronizar():
    from ..nube.microsoft import ErrorMicrosoft

    almacen = _almacen()
    if almacen is not None and almacen.configurado:
        try:
            nuevo = almacen.comprobar(forzar=True)
            flash("Llegaron cambios de SharePoint." if nuevo
                  else "Todo al día: no había cambios nuevos.", "exito")
        except ErrorMicrosoft as fallo:
            flash(_texto_error(fallo), "error")
    return redirect(request.referrer or url_for("ajustes.ajustes_inicio"))


@ajustes.post("/ajustes/navegador")
def elegir_navegador():
    from ..escritorio import navegadores

    configuracion = _configuracion()
    clave = (request.form.get("navegador") or "").strip()
    if clave == "otro":
        ruta = (request.form.get("navegador_ruta") or "").strip()
        if not navegadores.es_ejecutable_valido(ruta):
            flash("Ese programa no existe o no es un navegador.", "error")
            return redirect(url_for("ajustes.ajustes_inicio", seccion="ventana"))
        configuracion.guardar(navegador="otro", navegador_ruta=ruta)
    elif any(n["clave"] == clave for n in navegadores.detectar()):
        configuracion.guardar(navegador=clave)
    else:
        flash("Ese navegador no está instalado.", "error")
        return redirect(url_for("ajustes.ajustes_inicio", seccion="ventana"))
    flash("Navegador guardado. Se usará la próxima vez que abra el programa.", "exito")
    return redirect(url_for("ajustes.ajustes_inicio", seccion="ventana"))


@ajustes.post("/ajustes/navegador/buscar")
def buscar_navegador():
    """Abre el cuadro de Windows para elegir el programa del navegador."""
    from ..escritorio import dialogos, navegadores

    try:
        ruta = dialogos.elegir_ejecutable("Elegir el programa del navegador")
    except dialogos.Ocupado:
        return jsonify({"ok": False, "error": "Ya hay un cuadro abierto."}), 409
    if not ruta:
        return jsonify({"ok": False, "cancelado": True})
    if not navegadores.es_ejecutable_valido(ruta) or os.path.basename(ruta).lower() in (
        "firefox.exe", "iexplore.exe", "opera.exe", "launcher.exe",
    ):
        return jsonify({"ok": False, "error": "Ese navegador no puede abrir el sistema en una ventana propia."})

    return jsonify({"ok": True, "ruta": ruta, "nombre": os.path.splitext(os.path.basename(ruta))[0]})


@ajustes.post("/ajustes/tema")
def tema():
    valor = request.form.get("tema", "auto")
    if valor not in ("auto", "claro", "oscuro"):
        valor = "auto"
    _configuracion().guardar(tema=valor)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "tema": valor})
    return redirect(request.referrer or url_for("ajustes.ajustes_inicio"))


@ajustes.post("/ajustes/excel")
def excel():
    activo = request.form.get("activo") == "1"
    _configuracion().guardar(excel_automatico=activo)
    flash("El Excel en SharePoint se actualizará solo." if activo
          else "El Excel en SharePoint ya no se actualizará solo.", "exito")
    return redirect(url_for("ajustes.ajustes_inicio", seccion="excel"))


# -- Copias de seguridad (solo administración) -----------------------------------
#
#
def _exigir_admin():
    usuario = _usuario_o_nada()
    if not usuario or usuario.role != "administrador":
        flash("Las copias de seguridad las maneja la administración. Ingrese primero.", "error")
        return redirect(url_for("sesion.ingresar"))
    return None


@ajustes.get("/ajustes/respaldos")
def respaldos():
    from ..nube.microsoft import ErrorMicrosoft

    negado = _exigir_admin()
    if negado:
        return negado
    almacen = _almacen()
    copias, error = [], ""
    if almacen is not None and almacen.configurado:
        try:
            copias = almacen.respaldos()
        except ErrorMicrosoft as fallo:
            error = _texto_error(fallo)
    return render_template("respaldos.html", copias=copias, error=error)


@ajustes.get("/ajustes/respaldos/actual")
def descargar_actual():
    negado = _exigir_admin()
    if negado:
        return negado
    almacen = _almacen()
    datos = almacen.copia_actual()
    nombre = f"Registro de Horas MAJERIE {datetime.now():%Y-%m-%d %H%M}.majerie"
    return send_file(io.BytesIO(datos), as_attachment=True, download_name=nombre,
                     mimetype="application/octet-stream")


@ajustes.get("/ajustes/respaldos/<item>")
def descargar_respaldo(item: str):
    from ..nube.microsoft import ErrorMicrosoft

    negado = _exigir_admin()
    if negado:
        return negado
    try:
        datos = _almacen().bajar_respaldo(item)
    except ErrorMicrosoft as fallo:
        flash(_texto_error(fallo), "error")
        return redirect(url_for("ajustes.respaldos"))
    nombre = request.args.get("nombre") or "respaldo.majerie"
    return send_file(io.BytesIO(datos), as_attachment=True, download_name=nombre,
                     mimetype="application/octet-stream")


@ajustes.post("/ajustes/respaldos/restaurar")
def restaurar_respaldo():
    from ..nube.cifrado import ArchivoIlegible, sellar
    from ..nube.microsoft import ErrorMicrosoft

    negado = _exigir_admin()
    if negado:
        return negado
    almacen = _almacen()
    try:
        if request.form.get("item"):
            sobre = almacen.bajar_respaldo(request.form["item"])
        else:
            sobre = sellar(_base_de_archivo(request.files.get("archivo")))
        almacen.restaurar(sobre)
    except (ValueError, ArchivoIlegible) as fallo:
        flash(str(fallo), "error")
        return redirect(url_for("ajustes.respaldos"))
    except ErrorMicrosoft as fallo:
        flash(_texto_error(fallo), "error")
        return redirect(url_for("ajustes.respaldos"))
    flash("Copia restaurada. La versión anterior quedó guardada en Respaldos por si acaso.",
          "exito")
    return redirect(url_for("sesion.raiz"))


# -- Recuperar el acceso de administración ---------------------------------------
#
#
def _cuentas_de_recuperacion() -> list[dict]:
    from ..db import consultar_una

    try:
        fila = consultar_una("SELECT valor FROM meta WHERE clave = 'recuperacion'")
        return json.loads(fila["valor"]) if fila else []
    except (sqlite3.Error, ValueError, TypeError):
        return []


def _puede_recuperar() -> bool:
    almacen = _almacen()
    if almacen is None or not almacen.hay_copia_local:
        return False
    oid = almacen.cuenta.info().get("oid")
    return bool(oid) and any(c.get("oid") == oid for c in _cuentas_de_recuperacion())


@ajustes.post("/ajustes/recuperar")
def recuperar_acceso():
    """Nueva contraseña para la cuenta de administración.

    Solo desde una computadora conectada con una cuenta de Microsoft
    autorizada para esto (la que creó el sistema, o las que la
    administración agregue en Configuración).
    """
    from ..auth import cifrar_contrasena, sugerir_contrasena
    from ..db import consultar_una, ejecutar
    from ..historial import anotar

    if not _puede_recuperar():
        flash("Esta cuenta de Microsoft no está autorizada para recuperar el acceso.", "error")
        return redirect(url_for("ajustes.ajustes_inicio"))

    fila = consultar_una(
        "SELECT id, username FROM users WHERE role = 'administrador' "
        "ORDER BY (id = 'adm-majerie') DESC, username LIMIT 1"
    )
    if not fila:
        flash("No hay cuenta de administración en los datos.", "error")
        return redirect(url_for("ajustes.ajustes_inicio"))

    contrasena = sugerir_contrasena()
    ejecutar(
        "UPDATE users SET password_hash = ?, active = 1 WHERE id = ?",
        (cifrar_contrasena(contrasena), fila["id"]),
    )
    anotar("Restableció la contraseña de administración desde Ajustes", usuario="Recuperación")
    return render_template("recuperado.html", usuario=fila["username"], contrasena=contrasena)


# -- Ayuda -----------------------------------------------------------------------
#
#
@ajustes.get("/ayuda/registro-microsoft")
def ayuda_registro():
    """Instrucciones para el administrador de Microsoft 365."""
    return render_template("ayuda_registro.html", retorno="http://localhost")


MANUALES = {"uso": "Manual de Usuario.pdf"}


def ruta_manual(perfil: str):
    """El PDF del manual: dentro del .exe, o en `manual/pdf` mientras se
    trabaja con el código. None si esta copia no lo trae."""
    nombre = MANUALES.get(perfil)
    if not nombre:
        return None
    for carpeta in (cfg.RECURSOS / "manuales", cfg.RECURSOS.parent / "manual" / "pdf"):
        if (carpeta / nombre).is_file():
            return carpeta / nombre
    return None


@ajustes.get("/ayuda/manual/<perfil>.pdf")
def manual(perfil: str):
    """Los manuales de uso. Sin ingresar: el del administrador explica la
    puesta en marcha, que se hace antes de que exista ninguna cuenta."""
    ruta = ruta_manual(perfil)
    if ruta is None:
        flash("El manual no viene incluido en esta copia del programa: está junto al .exe.",
              "error")
        return redirect(request.referrer or url_for("sesion.raiz"))
    return send_file(ruta, mimetype="application/pdf", download_name=ruta.name,
                     as_attachment=False, max_age=0)


@ajustes.get("/ajustes/registro")
def ver_registro():
    """Las últimas líneas del registro del programa, para soporte."""
    try:
        texto = cfg.ARCHIVO_REGISTRO.read_text(encoding="utf-8", errors="replace")
    except OSError:
        texto = "Todavía no hay nada en el registro."
    lineas = texto.splitlines()[-400:]
    respuesta = current_app.response_class("\n".join(lineas), mimetype="text/plain")
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta
