"""Cuándo termina el programa.

No hay consola que cerrar: el programa vive mientras haya una ventana
abierta. Cada ventana consulta el estado cada poco, y esas consultas son su
latido; al cerrarse avisa con un «adiós». Además se vigila el proceso del
navegador, que con su perfil propio termina justo cuando se cierra la
ventana.
"""

from __future__ import annotations

import threading
import time


class Vida:
    ESPERA_INICIAL = 120  # segundos para que aparezca la primera ventana
    GRACIA = 6  # segundos sin ventanas antes de cerrar (una recarga no cierra)
    # Una ventana que no da señales en este tiempo se da por cerrada (por
    # ejemplo, si la computadora se suspendió con la ventana abierta).
    SILENCIO = 15 * 60

    def __init__(self):
        self._candado = threading.Lock()
        self._clientes = {}
        self._vacio_desde = time.monotonic()
        self._hubo_cliente = False
        self._cerrar_ya = False
        self.primer_latido = threading.Event()

    def latido(self, cliente) -> None:
        if not cliente:
            return
        with self._candado:
            self._clientes[str(cliente)[:64]] = time.monotonic()
            self._vacio_desde = None
            self._hubo_cliente = True
        self.primer_latido.set()

    def adios(self, cliente=None) -> None:
        """Una ventana se cerró (None: el navegador entero se cerró)."""
        with self._candado:
            if cliente is None:
                self._clientes.clear()
            else:
                self._clientes.pop(str(cliente)[:64], None)
            if not self._clientes and self._vacio_desde is None:
                self._vacio_desde = time.monotonic()

    def terminar(self) -> None:
        """Cierre pedido desde la propia interfaz."""
        with self._candado:
            self._cerrar_ya = True

    def ventanas(self) -> int:
        with self._candado:
            return len(self._clientes)

    def debe_cerrar(self) -> bool:
        with self._candado:
            if self._cerrar_ya:
                return True
            ahora = time.monotonic()
            for cliente, visto in list(self._clientes.items()):
                if ahora - visto > self.SILENCIO:
                    del self._clientes[cliente]
            if self._clientes:
                self._vacio_desde = None
                return False
            if self._vacio_desde is None:
                self._vacio_desde = ahora
            espera = self.GRACIA if self._hubo_cliente else self.ESPERA_INICIAL
            return ahora - self._vacio_desde >= espera
