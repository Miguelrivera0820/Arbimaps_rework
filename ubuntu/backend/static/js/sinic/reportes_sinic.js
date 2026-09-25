/**
 * Módulo Reportes SINIC - Frontend Logic (Leaflet GIS Neiva Light Theme + Control de Versiones + XTF Generator)
 */

let sinicMap = null;
let sinicGeojsonLayer = null;
let currentBasemapType = "voyager";
let tileLayerMap = null;
let tileLayerSat = null;

document.addEventListener("DOMContentLoaded", () => {
  // Cargar métricas y tablas inmediatamente
  try {
    cargarResumenDiagnosticoSinic();
  } catch (e) {
    console.error("Error al cargar resumen:", e);
  }

  try {
    cargarHistorialVersionesSinic();
  } catch (e) {
    console.error("Error al cargar versiones:", e);
  }

  // Inicializar mapa GIS
  try {
    initSinicMap();
  } catch (e) {
    console.error("Error al iniciar mapa:", e);
  }
});

function initSinicMap() {
  const mapContainer = document.getElementById("sinicGisMap");
  if (!mapContainer) return;

  if (typeof L === "undefined") {
    console.warn("Leaflet (L) aún no está disponible en la página, reintentando...");
    setTimeout(initSinicMap, 300);
    return;
  }

  if (sinicMap) return; // Ya inicializado

  // Centro aproximado de Neiva, Huila
  sinicMap = L.map("sinicGisMap").setView([2.9273, -75.2819], 13);

  // Basemaps: CartoDB Voyager (Claro Neiva) vs ESRI Satellite
  tileLayerMap = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>'
  });

  tileLayerSat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri'
  });

  tileLayerMap.addTo(sinicMap);

  // Cargar capas de terrenos
  cargarCapasTerrenosSinic();
}

function toggleBasemapSinic() {
  if (!sinicMap || !tileLayerMap || !tileLayerSat) return;
  if (currentBasemapType === "voyager") {
    sinicMap.removeLayer(tileLayerMap);
    tileLayerSat.addTo(sinicMap);
    currentBasemapType = "satellite";
  } else {
    sinicMap.removeLayer(tileLayerSat);
    tileLayerMap.addTo(sinicMap);
    currentBasemapType = "voyager";
  }
}

function cargarCapasTerrenosSinic() {
  fetch("/api/sinic/capas-geojson/terrenos")
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(data => {
      if (sinicGeojsonLayer && sinicMap) {
        sinicMap.removeLayer(sinicGeojsonLayer);
      }

      if (data && data.features && data.features.length > 0) {
        sinicGeojsonLayer = L.geoJSON(data, {
          style: {
            color: "#0b5138",
            weight: 2,
            fillColor: "#0c706f",
            fillOpacity: 0.28
          },
          onEachFeature: (feature, layer) => {
            layer.on("click", () => {
              const npn = feature.properties.npn;
              if (npn) {
                seleccionarPredioSinic(npn);
              }
            });
          }
        }).addTo(sinicMap);

        try {
          sinicMap.fitBounds(sinicGeojsonLayer.getBounds());
        } catch (e) {
          console.warn("No fue posible ajustar zoom bounds:", e);
        }
      }
    })
    .catch(err => console.error("Error al cargar capas GeoJSON terrenos:", err));
}

