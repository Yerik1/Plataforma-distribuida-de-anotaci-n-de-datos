"""Consultas Q1 a Q5 sobre el datalake Parquet en modo de solo lectura (§8, ADR-010)."""

import argparse
import contextlib
import io
import json
import platform
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

PRECISION_PERCENTIL = 10_000


def leer_eventos(spark: SparkSession, ruta: str, desde_mes: str | None = None) -> DataFrame:
    """Lee los eventos publicados y descarta duplicados por event_id (§6.3).

    Con `desde_mes`, el filtro sobre la columna de partición se aplica antes de deduplicar, para que
    Spark descarte los directorios mes=AAAA-MM anteriores sin leerlos. Es seguro porque los duplicados
    de un evento tienen el mismo `ts` y, por lo tanto, están en la misma partición.
    """
    eventos = spark.read.parquet(ruta)
    if desde_mes:
        eventos = eventos.where(F.col("mes") >= desde_mes)
    return eventos.dropDuplicates(["event_id"])


def mes_inicio_q1(referencia: date) -> str:
    return (referencia - timedelta(days=89)).strftime("%Y-%m")


def q1(eventos: DataFrame, referencia: date) -> DataFrame:
    """Tareas aprobadas por día y modalidad en los 90 días que terminan en la fecha de referencia."""
    fin = F.lit(referencia.isoformat()).cast("date")
    return (
        eventos.where(F.col("estado") == "aprobada")
        .withColumn("dia", F.to_date("ts"))
        .where(F.col("dia").between(F.date_sub(fin, 89), fin))
        .groupBy("dia", "modalidad")
        .agg(F.count("*").alias("aprobadas"))
        .orderBy("dia", "modalidad")
    )


def q2(eventos: DataFrame) -> DataFrame:
    """Proporción de aprobadas sobre revisadas por equipo del anotador y mes, con la decisión final de cada tarea."""
    ultima = Window.partitionBy("tarea_id").orderBy(F.col("ts").desc(), F.col("version").desc())
    finales = (
        eventos.where(F.col("estado").isin("aprobada", "rechazada"))
        .withColumn("orden", F.row_number().over(ultima))
        .where(F.col("orden") == 1)
        .withColumn("mes_decision", F.date_format("ts", "yyyy-MM"))
    )
    return (
        finales.groupBy("equipo_id", "mes_decision")
        .agg(
            F.sum(F.when(F.col("estado") == "aprobada", 1).otherwise(0)).alias("aprobadas"),
            F.count("*").alias("revisadas"),
        )
        .withColumn("proporcion_aprobadas", F.round(F.col("aprobadas") / F.col("revisadas"), 4))
        .withColumnRenamed("mes_decision", "mes")
        .orderBy("equipo_id", "mes")
    )


def q3(eventos: DataFrame) -> DataFrame:
    """Duración media y percentil 95 de cada toma, de abierta a anotada, por modalidad y tipo de tarea."""
    return (
        eventos.where((F.col("estado") == "anotada") & F.col("duracion_anotacion_ms").isNotNull())
        .groupBy("modalidad", "tipo_tarea")
        .agg(
            F.count("*").alias("anotaciones"),
            F.round(F.avg("duracion_anotacion_ms"), 4).alias("duracion_media_ms"),
            F.percentile_approx("duracion_anotacion_ms", 0.95, PRECISION_PERCENTIL)
            .cast("double")
            .alias("duracion_p95_ms"),
        )
        .orderBy("modalidad", "tipo_tarea")
    )


def q4(eventos: DataFrame) -> DataFrame:
    """Proporción de filas rechazadas sobre filas revisadas por cliente y proyecto."""
    return (
        eventos.where(F.col("estado").isin("aprobada", "rechazada"))
        .groupBy("cliente_id", "proyecto_id")
        .agg(
            F.sum(F.when(F.col("estado") == "rechazada", 1).otherwise(0)).alias("rechazadas"),
            F.count("*").alias("revisadas"),
        )
        .withColumn("proporcion_rechazadas", F.round(F.col("rechazadas") / F.col("revisadas"), 4))
        .orderBy("cliente_id", "proyecto_id")
    )


