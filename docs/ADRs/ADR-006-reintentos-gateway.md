# ADR-006. Política de reintentos seguros del gateway

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

El gateway debe aplicar reintentos seguros (§4), pero el enunciado no define a qué operaciones aplican. Si MongoDB no responde en un envío, se devuelve 503 sin reintento (§5).

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Reintentar solo operaciones idempotentes | Seguro por construcción | Los `POST` fallidos los reintenta el cliente |
| Reintentar todo con una cabecera `Idempotency-Key` guardada en Valkey | Cubre también los `POST` | Requiere almacenar respuestas por llave; contradice el 503 sin reintento de §5 |
| Sin reintentos | Trivial | No cumple §4 |

## Decisión

- Reintentos solo en `GET` y en `PUT /tareas/{id}/borrador`.
- Máximo 2 reintentos, con espera exponencial y variación aleatoria.
- Solo ante error de conexión, tiempo agotado o 502/503 del servicio interno.
- Ningún `POST` se reintenta en el gateway.

## Justificación

Un `GET` o una sobrescritura del mismo borrador producen el mismo resultado al repetirse; las demás rutas cambian estado. La regla coincide con el 503 sin reintento de §5.

## Consecuencias

- El simulador reenvía tras un 503 reutilizando el mismo `event_id` (ADR-007).
- P1 documenta un caso de reintento exitoso y uno de envío con 503 sin reintento (§10).