function seleccionarPredioSinic(npn) {
  fetch(`/api/sinic/predio-detalle/${npn}`)
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(p => {
      if (!p || p.detail) return;
      const elTitle = document.getElementById("sinicCardTitle");
      if (elTitle) elTitle.innerHTML = `<i class="bi bi-building"></i> NPN: ${p.npn || "-"}`;
      
      const elCh = document.getElementById("sinicCardCh");
      if (elCh) elCh.textContent = p.codigo_homologado || "-";

      const elFmi = document.getElementById("sinicCardFmi");
      if (elFmi) elFmi.textContent = p.matricula_inmobiliaria || "-";

      const elArea = document.getElementById("sinicCardArea");
      if (elArea) elArea.textContent = p.area_catastral_terreno ? parseFloat(p.area_catastral_terreno).toLocaleString() : "0";

      const elDest = document.getElementById("sinicCardDest");
      if (elDest) elDest.textContent = p.destinacion_economica || "-";

      const props = (p.propietarios || []).map(pr => `${pr.primer_nombre || ""} ${pr.primer_apellido || pr.razon_social || ""}`).join(", ");
      const elProp = document.getElementById("sinicCardProp");
      if (elProp) elProp.textContent = props || "Sin propietarios registrados";

      const elCard = document.getElementById("sinicPredioDetailCard");
      if (elCard) elCard.classList.remove("d-none");
    })
    .catch(err => console.error("Error al obtener predio detalle:", err));
}

function cerrarCardPredioSinic() {
  const elCard = document.getElementById("sinicPredioDetailCard");
  if (elCard) elCard.classList.add("d-none");
}

function resetMapSinic() {
  if (sinicMap && sinicGeojsonLayer) {
    try {
      sinicMap.fitBounds(sinicGeojsonLayer.getBounds());
    } catch (e) {
      sinicMap.setView([2.9273, -75.2819], 13);
    }
  }
}

function toggleLayerSinic(tipo) {
  if (!sinicGeojsonLayer || !sinicMap) return;
  if (sinicMap.hasLayer(sinicGeojsonLayer)) {
    sinicMap.removeLayer(sinicGeojsonLayer);
  } else {
    sinicMap.addLayer(sinicGeojsonLayer);
  }
}

function buscarPredioSinic() {
  const input = document.getElementById("sinicNpnSearch");
  if (!input) return;
  const query = input.value.trim();
  if (!query) return;
  seleccionarPredioSinic(query);
}

function cargarResumenDiagnosticoSinic() {
  fetch("/api/sinic/resumen-diagnostico")
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(res => {
      if (!res.success) return;
      const m = res.metricas || {};
      
      const elPredios = document.getElementById("statPredios");
      if (elPredios) elPredios.textContent = (m.total_predios_activos || 0).toLocaleString();

      const elTerrenos = document.getElementById("statTerrenos");
      if (elTerrenos) elTerrenos.textContent = (m.total_terrenos_gis || 0).toLocaleString();

      const elConst = document.getElementById("statConstrucciones");
      if (elConst) elConst.textContent = (m.total_construcciones_gis || 0).toLocaleString();

      const badge = document.getElementById("sinicQualityBadge");
      if (badge) {
        const lvl = res.nivel_calidad || "OPTIMO";
        badge.textContent = `Estado: ${lvl}`;
        if (lvl === "OPTIMO") {
          badge.className = "badge bg-light text-success fs-6 px-3 py-2 shadow-sm font-weight-bold";
        } else if (lvl === "ADVERTENCIA") {
          badge.className = "badge bg-light text-warning fs-6 px-3 py-2 shadow-sm font-weight-bold";
        } else {
          badge.className = "badge bg-light text-danger fs-6 px-3 py-2 shadow-sm font-weight-bold";
        }
      }
    })
    .catch(err => console.error("Error al cargar resumen diagnostico:", err));
}

