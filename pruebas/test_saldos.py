"""Saldo de horas acumuladas y de vacaciones: lo que el colaborador ve."""

from __future__ import annotations

import io
import re
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from pruebas import entorno

import openpyxl  # noqa: E402

from app.lib.ausencias import dias_disfrutados, dias_habiles_entre  # noqa: E402
from app.lib.tiempo import formatear_numero, hoy_iso  # noqa: E402


def _numero(texto: str) -> float:
    return float(texto.replace("+", "").replace("−", "-").replace(".", "").replace(",", ".")
                 .replace("h", "").strip())


class SaldoDeHoras(unittest.TestCase):
    def setUp(self):
        self.app = entorno.aplicacion()
        self.ana = self.app.test_client()
        entorno.entrar(self.ana, "ana", entorno.CLAVE_ANA)

    def _saldo(self):
        from app.datos import cargar_instantanea
        from app.lib.ajustes import ajustes_de
        from app.lib.estadisticas import con_horas, saldo_horas

        with self.app.test_request_context():
            persona = SimpleNamespace(id="col-ana", role="colaborador")
            inst = cargar_instantanea(persona)
            config = ajustes_de(inst.collaboratorSettings, "col-ana")
            registros = con_horas([r for r in inst.entries if r.userId == "col-ana"], inst.lunches)
            return saldo_horas(registros, inst.absences, config, "col-ana"), config

    def _indicador(self, html: str) -> float:
        valor = re.search(r"Horas acumuladas</p>.*?indicador-valor\">([^<]+)<", html, re.S)
        return _numero(valor.group(1))

    def test_el_desglose_suma_el_saldo(self):
        saldo, config = self._saldo()
        self.assertAlmostEqual(
            saldo.accumulated,
            config.carriedBalanceHours + saldo.workedTotal - saldo.targetTotal - saldo.spentTotal,
            places=2,
        )
        self.assertEqual(saldo.spentTotal, 8.5)
        html = self.ana.get("/registro").get_data(as_text=True)
        self.assertIn("¿Cómo se calcula mi saldo de horas", html)
        self.assertAlmostEqual(self._indicador(html), saldo.accumulated, places=2)

    def test_hoy_cuenta_al_registrar(self):
        hoy = date.today()
        if not entorno.dia_habil(hoy):
            self.skipTest("Hoy no es día hábil")
        antes, config = self._saldo()
        self.assertFalse(antes.todayCounts)
        self.ana.post("/registro", data={"accion": "crear", "date": hoy_iso(), "start": "08:00",
                                         "end": "12:00", "projectId": "p1", "notes": "Mañana",
                                         "vista": "dia"})
        despues, _ = self._saldo()
        self.assertTrue(despues.todayCounts)
        self.assertAlmostEqual(despues.accumulated,
                               antes.accumulated + 4 - config.dailyTargetHours, places=2)

    def test_la_semana_termina_en_el_saldo(self):
        saldo, _ = self._saldo()
        html = self.ana.get("/registro?vista=semana").get_data(as_text=True)
        saldos = re.findall(r'title="Horas acumuladas al cierre del día">saldo\s*<b[^>]*>([^<]+)</b>', html)
        self.assertTrue(saldos)
        self.assertAlmostEqual(_numero(saldos[-1]), saldo.accumulated, places=2)

    def test_el_reporte_coincide(self):
        saldo, _ = self._saldo()
        admin = self.app.test_client()
        entorno.entrar(admin, "admin", entorno.CLAVE_ADMIN)
        libro = openpyxl.load_workbook(io.BytesIO(admin.get("/reportes/general.xlsx").data))
        resumen = [f for f in libro["Resumen"].iter_rows(values_only=True) if f and f[0] == "Ana Rojas"]
        self.assertAlmostEqual(float(resumen[0][5]), saldo.accumulated, places=2)


class Vacaciones(unittest.TestCase):
    def test_vacaciones_en_curso_se_reparten(self):
        hoy = date.today()
        inicio = entorno.habiles_hacia_atras(hoy, 2)
        fin = hoy + timedelta(days=9)
        dias = dias_habiles_entre(inicio.isoformat(), fin.isoformat())
        ausencia = SimpleNamespace(from_date=inicio.isoformat(), to_date=fin.isoformat(), days=dias)
        disfrutados = dias_disfrutados(ausencia, hoy.isoformat())
        self.assertEqual(disfrutados, dias_habiles_entre(inicio.isoformat(), hoy.isoformat()))
        self.assertLess(disfrutados, dias)
        pasadas = SimpleNamespace(from_date="2020-01-06", to_date="2020-01-10", days=5)
        self.assertEqual(dias_disfrutados(pasadas, hoy.isoformat()), 5)

    def test_no_se_traslada_con_corte_futuro(self):
        from app import acciones

        app = entorno.aplicacion()
        with app.test_request_context():
            admin = SimpleNamespace(role="administrador", actingAs="María Quesada", id="adm-majerie")
            futuro = (date.today() + timedelta(days=30)).isoformat()
            resultado = acciones.trasladar_vacaciones(admin, "col-ana", futuro)
            self.assertFalse(resultado["ok"])
            self.assertIn("todavía no llega", resultado["error"])
            resultado = acciones.trasladar_vacaciones(admin, "col-ana", hoy_iso())
            self.assertTrue(resultado["ok"], resultado)

    def test_pantalla_de_ausencias(self):
        app = entorno.aplicacion()
        ana = app.test_client()
        entorno.entrar(ana, "ana", entorno.CLAVE_ANA)
        html = ana.get("/ausencias").get_data(as_text=True)
        self.assertIn("Ver qué vacaciones se descuentan del saldo", html)
        self.assertIn("En espera de aprobación", html)
        self.assertIn(formatear_numero(20, 1), html)


if __name__ == "__main__":
    unittest.main()
