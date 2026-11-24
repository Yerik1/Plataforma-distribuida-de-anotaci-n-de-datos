"""P6: carga con 10, 40 y 100 usuarios virtuales, 30 s de calentamiento y tres corridas de 90 s por nivel (§10).

Ejecuta Locust en modo sin interfaz, guarda los CSV crudos en evidence/carga/ y muestrea docker stats
cada 10 s durante las corridas medidas. Resume p50, p95 y p99 por endpoint, envíos por minuto y errores.
"""

import argparse
import csv
import json
import subprocess
import sys
import threading
import time

from comun import EVIDENCIA, RAIZ, docker, docker_compose, guardar_evidencia

LOCUSTFILE = RAIZ / "pruebas" / "carga" / "locustfile.py"
ENVIO = "/tareas/[id]/enviar"


def locust(usuarios: int, segundos: int, prefijo: str | None, host: str) -> None:
    comando = [
        sys.executable, "-m", "locust", "-f", str(LOCUSTFILE), "--headless", "--host", host,
        "-u", str(usuarios), "-r", str(usuarios), "-t", f"{segundos}s", "--only-summary",
    ]
    if prefijo:
        comando += ["--csv", prefijo]
    subprocess.run(comando, cwd=RAIZ, capture_output=True, text=True, check=False)


def muestrear_stats(detener: threading.Event, muestras: list) -> None:
    while not detener.is_set():
        salida = docker("stats", "--no-stream", "--format", "{{json .}}")
        instante = round(time.time(), 1)
        for linea in salida.splitlines():
            try:
                fila = json.loads(linea)
                muestras.append({"t": instante, "nombre": fila["Name"], "cpu": fila["CPUPerc"], "memoria": fila["MemUsage"]})
            except (json.JSONDecodeError, KeyError):
                pass
        detener.wait(10)


def leer_estadisticas(prefijo: str, segundos: int) -> dict:
    endpoints = {}
    with open(f"{prefijo}_stats.csv", newline="", encoding="utf-8") as archivo:
        for fila in csv.DictReader(archivo):
            if fila["Name"] == "Aggregated":
                continue
            endpoints[fila["Name"]] = {
                "solicitudes": int(fila["Request Count"]),
                "fallas": int(fila["Failure Count"]),
                "p50_ms": float(fila["50%"]),
                "p95_ms": float(fila["95%"]),
                "p99_ms": float(fila["99%"]),
                "solicitudes_por_s": float(fila["Requests/s"]),
            }
    envios = endpoints.get(ENVIO, {"solicitudes": 0, "fallas": 0})
    total = sum(e["solicitudes"] for e in endpoints.values())
    fallas = sum(e["fallas"] for e in endpoints.values())
    return {
        "endpoints": endpoints,
        "envios_exitosos_por_minuto": round((envios["solicitudes"] - envios["fallas"]) * 60 / segundos, 1),
        "tasa_error": round(fallas / total, 4) if total else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--niveles", type=int, nargs="+", default=[10, 40, 100])
    parser.add_argument("--calentamiento", type=int, default=30)
    parser.add_argument("--duracion", type=int, default=90)
    parser.add_argument("--corridas", type=int, default=3)
    parser.add_argument("--host", default="http://localhost:8000")
    args = parser.parse_args()

    destino = EVIDENCIA / "carga"
    destino.mkdir(parents=True, exist_ok=True)
    marca = time.strftime("%Y%m%d-%H%M%S")
    niveles = {}
    for usuarios in args.niveles:
        locust(usuarios, args.calentamiento, None, args.host)
        corridas = []
        for corrida in range(1, args.corridas + 1):
            prefijo = str(destino / f"{marca}_u{usuarios}_c{corrida}")
            detener, muestras = threading.Event(), []
            hilo = threading.Thread(target=muestrear_stats, args=(detener, muestras), daemon=True)
            hilo.start()
            locust(usuarios, args.duracion, prefijo, args.host)
            detener.set()
            hilo.join()
            corridas.append(leer_estadisticas(prefijo, args.duracion) | {"docker_stats": muestras, "csv": f"{prefijo}_stats.csv"})
            print(f"{usuarios} usuarios, corrida {corrida}: {corridas[-1]['envios_exitosos_por_minuto']} envíos/min")
        niveles[str(usuarios)] = corridas

    guardar_evidencia(
        "p6_carga",
        "Latencias p50/p95/p99 por endpoint, envíos por minuto, errores y docker stats con 10, 40 y 100 usuarios",
        {
            "niveles": args.niveles, "calentamiento_s": args.calentamiento, "duracion_s": args.duracion,
            "corridas": args.corridas,
            # Valor real en el contenedor, para distinguir las corridas con w: 1 de las de majority (§6.1).
            "mongo_w": docker_compose("exec", "-T", "registro", "printenv", "MONGO_W") or "majority",
        },
        {"niveles": niveles},
    )


if __name__ == "__main__":
    main()
