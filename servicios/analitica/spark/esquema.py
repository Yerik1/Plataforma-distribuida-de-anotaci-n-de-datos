from pyspark.sql.types import (
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# Esquema del evento definido en ADR-008. `mes` es la columna de partición (eventos/mes=AAAA-MM/).
EVENTO = StructType(
    [
        StructField("event_id", StringType(), False),
        StructField("tipo_evento", StringType(), False),
        StructField("estado", StringType(), False),
        StructField("ts", TimestampType(), False),
        StructField("tarea_id", StringType(), False),
        StructField("batch_id", StringType(), True),
        StructField("proyecto_id", StringType(), False),
        StructField("cliente_id", StringType(), False),
        StructField("modalidad", StringType(), False),
        StructField("tipo_tarea", StringType(), False),
        StructField("anotador_id", StringType(), True),
        StructField("equipo_id", StringType(), True),
        StructField("revisor_id", StringType(), True),
        StructField("version", IntegerType(), True),
        StructField("ts_toma", TimestampType(), True),
        StructField("ts_primera_toma", TimestampType(), True),
        StructField("duracion_anotacion_ms", LongType(), True),
        StructField("sla_horas", IntegerType(), True),
        StructField("motivo_rechazo", StringType(), True),
        StructField("correlation_id", StringType(), True),
    ]
)
