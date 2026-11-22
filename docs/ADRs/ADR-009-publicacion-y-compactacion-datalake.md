# ADR-009. Publicación y compactación del datalake

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

§6.3 fija la escritura en ruta temporal, la publicación al terminar, el nombre tomado de identificadores del micro-lote y la deduplicación por `event_id` en Spark. El profesor confirmó la ruta `proyecto2/datalake/eventos/mes=AAAA-MM/`. El enunciado no define cómo se forma el nombre, cuándo se cierra un micro-lote ni cómo se compacta, aunque §11.2 pide documentar la compactación.

## Alternativas consideradas

**Nombre del archivo:**

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Hash de los `event_id` del lote | Reprocesar el mismo lote sobrescribe el mismo archivo (P4) | Un lote con composición distinta tras una reentrega genera otro archivo, cubierto por la deduplicación |
| Marca de tiempo | Simple | Reprocesar duplica archivos |

**Compactación:**

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Comando por partición mensual que deduplica y archiva los originales | Reduce archivos; reversible | Conviven originales y compactado durante la operación; la deduplicación lo cubre |
| Micro-lotes más grandes | Sin proceso adicional | Empeora la frescura medida en P4 |
| Delta Lake o Iceberg | Compactación transaccional | §6.3 especifica archivos Parquet en un directorio |

## Decisión

- El micro-lote se cierra al llegar a 500 eventos o a los 2 s, lo que ocurra primero (valores iniciales, ajustados con P4).
- Se escribe en `datalake/_tmp/`, se renombra con `os.rename` a `eventos/mes=AAAA-MM/part-<hash>.parquet` y solo entonces se confirman las entradas en Valkey (ADR-007).
- El comando `compactar --mes AAAA-MM` lee la partición, deduplica por `event_id`, publica `compactado-<hash>.parquet` por el mismo camino y mueve los originales a `datalake/_compactados/`. No se compacta el mes en curso.

## Justificación

El renombrado dentro del mismo volumen es atómico y el nombre determinista hace idempotente el reprocesamiento de P4. Archivar en lugar de borrar permite revertir una compactación fallida.

## Consecuencias

- `_tmp/`, `eventos/` y `_compactados/` residen en el mismo volumen; Spark solo lee `eventos/`.
- P5 reporta mediciones antes y después de compactar (§8).
- Los valores finales del micro-lote y su medición se documentan en `evidence/` (§11.2).
