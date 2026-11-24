"""Usuarios virtuales para P6. Solo usan las rutas HTTP del gateway (§3).

Nueve de cada diez usuarios son anotadores y uno es revisor, la misma proporción del catálogo (§9).
Los identificadores de proyectos, anotadores y revisores se leen de dataset/salida/simulacion.json.
"""

import itertools
import json
import os
import queue
import random
import time
from pathlib import Path

from locust import HttpUser, between, task

RAIZ = Path(__file__).resolve().parents[2]
CATALOGO = json.loads(Path(os.getenv("CATALOGO", RAIZ / "dataset" / "salida" / "simulacion.json")).read_text(encoding="utf-8"))
PROYECTOS = CATALOGO["proyectos"]
ANOTADORES = itertools.cycle(CATALOGO["anotadores"])
REVISORES = itertools.cycle(CATALOGO["revisores"])
MOTIVOS = ["geometria_invalida", "etiqueta_fuera_taxonomia", "objeto_omitido", "instruccion_no_seguida"]
BORRADORES = int(os.getenv("BORRADORES", "1"))
ANOTADAS: queue.Queue = queue.Queue()


def anotacion(proyecto: dict) -> dict:
    return {
        "etiqueta": random.choice(proyecto["etiquetas"]),
        "geometria": {"tipo": proyecto["tipo_tarea"], "valores": [round(random.random(), 3) for _ in range(6)]},
    }


class Anotador(HttpUser):
    weight = 9
    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        self.anotador_id = next(ANOTADORES)

    @task
    def anotar(self) -> None:
        proyecto = random.choice(PROYECTOS)
        with self.client.post(
            "/tareas/siguiente",
            json={"anotador_id": self.anotador_id, "proyecto_id": proyecto["proyecto_id"]},
            name="/tareas/siguiente",
            catch_response=True,
        ) as respuesta:
            if respuesta.status_code == 204:
                respuesta.success()
                return
            if respuesta.status_code != 200:
                respuesta.failure(f"HTTP {respuesta.status_code}")
                return
            tarea = respuesta.json()

        for paso in range(BORRADORES):
            self.client.put(
                f"/tareas/{tarea['tarea_id']}/borrador",
                json={"anotador_id": self.anotador_id, "token": tarea["token"], "contenido": {"paso": paso}},
                name="/tareas/[id]/borrador",
            )
            time.sleep(2)

        envio = self.client.post(
            f"/tareas/{tarea['tarea_id']}/enviar",
            json={"anotador_id": self.anotador_id, "token": tarea["token"], "anotacion": anotacion(proyecto)},
            name="/tareas/[id]/enviar",
        )
        if envio.status_code == 200:
            ANOTADAS.put(tarea["tarea_id"])


class Revisor(HttpUser):
    weight = 1
    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        self.revisor_id = next(REVISORES)

    @task
    def revisar(self) -> None:
        try:
            tarea_id = ANOTADAS.get_nowait()
        except queue.Empty:
            time.sleep(1)
            return
        inicio = self.client.post(
            f"/tareas/{tarea_id}/revision",
            json={"revisor_id": self.revisor_id, "accion": "iniciar"},
            name="/tareas/[id]/revision iniciar",
        )
        if inicio.status_code != 200:
            return
        if random.random() < 0.7:
            cuerpo, nombre = {"revisor_id": self.revisor_id, "accion": "aprobar"}, "/tareas/[id]/revision aprobar"
        else:
            cuerpo = {"revisor_id": self.revisor_id, "accion": "rechazar", "motivo": random.choice(MOTIVOS)}
            nombre = "/tareas/[id]/revision rechazar"
        self.client.post(f"/tareas/{tarea_id}/revision", json=cuerpo, name=nombre)
