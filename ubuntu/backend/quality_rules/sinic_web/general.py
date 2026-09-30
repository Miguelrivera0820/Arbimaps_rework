# -*- coding: utf-8 -*-
"""Reglas SINIC - Componente General.

Implementa las 19 reglas generales suministradas en el cruce SINIC/ARBIMAPS.

Metodología:
- Equivalencia Exacta: reutiliza sin modificar la lógica ARBIMAPS fuente mediante
  ``ejecutar_regla_exacta``.
- Parcial / Relacionada: usa la misma lectura de datos ARBIMAPS y ajusta únicamente
  el criterio descrito por SINIC y la observación del cruce.
"""
from __future__ import annotations

import re
import unicodedata

WebProject = None

from .compat import administrativo as arb_admin
from .support import dataset_from_layers, issues_to_result
from .engine import ejecutar_regla_exacta, metadata_regla
from .extensions import GENERAL_FUNCTIONS

COMPONENT_SLUG = "general"

LAYER_ALIASES = {}
LAYER_ALIASES.update({
    "ARB_Tramite": (
        "ARB_Tramite", "arb_tramite", "ARB Tramite", "ARB Trámite",
        "(ARB) Tramite", "(ARB) Trámite", "Tramite", "Trámite", "Tramites", "Trámites",
        "ILC_Tramite", "ilc_tramite",
    ),
    "ARB_PredioTramite": (
        "ARB_PredioTramite", "ARB_Predio_Tramite", "arb_prediotramite", "arb_predio_tramite",
        "ILC_PredioTramite", "ILC_Predio_Tramite", "ilc_prediotramite", "ilc_predio_tramite",
        "PredioTramite", "Predio_Tramite", "Predio Trámite",
    ),
})

ESTADO_PREDIO_FIELDS = (
    "estado_predio", "Estado_Predio", "estado", "Estado",
    "estado_ladm", "Estado_Ladm", "estado_registro", "Estado_Registro",
    "estado_actual", "Estado_Actual",
)

TRAMITE_REF_FIELDS = (
    "tramite", "Tramite", "trámite", "Trámite", "arb_tramite", "ARB_Tramite",
    "ilc_tramite", "ILC_Tramite", "tramite_id", "id_tramite", "Id_Tramite",
    "arb_predio_tramite", "ilc_predio_tramite",
)

PREDIO_REF_FIELDS = (
    "predio", "Predio", "arb_predio", "ARB_Predio", "ilc_predio", "ILC_Predio",
    "predio_id", "id_predio", "Id_Predio", "predio_asociado", "Predio_Asociado",
    "arb_predio_tramite", "ilc_predio_tramite",
    "Numero_Predial", "numero_predial", "Numero_Predial_Nacional", "numero_predial_nacional",
    "codigo_homologado", "Codigo_Homologado", "nupre", "NUPRE",
)

IDENTIFIER_FIELDS = (
    "t_ili_tid", "T_Ili_Tid", "T_ILI_TID", "t_id", "T_ID", "TID", "tid",
    "id", "ID", "id_operacion", "Id_Operacion", "ID_OPERACION", "local_id", "Local_ID",
)


def obtener_capas_relevantes():
    if WebProject is None:
        return {}
    capas = {}
    try:
        for layer in WebProject.instance().mapLayers().values():
            try:
                capas[layer.name()] = layer
            except Exception:
                pass
    except Exception:
        pass
    return capas


def _capas(layer_dict=None, layer_dic=None):
    return layer_dict if layer_dict is not None else (
        layer_dic if layer_dic is not None else obtener_capas_relevantes()
    )


def _dataset_y_helper(layer_dict=None, layer_dic=None):
    capas = _capas(layer_dict, layer_dic)
    dataset = dataset_from_layers(capas)
    return capas, dataset, arb_admin.NumeroPredialHelper(dataset)


def _norm(value):
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    return "".join(ch for ch in text if ch.isalnum())


def _raw_text(value):
    if value is None:
        return ""
    try:
        if hasattr(value, "isNull") and value.isNull():
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "<null>", "nan"}:
        return ""
    return text


