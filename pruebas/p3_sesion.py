"""P3: recuperación del borrador, reinicio de Valkey con AOF y vencimiento del lock."""

import argparse
import json
import time
from uuid import uuid4

from comun import (
    ANOTACION_LIDAR,
    cliente,
    crear_proyecto_con_tareas,
    docker_compose,
    esperar_salud,
    guardar_evidencia,
)


def ahora_ms() -> int:
    return int(time.time() * 1000)


def caso_interrupcion(c) -> tuple[dict, dict]:
    proyecto_id, _ = crear_proyecto_con_tareas(c, 1, "p3-interrupcion")
    anotador = f"p3-a-{uuid4().hex[:6]}"
    t = c.post("/tareas/siguiente", json={"anotador_id": anotador, "proyecto_id": proyecto_id}).json()
    sesion = {"anotador_id": anotador, "tarea_id": t["tarea_id"], "token": t["token"]}

    ultimo = 0
    for secuencia in range(1, 4):
        c.put(
            f"/tareas/{t['tarea_id']}/borrador",
            json={"anotador_id": anotador, "token": t["token"], "contenido": {"secuencia": secuencia, "ts_cliente": ahora_ms()}},
        ).raise_for_status()
        ultimo = secuencia
        time.sleep(2)

    recuperado = c.post("/sesiones/recuperar", json={"anotador_id": anotador})
    cuerpo = recuperado.json()
    edad_s = (ahora_ms() - cuerpo["borrador"]["ts"]) / 1000
    sesion["secuencia"] = ultimo
    return {
        "codigo_recuperacion": recuperado.status_code,
        "secuencia_enviada": ultimo,
        "secuencia_recuperada": cuerpo["borrador"]["contenido"]["secuencia"],
        "antiguedad_borrador_s": round(edad_s, 2),
        "cumple": recuperado.status_code == 200
        and cuerpo["borrador"]["contenido"]["secuencia"] == ultimo
        and edad_s <= 5,
    }, sesion


def caso_reinicio_valkey(c, sesion: dict) -> dict:
    secuencia = sesion["secuencia"] + 1
    c.put(
        f"/tareas/{sesion['tarea_id']}/borrador",
        json={"anotador_id": sesion["anotador_id"], "token": sesion["token"],
              "contenido": {"secuencia": secuencia, "ts_cliente": ahora_ms()}},
    ).raise_for_status()
    time.sleep(2)

    salida_kill = docker_compose("kill", "valkey")
    salida_start = docker_compose("start", "valkey")
    restauracion = esperar_salud(c, "operativo")

    recuperado = c.post("/sesiones/recuperar", json={"anotador_id": sesion["anotador_id"]})
    cuerpo = recuperado.json() if recuperado.status_code == 200 else {}
    secuencia_recuperada = (cuerpo.get("borrador") or {}).get("contenido", {}).get("secuencia")
    envio = c.post(
        f"/tareas/{sesion['tarea_id']}/enviar",
        json={"anotador_id": sesion["anotador_id"], "token": sesion["token"], "anotacion": ANOTACION_LIDAR},
    )
    return {
        "acciones": {"kill": salida_kill, "start": salida_start},
        "restauracion": restauracion,
        "codigo_recuperacion": recuperado.status_code,
        "secuencia_antes_del_reinicio": secuencia,
        "secuencia_recuperada": secuencia_recuperada,
        "envio_tras_reinicio": envio.status_code,
        "cumple": recuperado.status_code == 200 and secuencia_recuperada == secuencia and envio.status_code == 200,
    }


def caso_lock_vencido(c, espera_s: int) -> dict:
    proyecto_id, _ = crear_proyecto_con_tareas(c, 1, "p3-lock-vencido")
    a, b = f"p3-a-{uuid4().hex[:6]}", f"p3-b-{uuid4().hex[:6]}"
    ta = c.post("/tareas/siguiente", json={"anotador_id": a, "proyecto_id": proyecto_id}).json()
    inmediato = c.post("/tareas/siguiente", json={"anotador_id": b, "proyecto_id": proyecto_id}).status_code

    time.sleep(espera_s)

    tb = c.post("/tareas/siguiente", json={"anotador_id": b, "proyecto_id": proyecto_id})
    cuerpo_b = tb.json() if tb.status_code == 200 else {}
    envio_a = c.post(
        f"/tareas/{ta['tarea_id']}/enviar",
        json={"anotador_id": a, "token": ta["token"], "anotacion": ANOTACION_LIDAR},
    ).status_code
    recuperar_a = c.post("/sesiones/recuperar", json={"anotador_id": a}).status_code
    envio_b = c.post(
        f"/tareas/{ta['tarea_id']}/enviar",
        json={"anotador_id": b, "token": cuerpo_b.get("token", ""), "anotacion": ANOTACION_LIDAR},
    ).status_code
    return {
        "espera_s": espera_s,
        "siguiente_b_con_lock_vigente": inmediato,
        "siguiente_b_tras_vencimiento": tb.status_code,
        "misma_tarea": cuerpo_b.get("tarea_id") == ta["tarea_id"],
        "envio_dueno_anterior": envio_a,
        "recuperar_dueno_anterior": recuperar_a,
        "envio_nuevo_dueno": envio_b,
        "cumple": inmediato == 204
        and tb.status_code == 200
        and cuerpo_b.get("tarea_id") == ta["tarea_id"]
        and envio_a == 409
        and recuperar_a == 409
        and envio_b == 200,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--espera-lock", type=int, default=125, help="segundos de espera para que venza el lock")
    parser.add_argument("--sin-reinicio", action="store_true", help="omite el reinicio de Valkey")
    args = parser.parse_args()

    with cliente() as c:
        interrupcion, sesion = caso_interrupcion(c)
        resultado = {"interrupcion": interrupcion}
        if not args.sin_reinicio:
            resultado["reinicio_valkey"] = caso_reinicio_valkey(c, sesion)
        resultado["lock_vencido"] = caso_lock_vencido(c, args.espera_lock)

    resultado["cumple"] = all(v["cumple"] for v in resultado.values())
    guardar_evidencia(
        "p3_sesion",
        "Recuperar borrador tras interrupción, conservarlo tras reiniciar Valkey y reasignar la tarea al vencer el lock",
        {"espera_lock_s": args.espera_lock, "reinicio_valkey": not args.sin_reinicio},
        resultado,
    )
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
