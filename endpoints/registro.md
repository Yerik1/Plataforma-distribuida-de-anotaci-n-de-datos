# Servicio de registro

Interno, sin puertos publicados. Única capa con acceso a MongoDB (`plataforma`, réplica `rs0`, escritura `w: "majority"`). No consulta Valkey (§4).

| Método y ruta | Uso | Respuestas |
| --- | --- | --- |
| `POST /proyectos` | Crea el proyecto con su taxonomía y SLA | 201, 422 |
| `POST /proyectos/{id}/lotes` | Registra el lote y sus tareas en una transacción | 201, 404, 409, 422 |
| `GET /tareas?proyecto_id=&limite=` | Candidatas: `disponible` por prioridad y luego `abierta` con toma anterior al plazo del lock, con su token vigente (ADR-005) | 200 |
| `GET /tareas?actualizada_desde=&limite=` | Tareas modificadas desde un instante, con su `ultimo_evento`, para la conciliación (ADR-007) | 200 |
| `POST /tareas/{id}/transicion` | `tipo`: `asignar`, `enviar`, `liberar`, `iniciar_revision`, `aprobar`, `rechazar`, con `event_id`. Valida la transición sobre el estado leído y la aplica con un `findOneAndUpdate` condicionado al estado y a la versión leída. Responde la tarea y el evento generado (ADR-008) | 200, 404, 409, 422 |
| `GET /proyectos/{id}/exportar?cursor=&limite=` | Tareas aprobadas por cursor sobre `_id` (ADR-004) | 200, 404 |
| `GET /salud` | Estado del replica set | 200, 503 |

Cualquier operación que no obtiene respuesta de MongoDB devuelve 503.

## Transiciones

| Tipo | Estado requerido | Estado resultante |
| --- | --- | --- |
| `asignar` | `disponible`, o `abierta` con token anterior y toma vencida | `abierta` |
| `enviar` | `abierta` con el token y anotador de la asignación | `anotada` |
| `liberar` | `abierta` con el token y anotador de la asignación | `disponible` (fila `disponible` en el datalake) |
| `iniciar_revision` | `anotada`, revisor distinto del anotador | `en_revision` |
| `aprobar` | `en_revision` por el mismo revisor | `aprobada` |
| `rechazar` | `en_revision` por el mismo revisor | `disponible` (fila `rechazada` en el datalake) |

## Índices

| Nombre | Claves | Origen |
| --- | --- | --- |
| `proyecto_estado_prioridad` | `tareas (proyecto_id, estado, prioridad)` | §6.1 |
| `anotador_estado` | `tareas (asignacion.anotador_id, estado)` | §6.1 |
| `batch` | `tareas (batch_id)` | §6.1 |
| `cliente_estado` | `proyectos (cliente_id, estado)` | §6.1 |
| `proyecto_estado_id` | `tareas (proyecto_id, estado, _id)` | Exportación por cursor (ADR-004) |
| `actualizada` | `tareas (actualizada_en)` | Consulta de conciliación (ADR-007) |

## Concurrencia

Cada transición lee la tarea, valida la regla de §6.1 y escribe con un filtro que incluye la versión leída. Si otra transición modificó la tarea entre la lectura y la escritura, el filtro no coincide y la operación responde 409. La tarea guarda el evento completo de la última transición en `ultimo_evento` (ADR-004).
