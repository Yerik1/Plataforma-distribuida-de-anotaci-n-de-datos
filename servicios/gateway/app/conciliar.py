"""Reconstruye eventos confirmados en MongoDB que no llegaron al datalake (ADR-007).

Compara el último evento de cada tarea modificada desde un instante con los event_id presentes
en el datalake y reenvía al stream los que faltan. Uso:

    python -m app.conciliar --desde 2026-11-22T00:00:00+00:00
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import httpx

from .config import HISTORIAL_URL, REGISTRO_URL, SESION_URL


def conciliar(desde: datetime, limite: int) -> dict:
    revisadas, faltantes, reenviados, errores = 0, [], [], []
    vistos: set[str] = set()
    with httpx.Client(timeout=30) as http:
        while True:
            respuesta = http.get(
                f"{REGISTRO_URL}/tareas",
                params={"actualizada_desde": desde.isoformat(), "limite": limite},
            )
            respuesta.raise_for_status()
            tareas = [t for t in respuesta.json()["tareas"] if t["tarea_id"] not in vistos]
            if not tareas:
                break
            vistos.update(t["tarea_id"] for t in tareas)
            revisadas += len(tareas)

            eventos = {t["ultimo_evento"]["event_id"]: t["ultimo_evento"] for t in tareas}
            existentes = http.post(f"{HISTORIAL_URL}/eventos/existentes", json={"event_ids": list(eventos)})
            existentes.raise_for_status()
            presentes = set(existentes.json()["existentes"])

            for event_id, evento in eventos.items():
                if event_id in presentes:
                    continue
                faltantes.append(event_id)
                envio = http.post(f"{SESION_URL}/eventos", json={"evento": evento})
                (reenviados if envio.status_code == 201 else errores).append(event_id)

            desde = datetime.fromisoformat(tareas[-1]["actualizada_en"])
            if len(respuesta.json()["tareas"]) < limite:
                break

    return {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "tareas_revisadas": revisadas,
        "eventos_faltantes": len(faltantes),
        "eventos_reenviados": len(reenviados),
        "errores": errores,
        "event_ids_reenviados": reenviados,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--desde", required=True, help="instante ISO 8601 desde el que se revisan las tareas")
    parser.add_argument("--limite", type=int, default=1000)
    args = parser.parse_args()
    desde = datetime.fromisoformat(args.desde)
    if desde.tzinfo is None:
        desde = desde.replace(tzinfo=timezone.utc)
    resultado = conciliar(desde, args.limite)
    json.dump(resultado, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