def _resultado_issues(codigo, issues, dataset, equivalencia, origen):
    resultado = issues_to_result(str(codigo), issues)
    meta = metadata_regla(str(codigo))
    for err in resultado.get("errores", []) or []:
        detalles = dict(err.get("detalles") or err.get("details") or {})
        detalles.update({
            "sinic_id": str(codigo),
            "sinic_abreviatura": meta.get("abbreviation", "") if isinstance(meta, dict) else "",
            "tipo_equivalencia": equivalencia,
            "arbimaps_regla_origen": origen,
            "implementacion": "SINIC_AJUSTADA",
        })
        err["regla"] = str(codigo)
        err["detalles"] = detalles
        err["details"] = detalles
    resultado["regla_sinic"] = meta
    return resultado


def _resultado_errores(codigo, errores, equivalencia, origen):
    meta = metadata_regla(str(codigo))
    salida = []
    for original in errores:
        err = dict(original)
        detalles = dict(err.get("detalles") or err.get("details") or {})
        detalles.update({
            "sinic_id": str(codigo),
            "sinic_abreviatura": meta.get("abbreviation", "") if isinstance(meta, dict) else "",
            "tipo_equivalencia": equivalencia,
            "arbimaps_regla_origen": origen,
            "implementacion": "SINIC_AJUSTADA",
        })
        err["regla"] = str(codigo)
        err["detalles"] = detalles
        err["details"] = detalles
        salida.append(err)
    return {
        "cumple": len(salida) == 0,
        "errores": salida,
        "mensaje": (
            f"Se detectaron {len(salida)} incumplimientos en la regla SINIC {codigo}."
            if salida else f"No se detectaron errores en la regla SINIC {codigo}."
        ),
        "regla_sinic": meta,
    }


def _resultado_omitido(codigo, mensaje):
    # Las reglas 1-4 son las únicas omitidas por decisión del proyecto. Para una
    # regla activa, la ausencia de una capa/relación necesaria significa que no
    # pudo verificarse; nunca debe presentarse como omitida ni como cumplimiento.
    mensaje = str(mensaje).replace(" omitida:", " no verificable:")
    return {
        "cumple": True,
        "no_verificable": True,
        "errores": [],
        "mensaje": mensaje,
        "motivo_no_verificable": mensaje,
        "regla_sinic": metadata_regla(str(codigo)),
    }




def _resultado_no_aplica(codigo, mensaje):
    return {
        "cumple": True,
        "no_aplica": True,
        "errores": [],
        "mensaje": str(mensaje),
        "motivo_no_aplica": str(mensaje),
        "regla_sinic": metadata_regla(str(codigo)),
    }

def _npn_info(helper, row):
    result = helper.pull_predial_number(row, allow_guess=False)
    if not result:
        return None, "", None
    field_name, numero, raw = result
    return field_name, str(numero or "").strip(), raw


def _condicion(helper, row):
    raw = helper.get_field_value(row, helper.CONDICION_FIELDS)
    return raw, arb_admin._normalize_condicion(raw)


def _es_predio_activo(helper, row):
    """Solo excluye estados explícitamente inactivos/cancelados.

    Algunas versiones del modelo no materializan un campo Estado en ARB_Predio;
    en ese caso el registro se considera dentro del universo activo de la base.
    """
    raw = helper.get_field_value(row, ESTADO_PREDIO_FIELDS)
    if not raw:
        return True, raw
    token = _norm(raw)
    if any(x in token for x in ("INACTIVO", "CANCELADO", "CANCELACION", "RETIRADO", "ELIMINADO")):
        return False, raw
    if any(x in token for x in ("ACTIVO", "VIGENTE", "MANTENIDO", "INTEGRADO")):
        return True, raw
    return True, raw


def _issue(helper, row, codigo, mensaje, **details):
    return helper.make_issue(row, rule_id=str(codigo), message=mensaje, details=details)


# -----------------------------------------------------------------------------
# REGLAS SINIC GENERALES
# -----------------------------------------------------------------------------

