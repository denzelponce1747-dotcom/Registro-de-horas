/* Sistema de Registro de Horas · MAJERIE S.R.L
 *
 * Lo que la interfaz hace en el navegador:
 *
 * - El latido: cada ventana consulta `/estado` cada pocos segundos. Así el
 *   programa sabe que la ventana sigue abierta (al cerrarla, se apaga solo)
 *   y la pantalla sabe cómo está la conexión con SharePoint.
 * - El indicador de la nube y las franjas de aviso (sin conexión, sesión
 *   vencida, cambios nuevos de otra computadora).
 * - Formularios que no se pierden: si no se puede guardar, se avisa antes de
 *   enviar y lo escrito queda en pantalla.
 * - Tema claro/oscuro, avisos, confirmaciones y pequeñas animaciones.
 *
 * Todo funciona igual si algo de esto falla: los formularios siguen siendo
 * formularios normales.
 */
(function () {
  "use strict";

  const raiz = document.documentElement;
  const cuerpo = document.body;
  const sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const MAJERIE = (window.MAJERIE = window.MAJERIE || {});

  // ───────────────────────────────────────────── Identidad de la ventana

  function idVentana() {
    try {
      let id = sessionStorage.getItem("majerie:ventana");
      if (!id) {
        id = Math.random().toString(36).slice(2) + Date.now().toString(36);
        sessionStorage.setItem("majerie:ventana", id);
      }
      return id;
    } catch (_e) {
      return "ventana";
    }
  }

  const VENTANA = idVentana();

  // ───────────────────────────────────────────── Enfoque inicial

  // `autofocus` desplaza la página hasta el campo: en una ventana baja se
  // perdían el logotipo y los pasos de la guía. Se enfoca sin mover nada.
  const primerCampo = document.querySelector("[data-enfocar]");
  if (primerCampo) {
    try {
      primerCampo.focus({ preventScroll: true });
    } catch (_e) {
      primerCampo.focus();
    }
  }

  // ───────────────────────────────────────────── Avisos flotantes

  function cajaDeAvisos() {
    let caja = document.getElementById("avisos");
    if (!caja) {
      caja = document.createElement("div");
      caja.id = "avisos";
      caja.className = "avisos";
      caja.setAttribute("role", "status");
      caja.setAttribute("aria-live", "polite");
      cuerpo.appendChild(caja);
    }
    return caja;
  }

  const MARCAS = {
    exito: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5 10 17 19 7"/></svg>',
    error: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M12 7v6"/><path d="M12 17h.01"/></svg>',
    pendiente: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 7v5l3 2"/></svg>',
  };

  function retirar(aviso) {
    if (!aviso || aviso.classList.contains("saliendo")) return;
    aviso.classList.add("saliendo");
    setTimeout(() => aviso.remove(), 280);
  }

  function programar(aviso) {
    const duracion = aviso.classList.contains("aviso--error") ? 10000 : 7000;
    aviso.style.setProperty("--duracion-aviso", duracion + "ms");
    let restante = duracion;
    let inicio = Date.now();
    let reloj = setTimeout(() => retirar(aviso), restante);
    aviso.addEventListener("mouseenter", () => {
      clearTimeout(reloj);
      restante -= Date.now() - inicio;
    });
    aviso.addEventListener("mouseleave", () => {
      inicio = Date.now();
      reloj = setTimeout(() => retirar(aviso), Math.max(restante, 1200));
    });
    aviso.addEventListener("click", () => retirar(aviso));
  }

  MAJERIE.avisar = function (texto, tipo, titulo) {
    tipo = tipo || "exito";
    const aviso = document.createElement("div");
    aviso.className = "aviso" + (tipo === "error" ? " aviso--error" : tipo === "pendiente" ? " aviso--pendiente" : "");
    const encabezado =
      titulo || (tipo === "error" ? "No se pudo completar" : tipo === "pendiente" ? "Enviado a aprobación" : "Listo");
    aviso.innerHTML =
      '<span class="aviso-marca">' + (MARCAS[tipo] || MARCAS.exito) + "</span><div><b></b><p></p></div>";
    aviso.querySelector("b").textContent = encabezado;
    aviso.querySelector("p").textContent = texto;
    cajaDeAvisos().appendChild(aviso);
    programar(aviso);
    return aviso;
  };

  document.querySelectorAll(".avisos .aviso").forEach(programar);

  // ───────────────────────────────────────────── Confirmaciones

  let dialogo = null;

  function confirmar(texto, opciones) {
    opciones = opciones || {};
    if (!dialogo) {
      dialogo = document.createElement("dialog");
      dialogo.className = "dialogo";
      dialogo.innerHTML =
        '<form method="dialog" class="dialogo-cuerpo">' +
        '<span class="dialogo-icono"></span>' +
        '<p class="dialogo-texto"></p>' +
        '<div class="dialogo-acciones">' +
        '<button value="no" class="boton boton--secundario boton--sm">Cancelar</button>' +
        '<button value="si" class="boton boton--primario boton--sm" data-si>Sí, continuar</button>' +
        "</div></form>";
      cuerpo.appendChild(dialogo);
    }
    dialogo.querySelector(".dialogo-texto").textContent = texto;
    const si = dialogo.querySelector("[data-si]");
    si.textContent = opciones.aceptar || "Sí, continuar";
    si.className = "boton boton--sm " + (opciones.peligro ? "boton--peligro-fuerte" : "boton--primario");
    dialogo.querySelector(".dialogo-icono").innerHTML = opciones.peligro
      ? '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>'
      : '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>';
    dialogo.classList.toggle("dialogo--peligro", !!opciones.peligro);
    return new Promise((resolver) => {
      dialogo.addEventListener(
        "close",
        () => resolver(dialogo.returnValue === "si"),
        { once: true },
      );
      dialogo.returnValue = "";
      dialogo.showModal();
      setTimeout(() => si.focus(), 30);
    });
  }

  MAJERIE.confirmar = confirmar;

  // ───────────────────────────────────────────── Estado de la nube

  const indicador = document.getElementById("nube");
  const franjas = document.getElementById("franjas");
  const versionInicial = cuerpo.dataset.versionDatos;
  let ultimoEstado = null;
  let editando = false;

  document.addEventListener("input", (evento) => {
    if (evento.target.closest("form")) editando = true;
  });

  function textoHace(segundos) {
    if (segundos === null || segundos === undefined) return "";
    if (segundos < 10) return "al día";
    if (segundos < 60) return "hace " + segundos + " s";
    const minutos = Math.round(segundos / 60);
    return "hace " + minutos + " min";
  }

  function franja(id, clase, html) {
    if (!franjas) return;
    let elemento = document.getElementById(id);
    if (!html) {
      if (elemento) elemento.remove();
      return;
    }
    if (!elemento) {
      elemento = document.createElement("div");
      elemento.id = id;
      franjas.appendChild(elemento);
    }
    elemento.className = "franja " + clase;
    if (elemento.dataset.html !== html) {
      elemento.innerHTML = html;
      elemento.dataset.html = html;
    }
  }

  function pintarNube(nube) {
    if (!nube) return;
    ultimoEstado = nube;
    MAJERIE.nube = nube;

    let estado = "ok";
    let texto = "Sincronizado";
    if (!nube.configurado) {
      estado = "solo-lectura";
      texto = "Sin conectar";
    } else if (nube.necesita_sesion) {
      estado = "sesion";
      texto = "Reconectar";
    } else if (nube.falta_archivo) {
      estado = "error";
      texto = "Falta el archivo";
    } else if (nube.en_linea === false) {
      estado = "sin-conexion";
      texto = "Sin conexión";
    } else if (nube.ocupado) {
      estado = nube.ocupado;
      texto = nube.ocupado === "guardando" ? "Guardando…" : nube.ocupado === "descargando" ? "Trayendo cambios…" : "Comprobando…";
    } else if (nube.solo_lectura) {
      estado = "solo-lectura";
      texto = "Solo lectura";
    } else {
      texto = "SharePoint · " + textoHace(nube.hace);
    }

    if (indicador) {
      indicador.dataset.estado = estado;
      const etiqueta = indicador.querySelector(".nube-texto");
      if (etiqueta) etiqueta.textContent = texto;
      const detalle = [];
      if (nube.carpeta) detalle.push("Carpeta: " + nube.carpeta);
      if (nube.cuenta) detalle.push("Cuenta: " + nube.cuenta);
      if (nube.autor) detalle.push("Último cambio: " + nube.autor);
      if (nube.solo_lectura) detalle.push(nube.solo_lectura);
      indicador.title = detalle.join("\n") || texto;
    }

    // Franjas: lo que impide guardar, y los cambios que llegaron de otra
    // computadora mientras se miraba esta pantalla.
    if (nube.necesita_sesion) {
      franja("franja-nube", "franja--error",
        'La sesión de Microsoft venció y no se pueden guardar cambios. <a href="/conexion/microsoft?volver=' +
          encodeURIComponent(location.pathname + location.search) + '">Volver a conectar</a>');
    } else if (nube.configurado && nube.en_linea === false) {
      franja("franja-nube", "franja--alerta",
        "Sin conexión con SharePoint: está viendo la última copia. Lo que escriba se podrá guardar cuando vuelva la conexión.");
    } else if (nube.falta_archivo) {
      franja("franja-nube", "franja--error",
        'El archivo de datos ya no está en SharePoint. <a href="/ajustes">Revisar en Ajustes</a>');
    } else if (nube.solo_lectura && nube.configurado) {
      franja("franja-nube", "franja--alerta", nube.solo_lectura);
    } else {
      franja("franja-nube", "", "");
    }

    if (versionInicial !== undefined && String(nube.version_datos) !== String(versionInicial) && nube.version_datos > 0) {
      if (document.hidden && !editando) {
        recargarAlVolver = true;
      } else {
        franja("franja-nuevo", "franja--nuevo",
          "Llegaron cambios de otra computadora" + (nube.autor ? " (" + nube.autor + ")" : "") +
            '. <button type="button" data-recargar>Actualizar la pantalla</button>');
      }
    }
  }

  let recargarAlVolver = false;

  document.addEventListener("click", (evento) => {
    if (evento.target.closest("[data-recargar]")) location.reload();
  });

  async function consultar(extra) {
    try {
      const respuesta = await fetch("/estado?c=" + encodeURIComponent(VENTANA) + (extra || ""), {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!respuesta.ok) return null;
      const datos = await respuesta.json();
      pintarNube(datos.nube);
      return datos.nube;
    } catch (_e) {
      return null;
    }
  }

  MAJERIE.consultar = consultar;

  let reloj = null;
  function latir() {
    clearTimeout(reloj);
    consultar("").finally(() => {
      reloj = setTimeout(latir, document.hidden ? 50000 : 8000);
    });
  }
  latir();

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      if (recargarAlVolver && !editando) {
        location.reload();
        return;
      }
      clearTimeout(reloj);
      consultar("&refrescar=1").finally(() => {
        reloj = setTimeout(latir, 8000);
      });
    }
  });

  window.addEventListener("pagehide", () => {
    try {
      navigator.sendBeacon("/adios", VENTANA);
    } catch (_e) {
      /* el silencio del latido hace lo mismo, un poco después */
    }
  });

  // ───────────────────────────────────────────── Formularios

  function ocupar(boton, texto) {
    if (!boton || boton.dataset.ocupado) return;
    boton.dataset.ocupado = "1";
    boton.dataset.original = boton.innerHTML;
    boton.innerHTML = '<span class="girador" aria-hidden="true"></span><span>' + texto + "</span>";
    // Si la página no cambia (descarga de un archivo), el botón vuelve.
    setTimeout(() => liberar(boton), 15000);
  }

  function liberar(boton) {
    if (!boton || !boton.dataset.ocupado) return;
    boton.innerHTML = boton.dataset.original;
    delete boton.dataset.ocupado;
  }

  window.addEventListener("pageshow", () => {
    document.querySelectorAll("[data-ocupado]").forEach(liberar);
  });

  async function enviar(formulario, boton) {
    formulario.dataset.revisado = "1";
    const textoOcupado = boton && boton.dataset.textoOcupado;
    if ((formulario.method.toLowerCase() === "post" && !formulario.hasAttribute("data-local")) || textoOcupado) {
      ocupar(boton, textoOcupado || "Guardando…");
    }
    if (boton && formulario.requestSubmit) {
      formulario.requestSubmit(boton);
    } else if (formulario.requestSubmit) {
      formulario.requestSubmit();
    } else {
      formulario.submit();
    }
  }

  document.addEventListener("submit", async (evento) => {
    const formulario = evento.target;
    if (!(formulario instanceof HTMLFormElement)) return;
    const boton = evento.submitter || formulario.querySelector('[type="submit"]');

    if (formulario.dataset.revisado) {
      delete formulario.dataset.revisado;
      return;
    }

    const confirmacion = boton && boton.dataset.confirmar;
    const esPost = formulario.method.toLowerCase() === "post" && !formulario.hasAttribute("data-local");
    const sinGuardar = esPost && ultimoEstado && ultimoEstado.configurado && ultimoEstado.puede_guardar === false;
    const textoOcupado = boton && boton.dataset.textoOcupado;

    if (!confirmacion && !sinGuardar) {
      if (esPost || textoOcupado) ocupar(boton, textoOcupado || "Guardando…");
      return;
    }

    evento.preventDefault();

    if (confirmacion) {
      const peligro = !!(boton.classList.contains("boton-icono--peligro") || boton.dataset.peligro !== undefined);
      const sigue = await confirmar(confirmacion, { peligro, aceptar: boton.dataset.aceptar });
      if (!sigue) return;
    }

    if (sinGuardar) {
      // La última vez no se podía guardar: se mira de nuevo antes de enviar,
      // para no perder lo escrito si sigue sin conexión.
      const nube = await consultar("&comprobar=1");
      if (nube && nube.puede_guardar === false) {
        MAJERIE.avisar(
          (nube.solo_lectura || "No hay conexión con SharePoint.") + " Lo que escribió sigue en pantalla.",
          "error",
          "Todavía no se puede guardar",
        );
        return;
      }
    }

    enviar(formulario, boton);
  });

  // ───────────────────────────────────────────── Tema claro / oscuro

  function temaEfectivo() {
    const tema = raiz.dataset.tema || "auto";
    if (tema !== "auto") return tema;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
  }

  function guardarTema(tema) {
    const datos = new FormData();
    datos.append("tema", tema);
    fetch("/ajustes/tema", { method: "POST", body: datos, headers: { "X-Requested-With": "fetch" } }).catch(() => {});
  }

  function aplicarTema(tema, origen) {
    const cambiar = () => {
      raiz.dataset.tema = tema;
    };
    if (!document.startViewTransition || sinMovimiento) {
      cambiar();
      return;
    }
    const x = origen ? origen.x : innerWidth / 2;
    const y = origen ? origen.y : 0;
    const radio = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    raiz.classList.add("cambiando-tema");
    const transicion = document.startViewTransition(cambiar);
    transicion.ready.then(() => {
      raiz.animate(
        { clipPath: ["circle(0px at " + x + "px " + y + "px)", "circle(" + radio + "px at " + x + "px " + y + "px)"] },
        { duration: 620, easing: "cubic-bezier(0.65, 0, 0.35, 1)", pseudoElement: "::view-transition-new(root)" },
      );
    });
    transicion.finished.finally(() => raiz.classList.remove("cambiando-tema"));
  }

  document.addEventListener("click", (evento) => {
    const boton = evento.target.closest("[data-alternar-tema]");
    if (!boton) return;
    const nuevo = temaEfectivo() === "oscuro" ? "claro" : "oscuro";
    const caja = boton.getBoundingClientRect();
    aplicarTema(nuevo, { x: caja.left + caja.width / 2, y: caja.top + caja.height / 2 });
    guardarTema(nuevo);
  });

  document.querySelectorAll("[data-elegir-tema]").forEach((opcion) => {
    opcion.addEventListener("change", () => {
      if (!opcion.checked) return;
      const caja = opcion.closest("label").getBoundingClientRect();
      aplicarTema(opcion.value, { x: caja.left + caja.width / 2, y: caja.top + caja.height / 2 });
      guardarTema(opcion.value);
    });
  });

  // ───────────────────────────────────────────── Menú de la persona

  (function () {
    const contenedor = document.getElementById("menu-usuario");
    if (!contenedor) return;
    const disparador = document.getElementById("menu-disparador");
    const panel = document.getElementById("menu-panel");

    const cerrar = () => {
      panel.classList.add("oculto");
      disparador.setAttribute("aria-expanded", "false");
    };

    disparador.addEventListener("click", (evento) => {
      evento.stopPropagation();
      const abierto = disparador.getAttribute("aria-expanded") === "true";
      panel.classList.toggle("oculto", abierto);
      disparador.setAttribute("aria-expanded", String(!abierto));
    });

    document.addEventListener("pointerdown", (evento) => {
      if (!contenedor.contains(evento.target)) cerrar();
    });
    document.addEventListener("keydown", (evento) => {
      if (evento.key === "Escape") cerrar();
    });
  })();

  // ───────────────────────────────────────────── Editor de tarifa

  document.querySelectorAll("[data-tarifa]").forEach((bloque) => {
    const modo = bloque.querySelector("[data-modo-tarifa]");
    const valores = bloque.querySelector("[data-valores-tarifa]");
    if (!modo || !valores) return;
    modo.addEventListener("change", () => {
      valores.hidden = modo.value !== "propia";
      if (!valores.hidden) {
        const monto = valores.querySelector("input");
        if (monto) monto.focus();
      }
    });
  });

  // ───────────────────────────────────────────── Números que cuentan

  function leerNumero(texto) {
    const hallado = texto.match(/^([+\-−]?)([\d.]+(?:,\d+)?)(.*)$/s);
    if (!hallado) return null;
    const signo = hallado[1];
    const crudo = hallado[2];
    const decimales = crudo.includes(",") ? crudo.split(",")[1].length : 0;
    const valor = parseFloat(crudo.replace(/\./g, "").replace(",", "."));
    if (!isFinite(valor)) return null;
    return { signo, valor, decimales, resto: hallado[3], miles: /\.\d{3}/.test(crudo) };
  }

  function formatear(valor, decimales, miles) {
    let texto = valor.toFixed(decimales);
    let [entero, fraccion] = texto.split(".");
    if (miles) entero = entero.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return fraccion ? entero + "," + fraccion : entero;
  }

  if (!sinMovimiento) {
    document.querySelectorAll(".indicador-valor, [data-contar]").forEach((elemento, indice) => {
      if (elemento.children.length) return;
      const numero = leerNumero(elemento.textContent.trim());
      if (!numero || numero.valor === 0) return;
      const inicio = performance.now() + 180 + indice * 60;
      const duracion = 900;
      const paso = (ahora) => {
        const t = Math.min(1, Math.max(0, (ahora - inicio) / duracion));
        const suave = 1 - Math.pow(1 - t, 3);
        elemento.textContent = numero.signo + formatear(numero.valor * suave, numero.decimales, numero.miles) + numero.resto;
        if (t < 1) requestAnimationFrame(paso);
      };
      elemento.textContent = numero.signo + formatear(0, numero.decimales, numero.miles) + numero.resto;
      requestAnimationFrame(paso);
    });
  }

  // ───────────────────────────────────────────── Presentación de entrada

  const presentacion = document.getElementById("presentacion");
  if (presentacion) {
    if (raiz.dataset.presentar) {
      const espera = sinMovimiento ? 200 : 1900;
      setTimeout(() => {
        presentacion.classList.add("retirada");
        setTimeout(() => presentacion.remove(), 1400);
      }, espera);
    } else {
      presentacion.remove();
    }
  }
})();
