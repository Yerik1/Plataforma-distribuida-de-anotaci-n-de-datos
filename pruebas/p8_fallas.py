"""P8: fallas de MongoDB, reinicio de Valkey, sesión interrumpida y conciliación; RTO y RPO (§10).

Cada escenario restaura el entorno al terminar y registra las acciones de recuperación.
Requiere el sistema completo levantado con docker compose y el gateway en localhost:8000.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from comun import (
    ANOTACION_LIDAR,
    cliente,
    crear_proyecto_con_tareas,
    docker_compose,
    esperar_salud,
    guardar_evidencia,
)
from p4_historial import esperar_eventos, filas_de

MIEMBROS = ["mongo1", "mongo2", "mongo3"]


def replica(c) -> dict:
    try:
        return c.get("/salud").json().get("capas", {}).get("registro", {}).get("replica") or {}
    except Exception:
        return {}


def primario(c, excluir: str | None = None) -> str | None:
    """Pregunta el primario a MongoDB. /salud es un caché que el gateway refresca cada pocos segundos y,
    justo después de un cambio en la réplica, puede nombrar a un nodo que ya no es primario."""
    for nodo in MIEMBROS:
        if nodo == excluir:
            continue
        salida = docker_compose("exec", "-T", nodo, "mongosh", "--quiet", "--eval", "db.hello().primary")
        nombre = salida.strip().splitlines()[-1] if salida.strip() else ""
        if nombre.startswith("mongo") and ":" in nombre:
            return nombre.split(":")[0]
    return None


def esperar_primario_distinto(c, viejo: str, limite_s: float = 60) -> str | None:
    inicio = time.time()
    while time.time() - inicio < limite_s:
        nuevo = primario(c, excluir=viejo)
        if nuevo and nuevo != viejo:
            return nuevo
        time.sleep(1)
    return None


def tomar(c, proyecto_id: str, cantidad: int) -> list[dict]:
    tomadas = []
    for _ in range(cantidad):
        anotador = f"p8-{uuid4().hex[:8]}"
        t = c.post("/tareas/siguiente", json={"anotador_id": anotador, "proyecto_id": proyecto_id}).json()
        tomadas.append({"tarea_id": t["tarea_id"], "token": t["token"], "anotador_id": anotador})
    return tomadas


def enviar(c, t: dict) -> tuple[int, str | None]:
    try:
        r = c.post(
            f"/tareas/{t['tarea_id']}/enviar",
            json={"anotador_id": t["anotador_id"], "token": t["token"], "anotacion": ANOTACION_LIDAR},
        )
    except Exception:
        return 0, None
    event_id = r.json()["evento"]["event_id"] if r.status_code == 200 else None
    return r.status_code, event_id


def una_vez_en_mongodb_y_parquet(c, tomadas: list[dict], event_ids: list[str]) -> dict:
    """Un segundo envío responde 409 (la anotación quedó en MongoDB) y cada evento aparece una vez."""
    segundos = [enviar(c, t)[0] for t in tomadas]
    esperar_eventos(event_ids, limite_s=60)
    tabla = filas_de(event_ids)
    ids = tabla.column("event_id").to_pylist() if tabla is not None else []
    return {
        "segundo_envio": segundos,
        "eventos_en_parquet": len(set(ids)),
        "eventos_esperados": len(event_ids),
        "cumple": all(s == 409 for s in segundos) and set(ids) == set(event_ids),
    }


def secundario_caido(c) -> dict:
    proyecto_id, _ = crear_proyecto_con_tareas(c, 5, "p8-secundario")
    tomadas = tomar(c, proyecto_id, 5)
    actual = primario(c)
    secundario = next(m for m in MIEMBROS if m != actual)
    acciones = [docker_compose("stop", secundario)]
    salud = esperar_salud(c, "degradado")
    resultados = [enviar(c, t) for t in tomadas]
    inicio = time.time()
    acciones.append(docker_compose("start", secundario))
    restauracion = esperar_salud(c, "operativo")
    verificacion = una_vez_en_mongodb_y_parquet(c, tomadas, [e for _, e in resultados if e])
    return {
        "nodo_detenido": secundario,
        "salud_con_falla": salud["estado"],
        "codigos_envio": [r[0] for r in resultados],
        "rto_reincorporacion_s": round(time.time() - inicio, 1) if restauracion["segundos"] is not None else None,
        "verificacion": verificacion,
        "acciones": acciones,
        "cumple": all(r[0] == 200 for r in resultados) and verificacion["cumple"],
    }


def primario_caido(c) -> dict:
    proyecto_id, _ = crear_proyecto_con_tareas(c, 10, "p8-primario")
    tomadas = tomar(c, proyecto_id, 10)
    antes = [enviar(c, t) for t in tomadas[:5]]
    viejo = primario(c)
    acciones = [docker_compose("stop", viejo)]
    caida = time.time()

    despues, codigos = [], []
    pendientes = list(tomadas[5:])
    while pendientes and time.time() - caida < 90:
        codigo, event_id = enviar(c, pendientes[0])
        codigos.append({"t_s": round(time.time() - caida, 2), "codigo": codigo})
        if codigo == 200:
            despues.append((pendientes.pop(0), event_id))
        else:
            time.sleep(0.5)
    primera_escritura = next((x["t_s"] for x in codigos if x["codigo"] == 200), None)
    nuevo = esperar_primario_distinto(c, viejo)

    acciones.append(docker_compose("start", viejo))
    esperar_salud(c, "operativo")
    confirmadas = [t for t, (codigo, _) in zip(tomadas[:5], antes) if codigo == 200] + [t for t, _ in despues]
    event_ids = [e for codigo, e in antes if codigo == 200] + [e for _, e in despues]
    verificacion = una_vez_en_mongodb_y_parquet(c, confirmadas, event_ids)
    return {
        "primario_detenido": viejo,
        "nuevo_primario": nuevo,
        "codigos_antes": [codigo for codigo, _ in antes],
        "intentos_durante_eleccion": codigos,
        "rto_escritura_s": primera_escritura,
        "verificacion": verificacion,
        "acciones": acciones,
        "cumple": nuevo not in (None, viejo) and verificacion["cumple"],
    }


def sin_mayoria(c) -> dict:
    proyecto_id, _ = crear_proyecto_con_tareas(c, 3, "p8-sin-mayoria")
    tomadas = tomar(c, proyecto_id, 3)
    actual = primario(c)
    detenidos = [actual, next(m for m in MIEMBROS if m != actual)]
    acciones = [docker_compose("stop", *detenidos)]
    salud = esperar_salud(c, "caido")
    durante = [enviar(c, t)[0] for t in tomadas]

    inicio = time.time()
    acciones.append(docker_compose("start", *detenidos))
    restauracion = esperar_salud(c, "operativo", limite_s=120)
    rto = round(time.time() - inicio, 1) if restauracion["segundos"] is not None else None
    reenvios = [enviar(c, t) for t in tomadas]
    verificacion = una_vez_en_mongodb_y_parquet(c, tomadas, [e for _, e in reenvios if e])
    return {
        "nodos_detenidos": detenidos,
        "salud_con_falla": salud["estado"],
        "codigos_sin_mayoria": durante,
        "rto_restauracion_s": rto,
        "codigos_reenvio_tras_restaurar": [codigo for codigo, _ in reenvios],
        "verificacion": verificacion,
        "acciones": acciones,
        "cumple": all(codigo == 503 for codigo in durante)
        and all(codigo == 200 for codigo, _ in reenvios)
        and verificacion["cumple"],
    }


def reinicio_valkey(c) -> dict:
    """Envíos seguidos de un kill de Valkey: mide eventos perdidos (RPO) antes y después de conciliar."""
    proyecto_id, _ = crear_proyecto_con_tareas(c, 11, "p8-valkey")
    tomadas = tomar(c, proyecto_id, 11)
    borrador = tomadas.pop()
    c.put(
        f"/tareas/{borrador['tarea_id']}/borrador",
        json={"anotador_id": borrador["anotador_id"], "token": borrador["token"], "contenido": {"paso": "antes"}},
    ).raise_for_status()

    desde = datetime.now(timezone.utc).isoformat()
    event_ids = [e for codigo, e in (enviar(c, t) for t in tomadas) if codigo == 200]
    acciones = [docker_compose("kill", "valkey")]
    caida = time.time()
    acciones.append(docker_compose("start", "valkey"))
    restauracion = esperar_salud(c, "operativo")
    rto = round(time.time() - caida, 1) if restauracion["segundos"] is not None else None

    esperar_eventos(event_ids, limite_s=20)
    tabla = filas_de(event_ids)
    presentes = set(tabla.column("event_id").to_pylist()) if tabla is not None else set()
    perdidos = len(set(event_ids) - presentes)

    conciliacion = docker_compose("exec", "-T", "gateway", "python", "-m", "app.conciliar", "--desde", desde)
    esperar_eventos(event_ids, limite_s=30)
    tabla = filas_de(event_ids)
    despues = set(tabla.column("event_id").to_pylist()) if tabla is not None else set()
    recuperado = c.post("/sesiones/recuperar", json={"anotador_id": borrador["anotador_id"]})
    return {
        "envios_confirmados": len(event_ids),
        "rto_valkey_s": rto,
        "eventos_perdidos_antes_de_conciliar": perdidos,
        "conciliacion": conciliacion[-1500:],
        "eventos_perdidos_despues_de_conciliar": len(set(event_ids) - despues),
        "borrador_tras_reinicio": recuperado.status_code == 200 and (recuperado.json().get("borrador") or {}).get("contenido") == {"paso": "antes"},
        "acciones": acciones,
        "cumple": not (set(event_ids) - despues) and recuperado.status_code == 200,
    }


def sesion_interrumpida(c) -> dict:
    proyecto_id, _ = crear_proyecto_con_tareas(c, 1, "p8-sesion")
    t = tomar(c, proyecto_id, 1)[0]
    c.put(
        f"/tareas/{t['tarea_id']}/borrador",
        json={"anotador_id": t["anotador_id"], "token": t["token"], "contenido": {"paso": 1}},
    ).raise_for_status()
    time.sleep(3)
    recuperado = c.post("/sesiones/recuperar", json={"anotador_id": t["anotador_id"]})
    reanudado = c.post("/tareas/siguiente", json={"anotador_id": t["anotador_id"], "proyecto_id": proyecto_id})
    codigo, _ = enviar(c, t)
    return {
        "recuperacion": recuperado.status_code,
        "siguiente_devuelve_la_misma_tarea": reanudado.json().get("tarea_id") == t["tarea_id"],
        "envio_tras_recuperar": codigo,
        "cumple": recuperado.status_code == 200 and codigo == 200,
    }


ESCENARIOS = {
    "secundario": secundario_caido,
    "primario": primario_caido,
    "sin_mayoria": sin_mayoria,
    "valkey": reinicio_valkey,
    "sesion": sesion_interrumpida,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--escenarios", nargs="+", default=list(ESCENARIOS), choices=list(ESCENARIOS))
    args = parser.parse_args()

    resultado = {}
    with cliente() as c:
        esperar_salud(c, "operativo")
        for nombre in args.escenarios:
            print(f"escenario {nombre}...")
            resultado[nombre] = ESCENARIOS[nombre](c)
            esperar_salud(c, "operativo", limite_s=120)
    resultado["cumple"] = all(r["cumple"] for r in resultado.values())
    guardar_evidencia(
        "p8_fallas",
        "Fallas de MongoDB y Valkey, sesión interrumpida y conciliación: recuperación, RTO y RPO",
        {"escenarios": args.escenarios},
        resultado,
    )
    print(json.dumps({k: (v["cumple"] if isinstance(v, dict) else v) for k, v in resultado.items()}, indent=2))


if __name__ == "__main__":
    main()