def regla_6(layer_dict=None, layer_dic=None, **kwargs):
    """Para predios Activos, el NPN debe tener exactamente 30 caracteres numéricos y no ser solo ceros."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 1.2
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    for table_name, row in helper.iter_predios():
        activo, estado_raw = _es_predio_activo(helper, row)
        if not activo:
            continue
        field_name, numero, raw = _npn_info(helper, row)
        valido = bool(numero) and len(numero) == 30 and numero.isdigit() and numero != "0" * 30
        if valido:
            continue
        issues.append(_issue(
            helper, row, "6",
            "Para todo predio Activo, el NPN debe tener longitud exacta de 30 caracteres numéricos y no puede estar compuesto únicamente por ceros.",
            tabla=table_name,
            campo=field_name or "Numero_Predial_Nacional",
            valor=raw,
            numero_predial=numero,
            estado_predio=estado_raw,
            longitud=len(numero),
            es_numerico=numero.isdigit() if numero else False,
            es_solo_ceros=(numero == "0" * 30),
        ))
    return _resultado_issues("6", issues, dataset, "Parcial", "1.2")


def regla_10(layer_dict=None, layer_dic=None, **kwargs):
    """Posiciones 14-17 del NPN no deben corresponder a '0000'."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 1.3
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 17 or numero[13:17] != "0000":
            continue
        issues.append(_issue(helper, row, "10", "Las posiciones 14-17 del NPN no pueden corresponder a '0000'.",
                             tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
                             valor_14_17=numero[13:17]))
    return _resultado_issues("10", issues, dataset, "Parcial", "1.3")


def regla_11(layer_dict=None, layer_dic=None, **kwargs):
    """Posiciones 18-21 del NPN no deben corresponder a '0000'."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 1.3
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 21 or numero[17:21] != "0000":
            continue
        issues.append(_issue(helper, row, "11", "Las posiciones 18-21 del NPN no pueden corresponder a '0000'.",
                             tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
                             valor_18_21=numero[17:21]))
    return _resultado_issues("11", issues, dataset, "Parcial", "1.3")


def regla_12(layer_dict=None, layer_dic=None, **kwargs):
    """Posición 22 del NPN no debe corresponder al valor '1'."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 1.8
    # No se ejecuta 1.8 completa porque ARBIMAPS también prohíbe 5 y 6.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 22 or numero[21] != "1":
            continue
        issues.append(_issue(helper, row, "12", "La posición 22 del NPN no puede corresponder al valor '1'.",
                             tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
                             valor_22=numero[21]))
    return _resultado_issues("12", issues, dataset, "Parcial", "1.8")


def regla_13(layer_dict=None, layer_dic=None, **kwargs):
    """Si posición 22 del NPN es '0', las posiciones 23-30 deben corresponder a '00000000'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21] != "0":
            continue
        aplicables += 1
        if numero[22:30] == "00000000":
            continue
        issues.append(_issue(helper, row, "13", "Cuando la posición 22 del NPN es '0', las posiciones 23-30 deben ser '00000000'.",
                             tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
                             valor_22=numero[21], valor_23_30=numero[22:30]))
    if aplicables == 0:
        return _resultado_no_aplica("13", "Regla SINIC 13: no hay predios con posición 22 igual a '0'.")
    return _resultado_issues("13", issues, dataset, "Exacta", "1.1")

def regla_14(layer_dict=None, layer_dic=None, **kwargs):
    """Si posición 22 del NPN es '3', las posiciones 23-30 deben corresponder a '00000000'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21] != "3":
            continue
        aplicables += 1
        if numero[22:30] == "00000000":
            continue
        issues.append(_issue(helper, row, "14", "Cuando la posición 22 del NPN es '3', las posiciones 23-30 deben ser '00000000'.",
                             tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
                             valor_22=numero[21], valor_23_30=numero[22:30]))
    if aplicables == 0:
        return _resultado_no_aplica("14", "Regla SINIC 14: no hay predios con posición 22 igual a '3'.")
    return _resultado_issues("14", issues, dataset, "Exacta", "1.1")

def regla_15(layer_dict=None, layer_dic=None, **kwargs):
    """Si posición 22 del NPN es '4', las posiciones 23-30 deben corresponder a '00000000'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21] != "4":
            continue
        aplicables += 1
        if numero[22:30] == "00000000":
            continue
        issues.append(_issue(helper, row, "15", "Cuando la posición 22 del NPN es '4', las posiciones 23-30 deben ser '00000000'.",
                             tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
                             valor_22=numero[21], valor_23_30=numero[22:30]))
    if aplicables == 0:
        return _resultado_no_aplica("15", "Regla SINIC 15: no hay predios con posición 22 igual a '4'.")
    return _resultado_issues("15", issues, dataset, "Exacta", "1.1")

def regla_16(layer_dict=None, layer_dic=None, **kwargs):
    """Si posición 22 es '7' u '8' y 27-30 != '0000', las posiciones 23-26 deben ser '0000'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30:
            continue
        v22 = numero[21]
        v23_26 = numero[22:26]
        v27_30 = numero[26:30]
        if v22 not in {"7", "8"} or v27_30 == "0000":
            continue
        aplicables += 1
        if v23_26 == "0000":
            continue
        issues.append(_issue(helper, row, "16",
            "Cuando la posición 22 del NPN es '7' u '8' y las posiciones 27-30 son diferentes de '0000', las posiciones 23-26 deben ser '0000'.",
            tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
            valor_22=v22, valor_23_26=v23_26, valor_27_30=v27_30))
    if aplicables == 0:
        return _resultado_no_aplica("16", "Regla SINIC 16: no hay predios con patrón aplicable en posiciones 22 y 27-30.")
    return _resultado_issues("16", issues, dataset, "Parcial", "1.7; 1.1")

