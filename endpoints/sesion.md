# Servicio de sesión

Interno, sin puertos publicados. Única capa con acceso a Valkey (AOF `everysec`). No decide el estado definitivo de una tarea (§4).

| Método y ruta | Uso | Respuestas |
| --- | --- | --- |
| `POST /locks` | `SET lock:tarea:{id} <token> NX PX 120000` | 201, 409 |
| `DELETE /locks/{tarea_id}?token=&anotador_id=&limpiar=` | Libera el lock si el token coincide; con `limpiar` elimina también borrador, sesión y entrada en `editando` | 200, 409 |
| `PUT /sesiones/{anotador_id}` | Crea o reemplaza `sesion:{anotador}` y registra al anotador en `editando:{proyecto}` | 200 |
| `GET /sesiones/{anotador_id}` | Sesión, validez del lock y último borrador del anotador | 200, 404 |
| `PUT /tareas/{tarea_id}/borrador` | Guarda el borrador y renueva el lock solo si el token coincide (latido, ADR-005) | 200, 409 |

Cualquier operación que no obtiene respuesta de Valkey devuelve 503.

## Llaves

| Llave | Tipo | Contenido |
| --- | --- | --- |
| `lock:tarea:{id}` | string con expiración | Token de asignación |
| `sesion:{anotador}` | hash | `tarea_id`, `proyecto_id`, `token`, `etapa`, `inicio` |
| `borrador:{tarea}` | hash | `contenido`, `ts`, `anotador_id` |
| `editando:{proyecto}` | conjunto ordenado | Anotadores con puntaje igual a la hora del último latido |
| `salud:sesion` | string con expiración | Estado reportado cada 5 s con TTL de 15 s (ADR-011) |
