"""P1: rutas del gateway, exposición de puertos y /salud en estados operativo, degradado y caído."""

import argparse
import json
import socket
from uuid import uuid4

from comun import (
    ANOTACION_LIDAR,
    cliente,
    crear_proyecto_con_tareas,
    docker,
    docker_compose,
    esperar_salud,
    guardar_evidencia,
)

PUERTOS_HOST = {"gateway": 8000, "mongodb": 27017, "valkey": 6379}


def inspeccionar_red(nombre: str):
    salida = docker("network", "inspect", nombre)
    try:
        return json.loads(salida)
    except json.JSONDecodeError:
        return salida


def puerto_abierto(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def recorrido_rutas(c) -> list[dict]:
    registros = []

    def registrar(paso: str, respuesta, esperado: int) -> dict:
        cuerpo = respuesta.json() if respuesta.content else None
        registros.append({"paso": paso, "codigo": respuesta.status_code, "esperado": esperado,
                          "correcto": respuesta.status_code == esperado})
        return cuerpo or {}

    proyecto_id, _ = crear_proyecto_con_tareas(c, 1, "p1-rutas")
    a, b, d, revisor = (f"p1-{n}-{uuid4().hex[:6]}" for n in ("a", "b", "c", "revisor"))

    t = registrar("siguiente anotador A", c.post("/tareas/siguiente", json={"anotador_id": a, "proyecto_id": proyecto_id}), 200)
    tarea_id, token = t["tarea_id"], t["token"]
    registrar("borrador", c.put(f"/tareas/{tarea_id}/borrador", json={"anotador_id": a, "token": token, "contenido": {"paso": 1}}), 200)
    registrar("recuperar sesión", c.post("/sesiones/recuperar", json={"anotador_id": a}), 200)
    registrar("recuperar sin sesión", c.post("/sesiones/recuperar", json={"anotador_id": f"p1-x-{uuid4().hex[:6]}"}), 404)
    registrar("enviar", c.post(f"/tareas/{tarea_id}/enviar", json={"anotador_id": a, "token": token, "anotacion": ANOTACION_LIDAR}), 200)
    registrar("segundo envío", c.post(f"/tareas/{tarea_id}/enviar", json={"anotador_id": a, "token": token, "anotacion": ANOTACION_LIDAR}), 409)
    registrar("iniciar revisión", c.post(f"/tareas/{tarea_id}/revision", json={"revisor_id": revisor, "accion": "iniciar"}), 200)
    registrar("rechazo sin código", c.post(f"/tareas/{tarea_id}/revision", json={"revisor_id": revisor, "accion": "rechazar"}), 400)
    registrar("rechazo con código", c.post(f"/tareas/{tarea_id}/revision", json={"revisor_id": revisor, "accion": "rechazar", "motivo": "instruccion_no_seguida"}), 200)

    t = registrar("siguiente anotador B (retrabajo)", c.post("/tareas/siguiente", json={"anotador_id": b, "proyecto_id": proyecto_id}), 200)
    registrar("liberar", c.post(f"/tareas/{tarea_id}/liberar", json={"anotador_id": b, "token": t["token"]}), 200)

    t = registrar("siguiente anotador C", c.post("/tareas/siguiente", json={"anotador_id": d, "proyecto_id": proyecto_id}), 200)
    registrar("enviar C", c.post(f"/tareas/{tarea_id}/enviar", json={"anotador_id": d, "token": t["token"], "anotacion": ANOTACION_LIDAR}), 200)
    registrar("iniciar revisión C", c.post(f"/tareas/{tarea_id}/revision", json={"revisor_id": revisor, "accion": "iniciar"}), 200)
    registrar("aprobar", c.post(f"/tareas/{tarea_id}/revision", json={"revisor_id": revisor, "accion": "aprobar"}), 200)
    exportacion = registrar("exportar", c.get(f"/proyectos/{proyecto_id}/exportar"), 200)
    registros[-1]["tareas_exportadas"] = len(exportacion.get("tareas", []))
    registrar("siguiente sin tareas", c.post("/tareas/siguiente", json={"anotador_id": f"p1-z-{uuid4().hex[:6]}", "proyecto_id": proyecto_id}), 204)
    return registros


def escenarios_salud(c) -> list[dict]:
    resultados = [{"escenario": "normal", **esperar_salud(c, "operativo")}]

    docker_compose("stop", "mongo3")
    resultados.append({"escenario": "mongo3 detenido", **esperar_salud(c, "degradado")})
    docker_compose("start", "mongo3")
    resultados.append({"escenario": "mongo3 restaurado", **esperar_salud(c, "operativo")})

    docker_compose("stop", "sesion")
    resultados.append({"escenario": "servicio de sesión detenido", **esperar_salud(c, "caido")})
    docker_compose("start", "sesion")
    resultados.append({"escenario": "sesión restaurada", **esperar_salud(c, "operativo")})

    docker_compose("stop", "valkey")
    resultados.append({"escenario": "valkey detenido", **esperar_salud(c, "caido")})
    docker_compose("start", "valkey")
    resultados.append({"escenario": "valkey restaurado", **esperar_salud(c, "operativo")})
    return resultados


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-fallas", action="store_true", help="omite los escenarios que detienen contenedores")
    args = parser.parse_args()

    with cliente() as c:
        puertos = {nombre: puerto_abierto(p) for nombre, p in PUERTOS_HOST.items()}
        rutas = recorrido_rutas(c)
        salud = [{"escenario": "normal", **esperar_salud(c, "operativo")}] if args.sin_fallas else escenarios_salud(c)

    resultado = {
        "puertos_host": puertos,
        "solo_gateway_expuesto": puertos["gateway"] and not puertos["mongodb"] and not puertos["valkey"],
        "rutas": rutas,
        "rutas_correctas": all(r["correcto"] for r in rutas),
        "salud": salud,
        "docker_ps": docker("ps", "--format", "{{.Names}}\t{{.Ports}}"),
        "redes": {red: inspeccionar_red(f"proyecto2_{red}") for red in ("publica", "interna")},
    }
    guardar_evidencia(
        "p1_api_salud",
        "Verificar rutas del gateway, exposición de puertos y /salud por capa",
        {"escenarios_de_falla": not args.sin_fallas},
        resultado,
    )
    print(json.dumps({k: resultado[k] for k in ("puertos_host", "solo_gateway_expuesto", "rutas_correctas")}, indent=2))


if __name__ == "__main__":
    main()
