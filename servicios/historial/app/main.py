import json
import logging
import threading
import time
from contextlib import asynccontextmanager

import pyarrow.compute as pc
import pyarrow.dataset as ds
from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import DATALAKE, SALUD_INTERVALO_S, SALUD_TTL_S
from .consumidor import Consumidor

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("historial")

consumidor = Consumidor()


def reportar_salud() -> None:
    while not consumidor.detener.is_set():
        try:
            estado = consumidor.estado() | {"ts": int(time.time() * 1000)}
            consumidor.valkey.set("salud:historial", json.dumps(estado), ex=SALUD_TTL_S)
        except Exception as exc:
            log.warning("no se pudo reportar salud: %s", exc)
        consumidor.detener.wait(SALUD_INTERVALO_S)


@asynccontextmanager
async def ciclo_vida(_: FastAPI):
    hilos = [
        threading.Thread(target=consumidor.ejecutar, daemon=True),
        threading.Thread(target=reportar_salud, daemon=True),
    ]
    for hilo in hilos:
        hilo.start()
    yield
    consumidor.detener.set()


app = FastAPI(title="Servicio de historial", lifespan=ciclo_vida)


class ExistentesIn(BaseModel):
    event_ids: list[str] = Field(max_length=10_000)


@app.post("/eventos/existentes")
def eventos_existentes(datos: ExistentesIn):
    """Indica cuáles de los event_id ya están publicados en el datalake (conciliación, ADR-007)."""
    ruta = DATALAKE / "eventos"
    if not datos.event_ids or not ruta.exists():
        return {"existentes": []}
    tabla = ds.dataset(ruta, format="parquet", partitioning="hive").to_table(
        columns=["event_id"], filter=pc.field("event_id").isin(datos.event_ids)
    )
    return {"existentes": sorted(set(tabla.column("event_id").to_pylist()))}
