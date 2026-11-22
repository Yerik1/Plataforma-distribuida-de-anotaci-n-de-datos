"""P2: 50 solicitudes concurrentes contra 10 tareas libres y segundo envío con 409."""

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Manager
from uuid import uuid4

import httpx

from comun import (
    ANOTACION_LIDAR,
    GATEWAY_URL,
    cliente,
    crear_proyecto_con_tareas,
    guardar_evidencia,
    percentiles,
)


def solicitar(argumentos: tuple) -> dict:
    barrera, proyecto_id, anotador_id = argumentos
    with httpx.Client(base_url=GATEWAY_URL, timeout=30) as c:
        barrera.wait()
        inicio = time.perf_counter()
        respuesta = c.post("/tareas/siguiente", json={"anotador_id": anotador_id, "proyecto_id": proyecto_id})
        latencia = (time.perf_counter() - inicio) * 1000
    cuerpo = respuesta.json() if respuesta.status_code == 200 else {}
    return {
        "anotador_id": anotador_id,
        "codigo": respuesta.status_code,
        "tarea_id": cuerpo.get("tarea_id"),
        "token": cuerpo.get("token"),
        "latencia_ms": latencia,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solicitudes", type=int, default=50)
    parser.add_argument("--tareas", type=int, default=10)
    args = parser.parse_args()

    with cliente() as c:
        proyecto_id, tareas = crear_proyecto_con_tareas(c, args.tareas, "p2-concurrencia")
        salud_inicial = c.get("/salud").json()

    corrida = uuid4().hex[:6]
    with Manager() as manager:
        barrera = manager.Barrier(args.solicitudes)
        entradas = [(barrera, proyecto_id, f"p2-{corrida}-{i:03d}") for i in range(args.solicitudes)]
        with ProcessPoolExecutor(max_workers=args.solicitudes) as ejecutor:
            resultados = list(ejecutor.map(solicitar, entradas))

    codigos = Counter(r["codigo"] for r in resultados)
    asignadas = [r["tarea_id"] for r in resultados if r["codigo"] == 200]
    duplicadas = [t for t, n in Counter(asignadas).items() if n > 1]

    with cliente() as c:
        ganador = next(r for r in resultados if r["codigo"] == 200)
        cuerpo = {"anotador_id": ganador["anotador_id"], "token": ganador["token"], "anotacion": ANOTACION_LIDAR}
        primer_envio = c.post(f"/tareas/{ganador['tarea_id']}/enviar", json=cuerpo).status_code
        segundo_envio = c.post(f"/tareas/{ganador['tarea_id']}/enviar", json=cuerpo).status_code

    resultado = {
        "replica_set": salud_inicial.get("capas", {}).get("registro", {}).get("replica"),
        "codigos": dict(codigos),
        "asignaciones": len(asignadas),
        "sin_tarea_204": codigos.get(204, 0),
        "tareas_distintas_asignadas": len(set(asignadas)),
        "tareas_con_dos_duenos": duplicadas,
        "latencias": percentiles([r["latencia_ms"] for r in resultados]),
        "primer_envio": primer_envio,
        "segundo_envio": segundo_envio,
        "cumple": (
            len(asignadas) == args.tareas
            and codigos.get(204, 0) == args.solicitudes - args.tareas
            and not duplicadas
            and primer_envio == 200
            and segundo_envio == 409
        ),
        "detalle": resultados,
    }
    guardar_evidencia(
        "p2_concurrencia",
        f"{args.solicitudes} solicitudes concurrentes con {args.tareas} tareas libres; segundo envío responde 409",
        {"solicitudes": args.solicitudes, "tareas": args.tareas, "proyecto_id": proyecto_id},
        resultado,
    )
    print(json.dumps({k: v for k, v in resultado.items() if k != "detalle"}, indent=2))


if __name__ == "__main__":
    main()
