import hashlib
import os
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

TIEMPO = pa.timestamp("us", tz="UTC")

# Esquema del evento (ADR-008). La partición `mes` es el nombre del directorio, no una columna del archivo.
ESQUEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("tipo_evento", pa.string()),
        ("estado", pa.string()),
        ("ts", TIEMPO),
        ("tarea_id", pa.string()),
        ("batch_id", pa.string()),
        ("proyecto_id", pa.string()),
        ("cliente_id", pa.string()),
        ("modalidad", pa.string()),
        ("tipo_tarea", pa.string()),
        ("anotador_id", pa.string()),
        ("equipo_id", pa.string()),
        ("revisor_id", pa.string()),
        ("version", pa.int32()),
        ("ts_toma", TIEMPO),
        ("ts_primera_toma", TIEMPO),
        ("duracion_anotacion_ms", pa.int64()),
        ("sla_horas", pa.int32()),
        ("motivo_rechazo", pa.string()),
        ("correlation_id", pa.string()),
    ]
)
CAMPOS_TIEMPO = {"ts", "ts_toma", "ts_primera_toma"}


def a_fecha(valor):
    if valor is None or isinstance(valor, datetime):
        return valor
    return datetime.fromisoformat(valor)


def a_tabla(eventos: list[dict]) -> pa.Table:
    columnas = {
        campo.name: [a_fecha(e.get(campo.name)) if campo.name in CAMPOS_TIEMPO else e.get(campo.name) for e in eventos]
        for campo in ESQUEMA
    }
    return pa.table(columnas, schema=ESQUEMA)


def mes_de(evento: dict) -> str:
    return a_fecha(evento["ts"]).strftime("%Y-%m")


def nombre_lote(event_ids: list[str]) -> str:
    """Nombre determinista: el mismo conjunto de eventos produce el mismo archivo (ADR-009)."""
    huella = hashlib.sha256("\n".join(sorted(event_ids)).encode()).hexdigest()[:20]
    return f"part-{huella}.parquet"


def escribir_atomico(tabla: pa.Table, raiz: Path, mes: str, nombre: str) -> Path:
    """Escribe en _tmp/ y publica con un renombrado atómico en eventos/mes=AAAA-MM/ (§6.3)."""
    temporal = raiz / "_tmp" / nombre
    destino = raiz / "eventos" / f"mes={mes}" / nombre
    temporal.parent.mkdir(parents=True, exist_ok=True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(tabla, temporal)
    os.replace(temporal, destino)
    return destino


def publicar(raiz: Path, eventos: list[dict]) -> list[Path]:
    por_mes: dict[str, list[dict]] = {}
    for evento in eventos:
        por_mes.setdefault(mes_de(evento), []).append(evento)
    return [
        escribir_atomico(a_tabla(grupo), raiz, mes, nombre_lote([e["event_id"] for e in grupo]))
        for mes, grupo in sorted(por_mes.items())
    ]
