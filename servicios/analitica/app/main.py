"""Servicio de analítica: Q1 a Q5 sobre el datalake Parquet en modo de solo lectura (§8)."""

import json
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import valkey
from fastapi import FastAPI, HTTPException, Query
from pyspark.sql import SparkSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spark"))
from consultas import filas, leer_eventos, mes_inicio_q1, plan, q1, q2, q3, q4, q5  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("analitica")

SPARK_MASTER = os.getenv("SPARK_MASTER", "spark://spark-master:7077")
CONJUNTOS = {
    "principal": os.getenv("DATOS_PRINCIPAL", "/opt/datalake/eventos"),
    "ampliado": os.getenv("DATOS_AMPLIADO", "/opt/datalake/ampliado/eventos"),
    "validacion": os.getenv("DATOS_VALIDACION", "/opt/analitica/datos_prueba/parquet/eventos"),
}
CONSTRUCTORES = {"q1": None, "q2": q2, "q3": q3, "q4": q4, "q5": q5}

estado = {"spark": None, "detener": threading.Event()}


def crear_sesion() -> SparkSession:
    return (
        SparkSession.builder.appName("servicio-analitica")
        .master(SPARK_MASTER)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.sources.partitionColumnTypeInference.enabled", "false")
        .config("spark.cores.max", os.getenv("ANALITICA_CORES", "2"))
        .config("spark.executor.memory", os.getenv("ANALITICA_MEMORIA_EJECUTOR", "1g"))
        .config("spark.driver.host", os.getenv("SPARK_DRIVER_HOST", "analitica"))
        .config("spark.driver.bindAddress", "0.0.0.0")
        .getOrCreate()
    )


def reportar_salud() -> None:
    cliente = valkey.Valkey(host=os.getenv("VALKEY_HOST", "valkey"), decode_responses=True, socket_timeout=2)
    while not estado["detener"].is_set():
        spark = estado["spark"]
        activo = spark is not None and not spark.sparkContext._jsc.sc().isStopped()
        try:
            cliente.set(
                "salud:analitica",
                json.dumps({"estado": "operativo" if activo else "caido", "master": SPARK_MASTER, "ts": int(time.time() * 1000)}),
                ex=int(os.getenv("SALUD_TTL_S", "15")),
            )
        except Exception as exc:
            log.warning("no se pudo reportar salud: %s", exc)
        estado["detener"].wait(float(os.getenv("SALUD_INTERVALO_S", "5")))


@asynccontextmanager
async def ciclo_vida(_: FastAPI):
    estado["spark"] = crear_sesion()
    estado["spark"].sparkContext.setLogLevel("WARN")
    threading.Thread(target=reportar_salud, daemon=True).start()
    yield
    estado["detener"].set()
    estado["spark"].stop()


app = FastAPI(title="Servicio de analítica", lifespan=ciclo_vida)


def construir(consulta: str, conjunto: str, fecha_referencia: date | None):
    if consulta not in CONSTRUCTORES:
        raise HTTPException(404, "consulta no definida; use q1 a q5")
    if conjunto not in CONJUNTOS:
        raise HTTPException(422, f"conjunto no válido; use {', '.join(CONJUNTOS)}")
    ruta = CONJUNTOS[conjunto]
    if not Path(ruta).exists():
        raise HTTPException(404, f"el conjunto {conjunto} no tiene datos en {ruta}")
    if consulta == "q1":
        referencia = fecha_referencia or date.today()
        return q1(leer_eventos(estado["spark"], ruta, mes_inicio_q1(referencia)), referencia)
    return CONSTRUCTORES[consulta](leer_eventos(estado["spark"], ruta))


@app.get("/consultas/{consulta}")
def ejecutar(consulta: str, conjunto: str = "principal", fecha_referencia: date | None = Query(default=None)):
    inicio = time.perf_counter()
    resultados = filas(construir(consulta, conjunto, fecha_referencia))
    return {
        "consulta": consulta,
        "conjunto": conjunto,
        "fecha_referencia": (fecha_referencia or date.today()).isoformat() if consulta == "q1" else None,
        "tiempo_s": round(time.perf_counter() - inicio, 3),
        "filas": len(resultados),
        "resultados": resultados,
    }


@app.get("/consultas/{consulta}/plan")
def plan_ejecucion(consulta: str, conjunto: str = "principal", fecha_referencia: date | None = Query(default=None)):
    return {"consulta": consulta, "conjunto": conjunto, "plan": plan(construir(consulta, conjunto, fecha_referencia))}
