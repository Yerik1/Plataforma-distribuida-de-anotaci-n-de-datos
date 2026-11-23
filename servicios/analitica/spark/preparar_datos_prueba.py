"""Convierte el conjunto de prueba en JSON a Parquet particionado por mes, con el esquema de ADR-008."""

import argparse
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from esquema import EVENTO

DIRECTORIO = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", default=str(DIRECTORIO / "datos_prueba" / "eventos_prueba.json"))
    parser.add_argument("--salida", default=str(DIRECTORIO / "datos_prueba" / "parquet" / "eventos"))
    args = parser.parse_args()

    spark = (
        SparkSession.builder.appName("preparar-datos-prueba")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    crudo = spark.read.option("multiLine", True).json(args.entrada)
    eventos = crudo.select(
        *[
            F.to_timestamp(F.col(c.name)).alias(c.name)
            if c.dataType.typeName() == "timestamp"
            else F.col(c.name).cast(c.dataType).alias(c.name)
            for c in EVENTO.fields
        ]
    ).withColumn("mes", F.date_format("ts", "yyyy-MM"))

    eventos.write.mode("overwrite").partitionBy("mes").parquet(args.salida)
    escritos = spark.read.parquet(args.salida)
    print(f"eventos escritos: {escritos.count()} en {args.salida}")
    spark.stop()


if __name__ == "__main__":
    main()
