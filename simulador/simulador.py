"""Simulador de anotadores y revisores. Se comunica solo con el gateway por HTTP (§3).

Cada anotador pide la siguiente tarea, envía un borrador cada 2 segundos (§5) y luego la anotación.
Cada revisor toma tareas anotadas, inicia la revisión y la aprueba o rechaza con un código de motivo.
Los proyectos y anotadores se leen del archivo simulacion.json que produce el generador del catálogo.
"""

import argparse
import json
import queue
import random
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

MOTIVOS = ["geometria_invalida", "etiqueta_fuera_taxonomia", "objeto_omitido", "instruccion_no_seguida"]
GEOMETRIAS = {
    "span": lambda r: {"tipo": "span", "inicio": (i := r.randint(0, 500)), "fin": i + r.randint(1, 40)},
    "bbox": lambda r: {"tipo": "bbox", "x": r.randint(0, 1800), "y": r.randint(0, 1000), "ancho": r.randint(10, 300), "alto": r.randint(10, 300)},
    "poligono": lambda r: {"tipo": "poligono", "puntos": [[r.randint(0, 1900), r.randint(0, 1000)] for _ in range(r.randint(3, 8))]},
    "bbox_video": lambda r: {"tipo": "bbox_video", "cuadro": r.randint(0, 3000), "x": r.randint(0, 1800), "y": r.randint(0, 1000), "ancho": 120, "alto": 90},
    "cuboide_3d": lambda r: {"tipo": "cuboide_3d", "centro": [round(r.uniform(-40, 40), 2), round(r.uniform(-40, 40), 2), round(r.uniform(-1, 3), 2)], "dimensiones": [round(r.uniform(0.5, 5), 2), round(r.uniform(0.5, 2.5), 2), round(r.uniform(1, 3), 2)], "yaw": round(r.uniform(-3.14, 3.14), 2)},
}


class Simulacion:
    def __init__(self, args):
        self.args = args
        catalogo = json.loads(Path(args.catalogo).read_text(encoding="utf-8"))
        self.proyectos = catalogo["proyectos"][: args.proyectos] if args.proyectos else catalogo["proyectos"]
        self.anotadores = catalogo["anotadores"][: args.anotadores]
        self.revisores = catalogo["revisores"][: args.revisores]
        self.anotadas: queue.Queue = queue.Queue()
        self.fin = time.monotonic() + args.duracion
        self.conteo = Counter()
        self.bloqueo = threading.Lock()

    def registrar(self, operacion: str, codigo: int) -> None:
        with self.bloqueo:
            self.conteo[f"{operacion} {codigo}"] += 1

    def activa(self) -> bool:
        return time.monotonic() < self.fin

    def anotador(self, anotador_id: str, semilla: int) -> None:
        r = random.Random(semilla)
        with httpx.Client(base_url=self.args.gateway, timeout=30) as c:
            while self.activa():
                proyecto = r.choice(self.proyectos)
                resp = c.post("/tareas/siguiente", json={"anotador_id": anotador_id, "proyecto_id": proyecto["proyecto_id"]})
                self.registrar("siguiente", resp.status_code)
                if resp.status_code != 200:
                    time.sleep(1)
                    continue
                tarea = resp.json()
                for paso in range(self.args.borradores):
                    borrador = c.put(
                        f"/tareas/{tarea['tarea_id']}/borrador",
                        json={"anotador_id": anotador_id, "token": tarea["token"], "contenido": {"paso": paso}},
                    )
                    self.registrar("borrador", borrador.status_code)
                    time.sleep(2)
                anotacion = {"etiqueta": r.choice(proyecto["etiquetas"]), "geometria": GEOMETRIAS[proyecto["tipo_tarea"]](r)}
                for intento in range(self.args.reintentos_envio + 1):
                    envio = c.post(
                        f"/tareas/{tarea['tarea_id']}/enviar",
                        json={"anotador_id": anotador_id, "token": tarea["token"], "anotacion": anotacion},
                    )
                    self.registrar("enviar", envio.status_code)
                    if envio.status_code != 503:
                        break
                    time.sleep(2)
                if envio.status_code == 200:
                    self.anotadas.put(tarea["tarea_id"])

    def revisor(self, revisor_id: str, semilla: int) -> None:
        r = random.Random(semilla)
        with httpx.Client(base_url=self.args.gateway, timeout=30) as c:
            while self.activa():
                try:
                    tarea_id = self.anotadas.get(timeout=1)
                except queue.Empty:
                    continue
                inicio = c.post(f"/tareas/{tarea_id}/revision", json={"revisor_id": revisor_id, "accion": "iniciar"})
                self.registrar("revision_iniciar", inicio.status_code)
                if inicio.status_code != 200:
                    continue
                time.sleep(r.uniform(0.2, 1.0))
                if r.random() < self.args.probabilidad_aprobar:
                    decision = {"revisor_id": revisor_id, "accion": "aprobar"}
                else:
                    decision = {"revisor_id": revisor_id, "accion": "rechazar", "motivo": r.choice(MOTIVOS)}
                resp = c.post(f"/tareas/{tarea_id}/revision", json=decision)
                self.registrar(f"revision_{decision['accion']}", resp.status_code)

    def ejecutar(self) -> dict:
        hilos = [threading.Thread(target=self.anotador, args=(a, i)) for i, a in enumerate(self.anotadores)]
        hilos += [threading.Thread(target=self.revisor, args=(rv, 10_000 + i)) for i, rv in enumerate(self.revisores)]
        inicio = time.time()
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        return {
            "fecha_utc": datetime.now(timezone.utc).isoformat(),
            "configuracion": {k: v for k, v in vars(self.args).items() if k != "evidencia"},
            "segundos": round(time.time() - inicio, 1),
            "operaciones": dict(sorted(self.conteo.items())),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway", default="http://localhost:8000")
    parser.add_argument("--catalogo", default="dataset/salida/simulacion.json")
    parser.add_argument("--anotadores", type=int, default=10)
    parser.add_argument("--revisores", type=int, default=2)
    parser.add_argument("--proyectos", type=int, default=5, help="cantidad de proyectos usados; 0 usa todos")
    parser.add_argument("--duracion", type=int, default=60, help="segundos de simulación")
    parser.add_argument("--borradores", type=int, default=2, help="borradores por tarea, uno cada 2 s")
    parser.add_argument("--probabilidad-aprobar", type=float, default=0.7)
    parser.add_argument("--reintentos-envio", type=int, default=3, help="reenvíos tras un 503")
    parser.add_argument("--evidencia", default=None)
    args = parser.parse_args()

    resultado = Simulacion(args).ejecutar()
    if args.evidencia:
        destino = Path(args.evidencia)
        destino.mkdir(parents=True, exist_ok=True)
        marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        (destino / f"simulacion_{marca}.json").write_text(json.dumps(resultado, indent=2), encoding="utf-8")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
