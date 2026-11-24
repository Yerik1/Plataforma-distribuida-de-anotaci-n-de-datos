"""P4 (frescura): segundos entre el HTTP 200 de una aprobación y su aparición en Q1 consultada por el gateway."""

import argparse
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from comun import ANOTACION_LIDAR, cliente, crear_proyecto_con_tareas, guardar_evidencia, percentiles


def aprobadas_hoy(c) -> tuple[int, float]:
    hoy = datetime.now(timezone.utc).date().isoformat()
    respuesta = c.get("/analitica/q1", params={"conjunto": "principal", "fecha_referencia": hoy}, timeout=300)
    respuesta.raise_for_status()
    cuerpo = respuesta.json()
    total = sum(f["aprobadas"] for f in cuerpo["resultados"] if f["dia"] == hoy and f["modalidad"] == "lidar")
    return total, cuerpo["tiempo_s"]


def aprobar_una(c, proyecto_id: str) -> float:
    anotador, revisor = f"p4s-{uuid4().hex[:8]}", f"p4s-rev-{uuid4().hex[:6]}"
    t = c.post("/tareas/siguiente", json={"anotador_id": anotador, "proyecto_id": proyecto_id}).json()
    c.post(
        f"/tareas/{t['tarea_id']}/enviar",
        json={"anotador_id": anotador, "token": t["token"], "anotacion": ANOTACION_LIDAR},
    ).raise_for_status()
    c.post(f"/tareas/{t['tarea_id']}/revision", json={"revisor_id": revisor, "accion": "iniciar"}).raise_for_status()
    c.post(f"/tareas/{t['tarea_id']}/revision", json={"revisor_id": revisor, "accion": "aprobar"}).raise_for_status()
    return time.time()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--muestras", type=int, default=5)
    parser.add_argument("--limite-s", type=int, default=120)
    args = parser.parse_args()

    muestras = []
    with cliente() as c:
        proyecto_id, _ = crear_proyecto_con_tareas(c, args.muestras, "p4-frescura-spark")
        for _ in range(args.muestras):
            base, _ = aprobadas_hoy(c)
            aprobada = aprobar_una(c, proyecto_id)
            consultas, tiempos_q1 = 0, []
            visible = None
            while time.time() - aprobada < args.limite_s:
                total, tiempo_q1 = aprobadas_hoy(c)
                consultas += 1
                tiempos_q1.append(tiempo_q1)
                if total > base:
                    visible = round(time.time() - aprobada, 2)
                    break
            muestras.append({"segundos_200_a_q1": visible, "consultas_q1": consultas, "tiempos_q1_s": tiempos_q1})

    visibles = [m["segundos_200_a_q1"] * 1000 for m in muestras if m["segundos_200_a_q1"] is not None]
    resultado = {
        "muestras": muestras,
        "frescura": percentiles(visibles),
        "cumple": len(visibles) == args.muestras,
    }
    guardar_evidencia(
        "p4_frescura_spark",
        "Segundos entre un HTTP 200 de aprobación y el evento visible en Q1 de Spark",
        {"muestras": args.muestras, "limite_s": args.limite_s},
        resultado,
    )
    print(json.dumps({k: v for k, v in resultado.items() if k != "muestras"}, indent=2))


if __name__ == "__main__":
    main()
