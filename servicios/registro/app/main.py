import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pymongo import ReturnDocument
from pymongo.errors import (
    ConnectionFailure,
    ExecutionTimeout,
    PyMongoError,
    WriteConcernError,
    WTimeoutError,
)

from .config import LOCK_MS
from .db import cliente, crear_indices, db
from .modelos import LoteIn, ProyectoIn, TransicionIn
from .transiciones import TransicionInvalida, preparar, utc

logging.basicConfig(level=logging.INFO)

ERRORES_DISPONIBILIDAD = (ConnectionFailure, WriteConcernError, WTimeoutError, ExecutionTimeout)


@asynccontextmanager
async def ciclo_vida(_: FastAPI):
    crear_indices()
    yield


app = FastAPI(title="Servicio de registro", lifespan=ciclo_vida)


@app.exception_handler(ConnectionFailure)
@app.exception_handler(WriteConcernError)
@app.exception_handler(WTimeoutError)
@app.exception_handler(ExecutionTimeout)
async def mongo_no_disponible(_, exc):
    return JSONResponse(status_code=503, content={"detail": "MongoDB no disponible", "error": type(exc).__name__})


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def salida_tarea(doc: dict) -> dict:
    doc["tarea_id"] = doc.pop("_id")
    return doc


@app.post("/proyectos", status_code=201)
def crear_proyecto(datos: ProyectoIn):
    doc = {
        "_id": str(uuid4()),
        **datos.model_dump(),
        "estado": "activo",
        "creado_en": ahora_utc(),
    }
    db.proyectos.insert_one(doc)
    doc["proyecto_id"] = doc.pop("_id")
    return doc


@app.post("/proyectos/{proyecto_id}/lotes", status_code=201)
def registrar_lote(proyecto_id: str, lote: LoteIn):
    proyecto = db.proyectos.find_one({"_id": proyecto_id})
    if proyecto is None:
        raise HTTPException(404, "proyecto no encontrado")
    if proyecto.get("estado") != "activo":
        raise HTTPException(409, "el proyecto no está activo")

    ahora = ahora_utc()
    batch_id = str(uuid4())
    tareas = [
        {
            "_id": str(uuid4()),
            "proyecto_id": proyecto_id,
            "batch_id": batch_id,
            "cliente_id": proyecto["cliente_id"],
            "sla_horas": proyecto["sla_horas"],
            "modalidad": t.modalidad,
            "tipo_tarea": t.tipo_tarea,
            "prioridad": t.prioridad,
            "archivo": t.archivo.model_dump(),
            "estado": "disponible",
            "version": 0,
            "asignacion": None,
            "primera_toma_en": None,
            "anotacion": None,
            "ultima_revision": None,
            "ultimo_evento": None,
            "creada_en": ahora,
            "actualizada_en": ahora,
        }
        for t in lote.tareas
    ]
    batch = {
        "_id": batch_id,
        "proyecto_id": proyecto_id,
        "cliente_id": proyecto["cliente_id"],
        "cantidad_tareas": len(tareas),
        "creado_en": ahora,
    }

    def insertar(sesion):
        db.batches.insert_one(batch, session=sesion)
        db.tareas.insert_many(tareas, session=sesion)

    with cliente.start_session() as sesion:
        sesion.with_transaction(insertar)

    return {"batch_id": batch_id, "proyecto_id": proyecto_id, "tareas": [t["_id"] for t in tareas]}


