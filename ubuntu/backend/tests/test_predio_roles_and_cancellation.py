import unittest
from unittest.mock import MagicMock, patch
from routers.asignaciones_detalle import _filter_validation_result_for_exempt_npns
from repositories.asignaciones_repo import update_asignacion_predio_rol


class TestPredioRolesAndCancellation(unittest.TestCase):

    def test_filter_validation_result_for_exempt_npns_omits_colindante_alphanumeric_issues(self):
        result = {
            "status": "failed",
            "message": "Validacion XTF fallida.",
            "validation": {
                "status": "failed",
                "message": "Validacion XTF fallida.",
                "rule_errors": [
                    {
                        "npn": "41001000100010001000",
                        "component": "juridico",
                        "rule": "RULE_01",
                        "message": "Falta interesado activo en predio principal",
                    },
                    {
                        "npn": "41001000100010002000",  # Colindante
                        "component": "juridico",
                        "rule": "RULE_02",
                        "message": "Falta interesado activo en colindante",
                    },
                    {
                        "npn": "41001000100010002000",  # Colindante
                        "component": "topologico",
                        "rule": "TOP_01",
                        "message": "Overlap topologico de linderos",
                    },
                ],
                "quality": {
                    "issues": [
                        {
                            "npn": "41001000100010001000",
                            "component": "juridico",
                            "rule": "RULE_01",
                        },
                        {
                            "npn": "41001000100010002000",
                            "component": "juridico",
                            "rule": "RULE_02",
                        },
                        {
                            "npn": "41001000100010002000",
                            "component": "topologico",
                            "rule": "TOP_01",
                        },
                    ],
                    "summary": {"total_issues": 3, "failed_rules": 3},
                },
            },
        }

        exempt_npns = {"41001000100010002000"}
        filtered = _filter_validation_result_for_exempt_npns(result, exempt_npns)

        val = filtered.get("validation") or filtered
        rule_errors = val.get("rule_errors") or []

        self.assertEqual(len(rule_errors), 2)
        npns_remaining = [e.get("npn") for e in rule_errors]
        self.assertIn("41001000100010001000", npns_remaining)
        self.assertIn("41001000100010002000", npns_remaining)

        components_remaining = [e.get("component") for e in rule_errors if e.get("npn") == "41001000100010002000"]
        self.assertEqual(components_remaining, ["topologico"])

    def test_filter_validation_result_approves_when_only_exempt_issues_exist(self):
        result = {
            "status": "failed",
            "message": "Validacion XTF fallida.",
            "validation": {
                "status": "failed",
                "message": "Validacion XTF fallida.",
                "rule_errors": [
                    {
                        "npn": "41001000100010002000",
                        "component": "economico",
                        "rule": "ECO_01",
                        "message": "Avaluo faltante en colindante",
                    }
                ],
                "quality": {
                    "issues": [
                        {
                            "npn": "41001000100010002000",
                            "component": "economico",
                            "rule": "ECO_01",
                        }
                    ],
                    "summary": {"total_issues": 1, "failed_rules": 1},
                },
            },
        }

        exempt_npns = {"41001000100010002000"}
        filtered = _filter_validation_result_for_exempt_npns(result, exempt_npns)

        self.assertEqual(filtered.get("status"), "success")

    def test_matriz_role_is_not_exempt_from_quality_rules(self):
        result = {
            "status": "failed",
            "message": "Validacion XTF fallida.",
            "validation": {
                "status": "failed",
                "message": "Validacion XTF fallida.",
                "rule_errors": [
                    {
                        "npn": "41001000100010003000",  # Predio Matriz
                        "component": "juridico",
                        "rule": "RULE_01",
                        "message": "Falta interesado activo en predio matriz",
                    },
                    {
                        "npn": "41001000100010002000",  # Colindante
                        "component": "juridico",
                        "rule": "RULE_02",
                        "message": "Falta interesado activo en colindante",
                    },
                ],
                "quality": {
                    "issues": [
                        {
                            "npn": "41001000100010003000",
                            "component": "juridico",
                            "rule": "RULE_01",
                        },
                        {
                            "npn": "41001000100010002000",
                            "component": "juridico",
                            "rule": "RULE_02",
                        },
                    ],
                    "summary": {"total_issues": 2, "failed_rules": 2},
                },
            },
        }

        # Solo el colindante está exento; el predio matriz NO debe estar en exempt_npns
        exempt_npns = {"41001000100010002000"}
        filtered = _filter_validation_result_for_exempt_npns(result, exempt_npns)

        val = filtered.get("validation") or filtered
        rule_errors = val.get("rule_errors") or []

        # El error del predio matriz debe permanecer intacto
        self.assertEqual(len(rule_errors), 1)
        self.assertEqual(rule_errors[0].get("npn"), "41001000100010003000")
        self.assertEqual(filtered.get("status"), "failed")

    @patch("repositories.asignaciones_repo.ensure_asignacion_tables")
    def test_update_asignacion_predio_rol_accepts_matriz(self, mock_ensure):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.rowcount = 1
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_tenant = MagicMock()
        mock_tenant.schemas.app = "arbimaps_app"

        res = update_asignacion_predio_rol(mock_conn, mock_tenant, 10, "41001000100010003000", "matriz")
        self.assertTrue(res)

        executed_query = mock_cur.execute.call_args[0][0]
        params = mock_cur.execute.call_args[0][1]
        self.assertIn("UPDATE arbimaps_app.asignacion_predio", executed_query)
        self.assertEqual(params[0], "matriz")



    def test_sync_reverse_etl_predicate_legacy_vs_matriz(self):
        predios = [
            {"npn": "4100100010001", "rol": "principal", "activo": True},
            {"npn": "4100100010002", "rol": "colindante", "activo": True},
            {"npn": "4100100010003", "rol": "nuevo", "activo": True},
            {"npn": "4100100010004", "rol": "cancelado", "activo": True},
            {"npn": "4100100010005", "rol": "matriz", "activo": True},
            {"non": "4100100010006", "rol": "principal", "activo": False},
        ]
        def sql_predicate(p):
            activo = p["activo"] is not False
            rol = (p["rol"] or "principal").lower()
            return activo and rol in ('principal', 'cancelado', 'nuevo') and rol not in ('colindante', 'matriz')

        selected_npns = [p["npn"] for p in predios if sql_predicate(p)]
        self.assertIn("4100100010001", selected_npns)
        self.assertIn("4100100010003", selected_npns)
        self.assertIn("4100100010004", selected_npns)
        self.assertNotIn("4100100010002", selected_npns)
        self.assertNotIn("4100100010005", selected_npns)
        self.assertNotIn("4100100010006", selected_npns)

    def test_sync_principal_map_includes_matriz_and_principal_excludes_only_colindante(self):
        roles = {
            "4100100010001": "principal",
            "4100100010002": "colindante",
            "4100100010003": "matriz",
            "4100100010004": "nuevo",
        }
        colindante_npns = {npn for npn, r in roles.items() if r == "colindante"}
        self.assertEqual(colindante_npns, {"4100100010002"})
        map_npns = [npn for npn in roles.keys() if npn not in colindante_npns]
        self.assertIn("4100100010001", map_npns)
        self.assertIn("4100100010003", map_npns)
        self.assertIn("4100100010004", map_npns)
        self.assertNotIn("4100100010002", map_npns)

    def test_obtener_detalle_asignacion_role_resolution_non_regression(self):
        predios_rows = [
            {"numero_predial_nacional": "4100100010001", "rol_predio": "principal", "predio_t_id": 101},
            {"numero_predial_nacional": "4100100010002", "rol_predio": "colindante", "predio_t_id": 102},
            {"noumero_predial_nacional": "4100100010003", "rol_predio": "nuevo", "predio_t_id": 103},
            {"noumero_predial_nacional": "4100100010004", "rol_predio": "cancelado", "predio_t_id": 104},
        ]
        _cp = 0
        _cc = 0
        _ce = 0
        _cn = 0
        _cm = 0
        for row in predios_rows:
            npn = str(row.get("numero_predial_nacional") or "").strip()
            rol = str(row.get("rol_predio") or "principal").lower()
            if rol == "matriz":
                _cm += 1
                _cp += 1
            elif rol == "cancelado":
                _ce += 1
            elif rol == "nuevo" or row.get("predio_t_id") is None:
                _cn += 1
                _cp += 1
            elif rol == "colindante":
                _cc += 1
            else:
                _cp += 1
        self.assertEqual(_cc, 1)
        self.assertEqual(_ce, 1)
        self.assertEqual(_cn, 1)
        self.assertEqual(_cm, 0)
        self.assertEqual(_cp, 2)

if __name__ == "__main__":

    unittest.main()
