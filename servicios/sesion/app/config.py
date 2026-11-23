import os

VALKEY_HOST = os.getenv("VALKEY_HOST", "valkey")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
VALKEY_TIMEOUT_S = float(os.getenv("VALKEY_TIMEOUT_S", "2"))
LOCK_MS = int(os.getenv("LOCK_MS", "120000"))
SALUD_INTERVALO_S = float(os.getenv("SALUD_INTERVALO_S", "5"))
SALUD_TTL_S = int(os.getenv("SALUD_TTL_S", "15"))
