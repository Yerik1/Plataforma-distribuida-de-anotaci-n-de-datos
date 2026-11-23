"""Compacta una partición mensual del datalake (ADR-009).

Lee los archivos de eventos/mes=AAAA-MM/, elimina duplicados por event_id, publica un único
archivo compactado y mueve los originales a _compactados/mes=AAAA-MM/. Uso:

    python -m app.compactar --mes 2026-10
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from .config import DATALAKE
from .parquet import ESQUEMA, escribir_atomico, nombre_lote


def compactar(mes: str, forzar: bool) -> dict:
    if mes == datetime.now(timezone.utc).strftime("%Y-%m") and not forzar:
        raise SystemExit("el mes en curso recibe eventos; use --forzar para compactarlo")
    particion = DATALAKE / "eventos" / f"mes={mes}"
    originales = sorted(p for p in particion.glob("*.parquet"))
    if len(originales) < 2:
        return {"mes": mes, "archivos_originales": len(originales), "compactado": None}

    tabla = pa.concat_tables([pq.read_table(p, schema=ESQUEMA) for p in originales])
    ids = tabla.column("event_id").to_pylist()
    vistos: set[str] = set()
    indices = [i for i, e in enumerate(ids) if not (e in vistos or vistos.add(e))]
    unica = tabla.take(indices)

    compactado = escribir_atomico(unica, DATALAKE, mes, "compactado-" + nombre_lote(list(vistos))[5:])
    archivo = DATALAKE / "_compactados" / f"mes={mes}"
    archivo.mkdir(parents=True, exist_ok=True)
    for original in originales:
        if original != compactado:
            shutil.move(str(original), archivo / original.name)

    return {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "mes": mes,
        "archivos_originales": len(originales),
        "filas_leidas": tabla.num_rows,
        "duplicados_eliminados": tabla.num_rows - unica.num_rows,
        "filas_compactadas": unica.num_rows,
        "compactado": compactado.name,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mes", required=True, help="AAAA-MM")
    parser.add_argument("--forzar", action="store_true", help="permite compactar el mes en curso")
    args = parser.parse_args()
    json.dump(compactar(args.mes, args.forzar), sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
