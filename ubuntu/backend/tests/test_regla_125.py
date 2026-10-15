"""Pruebas de la regla 3_ET_CF_125 SINIC: predio activo NPH/Condominio UP."""
import unittest

from quality_rules.sinic_web.extensions import regla_125
from quality_rules.sinic_web.support import WebLayer


class Regla125Test(unittest.TestCase):
    @staticmethod
    def ejecutar(predios, terrenos=(), relaciones=()):
        capas = {
            "ARB_Predio": WebLayer("ARB_Predio", predios),
            "ARB_Terreno": WebLayer("ARB_Terreno", terrenos),
        }
        if relaciones:
            capas["col_uebaunit"] = WebLayer("col_uebaunit", relaciones)
        return regla_125(layer_dict=capas)

    def test_activos_nph_y_condominio_sin_terreno_generan_error(self):
        resultado = self.ejecutar([
            {"TID": "p1", "Estado": "Activo", "Condicion_Predio": "NPH"},
            {"TID": "p2", "Estado": "Activo", "Condicion_Predio": "Condominio.Unidad_Predial"},
        ])
        self.assertFalse(resultado["cumple"])
        self.assertEqual({e["aid"] for e in resultado["errores"]}, {"p1", "p2"})

    def test_solo_estado_activo_y_condiciones_objetivo(self):
        resultado = self.ejecutar([
            {"TID": "p1", "Estado": "Inactivo", "Condicion_Predio": "NPH"},
            {"TID": "p2", "Estado": "Cancelado", "Condicion_Predio": "Condominio.Unidad_Predial"},
            {"TID": "p3", "Estado": "Activo", "Condicion_Predio": "PH.Unidad_Predial"},
            {"TID": "p4", "Estado": "Activo", "Condicion_Predio": "Condominio.Matriz"},
            {"TID": "p5", "Estado": "Activo", "Condicion_Predio": "Informal en altura"},
            {"TID": "p6", "Condicion_Predio": "NPH"},
        ])
        self.assertTrue(resultado["cumple"])
        self.assertEqual(resultado["errores"], [])

    def test_terreno_asociado_directamente_cumple(self):
        resultado = self.ejecutar([
            {"TID": "p1", "Estado": "Activo", "Condicion_Predio": "NPH"},
            {"TID": "p2", "Estado": "Activo", "Condicion_Predio": "Condominio.Unidad_Predial"},
        ], [
            {"TID": "t1", "predio": "p1"},
            {"TID": "t2", "arb_predio_terreno": "p2"},
        ])
        self.assertTrue(resultado["cumple"])

    def test_codigos_de_catalogo_105_65_60(self):
        resultado = self.ejecutar([
            {"t_id": 1, "estado": 105, "condicion_predio": 65},
            {"t_id": 2, "estado": 105, "condicion_predio": 60},
            {"t_id": 3, "estado": 105, "condicion_predio": 62},
        ])
        self.assertFalse(resultado["cumple"])
        self.assertEqual({e["aid"] for e in resultado["errores"]}, {"1", "2"})

    def test_union_intermedia_exige_terreno_real(self):
        predios = [{"TID": "p1", "Estado": "Activo", "Condicion_Predio": "NPH"}]
        relaciones = [{"baunit": "p1", "ue_cr_terreno": "t1"}]
        valido = self.ejecutar(predios, [{"TID": "t1"}], relaciones)
        invalido = self.ejecutar(predios, [], relaciones)
        self.assertTrue(valido["cumple"])
        self.assertFalse(invalido["cumple"])
        self.assertEqual(len(invalido["errores"]), 1)

    def test_terreno_asociado_a_otro_predio_no_satisface_la_regla(self):
        resultado = self.ejecutar([
            {"TID": "p1", "Estado": "Activo", "Condicion_Predio": "NPH"},
            {"TID": "p2", "Estado": "Activo", "Condicion_Predio": "NPH"},
        ], [{"TID": "t1", "predio": "p2"}])
        self.assertFalse(resultado["cumple"])
        self.assertEqual([e["aid"] for e in resultado["errores"]], ["p1"])


if __name__ == "__main__":
    unittest.main()
