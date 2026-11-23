import logging
import time

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from .config import (
    DB_NOMBRE,
    MONGO_TIMEOUT_MS,
    MONGO_URI,
    MONGO_W,
    MONGO_WTIMEOUT_MS,
)

log = logging.getLogger("registro")

cliente = MongoClient(
    MONGO_URI,
    w=int(MONGO_W) if MONGO_W.isdigit() else MONGO_W,
    wtimeoutMS=MONGO_WTIMEOUT_MS,
    serverSelectionTimeoutMS=MONGO_TIMEOUT_MS,
    connectTimeoutMS=MONGO_TIMEOUT_MS,
    socketTimeoutMS=MONGO_TIMEOUT_MS * 3,
    tz_aware=True,
)
db = cliente[DB_NOMBRE]

INDICES = [
    ("tareas", [("proyecto_id", ASCENDING), ("estado", ASCENDING), ("prioridad", DESCENDING)], "proyecto_estado_prioridad"),
    ("tareas", [("asignacion.anotador_id", ASCENDING), ("estado", ASCENDING)], "anotador_estado"),
    ("tareas", [("batch_id", ASCENDING)], "batch"),
    ("proyectos", [("cliente_id", ASCENDING), ("estado", ASCENDING)], "cliente_estado"),
    ("tareas", [("proyecto_id", ASCENDING), ("estado", ASCENDING), ("_id", ASCENDING)], "proyecto_estado_id"),
    ("tareas", [("actualizada_en", ASCENDING)], "actualizada"),
]


def crear_indices(intentos: int = 60, espera_s: float = 2.0) -> None:
    for intento in range(1, intentos + 1):
        try:
            for coleccion, claves, nombre in INDICES:
                db[coleccion].create_index(claves, name=nombre)
            log.info("índices verificados")
            return
        except PyMongoError as exc:
            log.warning("índices pendientes (intento %d): %s", intento, exc)
            time.sleep(espera_s)
    log.error("no fue posible crear los índices")
