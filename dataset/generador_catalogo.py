"""Genera y carga en MongoDB el catálogo del registro con los volúmenes de §9."""

import argparse
import hashlib
import json
import random
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

CLIENTES = 60
PROYECTOS_ACTIVOS = 120
PROYECTOS_CERRADOS = 60
BATCHES_POR_PROYECTO = 5
TAREAS_POR_BATCH = 100
EQUIPOS = 30
ANOTADORES_POR_EQUIPO = 10
REVISORES_POR_EQUIPO = 1
SLA_HORAS = 48

# Proporción 30/30/20/20 aplicada a los proyectos; cada proyecto tiene una sola modalidad.
PROPORCION_MODALIDAD = {"texto": 0.30, "imagen": 0.30, "video": 0.20, "lidar": 0.20}

TAXONOMIAS = {
    "texto": [
        ("texto#persona", "Nombre propio de una persona."),
        ("texto#organizacion", "Empresa, institución o agrupación."),
        ("texto#lugar", "País, ciudad o dirección."),
        ("texto#fecha", "Fecha u hora explícita."),
    ],
    "imagen": [
        ("imagen#peaton", "Persona que se desplaza a pie."),
        ("imagen#vehiculo", "Automóvil, camión, autobús o motocicleta."),
        ("imagen#ciclista", "Bicicleta o patineta con su conductor."),
        ("imagen#signal", "Señal de tránsito vertical o semáforo."),
    ],
    "video": [
        ("video#peaton", "Persona que se desplaza a pie."),
        ("video#vehiculo", "Automóvil, camión, autobús o motocicleta."),
        ("video#ciclista", "Bicicleta o patineta con su conductor."),
    ],
    "lidar": [
        ("lidar#peaton", "Persona que se desplaza a pie."),
        ("lidar#vehiculo", "Automóvil, camión, autobús o motocicleta."),
        ("lidar#ciclista", "Bicicleta o patineta con su conductor; un skater es ciclista."),
        ("lidar#signal", "Señal de tránsito vertical o semáforo."),
    ],
}

ARCHIVO_POR_MODALIDAD = {
    "texto": {"mime": "text/plain", "extension": ".txt", "bytes": (2_000, 200_000)},
    "imagen": {"mime": "image/jpeg", "extension": ".jpg", "bytes": (200_000, 5_000_000)},
    "video": {"mime": "video/mp4", "extension": ".mp4", "bytes": (5_000_000, 200_000_000)},
    "lidar": {"mime": "application/vnd.las", "extension": ".las", "bytes": (10_000_000, 300_000_000)},
}

COLECCIONES = ("clientes", "proyectos", "batches", "tareas", "anotadores")