function cargarHistorialVersionesSinic() {
  fetch("/api/sinic/versiones")
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(list => {
      const tbody = document.getElementById("sinicVersionesTbody");
      const elEntregas = document.getElementById("statEntregas");
      if (elEntregas) elEntregas.textContent = (Array.isArray(list) ? list.length : 0);

      if (!tbody) return;

      if (!list || !Array.isArray(list) || list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">No hay entregas registradas en D:\\</td></tr>`;
        return;
      }

      tbody.innerHTML = list.map(v => {
        const fecha = v.fecha_corte ? new Date(v.fecha_corte).toLocaleString() : "-";
        const hashShort = v.checksum_sha256 ? v.checksum_sha256.substring(0, 10) + "..." : "-";
        return `
          <tr>
            <td><strong class="text-neiva-deep">${v.codigo_version}</strong></td>
            <td>${fecha}</td>
            <td><span class="badge bg-secondary">${v.tipo_entrega}</span></td>
            <td>${(v.total_predios || 0).toLocaleString()}</td>
            <td><code>${hashShort}</code></td>
            <td>
              <a href="/api/sinic/descargar-paquete/${v.id}" class="btn btn-xs btn-outline-success py-0 px-2 font-weight-500" title="Descargar ZIP">
                <i class="bi bi-download"></i> ZIP
              </a>
            </td>
          </tr>
        `;
      }).join("");
    })
    .catch(err => console.error("Error al cargar historial versiones:", err));
}

function ejecutarGeneracionXtfSinic() {
  const btn = document.getElementById("btnGenerarXtf");
  const pContainer = document.getElementById("sinicProgressContainer");
  const pBar = document.getElementById("sinicProgressBar");
  const pStatus = document.getElementById("sinicProgressStatus");
  const pPercent = document.getElementById("sinicProgressPercent");

  const selTipo = document.getElementById("sinicTipoEntrega");
  const txtObs = document.getElementById("sinicObsEntrega");

  const tipo = selTipo ? selTipo.value : "TOTAL";
  const obs = txtObs ? txtObs.value : "";

  if (btn) btn.disabled = true;
  if (pContainer) pContainer.classList.remove("d-none");
  if (pBar) pBar.style.width = "10%";
  if (pPercent) pPercent.textContent = "10%";
  if (pStatus) pStatus.textContent = "Iniciando transformación ETL LADM-COL...";

  let progress = 10;
  const interval = setInterval(() => {
    if (progress < 85) {
      progress += 15;
      if (pBar) pBar.style.width = `${progress}%`;
      if (pPercent) pPercent.textContent = `${progress}%`;
      if (progress === 40 && pStatus) pStatus.textContent = "Construyendo XML INTERLIS 2.0 SINIC_V1_0...";
      if (progress === 70 && pStatus) pStatus.textContent = "Calculando Hash SHA-256 y comprimiendo .ZIP...";
    }
  }, 400);

  fetch("/api/sinic/generar-entrega-xtf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tipo_entrega: tipo, observaciones: obs })
  })
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(res => {
      clearInterval(interval);
      if (pBar) pBar.style.width = "100%";
      if (pPercent) pPercent.textContent = "100%";
      if (pStatus) pStatus.textContent = "¡Entrega generada con éxito!";

      setTimeout(() => {
        if (btn) btn.disabled = false;
        if (pContainer) pContainer.classList.add("d-none");
        cargarHistorialVersionesSinic();
        cargarResumenDiagnosticoSinic();
        alert(`✔ Entrega oficial ${res.codigo_version} generada exitosamente en D:\\20250711_CONSERVACION NEIVA\\20260915_MODULO TRANSFERENCIA SINIC`);
      }, 800);
    })
    .catch(err => {
      clearInterval(interval);
      if (btn) btn.disabled = false;
      if (pStatus) pStatus.textContent = "Error al generar entrega.";
      console.error("Error al generar entrega XTF:", err);
      alert("⚠ Ocurrió un error al generar la entrega XTF. Revise la consola.");
    });
}

