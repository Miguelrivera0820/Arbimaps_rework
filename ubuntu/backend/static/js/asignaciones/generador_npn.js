/**
 * generador_npn.js
 * Módulo interactivo del Generador Oficial de Números Prediales Nacionales (30 Dígitos)
 * y Códigos Homologados para el Municipio de Neiva.
 */

(function () {
  const rp = (window.asignacionesConfig && window.asignacionesConfig.rp) || "";

  // Elementos principales del modal
  let modalGen, btnCloseGen, btnCerrarModalGenBottom;
  let btnTabGen, btnTabRes, paneGen, paneRes, badgeTotalRes;
  let inputMatriz, countDigitos, inputCantidad, selectTipoMut, selectCondicion;
  let rowPhParams, inputEdificio, inputPiso, inputTramite, inputObs, btnEjecutarGen;
  let wrapResultados, tbodyResultados, badgeStock, lblCantGen, btnCopiarTodo, btnDescargarCsv;
  let tbodyReservas, chkTodosReservas, btnLiberarSelec, btnConsolidarSelec, btnRefrescarRes;

  // Asistente Territorial
  let boxAsistente, btnToggleAsistente, btnCerrarAsistente;
  let selSector, selComuna, inpComuna, inpBarrio, selVeredas, btnConsultarManzana;
  let boxSugerencia, txtSugerencia, btnAplicarSugerencia;

  let ultimosPrediosGenerados = [];
  let listaReservasActivas = [];
  let ultimaSugerenciaData = null;
  let catalogoVeredasCargado = false;
  let moduloInicializado = false;

  function bindElements() {
    modalGen = document.getElementById("modalGeneradorNpn");
    btnCloseGen = document.getElementById("btnCloseGeneradorNpnModal");
    btnCerrarModalGenBottom = document.getElementById("btnCerrarModalGenBottom");

    btnTabGen = document.getElementById("btnTabGenerar");
    btnTabAsignar = document.getElementById("btnTabAsignarExistentes");
    btnTabRes = document.getElementById("btnTabReservas");
    paneGen = document.getElementById("paneGenerarNpn");
    paneAsignar = document.getElementById("paneAsignarExistentes");
    paneRes = document.getElementById("paneReservasActivas");
    badgeTotalRes = document.getElementById("badgeTotalReservasCount");

    inputMatriz = document.getElementById("genPredioMatrizInput");
    countDigitos = document.getElementById("genDigitosCount");
    inputCantidad = document.getElementById("genCantidadInput");
    selectTipoMut = document.getElementById("genTipoMutacionSelect");
    selectCondicion = document.getElementById("genCondicionSelect");
    rowPhParams = document.getElementById("rowPhParams");
    inputEdificio = document.getElementById("genEdificioInput");
    inputPiso = document.getElementById("genPisoInput");
    inputTramite = document.getElementById("genTramiteInput");
    inputObs = document.getElementById("genObservacionesInput");
    btnEjecutarGen = document.getElementById("btnEjecutarGeneradorNpn");

    wrapResultados = document.getElementById("wrapResultadosGenerador");
    tbodyResultados = document.getElementById("tbodyResultadosGenerador");
    badgeStock = document.getElementById("badgeStockDisponibles");
    lblCantGen = document.getElementById("lblCantGenerada");
    btnCopiarTodo = document.getElementById("btnCopiarTodoGenerador");
    btnDescargarCsv = document.getElementById("btnDescargarCsvGenerador");

    tbodyReservas = document.getElementById("tbodyReservasActivas");
    chkTodosReservas = document.getElementById("chkTodosReservas");
    btnLiberarSelec = document.getElementById("btnLiberarSeleccionados");
    btnConsolidarSelec = document.getElementById("btnConsolidarSeleccionados");
    btnRefrescarRes = document.getElementById("btnRefrescarReservas");

    boxAsistente = document.getElementById("boxAsistenteTerritorial");
    btnToggleAsistente = document.getElementById("btnToggleAsistenteTerritorial");
    btnCerrarAsistente = document.getElementById("btnCerrarAsistenteTerritorial");
    selSector = document.getElementById("asistenteSectorSelect");
    selComuna = document.getElementById("asistenteComunaSelect");
    inpComuna = document.getElementById("asistenteComunaInput");
    inpBarrio = document.getElementById("asistenteBarrioInput");
    selVeredas = document.getElementById("asistenteVeredasSelect");
    btnConsultarManzana = document.getElementById("btnConsultarSiguienteManzana");
    boxSugerencia = document.getElementById("resultadoSugerenciaBox");
    txtSugerencia = document.getElementById("textoResultadoSugerencia");
    btnAplicarSugerencia = document.getElementById("btnAplicarSugerenciaManzana");
  }

  function actualizarVisibilidadParametrosPh() {
    if (!rowPhParams || !selectCondicion) return;
    const cond = selectCondicion.value;
    const esPh = ["9", "8", "7", "5"].includes(cond) || (selectTipoMut && selectTipoMut.value === "PH");
    rowPhParams.style.display = esPh ? "flex" : "none";
  }

  async function consultarStockDisponibles() {
    if (!badgeStock) return;
    try {
      const resp = await fetch(`${rp}/api/v1/predios-generador/inventario-resumen`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data && data.resumen) {
        const disponibles = data.resumen.disponibles || 0;
        const reservados = data.resumen.reservados || 0;
        badgeStock.textContent = `${disponibles.toLocaleString()} disponibles`;
        if (badgeTotalRes) badgeTotalRes.textContent = reservados;
      }
    } catch (e) {
      console.warn("No se pudo consultar stock de homologados", e);
    }
  }

  async function cargarCatalogoVeredas() {
    if (catalogoVeredasCargado || !selVeredas) return;
    try {
      const res = await fetch(`${rp}/api/v1/predios-generador/catalogo-territorial`);
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.veredas && data.veredas.length > 0) {
        selVeredas.innerHTML = '<option value="0000">0000 - Vereda General / Sin código</option>';
        data.veredas.forEach(v => {
          const opt = document.createElement("option");
          opt.value = v.codigo_4d;
          opt.textContent = `${v.codigo_4d} - ${v.nombre}`;
          selVeredas.appendChild(opt);
        });
        const sigNum = String(data.veredas.length + 1).padStart(4, "0");
        const optNueva = document.createElement("option");
        optNueva.value = sigNum;
        optNueva.textContent = `+ ${sigNum} - [Incorporar Nueva Vereda]`;
        selVeredas.appendChild(optNueva);
        catalogoVeredasCargado = true;
      }
    } catch (e) {
      console.warn("No se pudo cargar el catálogo de veredas", e);
    }
  }

  async function ejecutarConsultaSiguienteManzana() {
    if (!txtSugerencia || !boxSugerencia) return;
    const sectorVal = selSector ? (selSector.value === "OTRO" ? "00" : selSector.value) : "01";
    const comunaVal = inpComuna ? (inpComuna.value.trim() || "00") : "00";
    const barrioVal = inpBarrio ? (inpBarrio.value.trim() || "0000") : "0000";

    boxSugerencia.classList.remove("d-none");
    txtSugerencia.innerHTML = '<span class="text-muted"><span class="spinner-border spinner-border-sm me-1"></span> Consultando consecutivo territorial...</span>';

    try {
      const res = await fetch(`${rp}/api/v1/predios-generador/sugerir-consecutivos-territoriales?sector=${sectorVal}&comuna=${comunaVal}&barrio=${barrioVal}`);
      if (!res.ok) throw new Error("Error al consultar consecutivos");
      const data = await res.json();
      ultimaSugerenciaData = data;

      const tipoZona = data.sector === "01" ? `Sector Urbano ${data.sector} | Comuna ${data.comuna}` : `Sector Rural ${data.sector} | Corregimiento ${data.comuna} | Vereda ${data.barrio}`;
      txtSugerencia.innerHTML = `
        <div>
          <strong class="text-navy">${tipoZona}</strong><br>
          <span class="text-muted">Última Manzana / Polígono:</span> <strong>${data.max_manzana_existente}</strong> 
          <span class="badge bg-secondary ms-1">${data.total_manzanas_en_zona} existentes</span><br>
          <span class="text-success fw-bold"><i class="bi bi-arrow-right-circle me-1"></i>Siguiente Manzana Sugerida: <u>${data.siguiente_manzana_sugerida}</u></span>
        </div>
      `;
    } catch (err) {
      console.error(err);
      txtSugerencia.innerHTML = '<span class="text-danger">No se pudo consultar el consecutivo.</span>';
    }
  }

  function renderResultadosGenerados(items) {
    if (!tbodyResultados || !wrapResultados) return;
    if (!items || items.length === 0) {
      wrapResultados.classList.add("d-none");
      return;
    }
    wrapResultados.classList.remove("d-none");
    if (lblCantGen) lblCantGen.textContent = items.length;

    let html = "";
    items.forEach((item, index) => {
      html += `
        <tr>
          <td class="text-center fw-bold text-muted">${index + 1}</td>
          <td>
            <span class="font-monospace fw-bold text-navy">${item.numero_predial}</span>
          </td>
          <td>
            <span class="badge bg-success-subtle text-success border border-success-subtle font-monospace px-2 py-1">${item.codigo_homologado}</span>
          </td>
          <td class="text-center">
            <span class="badge bg-warning text-dark">${item.estado}</span>
          </td>
          <td class="text-center">
            <div class="btn-group btn-group-sm">
              <button class="btn btn-xs btn-outline-primary py-0 px-2 btn-copiar-npn" data-npn="${item.numero_predial}" title="Copiar NPN">
                <i class="bi bi-clipboard"></i> NPN
              </button>
              <button class="btn btn-xs btn-outline-success py-0 px-2 btn-copiar-ch" data-ch="${item.codigo_homologado}" title="Copiar Homologado">
                <i class="bi bi-clipboard-check"></i> Homol.
              </button>
            </div>
          </td>
        </tr>
      `;
    });
    tbodyResultados.innerHTML = html;

    tbodyResultados.querySelectorAll(".btn-copiar-npn").forEach(btn => {
      btn.addEventListener("click", () => {
        const val = btn.getAttribute("data-npn");
        navigator.clipboard.writeText(val).then(() => {
          Swal.fire({ toast: true, position: 'top-end', icon: 'success', title: 'NPN copiado', showConfirmButton: false, timer: 1500 });
        });
      });
    });

    tbodyResultados.querySelectorAll(".btn-copiar-ch").forEach(btn => {
      btn.addEventListener("click", () => {
        const val = btn.getAttribute("data-ch");
        navigator.clipboard.writeText(val).then(() => {
          Swal.fire({ toast: true, position: 'top-end', icon: 'success', title: 'Homologado copiado', showConfirmButton: false, timer: 1500 });
        });
      });
    });
  }

  function renderTablaReservas(items) {
    if (!tbodyReservas) return;
    if (!items || items.length === 0) {
      tbodyReservas.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4"><i class="bi bi-info-circle me-1"></i> No se encontraron reservas con los filtros aplicados.</td></tr>`;
      return;
    }

    let html = "";
    items.forEach(r => {
      const fechaFormateada = r.fecha_asignacion ? new Date(r.fecha_asignacion).toLocaleString() : "S/F";
      html += `
        <tr>
          <td class="text-center">
            <input type="checkbox" class="form-check-input chk-reserva-item" value="${r.codigo_homologado}">
          </td>
          <td>
            <span class="badge bg-success-subtle text-success border border-success-subtle font-monospace px-2 py-1">${r.codigo_homologado}</span>
          </td>
          <td>
            <span class="font-monospace fw-semibold text-navy">${r.numero_predial || '<span class="text-muted">Sin NPN</span>'}</span>
          </td>
          <td>
            <small class="d-block fw-semibold text-dark">${r.usuario}</small>
            <small class="text-muted d-block" style="font-size: 0.72rem;">${r.observaciones || 'Sin notas'}</small>
          </td>
          <td>
            <small class="text-muted">${fechaFormateada}</small>
          </td>
          <td class="text-center">
            <div class="btn-group btn-group-sm">
              <button class="btn btn-xs btn-outline-success py-0 px-2 btn-fijar-individual" data-ch="${r.codigo_homologado}" title="Fijar / Consolidar definitivamente en base">
                <i class="bi bi-check2-circle"></i> Fijar
              </button>
              <button class="btn btn-xs btn-outline-danger py-0 px-2 btn-liberar-individual" data-ch="${r.codigo_homologado}" title="Liberar código hacia disponibles">
                <i class="bi bi-trash3"></i>
              </button>
            </div>
          </td>
        </tr>
      `;
    });
    tbodyReservas.innerHTML = html;

    tbodyReservas.querySelectorAll(".btn-liberar-individual").forEach(b => {
      b.addEventListener("click", () => {
        const ch = b.getAttribute("data-ch");
        confirmarYLiberarCodigos([ch]);
      });
    });

    tbodyReservas.querySelectorAll(".btn-fijar-individual").forEach(b => {
      b.addEventListener("click", () => {
        const ch = b.getAttribute("data-ch");
        confirmarYConsolidarCodigos([ch]);
      });
    });
  }

  function aplicarFiltrosReservas() {
    const inpQuery = document.getElementById("inpFiltroReservas");
    const selAntiguedad = document.getElementById("selAntiguedadReservas");

    const query = (inpQuery ? inpQuery.value : "").toLowerCase().trim();
    const antiguedad = selAntiguedad ? selAntiguedad.value : "TODOS";
    const ahora = new Date();

    const filtrados = listaReservasActivas.filter(r => {
      const matchTexto = !query ||
        (r.codigo_homologado || "").toLowerCase().includes(query) ||
        (r.numero_predial || "").toLowerCase().includes(query) ||
        (r.usuario || "").toLowerCase().includes(query) ||
        (r.observaciones || "").toLowerCase().includes(query);

      if (!matchTexto) return false;

      if (antiguedad === "TODOS") return true;
      if (!r.fecha_asignacion) return false;

      const fechaRes = new Date(r.fecha_asignacion);
      const difDias = (ahora - fechaRes) / (1000 * 60 * 60 * 24);

      if (antiguedad === "HOY") {
        return fechaRes.toDateString() === ahora.toDateString();
      } else if (antiguedad === "15") {
        return difDias >= 15;
      } else if (antiguedad === "30") {
        return difDias >= 30;
      }
      return true;
    });

    renderTablaReservas(filtrados);
  }

  async function cargarReservasActivas() {
    if (!tbodyReservas) return;
    tbodyReservas.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm me-1"></span> Cargando reservas activas...</td></tr>`;

    try {
      const resp = await fetch(`${rp}/api/v1/predios-generador/reservas-activas`);
      if (!resp.ok) throw new Error("Error al consultar reservas activas");
      const data = await resp.json();
      listaReservasActivas = data.items || [];
      if (badgeTotalRes) badgeTotalRes.textContent = listaReservasActivas.length;

      aplicarFiltrosReservas();
    } catch (err) {
      console.error(err);
      tbodyReservas.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-3">Error al cargar reservas activas.</td></tr>`;
    }
  }

  async function ejecutarLiberacionInactivas(dias = 30) {
    const result = await Swal.fire({
      title: `¿Liberar reservas inactivas (> ${dias} días)?`,
      text: `Todas las reservas en estado RESERVADO con más de ${dias} días de antigüedad volverán al stock DISPONIBLE de la bolsa.`,
      icon: "warning",
      showCancelButton: true,
      confirmButtonColor: "#dc2626",
      cancelButtonColor: "#6c757d",
      confirmButtonText: "Sí, liberar inactivas",
      cancelButtonText: "Cancelar"
    });

    if (result.isConfirmed) {
      try {
        const resp = await fetch(`${rp}/api/v1/predios-generador/liberar-reservas-inactivas`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dias_antiguedad: dias })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Error al liberar reservas inactivas.");

        Swal.fire({
          icon: "success",
          title: "Liberación Completada",
          text: `Se liberaron ${data.codigos_liberados} reservas inactivas (> ${dias} días) hacia la bolsa disponible.`,
          timer: 3000,
          showConfirmButton: false
        });

        cargarReservasActivas();
        consultarStockDisponibles();
      } catch (err) {
        Swal.fire({ icon: "error", title: "Error", text: err.message });
      }
    }
  }

  async function confirmarYLiberarCodigos(codigos) {
    if (!codigos || codigos.length === 0) return;
    const result = await Swal.fire({
      title: `¿Liberar ${codigos.length} código(s)?`,
      text: "El código volverá a estado DISPONIBLE en la bolsa oficial de Neiva para ser asignado en otros trámites.",
      icon: "warning",
      showCancelButton: true,
      confirmButtonColor: "#dc2626",
      cancelButtonColor: "#6c757d",
      confirmButtonText: "Sí, liberar",
      cancelButtonText: "Cancelar"
    });

    if (result.isConfirmed) {
      try {
        const resp = await fetch(`${rp}/api/v1/predios-generador/liberar-homologados`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ codigos: codigos, motivo: "Liberación solicitada por usuario" })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Error al liberar");

        Swal.fire({
          icon: "success",
          title: "Liberación Exitosa",
          text: `Se liberaron ${data.codigos_liberados} código(s) hacia la bolsa disponible.`,
          timer: 2000,
          showConfirmButton: false
        });

        cargarReservasActivas();
        consultarStockDisponibles();
      } catch (e) {
        Swal.fire("Error", e.message, "error");
      }
    }
  }

  async function confirmarYConsolidarCodigos(codigos) {
    if (!codigos || codigos.length === 0) return;
    const result = await Swal.fire({
      title: `¿Fijar y Consolidar en Base ${codigos.length} predio(s)?`,
      text: "El código pasará a estado ASIGNADO de forma definitiva en la base de datos oficial.",
      icon: "question",
      showCancelButton: true,
      confirmButtonColor: "#059669",
      cancelButtonColor: "#6c757d",
      confirmButtonText: "Sí, fijar en base",
      cancelButtonText: "Cancelar"
    });

    if (result.isConfirmed) {
      try {
        const resp = await fetch(`${rp}/api/v1/predios-generador/consolidar-homologados`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ codigos: codigos })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Error al consolidar");

        Swal.fire({
          icon: "success",
          title: "Predio(s) Consolidados",
          text: `Se fijaron ${data.codigos_consolidados} predio(s) en estado definitivo (ASIGNADO).`,
          timer: 2000,
          showConfirmButton: false
        });

        cargarReservasActivas();
        consultarStockDisponibles();
      } catch (e) {
        Swal.fire("Error", e.message, "error");
      }
    }
  }

  function initListeners() {
    if (moduloInicializado) return;
    bindElements();
    if (!modalGen) return;

    if (!document.body.contains(modalGen)) {
      document.body.appendChild(modalGen);
    }

    let mouseDownOnOverlay = false;
    modalGen.addEventListener("mousedown", (e) => {
      mouseDownOnOverlay = (e.target === modalGen);
    });

    modalGen.addEventListener("mouseup", (e) => {
      if (e.target === modalGen && mouseDownOnOverlay) {
        modalGen.classList.add("d-none");
        modalGen.style.display = "none";
      }
      mouseDownOnOverlay = false;
    });

    const dialogContainer = modalGen.querySelector(".npn-modal-dialog");
    if (dialogContainer) {
      dialogContainer.addEventListener("click", (e) => {
        e.stopPropagation();
      });
    }

    if (btnCloseGen) {
      btnCloseGen.addEventListener("click", () => {
        modalGen.classList.add("d-none");
        modalGen.style.display = "none";
      });
    }
    if (btnCerrarModalGenBottom) {
      btnCerrarModalGenBottom.addEventListener("click", () => {
        modalGen.classList.add("d-none");
        modalGen.style.display = "none";
      });
    }

    if (btnTabGen && btnTabRes) {
      const resetTabClasses = () => {
        [btnTabGen, btnTabAsignar, btnTabRes].forEach(b => {
          if (b) b.classList.remove("npn-main-tab-active");
        });
        [paneGen, paneAsignar, paneRes].forEach(p => {
          if (p) p.classList.add("d-none");
        });
      };

      btnTabGen.addEventListener("click", () => {
        resetTabClasses();
        if (btnTabGen) btnTabGen.classList.add("npn-main-tab-active");
        if (paneGen) paneGen.classList.remove("d-none");
      });

      if (btnTabAsignar) {
        btnTabAsignar.addEventListener("click", () => {
          resetTabClasses();
          btnTabAsignar.classList.add("npn-main-tab-active");
          if (paneAsignar) paneAsignar.classList.remove("d-none");
        });
      }

      btnTabRes.addEventListener("click", () => {
        resetTabClasses();
        if (btnTabRes) btnTabRes.classList.add("npn-main-tab-active");
        if (paneRes) paneRes.classList.remove("d-none");
        cargarReservasActivas();
      });
    }

    if (inputMatriz && countDigitos) {
      inputMatriz.addEventListener("input", () => {
        const val = inputMatriz.value.replace(/\D/g, "");
        inputMatriz.value = val;
        countDigitos.textContent = val.length;
        countDigitos.className = val.length === 30 ? "fw-bold text-success" : (val.length > 0 ? "fw-bold text-warning" : "fw-bold");

        if (val.length === 30) {
          const condDig = val.substring(21, 22);
          if (["9", "8", "7", "5"].includes(condDig)) {
            if (selectCondicion) selectCondicion.value = condDig;
            const edifDig = val.substring(22, 24);
            const pisoDig = val.substring(24, 26);
            if (inputEdificio && edifDig !== "00") inputEdificio.value = edifDig;
            if (inputPiso && pisoDig !== "00") inputPiso.value = pisoDig;
            actualizarVisibilidadParametrosPh();
          }
        }
      });
    }

    if (selectTipoMut && selectCondicion) {
      selectTipoMut.addEventListener("change", () => {
        const val = selectTipoMut.value;
        if (val === "PH") {
          selectCondicion.value = "9";
        } else if (val === "MEJORA") {
          selectCondicion.value = "5";
        } else if (val === "MANZANA_NUEVA") {
          selectCondicion.value = "0";
          if (boxAsistente) {
            boxAsistente.style.display = "block";
            ejecutarConsultaSiguienteManzana();
          }
        } else if (val === "DESENGLOBE" || val === "SEGREGACION") {
          if (selectCondicion.value === "9" || selectCondicion.value === "5") {
            selectCondicion.value = "0";
          }
        }
        actualizarVisibilidadParametrosPh();
      });

      selectCondicion.addEventListener("change", actualizarVisibilidadParametrosPh);
    }

    if (selComuna) {
      selComuna.addEventListener("change", () => {
        const val = selComuna.value;
        if (val === "OTRA") {
          if (inpComuna) {
            inpComuna.style.display = "block";
            inpComuna.value = "";
            inpComuna.focus();
          }
        } else {
          if (inpComuna) {
            inpComuna.style.display = "none";
            inpComuna.value = val;
          }
          ejecutarConsultaSiguienteManzana();
        }
      });
    }

    if (selSector) {
      selSector.addEventListener("change", () => {
        const sec = selSector.value;
        if (sec === "01") {
          if (selComuna) selComuna.style.display = "block";
          if (inpComuna) {
            inpComuna.style.display = "none";
            inpComuna.value = selComuna ? selComuna.value : "09";
          }
          if (selVeredas) selVeredas.style.display = "none";
          if (inpBarrio) {
            inpBarrio.style.display = "block";
            inpBarrio.value = "0000";
          }
          ejecutarConsultaSiguienteManzana();
        } else {
          cargarCatalogoVeredas();
          if (selComuna) selComuna.style.display = "none";
          if (inpComuna) {
            inpComuna.style.display = "none";
            inpComuna.value = (sec !== "00" && sec !== "OTRO") ? sec : "00";
          }
          if (selVeredas) selVeredas.style.display = "block";
          if (inpBarrio && selVeredas) {
            inpBarrio.value = selVeredas.value || "0000";
          }
          ejecutarConsultaSiguienteManzana();
        }
      });
    }

    if (selVeredas && inpBarrio) {
      selVeredas.addEventListener("change", () => {
        inpBarrio.value = selVeredas.value;
        ejecutarConsultaSiguienteManzana();
      });
    }

    if (btnToggleAsistente && boxAsistente) {
      btnToggleAsistente.addEventListener("click", () => {
        const isHidden = boxAsistente.style.display === "none";
        boxAsistente.style.display = isHidden ? "block" : "none";
        if (isHidden) {
          cargarCatalogoVeredas();
          ejecutarConsultaSiguienteManzana();
        }
      });
    }

    if (btnCerrarAsistente && boxAsistente) {
      btnCerrarAsistente.addEventListener("click", () => {
        boxAsistente.style.display = "none";
      });
    }

    if (btnConsultarManzana) {
      btnConsultarManzana.addEventListener("click", () => {
        ejecutarConsultaSiguienteManzana();
      });
    }

    if (btnAplicarSugerencia) {
      btnAplicarSugerencia.addEventListener("click", () => {
        if (!ultimaSugerenciaData || !inputMatriz) return;
        inputMatriz.value = ultimaSugerenciaData.npn_base_sugerido;
        if (countDigitos) {
          countDigitos.textContent = "30";
          countDigitos.className = "fw-bold text-success";
        }
        if (boxAsistente) boxAsistente.style.display = "none";
        Swal.fire({
          icon: "success",
          title: `Manzana / Polígono ${ultimaSugerenciaData.siguiente_manzana_sugerida} Aplicada`,
          text: `Se cargó el NPN base correlativo para esta zona. El primer predio iniciará en Terreno 0001.`,
          timer: 2000,
          showConfirmButton: false
        });
      });
    }

    let generandoActual = false;
    if (btnEjecutarGen) {
      btnEjecutarGen.addEventListener("click", async () => {
        if (generandoActual) return;
        generandoActual = true;
        const matriz = inputMatriz ? inputMatriz.value.trim() : "";
        const cantidad = inputCantidad ? parseInt(inputCantidad.value, 10) : 1;
        const tipoMut = selectTipoMut ? selectTipoMut.value : "DESENGLOBE";
        const tramite = inputTramite ? inputTramite.value.trim() : "";
        const obs = inputObs ? inputObs.value.trim() : "";

        if (!matriz || matriz.length !== 30) {
          Swal.fire({ icon: "warning", title: "Predio Matriz Inválido", text: "Debes ingresar exactamente 30 dígitos numéricos para el predio matriz de referencia." });
          return;
        }

        if (isNaN(cantidad) || cantidad < 1 || cantidad > 100) {
          Swal.fire({ icon: "warning", title: "Cantidad Inválida", text: "Indica una cantidad entre 1 y 100 predios a generar." });
          return;
        }

        btnEjecutarGen.disabled = true;
        btnEjecutarGen.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> Generando...`;

        try {
          const resp = await fetch(`${rp}/api/v1/predios-generador/generar-npn-homologados`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              predio_matriz: matriz,
              cantidad: cantidad,
              tipo_mutacion: tipoMut,
              condicion_propiedad: selectCondicion ? selectCondicion.value : "0",
              edificio: inputEdificio ? inputEdificio.value.trim().padStart(2, "0") : "00",
              piso: inputPiso ? inputPiso.value.trim().padStart(2, "0") : "00",
              consecutivo_tramite: tramite,
              observaciones: obs,
            }),
          });

          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "Error en la generación de números prediales");

          ultimosPrediosGenerados = data.items || [];
          renderResultadosGenerados(ultimosPrediosGenerados);
          consultarStockDisponibles();

          Swal.fire({
            icon: "success",
            title: "¡Predios Generados!",
            text: `Se generaron y reservaron exitosamente ${ultimosPrediosGenerados.length} predios con sus códigos homologados oficiales.`,
            timer: 2000,
            showConfirmButton: false,
          });
        } catch (err) {
          Swal.fire({ icon: "error", title: "No se pudo generar", text: err.message });
        } finally {
          btnEjecutarGen.disabled = false;
          btnEjecutarGen.innerHTML = `<i class="bi bi-lightning-charge-fill"></i> Generar`;
          generandoActual = false;
        }
      });
    }

    if (btnCopiarTodo) {
      btnCopiarTodo.addEventListener("click", () => {
        if (!ultimosPrediosGenerados || ultimosPrediosGenerados.length === 0) return;
        const lineas = ["NUMERO_PREDIAL\tCODIGO_HOMOLOGADO"];
        ultimosPrediosGenerados.forEach(i => lineas.push(`${i.numero_predial}\t${i.codigo_homologado}`));
        navigator.clipboard.writeText(lineas.join("\n")).then(() => {
          Swal.fire({ icon: "success", title: "Copiado al Portapapeles", text: `Se copiaron ${ultimosPrediosGenerados.length} registros listos para pegar en Alfa.`, timer: 2000, showConfirmButton: false });
        });
      });
    }

    if (btnDescargarCsv) {
      btnDescargarCsv.addEventListener("click", () => {
        if (!ultimosPrediosGenerados || ultimosPrediosGenerados.length === 0) return;
        let csvContent = "data:text/csv;charset=utf-8,NUMERO_PREDIAL,CODIGO_HOMOLOGADO,ESTADO,FECHA_RESERVA\n";
        ultimosPrediosGenerados.forEach(i => {
          csvContent += `${i.numero_predial},${i.codigo_homologado},${i.estado},${i.fecha_reserva || ''}\n`;
        });
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `predios_nuevos_homologados_${Date.now()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      });
    }

    if (chkTodosReservas && tbodyReservas) {
      chkTodosReservas.addEventListener("change", () => {
        const checked = chkTodosReservas.checked;
        tbodyReservas.querySelectorAll(".chk-reserva-item").forEach(chk => chk.checked = checked);
      });
    }

    if (btnLiberarSelec && tbodyReservas) {
      btnLiberarSelec.addEventListener("click", () => {
        const seleccionados = [];
        tbodyReservas.querySelectorAll(".chk-reserva-item:checked").forEach(chk => seleccionados.push(chk.value));
        if (seleccionados.length === 0) {
          Swal.fire({ icon: "info", title: "Sin selección", text: "Marca las casillas de las reservas que deseas liberar." });
          return;
        }
        confirmarYLiberarCodigos(seleccionados);
      });
    }

    if (btnConsolidarSelec && tbodyReservas) {
      btnConsolidarSelec.addEventListener("click", () => {
        const seleccionados = [];
        tbodyReservas.querySelectorAll(".chk-reserva-item:checked").forEach(chk => seleccionados.push(chk.value));
        if (seleccionados.length === 0) {
          Swal.fire({ icon: "info", title: "Sin selección", text: "Marca las casillas de las reservas que deseas fijar y consolidar definitivamente en base." });
          return;
        }
        confirmarYConsolidarCodigos(seleccionados);
      });
    }

    if (btnRefrescarRes) {
      btnRefrescarRes.addEventListener("click", () => cargarReservasActivas());
    }

    const btnCopiarTodoRes = document.getElementById("btnCopiarTodoReservas");
    if (btnCopiarTodoRes) {
      btnCopiarTodoRes.addEventListener("click", () => {
        if (!listaReservasActivas || listaReservasActivas.length === 0) {
          Swal.fire({ icon: "info", title: "Sin reservas", text: "No hay reservas activas en la lista para copiar." });
          return;
        }

        const seleccionados = [];
        if (tbodyReservas) {
          tbodyReservas.querySelectorAll(".chk-reserva-item:checked").forEach(chk => seleccionados.push(chk.value));
        }

        let itemsACopiar = listaReservasActivas;
        if (seleccionados.length > 0) {
          itemsACopiar = listaReservasActivas.filter(r => seleccionados.includes(r.codigo_homologado));
        }

        const lineas = ["NUMERO_PREDIAL\tCODIGO_HOMOLOGADO\tUSUARIO_TRAMITE\tFECHA_RESERVA"];
        itemsACopiar.forEach(r => {
          const npn = r.numero_predial || "";
          const ch = r.codigo_homologado || "";
          const userTramite = r.observaciones || r.usuario || "";
          const fecha = r.fecha_asignacion ? new Date(r.fecha_asignacion).toLocaleString() : "";
          lineas.push(`${npn}\t${ch}\t${userTramite}\t${fecha}`);
        });

        navigator.clipboard.writeText(lineas.join("\n")).then(() => {
          Swal.fire({
            icon: "success",
            title: "Copiado al Portapapeles",
            text: `Se copiaron ${itemsACopiar.length} registros en formato listo para Alfa.`,
            timer: 2000,
            showConfirmButton: false
          });
        });
      });
    }

    const btnDescargarCsvRes = document.getElementById("btnDescargarCsvReservas");
    if (btnDescargarCsvRes) {
      btnDescargarCsvRes.addEventListener("click", () => {
        if (!listaReservasActivas || listaReservasActivas.length === 0) {
          Swal.fire({ icon: "info", title: "Sin reservas", text: "No hay reservas activas en la lista para exportar." });
          return;
        }

        const seleccionados = [];
        if (tbodyReservas) {
          tbodyReservas.querySelectorAll(".chk-reserva-item:checked").forEach(chk => seleccionados.push(chk.value));
        }

        let itemsAExportar = listaReservasActivas;
        if (seleccionados.length > 0) {
          itemsAExportar = listaReservasActivas.filter(r => seleccionados.includes(r.codigo_homologado));
        }

        let csvContent = "data:text/csv;charset=utf-8,NUMERO_PREDIAL,CODIGO_HOMOLOGADO,ESTADO,USUARIO,OBSERVACIONES,FECHA_RESERVA\n";
        itemsAExportar.forEach(r => {
          const npn = (r.numero_predial || "").replace(/,/g, " ");
          const ch = (r.codigo_homologado || "").replace(/,/g, " ");
          const estado = (r.estado || "RESERVADO").replace(/,/g, " ");
          const usuario = (r.usuario || "").replace(/,/g, " ");
          const obs = (r.observaciones || "").replace(/,/g, " ");
          const fecha = r.fecha_asignacion ? new Date(r.fecha_asignacion).toLocaleString().replace(/,/g, " ") : "";
          csvContent += `${npn},${ch},${estado},${usuario},${obs},${fecha}\n`;
        });

        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `homologados_en_reserva_${Date.now()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      });
    }


    // ----------------------------------------------------
    // NUEVAS FUNCIONALIDADES: ALFA, FILTROS Y LIMPIEZA
    // ----------------------------------------------------
    const btnAlfaGen = document.getElementById("btnPlantillaAlfaGenerador");
    if (btnAlfaGen) {
      btnAlfaGen.addEventListener("click", () => {
        descargarPlantillaOficialAlfa(ultimosPrediosGenerados, `plantilla_alfa_nuevos_${Date.now()}.txt`);
      });
    }

    const btnAlfaRes = document.getElementById("btnPlantillaAlfaReservas");
    if (btnAlfaRes) {
      btnAlfaRes.addEventListener("click", () => {
        descargarPlantillaOficialAlfa(listaReservasActivas, `plantilla_alfa_reservas_${Date.now()}.txt`);
      });
    }

    const inpFiltroRes = document.getElementById("inpFiltroReservas");
    if (inpFiltroRes) {
      inpFiltroRes.addEventListener("input", () => aplicarFiltrosReservas());
    }

    const selAntiguedadRes = document.getElementById("selAntiguedadReservas");
    if (selAntiguedadRes) {
      selAntiguedadRes.addEventListener("change", () => aplicarFiltrosReservas());
    }

    const btnLibInactivas = document.getElementById("btnLiberarInactivas");
    if (btnLibInactivas) {
      btnLibInactivas.addEventListener("click", () => {
        const val = selAntiguedadRes && selAntiguedadRes.value === "15" ? 15 : 30;
        ejecutarLiberacionInactivas(val);
      });
    }

    initTabAsignarExistentes();
    moduloInicializado = true;

  }

  // =========================================================
  // LOGICA PESTAÑA 3: ASIGNAR HOMOLOGADOS A NPNS EXISTENTES
  // =========================================================
  let ultimosExistentesAsignados = [];

  function extraerNpnsValidos(texto) {
    if (!texto) return [];
    const lineas = texto.split(/[\s,;\n]+/);
    const validos = [];
    lineas.forEach(l => {
      const clean = l.replace(/\D/g, "");
      if (clean.length === 30 && !validos.includes(clean)) {
        validos.push(clean);
      }
    });
    return validos;
  }

  function initTabAsignarExistentes() {
    const areaNpns = document.getElementById("genAreaNpnsExistentes");
    const lblCount = document.getElementById("lblCountNpnsExistentes");
    const btnLimpiar = document.getElementById("btnLimpiarAreaNpns");
    const inpTramite = document.getElementById("genTramiteExistentesInput");
    const inpObs = document.getElementById("genObsExistentesInput");
    const btnConsultar = document.getElementById("btnConsultarNpnsExistentes");
    const btnEjecutar = document.getElementById("btnEjecutarAsignarExistentes");
    const wrapResultados = document.getElementById("wrapResultadosAsignacionExistentes");
    const lblCant = document.getElementById("lblCantExistentesGenerada");
    const tbody = document.getElementById("tbodyResultadosExistentes");
    const btnCopiar = document.getElementById("btnCopiarTodoExistentes");
    const btnCsv = document.getElementById("btnDescargarCsvExistentes");

    if (areaNpns && lblCount) {
      areaNpns.addEventListener("input", () => {
        const val = extraerNpnsValidos(areaNpns.value);
        lblCount.textContent = val.length;
        lblCount.className = val.length > 0 ? "fw-bold text-success" : "fw-bold text-muted";
      });
    }

    if (btnLimpiar && areaNpns) {
      btnLimpiar.addEventListener("click", () => {
        areaNpns.value = "";
        if (lblCount) {
          lblCount.textContent = "0";
          lblCount.className = "fw-bold text-muted";
        }
      });
    }

    let buscandoEnProgreso = false;
    if (btnConsultar && areaNpns) {
      btnConsultar.addEventListener("click", async () => {
        if (buscandoEnProgreso) return;
        const validos = extraerNpnsValidos(areaNpns.value);
        if (validos.length === 0) {
          Swal.fire({ icon: "warning", title: "Sin NPNs Válidos", text: "Ingresa al menos un NPN de 30 dígitos numéricos para buscar." });
          return;
        }

        buscandoEnProgreso = true;
        btnConsultar.disabled = true;
        btnConsultar.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> Buscando...`;

        try {
          const resp = await fetch(`${rp}/api/v1/predios-generador/consultar-npns-existentes`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ numeros_prediales: validos })
          });

          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "Error al realizar la consulta diagnóstica.");

          const itemsDiagnostico = data.items || [];
          if (wrapResultados) wrapResultados.classList.remove("d-none");
          if (lblCant) lblCant.textContent = itemsDiagnostico.length;

          renderResultadosDiagnostico(itemsDiagnostico, tbody);

          Swal.fire({
            icon: "info",
            title: "Diagnóstico Completado",
            text: `Se verificaron ${data.total_consultados} NPNs: ${data.total_sin_homologado} listos para homologar y ${data.total_con_homologado} que ya poseen código.`,
            timer: 3000,
            showConfirmButton: false
          });
        } catch (err) {
          Swal.fire({ icon: "error", title: "No se pudo consultar", text: err.message });
        } finally {
          btnConsultar.disabled = false;
          btnConsultar.innerHTML = `<i class="bi bi-search me-1"></i> 1. Buscar`;
          buscandoEnProgreso = false;
        }
      });
    }

    let asignandoEnProgreso = false;
    if (btnEjecutar && areaNpns) {
      btnEjecutar.addEventListener("click", async () => {
        if (asignandoEnProgreso) return;
        const validos = extraerNpnsValidos(areaNpns.value);
        if (validos.length === 0) {
          Swal.fire({ icon: "warning", title: "Sin NPNs Válidos", text: "Ingresa al menos un NPN de 30 dígitos numéricos para procesar." });
          return;
        }

        if (validos.length > 100) {
          Swal.fire({ icon: "warning", title: "Límite Excedido", text: "Solo se permite procesar hasta 100 NPNs por solicitud." });
          return;
        }

        asignandoEnProgreso = true;
        btnEjecutar.disabled = true;
        btnEjecutar.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> Procesando...`;

        try {
          const resp = await fetch(`${rp}/api/v1/predios-generador/asignar-homologado-existentes`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              numeros_prediales: validos,
              consecutivo_tramite: inpTramite ? inpTramite.value.trim() : "",
              observaciones: inpObs ? inpObs.value.trim() : ""
            })
          });

          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "Error al asignar homologados a NPNs existentes.");

          ultimosExistentesAsignados = data.items || [];
          if (wrapResultados) wrapResultados.classList.remove("d-none");
          if (lblCant) lblCant.textContent = ultimosExistentesAsignados.length;

          renderResultadosExistentes(ultimosExistentesAsignados, tbody);
          consultarStockDisponibles();

          const totalmenteNuevos = ultimosExistentesAsignados.filter(i => i.es_nueva_reserva).length;
          const previamenteHomologados = ultimosExistentesAsignados.length - totalmenteNuevos;

          Swal.fire({
            icon: "success",
            title: "¡Homologación Completada!",
            text: `Se asignaron y reservaron códigos nuevos para ${totalmenteNuevos} predio(s). ${previamenteHomologados > 0 ? previamenteHomologados + ' predio(s) previamente homologados fueron omitidos por protección.' : ''}`,
            timer: 3500,
            showConfirmButton: false
          });
        } catch (err) {
          Swal.fire({ icon: "error", title: "No se pudo asignar", text: err.message });
        } finally {
          btnEjecutar.disabled = false;
          btnEjecutar.innerHTML = `<i class="bi bi-lightning-charge-fill me-1"></i> Asignar Homologados`;
          asignandoEnProgreso = false;
        }
      });
    }

    if (btnCopiar) {
      btnCopiar.addEventListener("click", () => {
        if (!ultimosExistentesAsignados || ultimosExistentesAsignados.length === 0) return;
        const lineas = ["NUMERO_PREDIAL\tCODIGO_HOMOLOGADO\tORIGEN_BASE"];
        ultimosExistentesAsignados.forEach(i => lineas.push(`${i.numero_predial}\t${i.codigo_homologado}\t${i.origen_base}`));
        navigator.clipboard.writeText(lineas.join("\n")).then(() => {
          Swal.fire({ icon: "success", title: "Copiado al Portapapeles", text: `Se copiaron ${ultimosExistentesAsignados.length} registros listos para Alfa.`, timer: 2000, showConfirmButton: false });
        });
      });
    }

    if (btnCsv) {
          const btnAlfaExistentes = document.getElementById("btnPlantillaAlfaExistentes");
    if (btnAlfaExistentes) {
      btnAlfaExistentes.addEventListener("click", () => {
        descargarPlantillaOficialAlfa(ultimosExistentesAsignados, `plantilla_alfa_existentes_${Date.now()}.txt`);
      });
    }

    btnCsv.addEventListener("click", () => {
        if (!ultimosExistentesAsignados || ultimosExistentesAsignados.length === 0) return;
        let csvContent = "data:text/csv;charset=utf-8,NUMERO_PREDIAL,CODIGO_HOMOLOGADO,ORIGEN_BASE,ESTADO,FECHA_RESERVA\n";
        ultimosExistentesAsignados.forEach(i => {
          csvContent += `${i.numero_predial},${i.codigo_homologado},${i.origen_base},${i.estado},${i.fecha_reserva || ''}\n`;
        });
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `homologados_predios_existentes_${Date.now()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      });
    }
  }

  function renderResultadosDiagnostico(items, tbody) {
    if (!tbody) return;
    if (!items || items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">No hay predios consultados.</td></tr>`;
      return;
    }

    let html = "";
    items.forEach((item, index) => {
      const badgeHomo = item.tiene_homologado
        ? `<span class="badge bg-info-subtle text-info border border-info-subtle px-2 py-1"><i class="bi bi-shield-check me-1"></i>Ya Homologado (${item.codigo_homologado_actual})</span>`
        : `<span class="badge bg-success-subtle text-success border border-success-subtle px-2 py-1"><i class="bi bi-lightning me-1"></i>Listo para Asignar</span>`;

      html += `
        <tr>
          <td class="text-center fw-bold text-muted">${index + 1}</td>
          <td>
            <span class="font-monospace fw-bold text-navy">${item.numero_predial}</span>
          </td>
          <td>
            <span class="small fw-semibold text-secondary">${item.origen_base}</span>
          </td>
          <td>
            ${badgeHomo}
          </td>
          <td class="text-center">
            <span class="badge bg-secondary">${item.estado_homologado_actual || 'PENDIENTE'}</span>
          </td>
          <td class="text-center">
            <button class="btn btn-xs btn-outline-primary py-0 px-2 btn-copiar-npn-e" data-npn="${item.numero_predial}" title="Copiar NPN">
              <i class="bi bi-clipboard"></i> NPN
            </button>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;

    tbody.querySelectorAll(".btn-copiar-npn-e").forEach(btn => {
      btn.addEventListener("click", () => {
        const val = btn.getAttribute("data-npn");
        navigator.clipboard.writeText(val).then(() => {
          Swal.fire({ icon: "success", title: "NPN Copiado", text: val, timer: 1500, showConfirmButton: false });
        });
      });
    });
  }

  function renderResultadosExistentes(items, tbody) {
    if (!tbody) return;
    if (!items || items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">No hay predios asignados.</td></tr>`;
      return;
    }

    let html = "";
    items.forEach((item, index) => {
      const badgeRes = item.es_nueva_reserva 
        ? `<span class="badge bg-success-subtle text-success border border-success-subtle px-2 py-1"><i class="bi bi-plus-circle me-1"></i>Nuevo Homologado</span>` 
        : `<span class="badge bg-info-subtle text-info border border-info-subtle px-2 py-1"><i class="bi bi-clock-history me-1"></i>Previamente Asignado</span>`;

      html += `
        <tr>
          <td class="text-center fw-bold text-muted">${index + 1}</td>
          <td>
            <span class="font-monospace fw-bold text-navy">${item.numero_predial}</span>
          </td>
          <td>
            <span class="small fw-semibold text-secondary">${item.origen_base}</span>
          </td>
          <td>
            <span class="badge bg-success-subtle text-success border border-success-subtle font-monospace px-2 py-1">${item.codigo_homologado}</span>
            ${badgeRes}
          </td>
          <td class="text-center">
            <span class="badge bg-warning text-dark">${item.estado}</span>
          </td>
          <td class="text-center">
            <div class="btn-group btn-group-sm">
              <button class="btn btn-xs btn-outline-primary py-0 px-2 btn-copiar-npn-e" data-npn="${item.numero_predial}" title="Copiar NPN">
                <i class="bi bi-clipboard"></i> NPN
              </button>
              <button class="btn btn-xs btn-outline-success py-0 px-2 btn-copiar-ch-e" data-ch="${item.codigo_homologado}" title="Copiar Homologado">
                <i class="bi bi-clipboard-check"></i> Homol.
              </button>
            </div>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;

    tbody.querySelectorAll(".btn-copiar-npn-e").forEach(btn => {
      btn.addEventListener("click", () => {
        const val = btn.getAttribute("data-npn");
        navigator.clipboard.writeText(val).then(() => {
          Swal.fire({ icon: "success", title: "NPN Copiado", text: val, timer: 1500, showConfirmButton: false });
        });
      });
    });

    tbody.querySelectorAll(".btn-copiar-ch-e").forEach(btn => {
      btn.addEventListener("click", () => {
        const val = btn.getAttribute("data-ch");
        navigator.clipboard.writeText(val).then(() => {
          Swal.fire({ icon: "success", title: "Código Homologado Copiado", text: val, timer: 1500, showConfirmButton: false });
        });
      });
    });
  }


  // API Pública Global
  window.abrirGeneradorNpn = function (opts = {}) {
    initListeners();
    bindElements();
    if (!modalGen) return;

    modalGen.classList.remove("d-none");
    modalGen.style.display = "flex";
    consultarStockDisponibles();

    if (opts.predioMatriz && inputMatriz) {
      inputMatriz.value = opts.predioMatriz.replace(/\D/g, "");
      if (countDigitos) {
        countDigitos.textContent = inputMatriz.value.length;
        countDigitos.className = inputMatriz.value.length === 30 ? "fw-bold text-success" : "fw-bold text-warning";
      }
    }

    if (opts.consecutivoTramite && inputTramite) {
      inputTramite.value = opts.consecutivoTramite;
    }

    if (opts.tipoMutacion && selectTipoMut) {
      selectTipoMut.value = opts.tipoMutacion;
      selectTipoMut.dispatchEvent(new Event("change"));
    }
  };

  // Escucha global por delegación de eventos para cualquier botón de apertura en el DOM
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("#btnAbrirGeneradorNpn, #btnAbrirGeneradorDetalle, #btnHeaderGenerarNpn");
    if (btn) {
      e.preventDefault();
      
      let predioMatriz = "";
      let tramite = "";

      // Intentar extraer de contexto de Cargas
      const txtPredios = document.getElementById("txtPredios");
      if (txtPredios && txtPredios.value.trim()) {
        predioMatriz = txtPredios.value.trim().split(/[\s,;\n]+/)[0] || "";
      }

      // Intentar extraer de contexto de Detalle
      const elNpn = document.getElementById("resumenPredioNumero");
      if (elNpn && elNpn.textContent && elNpn.textContent.trim().replace(/\D/g, "").length === 30) {
        predioMatriz = elNpn.textContent.trim().replace(/\D/g, "");
      } else {
        const primerRow = document.querySelector("#asigDetallePrediosBody tr td:nth-child(2)");
        if (primerRow && primerRow.textContent.trim().replace(/\D/g, "").length === 30) {
          predioMatriz = primerRow.textContent.trim().replace(/\D/g, "");
        }
      }

      const elBreadcrumb = document.getElementById("breadcrumbAssignmentName");
      if (elBreadcrumb && elBreadcrumb.textContent) {
        tramite = elBreadcrumb.textContent.trim();
      }

      window.abrirGeneradorNpn({
        predioMatriz: predioMatriz,
        consecutivoTramite: tramite,
        tipoMutacion: "DESENGLOBE"
      });
    }
  });

  // Auto-inicializar al cargar DOM
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initListeners);
  } else {
    initListeners();
  }
})();


  function descargarPlantillaOficialAlfa(items, nombreArchivo = "plantilla_cargue_alfa.txt") {
    if (!items || items.length === 0) {
      Swal.fire({ icon: "info", title: "Sin datos", text: "No hay registros para exportar en la plantilla de Alfa." });
      return;
    }

    const headers = ["NUMERO_PREDIAL", "CODIGO_HOMOLOGADO", "CONSECUTIVO_TRAMITE", "CONDICION_PROPIEDAD", "USUARIO", "FECHA_ASIGNACION", "ESTADO"];
    let tsvContent = "\uFEFF" + headers.join("\t") + "\n";

    items.forEach(item => {
      const npn = item.numero_predial || item.numero_predial_matriz || "";
      const ch = item.codigo_homologado || "";
      const tramite = item.consecutivo_tramite || item.tramite || "";
      const cond = item.condicion || item.condicion_propiedad || "";
      const user = item.usuario || "";
      const fecha = item.fecha_reserva || item.fecha_asignacion || "";
      const estado = item.estado || "RESERVADO";

      tsvContent += `${npn}\t${ch}\t${tramite}\t${cond}\t${user}\t${fecha}\t${estado}\n`;
    });

    const blob = new Blob([tsvContent], { type: "text/tab-separated-values;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nombreArchivo;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    Swal.fire({
      toast: true,
      position: "top-end",
      icon: "success",
      title: "Plantilla Alfa descargada",
      showConfirmButton: false,
      timer: 2000
    });
  }
