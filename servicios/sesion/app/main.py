import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from valkey.exceptions import ConnectionError as ValkeyConnectionError
from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from .almacen import (
    GUARDAR_BORRADOR,
    LIBERAR,
    cliente,
    llave_borrador,
    llave_editando,
    llave_envio,
    llave_lock,
    llave_sesion,
)
from .config import LOCK_MS, SALUD_INTERVALO_S, SALUD_TTL_S, STREAM_EVENTOS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sesion")


def reportar_salud(detener: threading.Event) -> None:
    while not detener.is_set():
        try:
            cliente.set(
                "salud:sesion",
                json.dumps({"estado": "operativo", "ts": int(time.time() * 1000)}),
                ex=SALUD_TTL_S,
            )
        except (ValkeyConnectionError, ValkeyTimeoutError) as exc:
            log.warning("no se pudo reportar salud: %s", exc)
        detener.wait(SALUD_INTERVALO_S)


@asynccontextmanager
async def ciclo_vida(_: FastAPI):
    detener = threading.Event()
    hilo = threading.Thread(target=reportar_salud, args=(detener,), daemon=True)
    hilo.start()
    yield
    detener.set()


app = FastAPI(title="Servicio de sesión", lifespan=ciclo_vida)


@app.exception_handler(ValkeyConnectionError)
@app.exception_handler(ValkeyTimeoutError)
async def valkey_no_disponible(_, exc):
    return JSONResponse(status_code=503, content={"detail": "Valkey no disponible", "error": type(exc).__name__})


def ahora_ms() -> int:
    return int(time.time() * 1000)


def leer_borrador(tarea_id: str, anotador_id: str) -> dict | None:
    datos = cliente.hgetall(llave_borrador(tarea_id))
    if not datos or datos.get("anotador_id") != anotador_id:
        return None
    return {"contenido": json.loads(datos["contenido"]), "ts": int(datos["ts"])}


class LockIn(BaseModel):
    tarea_id: str = Field(min_length=1)
    token: str = Field(min_length=1)
    ttl_ms: int = Field(default=LOCK_MS, gt=0)


class SesionIn(BaseModel):
    tarea_id: str = Field(min_length=1)
    proyecto_id: str = Field(min_length=1)
    token: str = Field(min_length=1)
    etapa: str = "anotacion"


def leer_envio(tarea_id: str, anotador_id: str) -> dict | None:
    datos = cliente.hgetall(llave_envio(tarea_id))
    if not datos or datos.get("anotador_id") != anotador_id:
        return None
    return json.loads(datos["datos"]) | {"ts": int(datos["ts"]), "token": datos["token"]}


class EnvioPendiente(BaseModel):
    event_id: str = Field(min_length=1)
    anotacion: dict[str, Any]


class BorradorIn(BaseModel):
    anotador_id: str = Field(min_length=1)
    token: str = Field(min_length=1)
    contenido: dict[str, Any] | None = None
    envio: EnvioPendiente | None = None

    @model_validator(mode="after")
    def un_solo_contenido(self):
        if (self.contenido is None) == (self.envio is None):
            raise ValueError("se requiere exactamente uno de contenido o envio")
        return self


class EventoIn(BaseModel):
    evento: dict[str, Any]
    limpiar_envio: str | None = None


@app.post("/locks", status_code=201)
def adquirir_lock(datos: LockIn):
    if not cliente.set(llave_lock(datos.tarea_id), datos.token, nx=True, px=datos.ttl_ms):
        raise HTTPException(409, "la tarea ya tiene un lock activo")
    return {"adquirido": True}


@app.delete("/locks/{tarea_id}")
def liberar_lock(
    tarea_id: str,
    token: str = Query(min_length=1),
    anotador_id: str = "",
    limpiar: bool = False,
):
    proyecto_id = cliente.hget(llave_sesion(anotador_id), "proyecto_id") if limpiar and anotador_id else None
    liberado = LIBERAR(
        keys=[
            llave_lock(tarea_id),
            llave_borrador(tarea_id),
            llave_sesion(anotador_id),
            llave_editando(proyecto_id or ""),
            llave_envio(tarea_id),
        ],
        args=[token, "1" if limpiar else "0", tarea_id, anotador_id],
    )
    if not liberado:
        raise HTTPException(409, "el token no corresponde al lock")
    return {"liberado": True}


@app.put("/sesiones/{anotador_id}")
def abrir_sesion(anotador_id: str, datos: SesionIn):
    ts = ahora_ms()
    with cliente.pipeline() as tx:
        tx.delete(llave_sesion(anotador_id))
        tx.hset(
            llave_sesion(anotador_id),
            mapping={
                "tarea_id": datos.tarea_id,
                "proyecto_id": datos.proyecto_id,
                "token": datos.token,
                "etapa": datos.etapa,
                "inicio": ts,
            },
        )
        tx.zadd(llave_editando(datos.proyecto_id), {anotador_id: ts})
        tx.execute()
    return {"anotador_id": anotador_id, **datos.model_dump(), "borrador": leer_borrador(datos.tarea_id, anotador_id)}


@app.get("/sesiones/{anotador_id}")
def consultar_sesion(anotador_id: str):
    sesion = cliente.hgetall(llave_sesion(anotador_id))
    if not sesion:
        raise HTTPException(404, "sin sesión")
    lock = cliente.get(llave_lock(sesion["tarea_id"]))
    return {
        "anotador_id": anotador_id,
        "tarea_id": sesion["tarea_id"],
        "proyecto_id": sesion["proyecto_id"],
        "token": sesion["token"],
        "etapa": sesion.get("etapa"),
        "lock_valido": lock == sesion["token"],
        "borrador": leer_borrador(sesion["tarea_id"], anotador_id),
        "envio_pendiente": leer_envio(sesion["tarea_id"], anotador_id),
    }


@app.put("/tareas/{tarea_id}/borrador")
def guardar_borrador(tarea_id: str, datos: BorradorIn):
    """Guarda el borrador o el envío pendiente y renueva el lock si el token coincide (latido, ADR-005)."""
    sesion = cliente.hgetall(llave_sesion(datos.anotador_id))
    if not sesion or sesion.get("tarea_id") != tarea_id:
        raise HTTPException(409, "la tarea no corresponde a la sesión activa")
    ts = ahora_ms()
    envio = json.dumps(datos.envio.model_dump()) if datos.envio else ""
    contenido = json.dumps(datos.contenido) if datos.contenido is not None else ""
    guardado = GUARDAR_BORRADOR(
        keys=[
            llave_lock(tarea_id),
            llave_borrador(tarea_id),
            llave_editando(sesion["proyecto_id"]),
            llave_envio(tarea_id),
        ],
        args=[datos.token, LOCK_MS, contenido, ts, datos.anotador_id, ts - LOCK_MS, envio],
    )
    if not guardado:
        raise HTTPException(409, "el token no corresponde al lock")
    return {"guardado": True, "tipo": "envio" if envio else "borrador", "ts": ts}


@app.post("/eventos", status_code=201)
def registrar_evento(datos: EventoIn):
    """Agrega un evento confirmado por MongoDB al stream que consume Historial (ADR-007)."""
    with cliente.pipeline() as tx:
        tx.xadd(STREAM_EVENTOS, {"evento": json.dumps(datos.evento)})
        if datos.limpiar_envio:
            tx.delete(llave_envio(datos.limpiar_envio))
        entrada, *_ = tx.execute()
    return {"id": entrada}