class Generador:
    def __init__(self, semilla: int, referencia: datetime):
        self.rng = random.Random(semilla)
        self.referencia = referencia

    def nuevo_id(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def modalidades(self, cantidad: int) -> list[str]:
        lista = []
        for modalidad, proporcion in PROPORCION_MODALIDAD.items():
            lista += [modalidad] * round(cantidad * proporcion)
        self.rng.shuffle(lista)
        return lista

    def geometria(self, modalidad: str, indice: int) -> str:
        if modalidad == "imagen":
            return "bbox" if indice % 2 == 0 else "poligono"
        return {"texto": "span", "video": "bbox_video", "lidar": "cuboide_3d"}[modalidad]

    def meta(self, modalidad: str) -> dict:
        r = self.rng
        if modalidad == "texto":
            return {"caracteres": r.randint(500, 50_000), "idioma": "es"}
        if modalidad == "imagen":
            return {"ancho": r.choice([1280, 1920, 3840]), "alto": r.choice([720, 1080, 2160]), "valor_min": 0, "valor_max": 255}
        if modalidad == "video":
            return {"duracion_s": r.randint(10, 600), "fps": r.choice([24, 30, 60]), "ancho": 1920, "alto": 1080}
        x = round(r.uniform(40, 120), 2)
        return {
            "puntos": r.randint(200_000, 3_000_000),
            "x_min": -x, "x_max": x,
            "y_min": -x, "y_max": x,
            "z_min": round(r.uniform(-3, -1), 2), "z_max": round(r.uniform(5, 15), 2),
        }

    def archivo(self, proyecto_id: str, tarea_id: str, modalidad: str) -> dict:
        datos = ARCHIVO_POR_MODALIDAD[modalidad]
        uri = f"s3://anotacion-datos/{proyecto_id}/{tarea_id}{datos['extension']}"
        return {
            "uri": uri,
            "sha256": hashlib.sha256(uri.encode()).hexdigest(),
            "bytes": self.rng.randint(*datos["bytes"]),
            "mime": datos["mime"],
            "meta": self.meta(modalidad),
        }

    def generar(self) -> dict:
        ref = self.referencia
        clientes = [
            {"_id": self.nuevo_id(), "nombre": f"Cliente {i + 1:03d}", "creado_en": ref}
            for i in range(CLIENTES)
        ]

        anotadores = []
        for e in range(EQUIPOS):
            equipo_id = f"equipo-{e + 1:02d}"
            for m in range(ANOTADORES_POR_EQUIPO):
                anotadores.append({
                    "_id": self.nuevo_id(),
                    "nombre": f"Anotador {e * ANOTADORES_POR_EQUIPO + m + 1:03d}",
                    "equipo_id": equipo_id,
                    "rol": "revisor" if m < REVISORES_POR_EQUIPO else "anotador",
                })

        total_proyectos = PROYECTOS_ACTIVOS + PROYECTOS_CERRADOS
        modalidades = self.modalidades(PROYECTOS_ACTIVOS) + self.modalidades(PROYECTOS_CERRADOS)
        proyectos, cerrados = [], []
        for i in range(total_proyectos):
            modalidad = modalidades[i]
            proyecto = {
                "_id": self.nuevo_id(),
                "cliente_id": clientes[i % CLIENTES]["_id"],
                "nombre": f"Proyecto {i + 1:03d}",
                "modalidad": modalidad,
                "tipo_tarea": self.geometria(modalidad, i),
                "taxonomia": [{"etiqueta": e, "instruccion": ins} for e, ins in TAXONOMIAS[modalidad]],
                "sla_horas": SLA_HORAS,
                "creado_en": ref,
            }
            if i < PROYECTOS_ACTIVOS:
                proyectos.append(proyecto | {"estado": "activo"})
            else:
                cerrados.append(proyecto | {"estado": "cerrado"})

        batches, tareas = [], []
        for proyecto in proyectos:
            for _ in range(BATCHES_POR_PROYECTO):
                batch_id = self.nuevo_id()
                batches.append({
                    "_id": batch_id,
                    "proyecto_id": proyecto["_id"],
                    "cliente_id": proyecto["cliente_id"],
                    "cantidad_tareas": TAREAS_POR_BATCH,
                    "creado_en": ref,
                })
                for _ in range(TAREAS_POR_BATCH):
                    tarea_id = self.nuevo_id()
                    tareas.append({
                        "_id": tarea_id,
                        "proyecto_id": proyecto["_id"],
                        "batch_id": batch_id,
                        "cliente_id": proyecto["cliente_id"],
                        "sla_horas": proyecto["sla_horas"],
                        "modalidad": proyecto["modalidad"],
                        "tipo_tarea": proyecto["tipo_tarea"],
                        "prioridad": self.rng.randint(1, 5),
                        "archivo": self.archivo(proyecto["_id"], tarea_id, proyecto["modalidad"]),
                        "estado": "disponible",
                        "version": 0,
                        "asignacion": None,
                        "primera_toma_en": None,
                        "anotacion": None,
                        "ultima_revision": None,
                        "ultimo_evento": None,
                        "creada_en": ref,
                        "actualizada_en": ref,
                    })

        return {
            "clientes": clientes,
            "proyectos": proyectos,
            "batches": batches,
            "tareas": tareas,
            "anotadores": anotadores,
            "proyectos_cerrados": cerrados,
        }


def insertar(db, coleccion: str, documentos: list[dict], bloque: int = 5_000) -> None:
    for inicio in range(0, len(documentos), bloque):
        db[coleccion].insert_many(documentos[inicio:inicio + bloque], ordered=False)


def a_json(valor):
    if isinstance(valor, datetime):
        return valor.isoformat()
    raise TypeError(type(valor))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--semilla", type=int, default=2026)
    parser.add_argument("--fecha-referencia", default="2026-11-01T00:00:00+00:00")
    parser.add_argument("--salida", default="salida")
    parser.add_argument("--evidencia", default=None)
    parser.add_argument("--limpiar", action="store_true", help="elimina los documentos existentes antes de cargar")
    args = parser.parse_args()

    referencia = datetime.fromisoformat(args.fecha_referencia)
    db = MongoClient(args.mongo_uri, w="majority", tz_aware=True)["plataforma"]

    existentes = {c: db[c].estimated_document_count() for c in COLECCIONES}
    if any(existentes.values()) and not args.limpiar:
        print(f"la base plataforma ya contiene documentos: {existentes}; use --limpiar para recargar")
        sys.exit(1)
    if args.limpiar:
        for coleccion in COLECCIONES:
            db[coleccion].delete_many({})

    datos = Generador(args.semilla, referencia).generar()
    for coleccion in COLECCIONES:
        insertar(db, coleccion, datos[coleccion])

    conteos = {c: db[c].count_documents({}) for c in COLECCIONES}
    resumen = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "semilla": args.semilla,
        "fecha_referencia": referencia.isoformat(),
        "comando": " ".join(sys.argv),
        "conteos_mongodb": conteos,
        "proyectos_solo_historial": len(datos["proyectos_cerrados"]),
        "tareas_por_modalidad": dict(Counter(t["modalidad"] for t in datos["tareas"])),
        "tareas_por_tipo": dict(Counter(t["tipo_tarea"] for t in datos["tareas"])),
        "anotadores_por_rol": dict(Counter(a["rol"] for a in datos["anotadores"])),
        "equipos": len({a["equipo_id"] for a in datos["anotadores"]}),
    }

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "proyectos_cerrados.json").write_text(
        json.dumps(datos["proyectos_cerrados"], default=a_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    simulacion = {
        "proyectos": [
            {
                "proyecto_id": p["_id"],
                "modalidad": p["modalidad"],
                "tipo_tarea": p["tipo_tarea"],
                "etiquetas": [e["etiqueta"] for e in p["taxonomia"]],
            }
            for p in datos["proyectos"]
        ],
        "anotadores": [a["_id"] for a in datos["anotadores"] if a["rol"] == "anotador"],
        "revisores": [a["_id"] for a in datos["anotadores"] if a["rol"] == "revisor"],
    }
    (salida / "simulacion.json").write_text(json.dumps(simulacion, indent=2), encoding="utf-8")
    (salida / "resumen_catalogo.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.evidencia:
        destino = Path(args.evidencia)
        destino.mkdir(parents=True, exist_ok=True)
        marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        (destino / f"dataset_catalogo_{marca}.json").write_text(
            json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(json.dumps(resumen, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