def regla_17(layer_dict=None, layer_dic=None, **kwargs):
    """Si posición 22 es '9' y 27-30 != '0000', las posiciones 23-26 deben ser diferentes de '0000'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21] != "9" or numero[26:30] == "0000":
            continue
        aplicables += 1
        if numero[22:26] != "0000":
            continue
        issues.append(_issue(helper, row, "17", "Para unidades PH, las posiciones 23-26 no pueden ser '0000' cuando 27-30 identifican una unidad.",
                             tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
                             valor_22=numero[21], valor_23_26=numero[22:26], valor_27_30=numero[26:30]))
    if aplicables == 0:
        return _resultado_no_aplica("17", "Regla SINIC 17: no hay predios PH unidad con patrón aplicable.")
    return _resultado_issues("17", issues, dataset, "Exacta", "1.5")

def regla_18(layer_dict=None, layer_dic=None, **kwargs):
    """Si posición 22 del NPN es '2', posiciones 23-24 deben corresponder al valor '00'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []
    aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 24 or numero[21] != "2":
            continue
        aplicables += 1
        if numero[22:24] == "00":
            continue
        issues.append(_issue(helper, row, "18", "Cuando la posición 22 del NPN es '2', las posiciones 23-24 deben ser '00'.",
                             tabla=table_name, campo=field_name, valor=raw, numero_predial=numero,
                             valor_22=numero[21], valor_23_24=numero[22:24]))
    if aplicables == 0:
        return _resultado_no_aplica("18", "Regla SINIC 18: no hay predios con posición 22 igual a '2'.")
    return _resultado_issues("18", issues, dataset, "Parcial", "1.1")

def regla_34(layer_dict=None, layer_dic=None, **kwargs):
    """Si posiciones 22-30 del NPN son '000000000', la condición del predio debe ser 'NPH'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []; aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21:30] != "000000000": continue
        aplicables += 1
        condicion_raw, condicion = _condicion(helper, row)
        if condicion == "NPH": continue
        issues.append(_issue(helper, row, "34", "Cuando las posiciones 22-30 del NPN son '000000000', la condición del predio debe ser NPH.", tabla=table_name, campo=field_name, valor=raw, numero_predial=numero, condicion_predio=condicion_raw, condicion_normalizada=condicion))
    if aplicables == 0: return _resultado_no_aplica("34", "Regla SINIC 34: no hay predios con patrón NPN 000000000 en posiciones 22-30.")
    return _resultado_issues("34", issues, dataset, "Parcial", "1.1")

def regla_35(layer_dict=None, layer_dic=None, **kwargs):
    """Si posiciones 22-30 son '300000000', la condición debe ser 'Bien_Uso_Publico'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []; aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21:30] != "300000000": continue
        aplicables += 1
        condicion_raw, condicion = _condicion(helper, row)
        if condicion == "BIEN_USO_PUBLICO": continue
        issues.append(_issue(helper, row, "35", "Cuando las posiciones 22-30 del NPN son '300000000', la condición debe ser Bien_Uso_Publico.", tabla=table_name, campo=field_name, valor=raw, numero_predial=numero, condicion_predio=condicion_raw, condicion_normalizada=condicion))
    if aplicables == 0: return _resultado_no_aplica("35", "Regla SINIC 35: no hay predios con patrón 300000000 en posiciones 22-30.")
    return _resultado_issues("35", issues, dataset, "Parcial", "1.1")