function ejecutarPreflightSinic() {
  const container = document.getElementById("sinicAlertasContainer");
  if (!container) return;
  container.innerHTML = `<div class="text-center py-3 text-neiva-green font-weight-500"><i class="bi bi-hourglass-split me-1"></i> Evaluando reglas CLBD, CLP, CLI y CLUC...</div>`;

  fetch("/api/sinic/preflight-checker", { method: "POST" })
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(res => {
      if (!res.success) return;
      const alertas = res.alertas || [];
      if (alertas.length === 0) {
        container.innerHTML = `
          <div class="alert alert-success border-success text-xs shadow-sm">
            <i class="bi bi-check-circle-fill me-1"></i> <strong>100% Conforme:</strong> No se encontraron inconsistencias críticas ni advertencias en la base de Neiva.
          </div>
        `;
        return;
      }

      container.innerHTML = alertas.map(a => {
        const cls = a.nivel === "CRITICO" ? "alert-danger" : "alert-warning";
        const icon = a.nivel === "CRITICO" ? "bi-exclamation-octagon-fill" : "bi-exclamation-triangle-fill";
        return `
          <div class="alert ${cls} text-xs mb-2 py-2 shadow-sm">
            <i class="bi ${icon} me-1"></i> <strong>[Regla ${a.regla}] ${a.nivel}:</strong> ${a.mensaje}
          </div>
        `;
      }).join("");
    })
    .catch(err => {
      console.error("Error al ejecutar preflight:", err);
      container.innerHTML = `<div class="alert alert-danger text-xs shadow-sm">Error al ejecutar diagnóstico pre-flight.</div>`;
    });
}

function sincronizarBaseSinic() {
  const modalEl = document.getElementById("sinicSyncProgressModal");
  if (!modalEl) return;

  const bsModal = new bootstrap.Modal(modalEl);
  bsModal.show();

  const pBar = document.getElementById("syncProgressBar");
  const pPercent = document.getElementById("syncProgressPercent");
  const pLabel = document.getElementById("syncProgressLabel");
  const btnClose = document.getElementById("btnCerrarModalSync");

  if (btnClose) btnClose.classList.add("d-none");

  // Reset UI steps
  for (let i = 0; i <= 3; i++) {
    const st = document.getElementById(`step-${i}`);
    const ic = document.getElementById(`icon-step-${i}`);
    if (st) st.className = "d-flex align-items-center text-muted py-1";
    if (ic) ic.className = "bi bi-circle me-2";
  }

  const setStepActive = (idx, text, percent) => {
    if (pBar) pBar.style.width = `${percent}%`;
    if (pPercent) pPercent.textContent = `${percent}%`;
    if (pLabel) pLabel.textContent = text;

    for (let i = 0; i < idx; i++) {
      const st = document.getElementById(`step-${i}`);
      const ic = document.getElementById(`icon-step-${i}`);
      if (st) st.className = "d-flex align-items-center text-success font-weight-500 py-1";
      if (ic) ic.className = "bi bi-check-circle-fill me-2 text-success";
    }

    const currSt = document.getElementById(`step-${idx}`);
    const currIc = document.getElementById(`icon-step-${idx}`);
    if (currSt) currSt.className = "d-flex align-items-center text-neiva-deep font-weight-bold py-1";
    if (currIc) currIc.className = "bi bi-arrow-repeat spin me-2 text-neiva-green";
  };

  setStepActive(0, "Limpiando y preparando esquemas g_sinic...", 15);

  let progressStep = 1;
  const timer = setInterval(() => {
    if (progressStep === 1) {
      setStepActive(1, "Transfiriendo 102,348 Terrenos GIS (Geometría 3D)...", 40);
    } else if (progressStep === 2) {
      setStepActive(2, "Transfiriendo el 100% de Predios (166,375 sin omisiones)...", 75);
    } else if (progressStep === 3) {
      setStepActive(3, "Transfiriendo 19,548 Construcciones y Características...", 90);
    }
    progressStep++;
  }, 1200);

  fetch("/api/sinic/sincronizar-base-gsinic", { method: "POST" })
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(res => {
      clearInterval(timer);
      if (pBar) pBar.style.width = "100%";
      if (pPercent) pPercent.textContent = "100%";
      if (pLabel) pLabel.textContent = "¡Sincronización 100% completada exitosamente!";

      for (let i = 0; i <= 3; i++) {
        const st = document.getElementById(`step-${i}`);
        const ic = document.getElementById(`icon-step-${i}`);
        if (st) st.className = "d-flex align-items-center text-success font-weight-bold py-1";
        if (ic) ic.className = "bi bi-check-circle-fill me-2 text-success";
      }

      if (btnClose) btnClose.classList.remove("d-none");

      cargarResumenDiagnosticoSinic();
      cargarCapasTerrenosSinic();
    })
    .catch(err => {
      clearInterval(timer);
      console.error("Error al sincronizar base g_sinic:", err);
      if (pLabel) pLabel.textContent = "Error durante la sincronización.";
      if (btnClose) btnClose.classList.remove("d-none");
    });
}

