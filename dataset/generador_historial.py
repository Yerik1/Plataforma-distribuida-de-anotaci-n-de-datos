"""Genera el historial de eventos en Parquet para los 180 proyectos del catálogo (§9, ADR-013).

Simula el ciclo de vida de cada tarea (toma, anotación, revisión y, si hay rechazo, retrabajo)
con el esquema de ADR-008 y escribe los eventos particionados por mes. El catálogo se reconstruye
con la misma semilla del generador del catálogo, por lo que los identificadores coinciden con MongoDB.
"""

import argparse
import hashlib
import json
import math
import os
import random
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from generador_catalogo import Generador

TIEMPO = pa.timestamp("us", tz="UTC")
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

# Mediana de la duración de anotación por modalidad, en minutos (distribución lognormal).
DURACION_MEDIANA_MIN = {"texto": 12, "imagen": 20, "video": 45, "lidar": 70}
DISPERSION = 0.5
ESPERA_REVISION_H = 8
DURACION_REVISION_MIN = 20
ESPERA_RETRABAJO_H = 10
MOTIVOS = ["geometria_invalida", "etiqueta_fuera_taxonomia", "objeto_omitido", "instruccion_no_seguida"]
TIPOS = {
    "abierta": "tarea_abierta",
    "anotada": "tarea_anotada",
    "en_revision": "revision_iniciada",
    "aprobada": "tarea_aprobada",
    "rechazada": "tarea_rechazada",
}