@app.get("/tareas")
def consultar_tareas(
    proyecto_id: str | None = None,
    actualizada_desde: datetime | None = None,
    limite: int = Query(20, ge=1, le=1000),
):
    """Candidatas de un proyecto (ADR-005) o tareas modificadas desde un instante para la conciliación (ADR-007)."""
    if actualizada_desde is not None:
        desde = utc(actualizada_desde)
        docs = list(
            db.tareas.find(
                {"actualizada_en": {"$gte": desde}, "ultimo_evento": {"$ne": None}},
                {"ultimo_evento": 1, "actualizada_en": 1},
            )
            .sort([("actualizada_en", 1), ("_id", 1)])
            .limit(limite)
        )
        return {
            "tareas": [
                {"tarea_id": d["_id"], "actualizada_en": utc(d["actualizada_en"]), "ultimo_evento": d["ultimo_evento"]}
                for d in docs
            ]
        }
    if proyecto_id is None:
        raise HTTPException(422, "se requiere proyecto_id o actualizada_desde")

    proyeccion = {"_id": 1, "estado": 1, "asignacion.token": 1}
    candidatas = list(
        db.tareas.find({"proyecto_id": proyecto_id, "estado": "disponible"}, proyeccion)
        .sort("prioridad", -1)
        .limit(limite)
    )
    restantes = limite - len(candidatas)
    if restantes > 0:
        limite_toma = ahora_utc() - timedelta(milliseconds=LOCK_MS)
        candidatas += list(
            db.tareas.find(
                {"proyecto_id": proyecto_id, "estado": "abierta", "asignacion.tomada_en": {"$lt": limite_toma}},
                proyeccion,
            )
            .sort("prioridad", -1)
            .limit(restantes)
        )
    return {
        "candidatas": [
            {
                "tarea_id": c["_id"],
                "estado": c["estado"],
                "token_anterior": (c.get("asignacion") or {}).get("token") if c["estado"] == "abierta" else None,
            }
            for c in candidatas
        ]
    }


@app.post("/tareas/{tarea_id}/transicion")
def aplicar_transicion(
    tarea_id: str,
    transicion: TransicionIn,
    x_correlation_id: str | None = Header(default=None),
):
    tarea = db.tareas.find_one({"_id": tarea_id})
    if tarea is None:
        raise HTTPException(404, "tarea no encontrada")
    try:
        filtro, actualizacion, evento = preparar(tarea, transicion, ahora_utc(), x_correlation_id or "")
    except TransicionInvalida as exc:
        raise HTTPException(409, {"mensaje": str(exc), "estado_actual": tarea["estado"]})

    actualizada = db.tareas.find_one_and_update(filtro, actualizacion, return_document=ReturnDocument.AFTER)
    if actualizada is None:
        actual = db.tareas.find_one({"_id": tarea_id}, {"estado": 1})
        raise HTTPException(
            409, {"mensaje": "la tarea cambió durante la transición", "estado_actual": actual and actual["estado"]}
        )
    return {"tarea": salida_tarea(actualizada), "evento": evento}


@app.get("/proyectos/{proyecto_id}/exportar")
def exportar(proyecto_id: str, cursor: str | None = None, limite: int = Query(100, ge=1, le=500)):
    if db.proyectos.find_one({"_id": proyecto_id}, {"_id": 1}) is None:
        raise HTTPException(404, "proyecto no encontrado")
    filtro = {"proyecto_id": proyecto_id, "estado": "aprobada"}
    if cursor:
        filtro["_id"] = {"$gt": cursor}
    docs = list(db.tareas.find(filtro, {"asignacion.token": 0}).sort("_id", 1).limit(limite + 1))
    siguiente = docs[limite - 1]["_id"] if len(docs) > limite else None
    return {
        "proyecto_id": proyecto_id,
        "tareas": [salida_tarea(d) for d in docs[:limite]],
        "siguiente_cursor": siguiente,
    }


@app.get("/salud")
def salud():
    try:
        estado_rs = cliente.admin.command("replSetGetStatus")
    except PyMongoError as exc:
        return JSONResponse(
            status_code=503,
            content={"estado": "caido", "replica": None, "error": type(exc).__name__},
        )
    miembros = estado_rs.get("members", [])
    sanos = sum(1 for m in miembros if m.get("health") == 1)
    primario = next((m["name"] for m in miembros if m.get("stateStr") == "PRIMARY"), None)
    if primario is None:
        estado = "caido"
    elif sanos < len(miembros):
        estado = "degradado"
    else:
        estado = "operativo"
    contenido = {
        "estado": estado,
        "replica": {
            "primario": primario,
            "miembros_sanos": sanos,
            "miembros_totales": len(miembros),
            "miembros": [{"nombre": m["name"], "estado": m.get("stateStr")} for m in miembros],
        },
    }
    return JSONResponse(status_code=503 if estado == "caido" else 200, content=contenido)