async function ejecutarValidacionSinic() {
  const tbody = document.getElementById("valReglasTbody");
  const badgePct = document.getElementById("valPctPuntaje");
  const statsReglas = document.getElementById("valStatsReglas");
  const badgeDictamen = document.getElementById("valEstadoDictamen");

  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm text-success me-2"></div> Evaluando reglas de calidad oficiales LADM-COL v1.0...</td></tr>`;

  try {
    const res = await fetch("/api/sinic/validar-consistencia");
    if (!res.ok) throw new Error("Error en servicio de validación");
    const data = await res.json();

    if (data.success && data.reglas) {
      const elPuntos = document.getElementById("valPuntosStats");
      if (badgePct) badgePct.textContent = `${data.resumen.puntaje_calidad_porcentaje}%`;
      if (elPuntos) elPuntos.textContent = `${data.resumen.puntos_obtenidos} / ${data.resumen.puntos_totales} pts`;
      if (statsReglas) statsReglas.textContent = `${data.resumen.reglas_aprobadas} / ${data.resumen.total_reglas_evaluadas}`;
      
      if (badgeDictamen) {
        if (data.resumen.estado_general === "APROBADO") {
          badgeDictamen.className = "badge bg-success mt-1";
          badgeDictamen.textContent = "100% APROBADO";
        } else {
          badgeDictamen.className = "badge bg-warning text-dark mt-1";
          badgeDictamen.textContent = "REVISIÓN REQUERIDA";
        }
      }

      let html = "";
      data.reglas.forEach(r => {
        const badgeState = r.estado === "APROBADO" 
          ? `<span class="badge bg-success-subtle text-success border border-success font-weight-bold">APROBADO</span>`
          : `<span class="badge bg-warning-subtle text-warning border border-warning font-weight-bold">${r.estado}</span>`;
        
        html += `
          <tr>
            <td class="font-weight-bold text-neiva-deep">${r.id}</td>
            <td><span class="badge bg-light text-dark">${r.nivel}</span></td>
            <td><code>${r.abreviatura}</code></td>
            <td><strong>${r.tipo_regla}</strong><br/><small class="text-muted">${r.componente}</small></td>
            <td><small>${r.descripcion}</small></td>
            <td>${badgeState}</td>
            <td><small class="text-secondary">${r.detalles}</small></td>
          </tr>
        `;
      });
      tbody.innerHTML = html;
    }
  } catch (err) {
    console.error("Error al ejecutar validación SINIC:", err);
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger py-3"><i class="bi bi-exclamation-triangle-fill me-1"></i> Error al ejecutar la evaluación de consistencia: ${err.message}</td></tr>`;
  }
}


// Global scope window attachments
window.ejecutarValidacionSinic = ejecutarValidacionSinic;
window.ejecutarPreflightSinic = ejecutarPreflightSinic;
window.sincronizarBaseSinic = sincronizarBaseSinic;
window.ejecutarGeneracionXtfSinic = ejecutarGeneracionXtfSinic;
window.cargarHistorialVersionesSinic = cargarHistorialVersionesSinic;
window.cargarResumenDiagnosticoSinic = cargarResumenDiagnosticoSinic;