class Historial:
    def __init__(self, args, catalogo: dict):
        self.args = args
        self.rng = random.Random(args.semilla_historial)
        self.proyectos = catalogo["proyectos"] + catalogo["proyectos_cerrados"]
        self.anotadores = [a for a in catalogo["anotadores"] if a["rol"] == "anotador"]
        self.revisores = [a for a in catalogo["anotadores"] if a["rol"] == "revisor"]
        self.fin = datetime.fromisoformat(args.fin).replace(tzinfo=timezone.utc)
        self.inicio = self.fin - timedelta(days=30 * args.meses)
        self.estadisticas = Counter()

    def nuevo_id(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def horas(self, media: float) -> timedelta:
        return timedelta(hours=self.rng.expovariate(1 / media))

    def tarea(self, columnas: dict) -> None:
        r = self.rng
        proyecto = r.choice(self.proyectos)
        tarea_id = self.nuevo_id()
        batch_id = f"historico-{proyecto['_id'][:8]}"
        base = {
            "tarea_id": tarea_id,
            "batch_id": batch_id,
            "proyecto_id": proyecto["_id"],
            "cliente_id": proyecto["cliente_id"],
            "modalidad": proyecto["modalidad"],
            "tipo_tarea": proyecto["tipo_tarea"],
            "sla_horas": proyecto["sla_horas"],
        }
        rango = (self.fin - timedelta(days=2) - self.inicio).total_seconds()
        momento = self.inicio + timedelta(seconds=r.uniform(0, rango))
        primera_toma = momento
        version = 0
        sin_revision = r.random() < self.args.sin_revision

        for ciclo in range(self.args.max_ciclos):
            anotador = r.choice(self.anotadores)
            toma = momento
            minutos = r.lognormvariate(math.log(DURACION_MEDIANA_MIN[proyecto["modalidad"]]), DISPERSION)
            anotada = toma + timedelta(minutes=minutos)
            pasos = [("abierta", toma, None), ("anotada", anotada, int(minutos * 60_000))]

            revisor = None
            motivo = None
            if not sin_revision:
                revisor = r.choice(self.revisores)
                en_revision = anotada + self.horas(ESPERA_REVISION_H)
                decision_ts = en_revision + timedelta(minutes=r.expovariate(1 / DURACION_REVISION_MIN))
                ultima = ciclo == self.args.max_ciclos - 1
                rechazada = not ultima and r.random() < self.args.probabilidad_rechazo
                decision = "rechazada" if rechazada else "aprobada"
                motivo = r.choice(MOTIVOS) if rechazada else None
                pasos += [("en_revision", en_revision, None), (decision, decision_ts, None)]

            for estado, ts, duracion in pasos:
                version += 1
                fila = base | {
                    "event_id": self.nuevo_id(),
                    "tipo_evento": TIPOS[estado],
                    "estado": estado,
                    "ts": ts,
                    "anotador_id": anotador["_id"],
                    "equipo_id": anotador["equipo_id"],
                    "revisor_id": revisor["_id"] if revisor and estado in ("en_revision", "aprobada", "rechazada") else None,
                    "version": version,
                    "ts_toma": toma,
                    "ts_primera_toma": primera_toma,
                    "duracion_anotacion_ms": duracion,
                    "motivo_rechazo": motivo if estado == "rechazada" else None,
                    "correlation_id": "historico",
                }
                for campo in ESQUEMA.names:
                    columnas[campo].append(fila.get(campo))
                self.estadisticas[f"filas_{estado}"] += 1

            if sin_revision:
                self.estadisticas["tareas_sin_revision"] += 1
                return
            if pasos[-1][0] == "aprobada":
                self.estadisticas["tareas_aprobadas"] += 1
                self.estadisticas["ciclos"] += ciclo + 1
                if (pasos[-1][1] - primera_toma) > timedelta(hours=proyecto["sla_horas"]):
                    self.estadisticas["tareas_incumplen_sla"] += 1
                return
            momento = pasos[-1][1] + self.horas(ESPERA_RETRABAJO_H)


def escribir(tabla: pa.Table, salida: Path, bloque: int) -> list[str]:
    meses = pc.strftime(tabla.column("ts"), format="%Y-%m")
    archivos = []
    for mes in sorted(set(meses.to_pylist())):
        parte = tabla.filter(pc.equal(meses, mes))
        destino = salida / f"mes={mes}" / f"part-hist-{bloque:03d}.parquet"
        temporal = salida.parent / "_tmp" / f"{destino.parent.name}-{destino.name}"
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(parte, temporal)
        os.replace(temporal, destino)
        archivos.append(f"{destino.parent.name}/{destino.name}")
    return archivos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salida", required=True, help="directorio eventos/ del conjunto")
    parser.add_argument("--tareas", type=int, default=100_000)
    parser.add_argument("--meses", type=int, default=12)
    parser.add_argument("--fin", default="2026-11-15", help="fecha final de la ventana del historial")
    parser.add_argument("--probabilidad-rechazo", type=float, default=0.52)
    parser.add_argument("--max-ciclos", type=int, default=6)
    parser.add_argument("--sin-revision", type=float, default=0.03, help="fracción de tareas anotadas sin revisión")
    parser.add_argument("--tareas-por-bloque", type=int, default=10_000)
    parser.add_argument("--semilla", type=int, default=2026, help="semilla del catálogo")
    parser.add_argument("--fecha-referencia", default="2026-11-01T00:00:00+00:00", help="referencia del catálogo")
    parser.add_argument("--semilla-historial", type=int, default=7)
    parser.add_argument("--evidencia", default=None)
    parser.add_argument("--limpiar", action="store_true", help="elimina los archivos históricos previos del conjunto")
    args = parser.parse_args()

    salida = Path(args.salida)
    previos = sorted(salida.glob("mes=*/part-hist-*.parquet"))
    if previos and not args.limpiar:
        print(f"{salida} ya contiene {len(previos)} archivos históricos; use --limpiar para regenerarlos")
        sys.exit(1)
    for archivo in previos:
        archivo.unlink()

    catalogo = Generador(args.semilla, datetime.fromisoformat(args.fecha_referencia)).generar()
    historial = Historial(args, catalogo)
    archivos, total = [], 0
    for bloque, inicio in enumerate(range(0, args.tareas, args.tareas_por_bloque)):
        columnas = {campo: [] for campo in ESQUEMA.names}
        for _ in range(min(args.tareas_por_bloque, args.tareas - inicio)):
            historial.tarea(columnas)
        tabla = pa.table(columnas, schema=ESQUEMA)
        total += tabla.num_rows
        archivos += escribir(tabla, salida, bloque)
        print(f"bloque {bloque}: {tabla.num_rows} eventos")

    e = historial.estadisticas
    revisadas = e["filas_aprobada"] + e["filas_rechazada"]
    resumen = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "comando": " ".join(sys.argv),
        "parametros": {k: v for k, v in vars(args).items() if k not in ("evidencia", "limpiar")},
        "tareas": args.tareas,
        "proyectos": len(historial.proyectos),
        "eventos": total,
        "eventos_por_estado": {k[6:]: v for k, v in e.items() if k.startswith("filas_")},
        "tareas_aprobadas": e["tareas_aprobadas"],
        "tareas_sin_revision": e["tareas_sin_revision"],
        "ciclos_promedio_hasta_aprobar": round(e["ciclos"] / max(e["tareas_aprobadas"], 1), 3),
        "proporcion_filas_rechazadas": round(e["filas_rechazada"] / max(revisadas, 1), 4),
        "porcentaje_incumple_sla": round(100 * e["tareas_incumplen_sla"] / max(e["tareas_aprobadas"], 1), 2),
        "archivos": len(archivos),
        "huella_archivos": hashlib.sha256("\n".join(archivos).encode()).hexdigest()[:16],
    }
    if args.evidencia:
        destino = Path(args.evidencia)
        destino.mkdir(parents=True, exist_ok=True)
        marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        (destino / f"dataset_historial_{marca}.json").write_text(json.dumps(resumen, indent=2), encoding="utf-8")
    print(json.dumps(resumen, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
