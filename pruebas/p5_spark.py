"""P5: Q1 a Q5 sobre Parquet con uno y dos workers, primera ejecución frente a las siguientes (§8).

Ejecuta consultas.py con spark-submit dentro del master para cada combinación de workers y conjunto.
El servicio de analítica se detiene durante las mediciones porque su sesión de Spark ocupa núcleos
del clúster y alteraría la comparación; al terminar se vuelve a levantar.
"""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from comun import EVIDENCIA, RAIZ, docker_compose, guardar_evidencia

RUTAS = {
    "principal": ("datalake/eventos", "/opt/datalake/eventos"),
    "ampliado": ("datalake/ampliado/eventos", "/opt/datalake/ampliado/eventos"),
}
MASTER_UI = "http://localhost:8080/json/"


def workers_vivos() -> int:
    try:
        return httpx.get(MASTER_UI, timeout=5).json().get("aliveworkers", 0)
    except httpx.HTTPError:
        return -1


def ajustar_workers(cantidad: int) -> int:
    if cantidad == 2:
        docker_compose("--profile", "analitica", "--profile", "spark2", "up", "-d", "spark-worker-2")
    else:
        # Sin los perfiles, compose no resuelve la dependencia con spark-master y no detiene nada.
        docker_compose("--profile", "analitica", "--profile", "spark2", "stop", "spark-worker-2")
    inicio = time.time()
    while time.time() - inicio < 120 and workers_vivos() != cantidad:
        time.sleep(3)
    vivos = workers_vivos()
    if vivos != cantidad:
        raise SystemExit(f"se pidieron {cantidad} workers y hay {vivos} vivos; no se mide una configuración distinta")
    return vivos


def ejecutar(ruta_contenedor: str, repeticiones: int, fecha: str, planes: bool) -> dict:
    argumentos = [
        "exec", "-T", "spark-master", "/opt/spark/bin/spark-submit", "--master", "spark://spark-master:7077",
        "/opt/analitica/consultas.py", "--datos", ruta_contenedor, "--repeticiones", str(repeticiones),
        "--fecha-referencia", fecha, "--evidencia", "/opt/evidence",
    ] + (["--planes"] if planes else [])
    salida = docker_compose(*argumentos)
    coincidencia = re.search(r"evidencia: /opt/evidence/(\S+\.json)", salida)
    if not coincidencia:
        return {"error": salida[-2000:]}
    archivo = EVIDENCIA / coincidencia.group(1)
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    resumen = {}
    for consulta, tiempos in datos["tiempos_s"].items():
        posteriores = tiempos[1:]
        resumen[consulta] = {
            "primera_s": tiempos[0],
            "posteriores_s": posteriores,
            "promedio_posteriores_s": round(sum(posteriores) / len(posteriores), 3) if posteriores else None,
        }
    return {"archivo": archivo.name, "eventos_unicos": datos["eventos_unicos"], "tiempos": resumen}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--conjuntos", nargs="+", default=["principal", "ampliado"])
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--fecha-referencia", default=datetime.now(timezone.utc).date().isoformat())
    args = parser.parse_args()

    docker_compose("stop", "analitica")
    corridas, omitidos = [], []
    try:
        for cantidad in args.workers:
            vivos = ajustar_workers(cantidad)
            for conjunto in args.conjuntos:
                local, contenedor = RUTAS[conjunto]
                if not (RAIZ / local).exists():
                    omitidos.append({"conjunto": conjunto, "motivo": f"no existe {local}"})
                    continue
                planes = cantidad == args.workers[0] and conjunto == "principal"
                corridas.append(
                    {"workers": cantidad, "workers_vivos": vivos, "conjunto": conjunto}
                    | ejecutar(contenedor, args.repeticiones, args.fecha_referencia, planes)
                )
    finally:
        docker_compose("--profile", "analitica", "up", "-d", "analitica")

    guardar_evidencia(
        "p5_spark",
        "Tiempos de Q1 a Q5 con uno y dos workers, primera ejecución frente a ejecuciones posteriores",
        {"workers": args.workers, "conjuntos": args.conjuntos, "repeticiones": args.repeticiones,
         "fecha_referencia_q1": args.fecha_referencia},
        {"corridas": corridas, "conjuntos_omitidos": omitidos},
    )
    for corrida in corridas:
        print(corrida["workers"], corrida["conjunto"], {q: t["primera_s"] for q, t in corrida.get("tiempos", {}).items()})


if __name__ == "__main__":
    main()
