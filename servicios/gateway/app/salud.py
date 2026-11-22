import asyncio
import json
import logging
import time

from . import clientes
from .config import CAPAS, CAPAS_CRITICAS, REGISTRO_URL, SALUD_INTERVALO_S, SALUD_TTL_S

log = logging.getLogger("gateway.salud")

ultimo_estado: dict = {}


async def sondear_registro() -> None:
    """Registro no accede a Valkey (§4): el gateway consulta su estado y lo publica en Valkey."""
    while True:
        try:
            respuesta = await clientes.http.get(f"{REGISTRO_URL}/salud")
            estado = respuesta.json()
        except Exception:
            estado = {"estado": "caido", "detalle": "registro sin respuesta"}
        estado["ts"] = int(time.time() * 1000)
        try:
            await clientes.valkey.set("salud:registro", json.dumps(estado), ex=SALUD_TTL_S)
        except Exception as exc:
            log.warning("no se pudo publicar la salud de registro: %s", exc)
        await asyncio.sleep(SALUD_INTERVALO_S)


def estado_global(capas: dict[str, dict]) -> str:
    if any(capas[c]["estado"] in ("caido", "sin_reporte") for c in CAPAS_CRITICAS if c in capas):
        return "caido"
    if any(capas[c]["estado"] != "operativo" for c in capas):
        return "degradado"
    return "operativo"


async def consultar() -> tuple[int, dict]:
    global ultimo_estado
    try:
        valores = await clientes.valkey.mget([f"salud:{c}" for c in CAPAS])
    except Exception:
        contenido = {
            "estado": "caido",
            "capas": {"valkey": {"estado": "caido"}},
            "ultimo_estado_conocido": ultimo_estado or None,
        }
        return 503, contenido

    capas = {"valkey": {"estado": "operativo"}}
    for capa, valor in zip(CAPAS, valores):
        capas[capa] = json.loads(valor) if valor else {"estado": "sin_reporte"}
    contenido = {"estado": estado_global(capas), "capas": capas}
    ultimo_estado = contenido
    return (503 if contenido["estado"] == "caido" else 200), contenido
