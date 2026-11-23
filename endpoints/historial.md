# Servicio de historial

Interno, sin puertos publicados. Consume el stream `eventos:confirmados` de Valkey con el grupo `historial` y escribe el datalake en `datalake/eventos/mes=AAAA-MM/` (ADR-007, ADR-009). Reporta su estado en `salud:historial`.

| Método y ruta | Uso | Respuestas |
| --- | --- | --- |
| `POST /eventos/existentes` | Recibe `event_ids` y devuelve los que ya están publicados en el datalake (conciliación) | 200 |

## Micro-lotes

1. Lee con `XREADGROUP` hasta 500 eventos o 2 segundos, lo que ocurra primero (`LOTE_EVENTOS`, `LOTE_SEGUNDOS`).
2. Escribe cada mes del lote en `datalake/_tmp/` y lo publica con un renombrado atómico como `part-<huella>.parquet`, donde la huella depende solo de los `event_id` del lote.
3. Después de publicar ejecuta `XACK` y `XDEL`.
4. Al iniciar recupera con `XAUTOCLAIM` las entradas entregadas y no confirmadas; reprocesar el mismo lote sobrescribe el mismo archivo.

## Comandos

| Comando | Uso |
| --- | --- |
| `docker compose exec historial python -m app.compactar --mes AAAA-MM` | Deduplica y une los archivos de un mes cerrado; mueve los originales a `datalake/_compactados/` |

La prueba P4 crea `datalake/_control/fallar_tras_publicar` para que el servicio termine después de publicar y antes de confirmar un lote, y así demostrar el reprocesamiento.
