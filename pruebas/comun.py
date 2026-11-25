import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
RAIZ = Path(__file__).resolve().parents[1]
EVIDENCIA = RAIZ / "evidence"

TAXONOMIA_LIDAR = [
    {"etiqueta": "lidar#peaton", "instruccion": "Persona que se desplaza a pie."},
    {"etiqueta": "lidar#vehiculo", "instruccion": "Automóvil, camión, autobús o motocicleta."},
    {"etiqueta": "lidar#ciclista", "instruccion": "Bicicleta o patineta con su conductor; un skater es ciclista."},
    {"etiqueta": "lidar#signal", "instruccion": "Señal de tránsito vertical o semáforo."},
]

ANOTACION_LIDAR = {
    "etiqueta": "lidar#ciclista",
    "geometria": {"tipo": "cuboide_3d", "centro": [1.2, 3.4, 0.8], "dimensiones": [1.8, 0.6, 1.7], "yaw": 0.35},
}


def cliente() -> httpx.Client:
    return httpx.Client(base_url=GATEWAY_URL, timeout=30)


def tarea_lidar(indice: int, prioridad: int = 3) -> dict:
    uri = f"s3://anotacion-datos/pruebas/{uuid4()}-{indice}.las"
    return {
        "archivo": {
            "uri": uri,
            "sha256": hashlib.sha256(uri.encode()).hexdigest(),
            "bytes": 25_000_000,
            "mime": "application/vnd.las",
            "meta": {"puntos": 1_200_000, "x_min": -50.0, "x_max": 50.0, "z_min": -2.0, "z_max": 8.0},
        },
        "modalidad": "lidar",
        "tipo_tarea": "cuboide_3d",
        "prioridad": prioridad,
    }


def crear_proyecto_con_tareas(c: httpx.Client, cantidad: int, nombre: str) -> tuple[str, list[str]]:
    proyecto = c.post(
        "/proyectos",
        json={"cliente_id": str(uuid4()), "nombre": nombre, "taxonomia": TAXONOMIA_LIDAR, "sla_horas": 48},
    )
    proyecto.raise_for_status()
    proyecto_id = proyecto.json()["proyecto_id"]
    lote = c.post(f"/proyectos/{proyecto_id}/lotes", json={"tareas": [tarea_lidar(i) for i in range(cantidad)]})
    lote.raise_for_status()
    return proyecto_id, lote.json()["tareas"]


def docker_compose(*argumentos: str) -> str:
    resultado = subprocess.run(
        ["docker", "compose", *argumentos], cwd=RAIZ, capture_output=True, text=True, check=False
    )
    return (resultado.stdout + resultado.stderr).strip()


def docker(*argumentos: str) -> str:
    resultado = subprocess.run(["docker", *argumentos], capture_output=True, text=True, check=False)
    return (resultado.stdout + resultado.stderr).strip()


def esperar_salud(c: httpx.Client, estado: str, limite_s: int = 90) -> dict:
    inicio = time.time()
    contenido: dict = {}
    while time.time() - inicio < limite_s:
        try:
            contenido = c.get("/salud").json()
            if contenido.get("estado") == estado:
                return {"estado": estado, "segundos": round(time.time() - inicio, 1), "salud": contenido}
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return {"estado": contenido.get("estado"), "segundos": None, "salud": contenido}


def maquina() -> dict:
    return {
        "sistema": platform.platform(),
        "procesador": platform.processor() or platform.machine(),
        "cpus": os.cpu_count(),
        "python": platform.python_version(),
    }


def percentiles(valores: list[float]) -> dict:
    if not valores:
        return {"muestras": 0}
    ordenados = sorted(valores)

    def p(q: float) -> float:
        return round(ordenados[min(len(ordenados) - 1, int(q * len(ordenados)))], 2)

    return {"muestras": len(ordenados), "p50_ms": p(0.50), "p95_ms": p(0.95), "p99_ms": p(0.99)}


def guardar_evidencia(nombre: str, objetivo: str, configuracion: dict, resultado: dict) -> Path:
    EVIDENCIA.mkdir(exist_ok=True)
    marca = datetime.now(timezone.utc)
    ruta = EVIDENCIA / f"{nombre}_{marca.strftime('%Y%m%d-%H%M%S')}.json"
    contenido = {
        "fecha_utc": marca.isoformat(),
        "objetivo": objetivo,
        "configuracion": configuracion | {"maquina": maquina(), "gateway": GATEWAY_URL},
        "comando": " ".join([Path(sys.executable).name, *sys.argv]),
        "resultado": resultado,
    }
    ruta.write_text(json.dumps(contenido, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"evidencia: {ruta}")
    return ruta
