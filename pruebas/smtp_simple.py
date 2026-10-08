"""Servidor SMTP mínimo para las pruebas: sin cifrado, con AUTH PLAIN/LOGIN.

Guarda cada mensaje recibido en `mensajes` (lista de dicts con `de`,
`para` y `datos`). Solo la biblioteca estándar: corre igual en Windows.
"""

from __future__ import annotations

import base64
import socketserver
import threading

USUARIO = "avisos@majerie.test"
CLAVE = "Clave-Correcta1"


class _Manejador(socketserver.StreamRequestHandler):
    def _decir(self, linea: str) -> None:
        self.wfile.write((linea + "\r\n").encode("utf-8"))

    def _leer(self) -> str:
        return self.rfile.readline().decode("utf-8", "replace").rstrip("\r\n")

    def handle(self):
        servidor = self.server
        de, para, autenticado = "", [], False
        self._decir("220 prueba ESMTP")
        while True:
            linea = self._leer()
            if not linea and self.rfile.closed:
                return
            orden = linea.upper()
            if orden.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-prueba\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
            elif orden.startswith("AUTH PLAIN"):
                partes = linea.split(" ", 2)
                carga = partes[2] if len(partes) > 2 else ""
                if not carga:
                    self._decir("334 ")
                    carga = self._leer()
                _, usuario, clave = base64.b64decode(carga).decode().split("\x00")
                autenticado = usuario == USUARIO and clave == CLAVE
                self._decir("235 OK" if autenticado else "535 Credenciales incorrectas")
            elif orden.startswith("AUTH LOGIN"):
                self._decir("334 VXNlcm5hbWU6")
                usuario = base64.b64decode(self._leer()).decode()
                self._decir("334 UGFzc3dvcmQ6")
                clave = base64.b64decode(self._leer()).decode()
                autenticado = usuario == USUARIO and clave == CLAVE
                self._decir("235 OK" if autenticado else "535 Credenciales incorrectas")
            elif orden.startswith("MAIL FROM"):
                if not autenticado:
                    self._decir("530 Autentíquese primero")
                    continue
                de, para = linea.split(":", 1)[1].strip(" <>"), []
                self._decir("250 OK")
            elif orden.startswith("RCPT TO"):
                para.append(linea.split(":", 1)[1].strip(" <>"))
                self._decir("250 OK")
            elif orden == "DATA":
                self._decir("354 Termine con un punto")
                lineas = []
                while True:
                    actual = self._leer()
                    if actual == ".":
                        break
                    lineas.append(actual[1:] if actual.startswith("..") else actual)
                with servidor.candado:
                    servidor.mensajes.append({"de": de, "para": para, "datos": "\r\n".join(lineas)})
                self._decir("250 Recibido")
            elif orden == "RSET":
                de, para = "", []
                self._decir("250 OK")
            elif orden == "NOOP":
                self._decir("250 OK")
            elif orden == "QUIT":
                self._decir("221 Adiós")
                return
            elif not linea:
                return
            else:
                self._decir("502 No implementado")


class ServidorSMTP(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Manejador)
        self.mensajes: list[dict] = []
        self.candado = threading.Lock()
        self._hilo = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def puerto(self) -> int:
        return self.server_address[1]

    def __enter__(self):
        self._hilo.start()
        return self

    def __exit__(self, *_):
        self.shutdown()
        self.server_close()
