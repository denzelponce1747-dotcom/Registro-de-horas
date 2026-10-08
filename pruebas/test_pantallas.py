"""Todas las pantallas responden y los dos reportes de Excel se generan."""

from __future__ import annotations

import io
import unittest

from pruebas import entorno

import openpyxl  # noqa: E402

PANTALLAS_ADMIN = [
    "/dashboard", "/aprobaciones", "/aprobaciones?vista=ausencias", "/configuracion",
    "/configuracion?vista=proyectos", "/configuracion?vista=correo",
    "/configuracion?vista=historial", "/configuracion?vista=seguridad", "/ajustes",
]
PANTALLAS_COLABORADOR = [
    "/registro", "/registro?vista=semana", "/registro?vista=historial", "/ausencias",
    "/proyectos", "/cuenta",
]


class Pantallas(unittest.TestCase):
    def setUp(self):
        self.app = entorno.aplicacion()

    def test_administracion(self):
        cliente = self.app.test_client()
        entorno.entrar(cliente, "admin", entorno.CLAVE_ADMIN)
        for ruta in PANTALLAS_ADMIN:
            with self.subTest(ruta=ruta):
                self.assertEqual(cliente.get(ruta).status_code, 200)

    def test_colaborador(self):
        cliente = self.app.test_client()
        entorno.entrar(cliente, "ana", entorno.CLAVE_ANA)
        for ruta in PANTALLAS_COLABORADOR:
            with self.subTest(ruta=ruta):
                self.assertEqual(cliente.get(ruta).status_code, 200)

    def test_reportes(self):
        cliente = self.app.test_client()
        entorno.entrar(cliente, "admin", entorno.CLAVE_ADMIN)
        for tipo in ("general", "por-colaborador"):
            with self.subTest(tipo=tipo):
                respuesta = cliente.get(f"/reportes/{tipo}.xlsx")
                self.assertEqual(respuesta.status_code, 200)
                libro = openpyxl.load_workbook(io.BytesIO(respuesta.data))
                self.assertIn("Ana Rojas", libro.sheetnames)

    def test_manual(self):
        cliente = self.app.test_client()
        with cliente.get("/ayuda/manual/uso.pdf") as respuesta:
            self.assertEqual(respuesta.status_code, 200)
            self.assertTrue(respuesta.data.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
