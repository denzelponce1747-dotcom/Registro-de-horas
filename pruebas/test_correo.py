"""Avisos por correo: configuración, envío y comportamiento con SharePoint."""

from __future__ import annotations

import email
import re
import threading
import unittest
from email import policy
from pathlib import Path

from pruebas import entorno
from pruebas.smtp_simple import CLAVE, USUARIO, ServidorSMTP

from app.nube.almacen import SoloLectura  # noqa: E402


def _avisos(html: str) -> list[str]:
    return [re.sub(r"\s+", " ", m).strip()
            for m in re.findall(r'<div class="aviso[^"]*">.*?<p>(.*?)</p>', html, re.S)]


def _configurar(cliente, puerto: int, clave: str = CLAVE, **extra):
    datos = dict(accion="guardar-correo", vista="correo", activo="1", servidor="127.0.0.1",
                 puerto=str(puerto), seguridad="ninguna", usuario_smtp=USUARIO,
                 contrasena_smtp=clave, avisar_ausencias="1", avisar_registros="1",
                 copia="administracion@majerie.test")
    datos.update(extra)
    return cliente.post("/configuracion", data=datos)


class AvisosPorCorreo(unittest.TestCase):
    def setUp(self):
        self.app = entorno.aplicacion()
        self.admin = self.app.test_client()
        entorno.entrar(self.admin, "admin", entorno.CLAVE_ADMIN)

    def test_aprobar_vacaciones_avisa_a_la_persona(self):
        with ServidorSMTP() as smtp:
            _configurar(self.admin, smtp.puerto)
            self.admin.post("/aprobaciones", data=dict(accion="aprobar-ausencia", id="a-pend-vac",
                                                       vista="ausencias", nota="¡Disfrútelas!"))
            avisos = _avisos(self.admin.get("/aprobaciones").get_data(as_text=True))
            self.assertIn("Se avisó por correo a Ana Rojas.", avisos)
            self.assertEqual(len(smtp.mensajes), 1)
            mensaje = smtp.mensajes[0]
            self.assertEqual(sorted(mensaje["para"]), ["administracion@majerie.test", "ana@example.com"])
            correo = email.message_from_string(mensaje["datos"], policy=policy.default)
            self.assertIn("aprobada", correo["Subject"])
            texto = correo.get_body(("plain",)).get_content()
            self.assertIn("Vacaciones disponibles", texto)
            self.assertIn("¡Disfrútelas!", texto)

    def test_rechazar_permiso_con_horas(self):
        with ServidorSMTP() as smtp:
            _configurar(self.admin, smtp.puerto)
            self.admin.post("/aprobaciones", data=dict(accion="rechazar-ausencia", id="a-pend-perm",
                                                       vista="ausencias"))
            self.admin.get("/aprobaciones")
            self.assertEqual(len(smtp.mensajes), 1)
            correo = email.message_from_string(smtp.mensajes[0]["datos"], policy=policy.default)
            self.assertIn("rechazada", correo["Subject"])
            self.assertIn("Horas acumuladas", correo.get_body(("plain",)).get_content())

    def test_contrasena_incorrecta_no_impide_aprobar(self):
        with ServidorSMTP() as smtp:
            _configurar(self.admin, smtp.puerto, clave="otra")
            self.admin.post("/aprobaciones", data=dict(accion="aprobar-ausencia", id="a-pend-vac",
                                                       vista="ausencias"))
            avisos = _avisos(self.admin.get("/aprobaciones").get_data(as_text=True))
            self.assertIn("Ausencia aprobada.", avisos)
            self.assertTrue(any("rechazó el usuario o la contraseña" in a for a in avisos), avisos)
            self.assertEqual(smtp.mensajes, [])

    def test_apagados_no_envian(self):
        with ServidorSMTP() as smtp:
            _configurar(self.admin, smtp.puerto, activo="")
            self.admin.post("/aprobaciones", data=dict(accion="aprobar-ausencia", id="a-pend-vac",
                                                       vista="ausencias"))
            self.admin.get("/aprobaciones")
            self.assertEqual(smtp.mensajes, [])

    def test_correo_de_prueba(self):
        with ServidorSMTP() as smtp:
            _configurar(self.admin, smtp.puerto)
            self.admin.post("/configuracion", data=dict(accion="probar-correo", vista="correo",
                                                        para="maria@majerie.test"))
            avisos = _avisos(self.admin.get("/configuracion?vista=correo").get_data(as_text=True))
            self.assertIn("Se avisó por correo a maria@majerie.test.", avisos)
            self.assertEqual(len(smtp.mensajes), 1)

    def test_la_contrasena_no_va_a_la_base(self):
        with ServidorSMTP() as smtp:
            _configurar(self.admin, smtp.puerto)
        contenido = Path(entorno.CARPETA / "majerie.db").read_bytes()
        self.assertNotIn(CLAVE.encode(), contenido)
        self.assertNotIn(CLAVE.encode("utf-16-le"), contenido)


