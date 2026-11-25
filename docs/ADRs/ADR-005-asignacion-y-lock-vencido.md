# ADR-005. Asignación exclusiva y tareas con lock vencido

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

§6.2 fija el mecanismo base: lock con `SET NX PX` de 120 s renovado por el latido, asignación exclusiva con `findOneAndUpdate` y liberación del lock si MongoDB falla. §6.1 permite volver a ofrecer una tarea abierta cuyo plazo venció, y P3 lo prueba dejando vencer el candado (§10). El enunciado no resuelve cómo sabe Registro que el lock venció, si no puede consultar Valkey (§4) y la renovación solo ocurre en Valkey.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Prefiltro en MongoDB por antigüedad de la toma y `SET NX` como verificación definitiva | Sin escrituras extra en MongoDB; un `SET NX` exitoso prueba que el lock venció | Una sesión larga pasa el prefiltro y produce intentos fallidos de `SET NX` |
| Registro guarda `vence_en` y el gateway lo renueva en cada latido | Registro conoce el vencimiento exacto | Una escritura en MongoDB cada 2 s por anotador; el latido deja de vivir solo en Valkey (§6.2) |
| Proceso barredor que libera las tareas abiertas sin lock | Desacopla la liberación de la asignación | Componente adicional; la tarea tarda un ciclo del barredor en volver a la cola |

## Decisión

Prefiltro más `SET NX`:

1. Registro devuelve candidatas del proyecto por prioridad: primero las `disponible`, luego las `abierta` con `tomada_en` anterior a 120 s, junto con su token vigente.
2. El gateway genera un token y ejecuta `SET lock:tarea:{id} <token> NX PX 120000`. Si el lock existe, pasa a la siguiente candidata.
3. Con el lock adquirido, Registro ejecuta `findOneAndUpdate` filtrando por `_id` y estado (`disponible`, o `abierta` con el token anterior).
4. Si el resultado es nulo o MongoDB falla, el gateway libera el lock y prueba la siguiente candidata. Sin candidatas, responde 204.
5. `PUT /tareas/{id}/borrador` actúa como latido: renueva el lock solo si el token coincide (script Lua). Si no coincide, responde 409.

## Justificación

El lock en Valkey es la única fuente que conoce la renovación por latido, y `SET NX` ya es la operación exigida por §6.2. El filtro por token anterior en MongoDB impide que dos tomas sucesivas se pisen.

## Consecuencias

- El anotador que perdió el lock recibe 409 al guardar el borrador o al enviar (§6.1).
- `POST /tareas/siguiente` recibe `proyecto_id` para usar el índice `(proyecto_id, estado, prioridad)`.
- P2 verifica 10 asignaciones y 40 respuestas 204; P3 verifica que la tarea con lock vencido se ofrece a otra persona y que el dueño anterior recibe 409 (§10).
