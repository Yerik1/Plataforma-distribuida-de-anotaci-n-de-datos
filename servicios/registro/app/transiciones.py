from datetime import datetime, timedelta
from typing import Any

from .config import LOCK_MS
from .db import db
from .modelos import TransicionIn


def _asignar(tarea_id: str, t: TransicionIn, ahora: datetime) -> tuple[dict, Any]:
    anotador = db.anotadores.find_one({"_id": t.anotador_id}, {"equipo_id": 1})
    asignacion = {
        "anotador_id": t.anotador_id,
        "equipo_id": anotador.get("equipo_id") if anotador else None,
        "token": t.token,
        "tomada_en": ahora,
    }
    if t.token_anterior:
        filtro = {
            "_id": tarea_id,
            "estado": "abierta",
            "asignacion.token": t.token_anterior,
            "asignacion.tomada_en": {"$lt": ahora - timedelta(milliseconds=LOCK_MS)},
        }
    else:
        filtro = {"_id": tarea_id, "estado": "disponible"}
    actualizacion = [
        {
            "$set": {
                "estado": "abierta",
                "asignacion": {"$literal": asignacion},
                "primera_toma_en": {"$ifNull": ["$primera_toma_en", ahora]},
                "version": {"$add": [{"$ifNull": ["$version", 0]}, 1]},
                "actualizada_en": ahora,
            }
        }
    ]
    return filtro, actualizacion


def _enviar(tarea_id: str, t: TransicionIn, ahora: datetime) -> tuple[dict, Any]:
    filtro = {
        "_id": tarea_id,
        "estado": "abierta",
        "asignacion.token": t.token,
        "asignacion.anotador_id": t.anotador_id,
    }
    anotacion = t.anotacion.model_dump() | {"anotador_id": t.anotador_id, "enviada_en": ahora}
    actualizacion = {
        "$set": {"estado": "anotada", "anotacion": anotacion, "actualizada_en": ahora},
        "$inc": {"version": 1},
    }
    return filtro, actualizacion


def _liberar(tarea_id: str, t: TransicionIn, ahora: datetime) -> tuple[dict, Any]:
    filtro = {
        "_id": tarea_id,
        "estado": "abierta",
        "asignacion.token": t.token,
        "asignacion.anotador_id": t.anotador_id,
    }
    actualizacion = {
        "$set": {"estado": "disponible", "asignacion": None, "actualizada_en": ahora},
        "$inc": {"version": 1},
    }
    return filtro, actualizacion


def _iniciar_revision(tarea_id: str, t: TransicionIn, ahora: datetime) -> tuple[dict, Any]:
    filtro = {
        "_id": tarea_id,
        "estado": "anotada",
        "asignacion.anotador_id": {"$ne": t.revisor_id},
    }
    actualizacion = {
        "$set": {
            "estado": "en_revision",
            "ultima_revision": {
                "revisor_id": t.revisor_id,
                "decision": None,
                "motivo": None,
                "iniciada_en": ahora,
                "decidida_en": None,
            },
            "actualizada_en": ahora,
        },
        "$inc": {"version": 1},
    }
    return filtro, actualizacion


def _aprobar(tarea_id: str, t: TransicionIn, ahora: datetime) -> tuple[dict, Any]:
    filtro = {"_id": tarea_id, "estado": "en_revision", "ultima_revision.revisor_id": t.revisor_id}
    actualizacion = {
        "$set": {
            "estado": "aprobada",
            "ultima_revision.decision": "aprobada",
            "ultima_revision.decidida_en": ahora,
            "actualizada_en": ahora,
        },
        "$inc": {"version": 1},
    }
    return filtro, actualizacion


def _rechazar(tarea_id: str, t: TransicionIn, ahora: datetime) -> tuple[dict, Any]:
    filtro = {"_id": tarea_id, "estado": "en_revision", "ultima_revision.revisor_id": t.revisor_id}
    actualizacion = {
        "$set": {
            "estado": "disponible",
            "asignacion": None,
            "ultima_revision.decision": "rechazada",
            "ultima_revision.motivo": t.motivo,
            "ultima_revision.decidida_en": ahora,
            "actualizada_en": ahora,
        },
        "$inc": {"version": 1},
    }
    return filtro, actualizacion


CONSTRUCTORES = {
    "asignar": _asignar,
    "enviar": _enviar,
    "liberar": _liberar,
    "iniciar_revision": _iniciar_revision,
    "aprobar": _aprobar,
    "rechazar": _rechazar,
}


def construir(tarea_id: str, t: TransicionIn, ahora: datetime) -> tuple[dict, Any]:
    return CONSTRUCTORES[t.tipo](tarea_id, t, ahora)
