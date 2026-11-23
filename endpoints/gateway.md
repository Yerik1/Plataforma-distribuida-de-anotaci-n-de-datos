# Gateway

Único componente expuesto al host, en `http://localhost:8000` (ADR-002). Propaga la cabecera `X-Correlation-ID`; si la petición no la trae, la genera y la devuelve en la respuesta.

| Método y ruta | Cuerpo | Respuestas |
| --- | --- | --- |
| `POST /proyectos` | `cliente_id`, `nombre`, `taxonomia` (`etiqueta`, `instruccion`), `sla_horas`, `modalidad` opcional | 201, 422, 503 |
| `POST /proyectos/{id}/lotes` | `tareas`: `archivo` (`uri`, `sha256`, `bytes`, `mime`, `meta`), `modalidad`, `tipo_tarea`, `prioridad` | 201, 404, 409 (proyecto no activo), 422, 503 |
| `POST /tareas/siguiente` | `anotador_id`, `proyecto_id` | 200 (tarea, token y borrador recuperable), 204 (sin tareas), 503 |
| `PUT /tareas/{id}/borrador` | `anotador_id`, `token`, `contenido` | 200, 409 (token o sesión no corresponden), 503 |
| `POST /tareas/{id}/enviar` | `anotador_id`, `token`, `anotacion` (`etiqueta`, `geometria`) | 200 (`tarea` y `evento`), 409 (token no corresponde o tarea no abierta), 503 (MongoDB no responde, sin reintento; el envío queda pendiente en Valkey con el mismo `event_id`) |
| `POST /tareas/{id}/liberar` | `anotador_id`, `token` | 200, 409, 503 |
| `POST /tareas/{id}/revision` | `revisor_id`, `accion` (`iniciar`, `aprobar`, `rechazar`), `motivo` | 200, 400 (rechazo sin código válido), 409, 503 |
| `POST /sesiones/recuperar` | `anotador_id` | 200 (tarea, token y último borrador), 404 (sin sesión), 409 (lock vencido) |
| `GET /proyectos/{id}/exportar?cursor=&limite=` | | 200 (`tareas`, `siguiente_cursor`), 404, 503 |
| `GET /salud` | | 200 (operativo o degradado), 503 (caído) |

Códigos de motivo de rechazo (ADR-012): `geometria_invalida`, `etiqueta_fuera_taxonomia`, `objeto_omitido`, `instruccion_no_seguida`.

Reintentos (ADR-006): solo en `GET` y en `PUT /tareas/{id}/borrador`, hasta 2 veces, ante error de conexión, tiempo agotado o 502/503 del servicio interno.

Cada transición confirmada por MongoDB se publica en el stream `eventos:confirmados` por medio del servicio de sesión. Si esa publicación falla, la respuesta al cliente no cambia y el evento se recupera con la conciliación (ADR-007):

```
docker compose exec gateway python -m app.conciliar --desde 2026-11-22T00:00:00+00:00
```
