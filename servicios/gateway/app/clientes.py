import asyncio
import random
from contextvars import ContextVar

import httpx
import valkey.asyncio as valkey_async
from fastapi.responses import JSONResponse, Response

from .config import REINTENTOS, TIMEOUT_S, VALKEY_HOST, VALKEY_PORT

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

http: httpx.AsyncClient | None = None
valkey = valkey_async.Valkey(
    host=VALKEY_HOST,
    port=VALKEY_PORT,
    decode_responses=True,
    socket_timeout=1,
    socket_connect_timeout=1,
)


class ServicioNoDisponible(Exception):
    def __init__(self, servicio: str):
        super().__init__(servicio)
        self.servicio = servicio


def iniciar_http() -> None:
    global http
    http = httpx.AsyncClient(timeout=TIMEOUT_S)


async def cerrar_http() -> None:
    if http is not None:
        await http.aclose()


async def llamar(metodo: str, url: str, *, reintentar: bool = False, **kwargs) -> httpx.Response:
    """Llama a un servicio interno. Solo reintenta operaciones idempotentes (ADR-006)."""
    intentos = 1 + (REINTENTOS if reintentar else 0)
    cabeceras = {"X-Correlation-ID": correlation_id.get()}
    for intento in range(intentos):
        ultimo = intento == intentos - 1
        try:
            respuesta = await http.request(metodo, url, headers=cabeceras, **kwargs)
        except httpx.TransportError:
            if ultimo:
                raise ServicioNoDisponible(url)
        else:
            if respuesta.status_code not in (502, 503) or ultimo:
                return respuesta
        await asyncio.sleep(0.1 * (2**intento) + random.uniform(0, 0.05))
    raise ServicioNoDisponible(url)


def reenviar(respuesta: httpx.Response) -> Response:
    if respuesta.status_code == 204 or not respuesta.content:
        return Response(status_code=respuesta.status_code)
    return JSONResponse(status_code=respuesta.status_code, content=respuesta.json())