class _Cuenta:
    def info(self):
        return {"correo": "maria@majerie.test", "nombre": "María", "conectada": True}


class _AlmacenFalso:
    """Imita al almacén de SharePoint: puede repetir un guardado o fallar."""

    def __init__(self, ruta):
        self.ruta_base = Path(ruta)
        self.candado = threading.RLock()
        self.configurado = True
        self.hay_copia_local = True
        self.subidas = 0
        self.cuenta = _Cuenta()
        self.despues_de_guardar = []
        self.modo = "normal"

    def estado(self):
        return {"configurado": True, "cuenta": "maria@majerie.test", "nombre_cuenta": "María",
                "cuenta_conectada": True, "carpeta": "Datos", "carpeta_url": "", "sitio": "",
                "en_linea": True, "ocupado": False, "error": "", "necesita_sesion": False,
                "falta_archivo": False, "solo_lectura": "", "hace": 1, "version_datos": 1,
                "autor": "", "modificado": "", "subido": "", "copia_local": True, "modo": "",
                "puede_guardar": True}

    def guardar(self, ejecutar, forzar_subida=False):
        with self.candado:
            foto = self.ruta_base.read_bytes()
            modo, self.modo = self.modo, "normal"
            if modo == "conflicto":
                ejecutar()
                self.ruta_base.write_bytes(foto)
                return self.guardar(ejecutar)
            if modo == "falla":
                ejecutar()
                self.ruta_base.write_bytes(foto)
                raise SoloLectura("Sin conexión con SharePoint.")
            resultado = ejecutar()
            self.subidas += 1
            return resultado


class ConSharePoint(unittest.TestCase):
    def setUp(self):
        self.almacen = _AlmacenFalso(entorno.CARPETA / "majerie.db")
        self.app = entorno.aplicacion(self.almacen)
        self.admin = self.app.test_client()
        entorno.entrar(self.admin, "admin", entorno.CLAVE_ADMIN)

    def test_un_reintento_envia_un_solo_correo(self):
        with ServidorSMTP() as smtp:
            _configurar(self.admin, smtp.puerto)
            self.almacen.modo = "conflicto"
            self.admin.post("/aprobaciones", data=dict(accion="aprobar-ausencia", id="a-pend-vac",
                                                       vista="ausencias"))
            self.admin.get("/aprobaciones")
            self.assertEqual(len(smtp.mensajes), 1)

    def test_si_no_se_guarda_no_se_avisa(self):
        with ServidorSMTP() as smtp:
            _configurar(self.admin, smtp.puerto)
            self.almacen.modo = "falla"
            self.admin.post("/aprobaciones", data=dict(accion="aprobar-ausencia", id="a-pend-vac",
                                                       vista="ausencias"),
                            headers={"Referer": "/aprobaciones"})
            avisos = _avisos(self.admin.get("/aprobaciones").get_data(as_text=True))
            self.assertTrue(any(a.startswith("No se guardó") for a in avisos), avisos)
            self.assertEqual(smtp.mensajes, [])


if __name__ == "__main__":
    unittest.main()