def q5(eventos: DataFrame) -> DataFrame:
    """Horas entre la primera toma y la aprobación: p50, p95 y porcentaje que superó el SLA, por cliente."""
    horas = (F.col("ts").cast("long") - F.col("ts_primera_toma").cast("long")) / 3600.0
    return (
        eventos.where(F.col("estado") == "aprobada")
        .withColumn("horas", horas)
        .groupBy("cliente_id")
        .agg(
            F.count("*").alias("tareas_aprobadas"),
            F.round(F.percentile_approx("horas", 0.5, PRECISION_PERCENTIL), 4).alias("p50_horas"),
            F.round(F.percentile_approx("horas", 0.95, PRECISION_PERCENTIL), 4).alias("p95_horas"),
            F.round(
                100 * F.avg(F.when(F.col("horas") > F.col("sla_horas"), 1).otherwise(0)), 4
            ).alias("porcentaje_incumple_sla"),
        )
        .orderBy("cliente_id")
    )


def filas(df: DataFrame) -> list[dict]:
    resultado = []
    for fila in df.collect():
        registro = {}
        for clave, valor in fila.asDict().items():
            if isinstance(valor, (date, datetime)):
                valor = valor.isoformat()
            elif isinstance(valor, float):
                valor = round(valor, 4)
            registro[clave] = valor
        resultado.append(registro)
    return resultado


def plan(df: DataFrame) -> str:
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        df.explain(mode="formatted")
    return salida.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datos", required=True, help="ruta de eventos/ en el datalake")
    parser.add_argument("--fecha-referencia", default=None, help="fin de la ventana de Q1 (AAAA-MM-DD); por defecto, hoy")
    parser.add_argument("--esperados", default=None, help="JSON con resultados conocidos para validar")
    parser.add_argument("--repeticiones", type=int, default=1)
    parser.add_argument("--planes", action="store_true", help="incluye los planes de ejecución de Q1 y Q3")
    parser.add_argument("--evidencia", default=None, help="directorio donde guardar el resultado")
    args = parser.parse_args()

    referencia = date.fromisoformat(args.fecha_referencia) if args.fecha_referencia else date.today()
    spark = (
        SparkSession.builder.appName("consultas-q1-q5")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.sources.partitionColumnTypeInference.enabled", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    constructores = {
        "q1": lambda: q1(leer_eventos(spark, args.datos, mes_inicio_q1(referencia)), referencia),
        "q2": lambda: q2(leer_eventos(spark, args.datos)),
        "q3": lambda: q3(leer_eventos(spark, args.datos)),
        "q4": lambda: q4(leer_eventos(spark, args.datos)),
        "q5": lambda: q5(leer_eventos(spark, args.datos)),
    }

    # Cada repetición vuelve a leer el Parquet y construye un plan nuevo, para que Spark no
    # reutilice resultados intermedios de la ejecución anterior. La primera incluye la
    # inicialización (listado de archivos, arranque de ejecutores, compilación de código).
    resultados, tiempos = {}, {}
    for nombre, construir in constructores.items():
        tiempos[nombre] = []
        for _ in range(args.repeticiones):
            inicio = time.perf_counter()
            resultados[nombre] = filas(construir())
            tiempos[nombre].append(round(time.perf_counter() - inicio, 3))

    eventos = leer_eventos(spark, args.datos)
    salida = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "objetivo": "Ejecutar Q1 a Q5 sobre Parquet y validarlas contra resultados conocidos",
        "configuracion": {
            "datos": args.datos,
            "fecha_referencia_q1": referencia.isoformat(),
            "spark_version": spark.version,
            "master": spark.sparkContext.master,
            "paralelismo_por_defecto": spark.sparkContext.defaultParallelism,
            "repeticiones": args.repeticiones,
            "python": platform.python_version(),
        },
        "eventos_unicos": eventos.count(),
        "tiempos_s": tiempos,
        "resultados": resultados,
    }

    if args.esperados:
        esperados = json.loads(Path(args.esperados).read_text(encoding="utf-8"))
        salida["validacion"] = {q: resultados[q] == esperados[q] for q in constructores}
        salida["validacion"]["todas"] = all(salida["validacion"].values())

    if args.planes:
        salida["planes"] = {"q1": plan(constructores["q1"]()), "q3": plan(constructores["q3"]())}

    texto = json.dumps(salida, indent=2, ensure_ascii=False)
    if args.evidencia:
        destino = Path(args.evidencia)
        destino.mkdir(parents=True, exist_ok=True)
        marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        archivo = destino / f"spark_consultas_{marca}.json"
        archivo.write_text(texto, encoding="utf-8")
        print(f"evidencia: {archivo}")

    resumen = {k: salida[k] for k in ("eventos_unicos", "tiempos_s")}
    if "validacion" in salida:
        resumen["validacion"] = salida["validacion"]
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    spark.stop()


if __name__ == "__main__":
    main()
