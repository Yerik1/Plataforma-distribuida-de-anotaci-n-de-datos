import os
import socket
from pathlib import Path

VALKEY_HOST = os.getenv("VALKEY_HOST", "valkey")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
STREAM_EVENTOS = os.getenv("STREAM_EVENTOS", "eventos:confirmados")
GRUPO = os.getenv("GRUPO", "historial")
CONSUMIDOR = os.getenv("CONSUMIDOR", socket.gethostname())
DATALAKE = Path(os.getenv("DATALAKE", "/datalake"))
LOTE_EVENTOS = int(os.getenv("LOTE_EVENTOS", "500"))
LOTE_SEGUNDOS = float(os.getenv("LOTE_SEGUNDOS", "2"))
SALUD_INTERVALO_S = float(os.getenv("SALUD_INTERVALO_S", "5"))
SALUD_TTL_S = int(os.getenv("SALUD_TTL_S", "15"))
