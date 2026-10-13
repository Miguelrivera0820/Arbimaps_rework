
from pathlib import Path
import json

# Carpeta donde el backend guarda las validaciones
BASE = Path(__file__).resolve().parent
CARPETA = BASE / "resource" / "xtf_validation" / "reports"

XTF = "asignacion_neiva_129_Dig_006_bd5c3129.xtf"

print("\n========== DIAGNOSTICO SINIC WEB ==========")

if not CARPETA.exists():
    print("ERROR: No existe la carpeta de resultados.")
else:
    archivos = sorted(
        CARPETA.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    encontrado = False

    for archivo in archivos:
        try:
            data = json.loads(
                archivo.read_text(encoding="utf-8")
            )

            nombre = data.get("original_filename", "")

            if nombre.lower() != XTF.lower():
                continue

            encontrado = True

            quality = (
                data.get("validation", {})
                    .get("quality", {})
            )

            print("\nArchivo:", nombre)
            print("Municipio:", data.get("municipality_code"))
            print("JOB:", data.get("job_id"))

            print("\n========== CARTOGRAFIA ==========")

            origen = quality.get("cartography_source")
            capas = quality.get("loaded_layers", [])

            print("Origen:", origen or "VACIO")
            print("Total de capas:", len(capas))

            for capa in capas:
                print(" -", capa)

            print("\n========== REGLAS FISICAS ==========")

            for regla in quality.get("rules", []):
                codigo = str(regla.get("rule"))

                if codigo not in {
                    "84", "112", "129",
                    "145", "146", "147"
                }:
                    continue

                print(
                    f"\nRegla {codigo}: "
                    f"{regla.get('issue_count', 0)} errores"
                )

                print(
                    "Estado:",
                    regla.get("verification_status")
                )

                if regla.get("no_verificable"):
                    print("Validacion no verificable/parcial")

                mensaje = regla.get("mensaje")
                if mensaje:
                    print("Mensaje:", mensaje)

            break

        except Exception as exc:
            print("Error leyendo resultado:", exc)

    if not encontrado:
        print(
            "\nNo se encontro una validacion guardada "
            "para este XTF en este entorno."
        )

print("\n========== FIN ==========")
