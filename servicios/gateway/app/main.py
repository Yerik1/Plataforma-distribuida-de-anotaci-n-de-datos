import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any, Literal
from uuid import uuid4

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import clientes, salud
from .clientes import ServicioNoDisponible, llamar, reenviar
from .config import (
    ANALITICA_URL,
    CANDIDATAS,
    MOTIVOS_RECHAZO,
    REGISTRO_URL,
    SESION_URL,
    TIMEOUT_ANALITICA_S,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gateway")


@asynccontextmanager
async def ciclo_vida(_: FastAPI):
    clientes.iniciar_http()
    sondeo = asyncio.create_task(salud.sondear_registro())
    yield
    sondeo.cancel()
    with suppress(asyncio.CancelledError):
        await sondeo
    await clientes.cerrar_http()


app = FastAPI(title="Gateway", lifespan=ciclo_vida)


@app.middleware("http")
async def propagar_correlation_id(request: Request, call_next):
    valor = request.headers.get("X-Correlation-ID") or str(uuid4())
    marca = clientes.correlation_id.set(valor)
    try:
        respuesta = await call_next(request)
    finally:
        clientes.correlation_id.reset(marca)
    respuesta.headers["X-Correlation-ID"] = valor
    return respuesta


@app.exception_handler(ServicioNoDisponible)
async def servicio_no_disponible(_, exc: ServicioNoDisponible):
    return JSONResponse(status_code=503, content={"detail": "servicio interno no disponible"})


class SiguienteIn(BaseModel):
    anotador_id: str = Field(min_length=1)
    proyecto_id: str = Field(min_length=1)


class BorradorIn(BaseModel):
    anotador_id: str = Field(min_length=1)
    token: str = Field(min_length=1)
    contenido: dict[str, Any]


class EnvioIn(BaseModel):
    anotador_id: str = Field(min_length=1)
    token: str = Field(min_length=1)
    anotacion: dict[str, Any]


class LiberarIn(BaseModel):
    anotador_id: str = Field(min_length=1)
    token: str = Field(min_length=1)


class RevisionIn(BaseModel):
    revisor_id: str = Field(min_length=1)
    accion: Literal["iniciar", "aprobar", "rechazar"]
    motivo: str | None = None


class RecuperarIn(BaseModel):
    anotador_id: str = Field(min_length=1)


async def sesion_activa(anotador_id: str) -> dict | None:
    respuesta = await llamar("GET", f"{SESION_URL}/sesiones/{anotador_id}", reintentar=True)
    if respuesta.status_code == 404:
        return None
    if respuesta.status_code != 200:
        raise ServicioNoDisponible("sesion")
    return respuesta.json()


async def soltar_lock(tarea_id: str, token: str, anotador_id: str = "", limpiar: bool = False) -> None:
    with suppress(ServicioNoDisponible):
        await llamar(
            "DELETE",
            f"{SESION_URL}/locks/{tarea_id}",
            params={"token": token, "anotador_id": anotador_id, "limpiar": str(limpiar).lower()},
        )


async def publicar_evento(evento: dict, limpiar_envio: str | None = None) -> None:
    """Agrega el evento confirmado al stream. Si falla, la conciliación lo recupera desde MongoDB (ADR-007)."""
    try:
        respuesta = await llamar(
            "POST", f"{SESION_URL}/eventos", json={"evento": evento, "limpiar_envio": limpiar_envio}
        )
        if respuesta.status_code != 201:
            log.warning("evento %s no publicado: %s", evento["event_id"], respuesta.status_code)
    except ServicioNoDisponible:
        log.warning("evento %s no publicado: sesión no disponible", evento["event_id"])


def conflicto(mensaje: str) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": mensaje})


async def validar_dueno(tarea_id: str, anotador_id: str, token: str) -> tuple[dict | None, JSONResponse | None]:
    """Comprueba que el token coincide con la sesión y con el lock vigente (§5)."""
    sesion = await sesion_activa(anotador_id)
    if sesion is None or sesion["tarea_id"] != tarea_id or sesion["token"] != token:
        return None, conflicto("el token no corresponde a la sesión del anotador")
    if not sesion["lock_valido"]:
        return None, conflicto("el lock de la tarea venció")
    return sesion, None


@app.post("/proyectos")
async def crear_proyecto(datos: dict = Body(...)):
    return reenviar(await llamar("POST", f"{REGISTRO_URL}/proyectos", json=datos))


@app.post("/proyectos/{proyecto_id}/lotes")
async def registrar_lote(proyecto_id: str, datos: dict = Body(...)):
    return reenviar(await llamar("POST", f"{REGISTRO_URL}/proyectos/{proyecto_id}/lotes", json=datos))


@app.get("/proyectos/{proyecto_id}/exportar")
async def exportar(proyecto_id: str, cursor: str | None = None, limite: int = Query(100, ge=1, le=500)):
    parametros = {"limite": limite} | ({"cursor": cursor} if cursor else {})
    respuesta = await llamar(
        "GET", f"{REGISTRO_URL}/proyectos/{proyecto_id}/exportar", params=parametros, reintentar=True
    )
    return reenviar(respuesta)


@app.post("/tareas/siguiente")
async def siguiente_tarea(datos: SiguienteIn):
    sesion = await sesion_activa(datos.anotador_id)
    if sesion is not None and sesion["lock_valido"]:
        return {
            "tarea_id": sesion["tarea_id"],
            "proyecto_id": sesion["proyecto_id"],
            "token": sesion["token"],
            "borrador": sesion["borrador"],
            "reanudada": True,
        }

    respuesta = await llamar(
        "GET",
        f"{REGISTRO_URL}/tareas",
        params={"proyecto_id": datos.proyecto_id, "limite": CANDIDATAS},
        reintentar=True,
    )
    if respuesta.status_code != 200:
        return reenviar(respuesta)

    for candidata in respuesta.json()["candidatas"]:
        tarea_id = candidata["tarea_id"]
        token = str(uuid4())
        lock = await llamar("POST", f"{SESION_URL}/locks", json={"tarea_id": tarea_id, "token": token})
        if lock.status_code == 409:
            continue
        if lock.status_code != 201:
            return reenviar(lock)

        try:
            asignacion = await llamar(
                "POST",
                f"{REGISTRO_URL}/tareas/{tarea_id}/transicion",
                json={
                    "tipo": "asignar",
                    "event_id": str(uuid4()),
                    "anotador_id": datos.anotador_id,
                    "token": token,
                    "token_anterior": candidata["token_anterior"],
                },
            )
        except ServicioNoDisponible:
            await soltar_lock(tarea_id, token)
            raise

        if asignacion.status_code != 200:
            await soltar_lock(tarea_id, token)
            if asignacion.status_code == 409:
                continue
            return reenviar(asignacion)

        apertura = await llamar(
            "PUT",
            f"{SESION_URL}/sesiones/{datos.anotador_id}",
            json={"tarea_id": tarea_id, "proyecto_id": datos.proyecto_id, "token": token},
        )
        cuerpo = asignacion.json()
        await publicar_evento(cuerpo["evento"])
        if apertura.status_code != 200:
            return reenviar(apertura)
        return {
            "tarea_id": tarea_id,
            "proyecto_id": datos.proyecto_id,
            "token": token,
            "tarea": cuerpo["tarea"],
            "borrador": apertura.json()["borrador"],
            "reanudada": False,
        }

    return Response(status_code=204)


@app.put("/tareas/{tarea_id}/borrador")
async def guardar_borrador(tarea_id: str, datos: BorradorIn):
    respuesta = await llamar(
        "PUT", f"{SESION_URL}/tareas/{tarea_id}/borrador", json=datos.model_dump(), reintentar=True
    )
    return reenviar(respuesta)


@app.post("/tareas/{tarea_id}/enviar")
async def enviar_tarea(tarea_id: str, datos: EnvioIn):
    sesion, rechazo = await validar_dueno(tarea_id, datos.anotador_id, datos.token)
    if rechazo:
        return rechazo

    pendiente = sesion.get("envio_pendiente")
    event_id = pendiente["event_id"] if pendiente and pendiente["token"] == datos.token else str(uuid4())
    guardado = await llamar(
        "PUT",
        f"{SESION_URL}/tareas/{tarea_id}/borrador",
        json={
            "anotador_id": datos.anotador_id,
            "token": datos.token,
            "envio": {"event_id": event_id, "anotacion": datos.anotacion},
        },
        reintentar=True,
    )
    if guardado.status_code != 200:
        return reenviar(guardado)

    respuesta = await llamar(
        "POST",
        f"{REGISTRO_URL}/tareas/{tarea_id}/transicion",
        json={
            "tipo": "enviar",
            "event_id": event_id,
            "anotador_id": datos.anotador_id,
            "token": datos.token,
            "anotacion": datos.anotacion,
        },
    )
    if respuesta.status_code == 200:
        await publicar_evento(respuesta.json()["evento"], limpiar_envio=tarea_id)
        await soltar_lock(tarea_id, datos.token, datos.anotador_id, limpiar=True)
    return reenviar(respuesta)


@app.post("/tareas/{tarea_id}/liberar")
async def liberar_tarea(tarea_id: str, datos: LiberarIn):
    _, rechazo = await validar_dueno(tarea_id, datos.anotador_id, datos.token)
    if rechazo:
        return rechazo
    respuesta = await llamar(
        "POST",
        f"{REGISTRO_URL}/tareas/{tarea_id}/transicion",
        json={"tipo": "liberar", "event_id": str(uuid4()), "anotador_id": datos.anotador_id, "token": datos.token},
    )
    if respuesta.status_code == 200:
        await publicar_evento(respuesta.json()["evento"])
        await soltar_lock(tarea_id, datos.token, datos.anotador_id, limpiar=True)
    return reenviar(respuesta)


@app.post("/tareas/{tarea_id}/revision")
async def revisar_tarea(tarea_id: str, datos: RevisionIn):
    if datos.accion == "rechazar" and datos.motivo not in MOTIVOS_RECHAZO:
        return JSONResponse(
            status_code=400,
            content={"detail": "el rechazo requiere un código de motivo válido", "motivos": sorted(MOTIVOS_RECHAZO)},
        )
    tipo = {"iniciar": "iniciar_revision", "aprobar": "aprobar", "rechazar": "rechazar"}[datos.accion]
    cuerpo = {"tipo": tipo, "event_id": str(uuid4()), "revisor_id": datos.revisor_id}
    if datos.accion == "rechazar":
        cuerpo["motivo"] = datos.motivo
    respuesta = await llamar("POST", f"{REGISTRO_URL}/tareas/{tarea_id}/transicion", json=cuerpo)
    if respuesta.status_code == 200:
        await publicar_evento(respuesta.json()["evento"])
    return reenviar(respuesta)


@app.post("/sesiones/recuperar")
async def recuperar_sesion(datos: RecuperarIn):
    sesion = await sesion_activa(datos.anotador_id)
    if sesion is None:
        return JSONResponse(status_code=404, content={"detail": "el anotador no tiene una sesión"})
    if not sesion["lock_valido"]:
        return conflicto("la sesión venció y la tarea puede haber sido reasignada")
    return {
        "tarea_id": sesion["tarea_id"],
        "proyecto_id": sesion["proyecto_id"],
        "token": sesion["token"],
        "borrador": sesion["borrador"],
    }


@app.get("/analitica/{consulta}")
async def consulta_analitica(
    consulta: Literal["q1", "q2", "q3", "q4", "q5"],
    conjunto: Literal["principal", "ampliado", "validacion"] = "principal",
    fecha_referencia: str | None = None,
):
    """Ejecuta una de las cinco consultas exclusivamente sobre el datalake Parquet (§8)."""
    parametros = {"conjunto": conjunto} | ({"fecha_referencia": fecha_referencia} if fecha_referencia else {})
    respuesta = await llamar(
        "GET",
        f"{ANALITICA_URL}/consultas/{consulta}",
        params=parametros,
        reintentar=True,
        timeout=TIMEOUT_ANALITICA_S,
    )
    return reenviar(respuesta)


@app.get("/salud")
async def consultar_salud():
    codigo, contenido = await salud.consultar()
    return JSONResponse(status_code=codigo, content=contenido)
