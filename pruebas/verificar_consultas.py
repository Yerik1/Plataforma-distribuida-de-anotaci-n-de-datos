"""Verifica los resultados de Spark para Q1 a Q5 con un cálculo independiente sobre el mismo Parquet.

Lee el datalake con PyArrow, deduplica por event_id y recalcula cada consulta en Python. Compara
contra el JSON que produce consultas.py. Los conteos y proporciones deben coincidir exactamente;
los percentiles se comparan con una tolerancia relativa, porque Spark usa percentile_approx.
"""

import argparse
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pyarrow.dataset as ds

from comun import guardar_evidencia

COLUMNAS = [
    "event_id", "estado", "ts", "tarea_id", "proyecto_id", "cliente_id", "modalidad", "tipo_tarea",
    "equipo_id", "version", "ts_primera_toma", "duracion_anotacion_ms", "sla_horas",
]


def leer(ruta: Path) -> list[dict]:
    tabla = ds.dataset(ruta, format="parquet", partitioning="hive").to_table(columns=COLUMNAS)
    unicos = {}
    for fila in tabla.to_pylist():
        unicos.setdefault(fila["event_id"], fila)
    return list(unicos.values())


def rango_cercano(valores: list[float], q: float) -> float:
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(q * len(ordenados)) - 1)]


def calcular(eventos: list[dict], referencia: date) -> dict:
    q1 = defaultdict(int)
    for e in eventos:
        dia = e["ts"].date()
        if e["estado"] == "aprobada" and referencia - timedelta(days=89) <= dia <= referencia:
            q1[(dia.isoformat(), e["modalidad"])] += 1

    finales = {}
    for e in sorted(eventos, key=lambda e: (e["ts"], e["version"])):
        if e["estado"] in ("aprobada", "rechazada"):
            finales[e["tarea_id"]] = e
    q2 = defaultdict(lambda: [0, 0])
    for e in finales.values():
        clave = (e["equipo_id"], e["ts"].strftime("%Y-%m"))
        q2[clave][0] += e["estado"] == "aprobada"
        q2[clave][1] += 1

    q3 = defaultdict(list)
    q4 = defaultdict(lambda: [0, 0])
    q5 = defaultdict(list)
    for e in eventos:
        if e["estado"] == "anotada" and e["duracion_anotacion_ms"] is not None:
            q3[(e["modalidad"], e["tipo_tarea"])].append(e["duracion_anotacion_ms"])
        if e["estado"] in ("aprobada", "rechazada"):
            q4[(e["cliente_id"], e["proyecto_id"])][0] += e["estado"] == "rechazada"
            q4[(e["cliente_id"], e["proyecto_id"])][1] += 1
        if e["estado"] == "aprobada":
            horas = (e["ts"] - e["ts_primera_toma"]).total_seconds() / 3600
            q5[e["cliente_id"]].append((horas, horas > e["sla_horas"]))

    return {
        "q1": [{"dia": d, "modalidad": m, "aprobadas": n} for (d, m), n in sorted(q1.items())],
        "q2": [
            {"equipo_id": eq, "mes": mes, "aprobadas": a, "revisadas": n, "proporcion_aprobadas": round(a / n, 4)}
            for (eq, mes), (a, n) in sorted(q2.items())
        ],
        "q3": [
            {
                "modalidad": m, "tipo_tarea": t, "anotaciones": len(v),
                "duracion_media_ms": round(sum(v) / len(v), 4), "duracion_p95_ms": float(rango_cercano(v, 0.95)),
            }
            for (m, t), v in sorted(q3.items())
        ],
        "q4": [
            {"cliente_id": c, "proyecto_id": p, "rechazadas": r, "revisadas": n, "proporcion_rechazadas": round(r / n, 4)}
            for (c, p), (r, n) in sorted(q4.items())
        ],
        "q5": [
            {
                "cliente_id": c, "tareas_aprobadas": len(v),
                "p50_horas": round(rango_cercano([h for h, _ in v], 0.5), 4),
                "p95_horas": round(rango_cercano([h for h, _ in v], 0.95), 4),
                "porcentaje_incumple_sla": round(100 * sum(x for _, x in v) / len(v), 4),
            }
            for c, v in sorted(q5.items())
        ],
    }


PERCENTILES = {"duracion_p95_ms", "p50_horas", "p95_horas"}


def comparar(spark: list[dict], referencia: list[dict], tolerancia: float) -> dict:
    diferencias = []
    if len(spark) != len(referencia):
        diferencias.append({"filas_spark": len(spark), "filas_referencia": len(referencia)})
    for s, r in zip(spark, referencia):
        for campo, esperado in r.items():
            obtenido = s.get(campo)
            if campo in PERCENTILES:
                correcto = abs(obtenido - esperado) <= tolerancia * max(abs(esperado), 1e-9)
            elif isinstance(esperado, float):
                correcto = abs(obtenido - esperado) <= 1e-4
            else:
                correcto = obtenido == esperado
            if not correcto:
                diferencias.append({"fila": r, "campo": campo, "spark": obtenido, "referencia": esperado})
    return {"coincide": not diferencias, "filas": len(referencia), "diferencias": diferencias[:20]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spark", required=True, help="JSON generado por consultas.py")
    parser.add_argument("--datos", default="datalake/eventos", help="ruta local del mismo conjunto")
    parser.add_argument("--tolerancia-percentil", type=float, default=0.01)
    args = parser.parse_args()

    spark = json.loads(Path(args.spark).read_text(encoding="utf-8"))
    referencia_q1 = date.fromisoformat(spark["configuracion"]["fecha_referencia_q1"])
    eventos = leer(Path(args.datos))
    referencia = calcular(eventos, referencia_q1)
    resultado = {
        "archivo_spark": args.spark,
        "eventos_unicos_spark": spark["eventos_unicos"],
        "eventos_unicos_referencia": len(eventos),
        "consultas": {q: comparar(spark["resultados"][q], referencia[q], args.tolerancia_percentil) for q in referencia},
    }
    resultado["coinciden_todas"] = (
        resultado["eventos_unicos_spark"] == resultado["eventos_unicos_referencia"]
        and all(c["coincide"] for c in resultado["consultas"].values())
    )
    guardar_evidencia(
        "verificacion_consultas",
        "Contrastar Q1 a Q5 de Spark con un cálculo independiente sobre el mismo Parquet",
        {"datos": args.datos, "tolerancia_percentil": args.tolerancia_percentil},
        resultado,
    )
    print(json.dumps({q: c["coincide"] for q, c in resultado["consultas"].items()} | {"todas": resultado["coinciden_todas"]}, indent=2))


if __name__ == "__main__":
    main()
