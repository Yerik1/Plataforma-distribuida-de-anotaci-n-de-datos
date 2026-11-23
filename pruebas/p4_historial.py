"""P4: escritura del datalake, publicación atómica, reproceso de un micro-lote, deduplicación y fila rechazada."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from comun import (
    ANOTACION_LIDAR,
    RAIZ,
    cliente,
    crear_proyecto_con_tareas,
    docker,
    guardar_evidencia,
    percentiles,
)

DATALAKE = RAIZ / "datalake"
EVENTOS = DATALAKE / "eventos"
FALLA = DATALAKE / "_control" / "fallar_tras_publicar"


def filas_de(event_ids: list[str]):
    if not EVENTOS.exists():
        return None
    return ds.dataset(EVENTOS, format="parquet", partitioning="hive").to_table(
        filter=pc.field("event_id").isin(event_ids)
    )


def esperar_eventos(event_ids: list[str], limite_s: float = 60) -> float | None:
    inicio = time.time()
    while time.time() - inicio < limite_s:
        tabla = filas_de(event_ids)
        if tabla is not None and set(tabla.column("event_id").to_pylist()) >= set(event_ids):
            return round(time.time() - inicio, 2)
        time.sleep(0.2)
    return None


def tomar_y_enviar(c, proyecto_id: str) -> tuple[str, str, float]:
    anotador = f"p4-{uuid4().hex[:8]}"
    t = c.post("/tareas/siguiente", json={"anotador_id": anotador, "proyecto_id": proyecto_id}).json()
    respuesta = c.post(
        f"/tareas/{t['tarea_id']}/enviar",
        json={"anotador_id": anotador, "token": t["token"], "anotacion": ANOTACION_LIDAR},
    )
    respuesta.raise_for_status()
    return t["tarea_id"], respuesta.json()["evento"]["event_id"], time.time()


def caso_frescura(c, muestras: int) -> dict:
    proyecto_id, _ = crear_proyecto_con_tareas(c, muestras, "p4-frescura")
    segundos = []
    for _ in range(muestras):
        _, event_id, _ = tomar_y_enviar(c, proyecto_id)
        segundos.append(esperar_eventos([event_id]))
    validos = [s * 1000 for s in segundos if s is not None]
    return {
        "muestras": muestras,
        "visibles": len(validos),
        "segundos_200_a_parquet": segundos,
        "latencia": percentiles(validos),
    }


def caso_rechazo(c) -> dict:
    proyecto_id, _ = crear_proyecto_con_tareas(c, 1, "p4-rechazo")
    tarea_id, _, _ = tomar_y_enviar(c, proyecto_id)
    revisor = f"p4-revisor-{uuid4().hex[:6]}"
    c.post(f"/tareas/{tarea_id}/revision", json={"revisor_id": revisor, "accion": "iniciar"}).raise_for_status()
    rechazo = c.post(
        f"/tareas/{tarea_id}/revision",
        json={"revisor_id": revisor, "accion": "rechazar", "motivo": "objeto_omitido"},
    )
    rechazo.raise_for_status()
    cuerpo = rechazo.json()
    event_id = cuerpo["evento"]["event_id"]
    esperar_eventos([event_id])
    fila = filas_de([event_id]).to_pylist()[0]
    retrabajo = c.post("/tareas/siguiente", json={"anotador_id": f"p4-{uuid4().hex[:8]}", "proyecto_id": proyecto_id})
    return {
        "estado_mongodb_tras_rechazo": cuerpo["tarea"]["estado"],
        "estado_fila_parquet": fila["estado"],
        "motivo_en_parquet": fila["motivo_rechazo"],
        "tarea_vuelve_a_ofrecerse": retrabajo.status_code == 200 and retrabajo.json()["tarea_id"] == tarea_id,
        "cumple": cuerpo["tarea"]["estado"] == "disponible" and fila["estado"] == "rechazada",
    }


def reinicios_historial() -> int:
    salida = docker("inspect", "--format", "{{.RestartCount}}", "proyecto2-historial-1")
    return int(salida) if salida.isdigit() else -1


def caso_reproceso(c, cantidad: int) -> dict:
    proyecto_id, _ = crear_proyecto_con_tareas(c, cantidad, "p4-reproceso")
    reinicios_antes = reinicios_historial()
    FALLA.parent.mkdir(parents=True, exist_ok=True)
    FALLA.write_text("1")
    event_ids = [tomar_y_enviar(c, proyecto_id)[1] for _ in range(cantidad)]

    inicio = time.time()
    while FALLA.exists() and time.time() - inicio < 60:
        time.sleep(0.5)
    segundos = esperar_eventos(event_ids, limite_s=120)
    tabla = filas_de(event_ids)
    archivos = sorted(
        Path(f).name
        for f in ds.dataset(EVENTOS, format="parquet", partitioning="hive").files
        if filas_de_archivo(f, event_ids) > 0
    )
    return {
        "eventos": cantidad,
        "falla_inyectada_consumida": not FALLA.exists(),
        "reinicios_historial": {"antes": reinicios_antes, "despues": reinicios_historial()},
        "segundos_hasta_visibles": segundos,
        "filas_encontradas": tabla.num_rows,
        "event_id_unicos": len(set(tabla.column("event_id").to_pylist())),
        "archivos_que_contienen_los_eventos": archivos,
        "cumple": segundos is not None and tabla.num_rows == cantidad,
    }


def filas_de_archivo(ruta: str, event_ids: list[str]) -> int:
    tabla = pq.read_table(ruta, columns=["event_id"])
    return pc.sum(pc.is_in(tabla.column("event_id"), value_set=pa.array(event_ids))).as_py() or 0


def integridad() -> dict:
    archivos = list(EVENTOS.rglob("*.parquet"))
    ilegibles = []
    for archivo in archivos:
        try:
            pq.read_metadata(archivo)
        except Exception as exc:
            ilegibles.append(f"{archivo.name}: {exc}")
    temporales = list((DATALAKE / "_tmp").glob("*")) if (DATALAKE / "_tmp").exists() else []
    tabla = ds.dataset(EVENTOS, format="parquet", partitioning="hive").to_table(columns=["event_id"])
    unicos = pc.count_distinct(tabla.column("event_id")).as_py()
    return {
        "archivos": len(archivos),
        "particiones": sorted(p.name for p in EVENTOS.iterdir() if p.is_dir()),
        "archivos_ilegibles": ilegibles,
        "archivos_en_tmp": [t.name for t in temporales],
        "filas": tabla.num_rows,
        "event_id_unicos": unicos,
        "duplicados_que_spark_elimina": tabla.num_rows - unicos,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--muestras", type=int, default=10)
    parser.add_argument("--sin-reproceso", action="store_true", help="omite la falla inyectada en historial")
    args = parser.parse_args()

    with cliente() as c:
        resultado = {"frescura": caso_frescura(c, args.muestras), "rechazo": caso_rechazo(c)}
        if not args.sin_reproceso:
            resultado["reproceso"] = caso_reproceso(c, 5)
    resultado["integridad"] = integridad()
    resultado["cumple"] = (
        resultado["frescura"]["visibles"] == args.muestras
        and resultado["rechazo"]["cumple"]
        and resultado.get("reproceso", {"cumple": True})["cumple"]
        and not resultado["integridad"]["archivos_ilegibles"]
    )
    guardar_evidencia(
        "p4_historial",
        "Publicación atómica en Parquet, reproceso de un micro-lote, deduplicación y fila rechazada",
        {"muestras": args.muestras, "reproceso": not args.sin_reproceso},
        resultado,
    )
    print(json.dumps({k: v for k, v in resultado.items() if k != "integridad"} | {"integridad": {k: v for k, v in resultado["integridad"].items() if k != "particiones"}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