def regla_36(layer_dict=None, layer_dic=None, **kwargs):
    """Si 22-26='70000' y 27-30!='0000', la condición debe ser 'Parque_Cementerio.Unidad_Predial'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []; aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21:26] != "70000" or numero[26:30] == "0000": continue
        aplicables += 1
        condicion_raw, condicion = _condicion(helper, row)
        if condicion == "PARQUE_CEMENTERIO_UNIDAD_PREDIAL": continue
        issues.append(_issue(helper, row, "36", "El patrón 70000 + unidad en posiciones 27-30 exige condición Parque_Cementerio.Unidad_Predial.", tabla=table_name, campo=field_name, valor=raw, numero_predial=numero, valor_22_26=numero[21:26], valor_27_30=numero[26:30], condicion_predio=condicion_raw, condicion_normalizada=condicion))
    if aplicables == 0: return _resultado_no_aplica("36", "Regla SINIC 36: no hay unidades de Parque Cementerio aplicables.")
    return _resultado_issues("36", issues, dataset, "Relacionada, no equivalente", "1.1")

def regla_37(layer_dict=None, layer_dic=None, **kwargs):
    """Si posiciones 22-30 son '800000000', la condición debe ser 'Condominio.Matriz'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []; aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21:30] != "800000000": continue
        aplicables += 1
        condicion_raw, condicion = _condicion(helper, row)
        if condicion == "CONDOMINIO_MATRIZ": continue
        issues.append(_issue(helper, row, "37", "El patrón 800000000 en posiciones 22-30 exige condición Condominio.Matriz.", tabla=table_name, campo=field_name, valor=raw, numero_predial=numero, condicion_predio=condicion_raw, condicion_normalizada=condicion))
    if aplicables == 0: return _resultado_no_aplica("37", "Regla SINIC 37: no hay matrices de Condominio aplicables.")
    return _resultado_issues("37", issues, dataset, "Parcial", "1.6")

def regla_38(layer_dict=None, layer_dic=None, **kwargs):
    """Si 22-26='80000' y 27-30!='0000', la condición debe ser 'Condominio.Unidad_Predial'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []; aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21:26] != "80000" or numero[26:30] == "0000": continue
        aplicables += 1
        condicion_raw, condicion = _condicion(helper, row)
        if condicion == "CONDOMINIO_UNIDAD_PREDIAL": continue
        issues.append(_issue(helper, row, "38", "El patrón 80000 + unidad en posiciones 27-30 exige condición Condominio.Unidad_Predial.", tabla=table_name, campo=field_name, valor=raw, numero_predial=numero, valor_22_26=numero[21:26], valor_27_30=numero[26:30], condicion_predio=condicion_raw, condicion_normalizada=condicion))
    if aplicables == 0: return _resultado_no_aplica("38", "Regla SINIC 38: no hay unidades de Condominio aplicables.")
    return _resultado_issues("38", issues, dataset, "Parcial", "1.7")

def regla_39(layer_dict=None, layer_dic=None, **kwargs):
    """Si posiciones 22-30 son '900000000', la condición debe ser 'PH.Matriz'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []; aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21:30] != "900000000": continue
        aplicables += 1
        condicion_raw, condicion = _condicion(helper, row)
        if condicion == "PH_MATRIZ": continue
        issues.append(_issue(helper, row, "39", "El patrón 900000000 en posiciones 22-30 exige condición PH.Matriz.", tabla=table_name, campo=field_name, valor=raw, numero_predial=numero, condicion_predio=condicion_raw, condicion_normalizada=condicion))
    if aplicables == 0: return _resultado_no_aplica("39", "Regla SINIC 39: no hay matrices PH aplicables.")
    return _resultado_issues("39", issues, dataset, "Parcial", "1.4")

