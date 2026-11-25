from datetime import datetime, timedelta, timezone

from .config import LOCK_MS
from .db import db
from .modelos import TransicionIn

# Tipo de evento y estado de la fila en el datalake por transición (§6.1, ADR-008).
FILA = {
    "asignar": ("tarea_abierta", "abierta"),
    "enviar": ("tarea_anotada", "anotada"),
    "liberar": ("tarea_liberada", "disponible"),
    "iniciar_revision": ("revision_iniciada", "en_revision"),
    "aprobar": ("tarea_aprobada", "aprobada"),
    "rechazar": ("tarea_rechazada", "rechazada"),
}


class TransicionInvalida(Exception):
    pass


def utc(valor: datetime | None) -> datetime | None:
    if valor is not None and valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor


def iso(valor: datetime | None) -> str | None:
    return utc(valor).isoformat() if valor else None


def exigir(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise TransicionInvalida(mensaje)


def preparar(
    tarea: dict, t: TransicionIn, ahora: datetime, correlation_id: str
) -> tuple[dict, dict, dict]:
    """Valida la transición sobre el estado leído y arma el filtro, la actualización y el evento.

    El filtro incluye la versión leída: si otra transición modificó la tarea entre la lectura
    y la escritura, `find_one_and_update` no encuentra el documento y la operación responde 409.
    """
    version = tarea.get("version", 0)
    asignacion = tarea.get("asignacion") or {}
    estado = tarea["estado"]
    cambios: dict = {}
    toma = asignacion
    revisor = None
    duracion_ms = None

    if t.tipo == "asignar":
        if t.token_anterior:
            exigir(estado == "abierta", "la tarea no está abierta")
            exigir(asignacion.get("token") == t.token_anterior, "el token anterior no coincide")
            exigir(
                utc(asignacion["tomada_en"]) < ahora - timedelta(milliseconds=LOCK_MS),
                "el plazo de la toma anterior no ha vencido",
            )
        else:
            exigir(estado == "disponible", "la tarea no está disponible")
        anotador = db.anotadores.find_one({"_id": t.anotador_id}, {"equipo_id": 1})
        toma = {
            "anotador_id": t.anotador_id,
            "equipo_id": anotador.get("equipo_id") if anotador else None,
            "token": t.token,
            "tomada_en": ahora,
        }
        cambios = {
            "estado": "abierta",
            "asignacion": toma,
            "primera_toma_en": tarea.get("primera_toma_en") or ahora,
        }

    elif t.tipo in ("enviar", "liberar"):
        exigir(estado == "abierta", "la tarea no está abierta")
        exigir(
            asignacion.get("token") == t.token and asignacion.get("anotador_id") == t.anotador_id,
            "el token no corresponde a la asignación",
        )
        if t.tipo == "enviar":
            cambios = {
                "estado": "anotada",
                "anotacion": t.anotacion.model_dump() | {"anotador_id": t.anotador_id, "enviada_en": ahora},
            }
            duracion_ms = int((ahora - utc(asignacion["tomada_en"])).total_seconds() * 1000)
        else:
            cambios = {"estado": "disponible", "asignacion": None}

    elif t.tipo == "iniciar_revision":
        exigir(estado == "anotada", "la tarea no está anotada")
        exigir(asignacion.get("anotador_id") != t.revisor_id, "el revisor no puede revisar su propia anotación")
        revisor = t.revisor_id
        cambios = {
            "estado": "en_revision",
            "ultima_revision": {
                "revisor_id": t.revisor_id,
                "decision": None,
                "motivo": None,
                "iniciada_en": ahora,
                "decidida_en": None,
            },
        }

    else:
        revision = tarea.get("ultima_revision") or {}
        exigir(estado == "en_revision", "la tarea no está en revisión")
        exigir(revision.get("revisor_id") == t.revisor_id, "la revisión pertenece a otro revisor")
        revisor = t.revisor_id
        decision = "aprobada" if t.tipo == "aprobar" else "rechazada"
        cambios = {
            "estado": "aprobada" if t.tipo == "aprobar" else "disponible",
            "ultima_revision": revision | {"decision": decision, "motivo": t.motivo, "decidida_en": ahora},
        }
        if t.tipo == "rechazar":
            cambios["asignacion"] = None

    tipo_evento, estado_fila = FILA[t.tipo]
    evento = {
        "event_id": t.event_id,
        "tipo_evento": tipo_evento,
        "estado": estado_fila,
        "ts": iso(ahora),
        "tarea_id": tarea["_id"],
        "batch_id": tarea.get("batch_id"),
        "proyecto_id": tarea["proyecto_id"],
        "cliente_id": tarea["cliente_id"],
        "modalidad": tarea["modalidad"],
        "tipo_tarea": tarea["tipo_tarea"],
        "anotador_id": toma.get("anotador_id"),
        "equipo_id": toma.get("equipo_id"),
        "revisor_id": revisor,
        "version": version + 1,
        "ts_toma": iso(toma.get("tomada_en")),
        "ts_primera_toma": iso(cambios.get("primera_toma_en") or tarea.get("primera_toma_en")),
        "duracion_anotacion_ms": duracion_ms,
        "sla_horas": tarea.get("sla_horas"),
        "motivo_rechazo": t.motivo if t.tipo == "rechazar" else None,
        "correlation_id": correlation_id,
    }
    cambios |= {"version": version + 1, "actualizada_en": ahora, "ultimo_evento": evento}
    filtro = {"_id": tarea["_id"], "version": version, "estado": estado}
    return filtro, {"$set": cambios}, evento
