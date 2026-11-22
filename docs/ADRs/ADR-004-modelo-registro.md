# ADR-004. Modelo de documentos e índices del registro

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

§6.1 fija las colecciones (`clientes`, `proyectos`, `batches`, `tareas`, `anotadores`), los identificadores UUID, el contenido mínimo de la tarea y cuatro índices obligatorios; todo índice adicional debe justificarse con una consulta o medición. El enunciado no define si la tarea copia atributos de proyecto y cliente, ni cómo se pagina la exportación (§7).

## Alternativas consideradas

**Estructura de la tarea:**

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Estado vigente embebido y atributos copiados del proyecto (`cliente_id`, `sla_horas`, `modalidad`, `tipo_tarea`) | Cada transición se resuelve con un solo `findOneAndUpdate` y genera el evento sin leer otras colecciones | Los atributos copiados no cambian si el proyecto se modifica |
| Tarea mínima y lectura de proyecto y cliente en cada transición | Sin redundancia | Lecturas adicionales en el camino crítico de cada envío |

**Paginación de la exportación:**

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Cursor por `_id` con índice `(proyecto_id, estado, _id)` | Costo constante por página; estable ante aprobaciones concurrentes | Índice adicional |
| `skip` y `limit` | Sin índice adicional | El costo crece con la página; una aprobación concurrente desplaza resultados |

## Decisión

Estado embebido con atributos copiados y paginación por cursor. Documento de tarea:

| Campo | Contenido |
| --- | --- |
| `_id`, `proyecto_id`, `batch_id`, `cliente_id` | UUID |
| `modalidad`, `tipo_tarea`, `prioridad`, `sla_horas` | Copiados al registrar el lote |
| `archivo` | `uri`, `sha256`, `bytes`, `mime`, `meta` (§1) |
| `estado`, `version` | Estado de §6.1; la versión aumenta en cada transición |
| `asignacion` | `anotador_id`, `equipo_id`, `token`, `tomada_en` |
| `primera_toma_en` | No cambia tras un rechazo (ADR-010) |
| `anotacion`, `ultima_revision` | Anotación vigente y última decisión de revisión |
| `ultimo_evento` | Evento completo de la última transición, con su `event_id` (ADR-007) |
| `actualizada_en` | Hora de la última transición |

Índices adicionales a los cuatro de §6.1:

- `tareas (actualizada_en)`: consulta de conciliación (ADR-007).
- `tareas (proyecto_id, estado, _id)`: exportación por cursor.

## Justificación

La asignación y el envío son las rutas medidas en P6; resolverlas con una sola operación atómica mantiene la exclusividad de §6.1 y reduce la latencia. El cursor es la única opción sin resultados repetidos u omitidos durante la exportación.

## Consecuencias

- Cada índice adicional se justifica con `explain()` en `evidence/` (§6.1).
- Las anotaciones de tomas anteriores solo quedan en Parquet.
- El orden de exportación por `_id` no es cronológico.