def regla_40(layer_dict=None, layer_dic=None, **kwargs):
    """Si posición 22='9' y 23-30!='00000000', la condición debe ser 'PH.Unidad_Predial'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []; aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 30 or numero[21] != "9" or numero[22:30] == "00000000": continue
        aplicables += 1
        condicion_raw, condicion = _condicion(helper, row)
        if condicion == "PH_UNIDAD_PREDIAL": continue
        issues.append(_issue(helper, row, "40", "El patrón de unidad PH exige condición PH.Unidad_Predial.", tabla=table_name, campo=field_name, valor=raw, numero_predial=numero, valor_22=numero[21], valor_23_30=numero[22:30], condicion_predio=condicion_raw, condicion_normalizada=condicion))
    if aplicables == 0: return _resultado_no_aplica("40", "Regla SINIC 40: no hay unidades PH aplicables.")
    return _resultado_issues("40", issues, dataset, "Parcial", "1.5")

def regla_41(layer_dict=None, layer_dic=None, **kwargs):
    """Si posición 22 del NPN es '2', la condición del predio debe ser 'Informal'."""
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    issues = []; aplicables = 0
    for table_name, row in helper.iter_predios():
        field_name, numero, raw = _npn_info(helper, row)
        if len(numero) < 22 or numero[21] != "2": continue
        aplicables += 1
        condicion_raw, condicion = _condicion(helper, row)
        if condicion == "INFORMAL": continue
        issues.append(_issue(helper, row, "41", "Cuando la posición 22 del NPN es '2', la condición del predio debe ser Informal.", tabla=table_name, campo=field_name, valor=raw, numero_predial=numero, valor_22=numero[21], condicion_predio=condicion_raw, condicion_normalizada=condicion))
    if aplicables == 0: return _resultado_no_aplica("41", "Regla SINIC 41: no hay predios informales aplicables.")
    return _resultado_issues("41", issues, dataset, "Parcial", "1.1")

# -----------------------------------------------------------------------------
# SINIC 65 - Trámite catastral -> al menos un predio
# -----------------------------------------------------------------------------

def _iter_unique_layers(capas):
    seen = set()
    for layer in (capas or {}).values():
        if layer is None:
            continue
        try:
            lid = layer.id()
        except Exception:
            lid = id(layer)
        if lid in seen:
            continue
        seen.add(lid)
        yield layer


def _layer_name(layer):
    try:
        return str(layer.name())
    except Exception:
        return ""


def _field_map(layer):
    try:
        return {_norm(f.name()): f.name() for f in layer.fields()}
    except Exception:
        return {}


def _feature_value(feature, fmap, candidates):
    for candidate in candidates:
        real = fmap.get(_norm(candidate))
        if not real:
            continue
        try:
            value = feature[real]
        except Exception:
            continue
        text = _raw_text(value)
        if text:
            return text
    return ""


def _feature_values_by_name_contains(feature, fmap, token):
    token_norm = _norm(token)
    values = set()
    for norm_name, real in fmap.items():
        if token_norm not in norm_name:
            continue
        try:
            text = _raw_text(feature[real])
        except Exception:
            text = ""
        if text:
            values.add(text.strip("{}"))
    return values


def _feature_aliases(feature, layer, extra_fields=()):
    fmap = _field_map(layer)
    aliases = set()
    for field in tuple(IDENTIFIER_FIELDS) + tuple(extra_fields):
        value = _feature_value(feature, fmap, (field,))
        if value:
            aliases.add(value.strip("{}"))
    try:
        aliases.add(str(feature.id()))
    except Exception:
        pass
    aliases.discard("")
    return aliases


def _is_tramite_catalog_layer(name):
    n = _norm(name)
    return any(x in n for x in ("tramitetipo", "tipotramite", "catalogotramite", "dominiotramite"))


def _main_tramite_layers(capas):
    layers = []
    preferred = {"ARBTRAMITE", "ILCTRAMITE", "TRAMITE", "TRAMITES"}
    for layer in _iter_unique_layers(capas):
        name_norm = _norm(_layer_name(layer))
        if _is_tramite_catalog_layer(name_norm):
            continue
        if name_norm in preferred or (
            "TRAMITE" in name_norm and "PREDIO" not in name_norm and "DERECHO" not in name_norm
            and "TIPO" not in name_norm
        ):
            layers.append(layer)
    return layers


def _predio_layers(capas):
    layers = []
    for layer in _iter_unique_layers(capas):
        n = _norm(_layer_name(layer))
        if n in {"ARBPREDIO", "ILCPREDIO", "APREDIO", "PREDIO"} or n.endswith("ARBPREDIO") or n.endswith("ILCPREDIO"):
            layers.append(layer)
    return layers


def _relation_tramite_predio_layers(capas):
    layers = []
    for layer in _iter_unique_layers(capas):
        n = _norm(_layer_name(layer))
        if "TRAMITE" in n and "PREDIO" in n:
            layers.append(layer)
    return layers


def regla_65(layer_dict=None, layer_dic=None, **kwargs):
    """Todo trámite catastral debe estar asociado a mínimo un (1) predio en la base catastral."""
    # Equivalencia del cruce: Relacionada, no equivalente | ARBIMAPS: 1.52
    # SINIC exige cardinalidad Trámite -> Predio; no se reutiliza la correspondencia
    # trámite-entidad de 1.52 porque es un criterio distinto.
    capas = _capas(layer_dict, layer_dic)
    tramite_layers = _main_tramite_layers(capas)
    predio_layers = _predio_layers(capas)
    relation_layers = _relation_tramite_predio_layers(capas)

    if not tramite_layers:
        return _resultado_omitido("65", "Regla SINIC 65 omitida: no se encontró una capa de Trámite catastral.")
    if not predio_layers:
        return _resultado_omitido("65", "Regla SINIC 65 omitida: no se encontró una capa de Predio.")

    predio_aliases = set()
    predio_direct_tramites = set()
    for p_layer in predio_layers:
        fmap = _field_map(p_layer)
        try:
            features = p_layer.getFeatures()
        except Exception:
            features = []
        for feat in features:
            predio_aliases.update(_feature_aliases(feat, p_layer, PREDIO_REF_FIELDS))
            predio_direct_tramites.update(_feature_values_by_name_contains(feat, fmap, "tramite"))

    # Indexa relaciones explícitas Predio-Trámite cuando el modelo las materializa.
    relation_tramite_values = set()
    for rel_layer in relation_layers:
        fmap = _field_map(rel_layer)
        try:
            features = rel_layer.getFeatures()
        except Exception:
            features = []
        for feat in features:
            tram_vals = _feature_values_by_name_contains(feat, fmap, "tramite")
            pred_vals = _feature_values_by_name_contains(feat, fmap, "predio")
            if predio_aliases.intersection({v.strip("{}") for v in pred_vals}):
                relation_tramite_values.update(v.strip("{}") for v in tram_vals)

    errores = []
    for t_layer in tramite_layers:
        fmap = _field_map(t_layer)
        try:
            features = t_layer.getFeatures()
        except Exception:
            features = []
        for feat in features:
            tramite_aliases = _feature_aliases(feat, t_layer, TRAMITE_REF_FIELDS)
            direct_predios = _feature_values_by_name_contains(feat, fmap, "predio")

            asociado = bool(predio_aliases.intersection({v.strip("{}") for v in direct_predios}))
            if not asociado and tramite_aliases.intersection({v.strip("{}") for v in predio_direct_tramites}):
                asociado = True
            if not asociado and tramite_aliases.intersection(relation_tramite_values):
                asociado = True

            if asociado:
                continue

            aid = next(iter(tramite_aliases), None)
            if aid is None:
                try:
                    aid = str(feat.id())
                except Exception:
                    aid = "N/A"
            errores.append({
                "aid": aid,
                "descripcion": "Todo trámite catastral debe estar asociado a mínimo un (1) predio en la base catastral.",
                "capa": t_layer,
                "regla": "65",
                "detalles": {
                    "tabla": _layer_name(t_layer),
                    "tramite_id": aid,
                    "predios_asociados": 0,
                    "capas_relacion_tramite_predio_revisadas": [_layer_name(x) for x in relation_layers],
                },
            })

    return _resultado_errores("65", errores, "Relacionada, no equivalente", "1.52")


codigos_funciones = {
    "6": regla_6,
    "10": regla_10,
    "11": regla_11,
    "12": regla_12,
    "13": regla_13,
    "14": regla_14,
    "15": regla_15,
    "16": regla_16,
    "17": regla_17,
    "18": regla_18,
    "34": regla_34,
    "35": regla_35,
    "36": regla_36,
    "37": regla_37,
    "38": regla_38,
    "39": regla_39,
    "40": regla_40,
    "41": regla_41,
    "65": regla_65,
}
codigos_funciones.update(GENERAL_FUNCTIONS)

reglas_implementadas = dict(codigos_funciones)
reglas_exactas_pendientes_fuente = []
reglas_pendientes_logica = []
todas_las_reglas = list(codigos_funciones.keys())

clases_con_reglas = {"General": list(codigos_funciones.keys())}
RULE_FUNCTIONS = codigos_funciones


def limpiar_cache_validacion():
    limpiar = getattr(arb_admin, "limpiar_cache_validacion", None)
    if callable(limpiar):
        limpiar()


def aplicar_reglas(capas=None, codigos=None, incluir_pendientes=True):
    capas = capas if capas is not None else obtener_capas_relevantes()
    seleccion = list(codigos) if codigos is not None else list(codigos_funciones.keys())
    return {
        codigo: codigos_funciones[codigo](layer_dict=capas)
        for codigo in seleccion
        if codigo in codigos_funciones
    }
