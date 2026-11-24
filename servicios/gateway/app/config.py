import os


def lista(variable: str, defecto: str) -> list[str]:
    return [v.strip() for v in os.getenv(variable, defecto).split(",") if v.strip()]


REGISTRO_URL = os.getenv("REGISTRO_URL", "http://registro:8000")
SESION_URL = os.getenv("SESION_URL", "http://sesion:8000")
HISTORIAL_URL = os.getenv("HISTORIAL_URL", "http://historial:8000")
ANALITICA_URL = os.getenv("ANALITICA_URL", "http://analitica:8000")
VALKEY_HOST = os.getenv("VALKEY_HOST", "valkey")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))

TIMEOUT_S = float(os.getenv("TIMEOUT_S", "2"))
TIMEOUT_ANALITICA_S = float(os.getenv("TIMEOUT_ANALITICA_S", "300"))
REINTENTOS = int(os.getenv("REINTENTOS", "2"))
CANDIDATAS = int(os.getenv("CANDIDATAS", "20"))

SALUD_INTERVALO_S = float(os.getenv("SALUD_INTERVALO_S", "5"))
SALUD_TTL_S = int(os.getenv("SALUD_TTL_S", "15"))
CAPAS = lista("CAPAS", "registro,sesion,historial,analitica")
CAPAS_CRITICAS = lista("CAPAS_CRITICAS", "registro,sesion")

MOTIVOS_RECHAZO = {
    "geometria_invalida",
    "etiqueta_fuera_taxonomia",
    "objeto_omitido",
    "instruccion_no_seguida",
}
