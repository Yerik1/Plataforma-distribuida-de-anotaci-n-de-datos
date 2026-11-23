import json
import logging
import os
import threading
import time

import valkey
from valkey.exceptions import ResponseError

from .config import (
    CONSUMIDOR,
    DATALAKE,
    GRUPO,
    LOTE_EVENTOS,
    LOTE_SEGUNDOS,
    STREAM_EVENTOS,
    VALKEY_HOST,
    VALKEY_PORT,
)
from .parquet import publicar

log = logging.getLogger("historial.consumidor")

# Si existe este archivo, el proceso termina después de publicar y antes de confirmar el lote.
# Lo usa la prueba P4 para demostrar el reprocesamiento de un micro-lote.
FALLA_INYECTADA = DATALAKE / "_control" / "fallar_tras_publicar"


class Consumidor:
    def __init__(self) -> None:
        self.valkey = valkey.Valkey(
            host=VALKEY_HOST, port=VALKEY_PORT, decode_responses=True, socket_timeout=5, socket_connect_timeout=2
        )
        self.detener = threading.Event()
        self.metricas = {"eventos_publicados": 0, "lotes": 0, "archivos": 0, "ultimo_lote_ts": None, "error": None}

    def asegurar_grupo(self) -> None:
        try:
            self.valkey.xgroup_create(STREAM_EVENTOS, GRUPO, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def procesar(self, mensajes: list) -> None:
        validos = [(id_, campos) for id_, campos in mensajes if campos and "evento" in campos]
        ids = [id_ for id_, _ in mensajes]
        if validos:
            eventos = [json.loads(campos["evento"]) for _, campos in validos]
            archivos = publicar(DATALAKE, eventos)
            self.metricas["eventos_publicados"] += len(eventos)
            self.metricas["archivos"] += len(archivos)
            self.metricas["lotes"] += 1
            self.metricas["ultimo_lote_ts"] = int(time.time() * 1000)
            if FALLA_INYECTADA.exists():
                FALLA_INYECTADA.unlink()
                log.error("falla inyectada después de publicar %s y antes de confirmar", [a.name for a in archivos])
                os._exit(1)
        if ids:
            self.valkey.xack(STREAM_EVENTOS, GRUPO, *ids)
            self.valkey.xdel(STREAM_EVENTOS, *ids)

    def recuperar_pendientes(self) -> None:
        """Reprocesa las entradas entregadas y no confirmadas antes de una caída (XAUTOCLAIM)."""
        inicio = "0-0"
        while True:
            respuesta = self.valkey.xautoclaim(
                STREAM_EVENTOS, GRUPO, CONSUMIDOR, min_idle_time=0, start_id=inicio, count=LOTE_EVENTOS
            )
            siguiente, mensajes = respuesta[0], respuesta[1]
            if mensajes:
                log.info("reprocesando %d entradas pendientes", len(mensajes))
                self.procesar(mensajes)
            if siguiente in ("0-0", b"0-0"):
                return
            inicio = siguiente

    def ejecutar(self) -> None:
        while not self.detener.is_set():
            try:
                self.asegurar_grupo()
                self.recuperar_pendientes()
                self.consumir()
            except Exception as exc:
                self.metricas["error"] = f"{type(exc).__name__}: {exc}"
                log.warning("consumidor en espera: %s", self.metricas["error"])
                self.detener.wait(2)

    def consumir(self) -> None:
        lote: list = []
        inicio = None
        while not self.detener.is_set():
            faltan = LOTE_EVENTOS - len(lote)
            respuesta = self.valkey.xreadgroup(GRUPO, CONSUMIDOR, {STREAM_EVENTOS: ">"}, count=faltan, block=500)
            for _, mensajes in respuesta or []:
                if mensajes and inicio is None:
                    inicio = time.monotonic()
                lote.extend(mensajes)
            if lote and (len(lote) >= LOTE_EVENTOS or time.monotonic() - inicio >= LOTE_SEGUNDOS):
                self.procesar(lote)
                lote, inicio = [], None
                self.metricas["error"] = None

    def estado(self) -> dict:
        info = {"estado": "operativo" if self.metricas["error"] is None else "degradado", **self.metricas}
        try:
            info["longitud_stream"] = self.valkey.xlen(STREAM_EVENTOS)
            info["pendientes"] = self.valkey.xpending(STREAM_EVENTOS, GRUPO)["pending"]
        except Exception:
            pass
        return info
