# ADR-008. Esquema de evento desnormalizado

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

Spark no puede consultar MongoDB ni el servicio de historial (§8), por lo que cada fila de Parquet debe contener los atributos que agrupan o filtran Q1 a Q5. Además, 60 proyectos cerrados existen solo en el historial (§9). El enunciado no define el esquema del evento.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Evento desnormalizado con cliente, proyecto, modalidad, equipo, tiempos y SLA | Cada consulta se resuelve sobre una sola tabla; compatible con los proyectos que solo existen en el historial | Mayor tamaño por fila |
| Evento mínimo más tablas de dimensiones en Parquet | Menor redundancia | Dimensiones que exportar y versionar; joins en Spark |
| Evento mínimo y consulta a MongoDB desde Spark | Datos actuales | Prohibido por §8 |

## Decisión

| Campo | Tipo | Uso |
| --- | --- | --- |
| `event_id` | string (UUID) | Deduplicación (§6.3) |
| `tipo_evento` | string | `tarea_abierta`, `tarea_anotada`, `revision_iniciada`, `tarea_aprobada`, `tarea_rechazada` |
| `estado` | string | Estado de la fila según §6.1 (Q1, Q2, Q4) |
| `ts` | timestamp UTC | Momento de la transición (Q1) |
| `mes` | string AAAA-MM | Partición (§6.3) |
| `tarea_id`, `batch_id`, `proyecto_id`, `cliente_id` | string | Q2, Q4, Q5 y trazabilidad |
| `modalidad` | string | texto, imagen, video o lidar (Q1, Q3) |
| `tipo_tarea` | string | Geometría (Q3) |
| `anotador_id`, `equipo_id` | string | Q2 |
| `revisor_id` | string, nulo | Eventos de revisión |
| `version` | int | Versión de la tarea tras la transición (§6.1) |
| `ts_toma` | timestamp, nulo | Inicio de la toma vigente (Q3) |
| `ts_primera_toma` | timestamp, nulo | Primera toma; un rechazo no la reinicia (Q5) |
| `duracion_anotacion_ms` | long, nulo | Solo en `anotada`: de `abierta` a `anotada` (Q3) |
| `sla_horas` | int | Plazo de la tarea (Q5) |
| `motivo_rechazo` | string, nulo | Solo en `rechazada` (ADR-012) |
| `correlation_id` | string | Identificador propagado por el gateway (§4) |

## Justificación

Es la única opción compatible con §8 que evita joins, y permite que el generador escriba directamente los eventos de los proyectos cerrados (§9).

## Consecuencias

- Registro calcula `duracion_anotacion_ms` al generar el evento.
- `liberar` también cambia el estado (de `abierta` a `disponible`), por lo que genera una fila `disponible` con `tipo_evento` `tarea_liberada` (§6.1: cada transición que cambia el estado escribe una fila). Ninguna de Q1 a Q5 usa esas filas.
- Se conservan `ts_toma` y `ts_primera_toma` para recalcular duraciones al validar las consultas (§8).
- El generador usa este mismo esquema (ADR-013).
