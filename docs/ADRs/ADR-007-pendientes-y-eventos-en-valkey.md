# ADR-007. Envíos pendientes y eventos confirmados en Valkey

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

El objetivo exige mensajería durable (§2) y §4 asigna a Sesión el almacenamiento temporal de envíos pendientes. El enunciado no define el mecanismo, por lo que se consultó al profesor, quien indicó:

- No se requiere RabbitMQ ni otra cola. Valkey, con AOF en `everysec`, guarda los envíos pendientes.
- Si MongoDB no responde, se devuelve 503 sin reintento y el pendiente queda en Valkey.
- Cuando MongoDB confirma, se responde 200 y el historial toma el pendiente, lo escribe en Parquet y luego lo retira de Valkey. Si el historial cae antes de publicar, el pendiente se reprocesa.
- El informe declara que AOF puede perder el último segundo, y la tarea en MongoDB conserva el identificador del último evento para reconstruir ese caso.

Quedan como decisión del equipo la estructura en Valkey y el procedimiento de reconstrucción.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Stream `eventos:confirmados` con grupo de consumidores, más `envio:{tarea}` para lo no confirmado | El grupo registra lo entregado y no confirmado, lo que implementa el reprocesamiento indicado por el profesor | Dos estructuras distintas |
| Lista o hash con campo de estado | Una sola estructura | El seguimiento de lo entregado se implementa a mano |
| RabbitMQ o patrón outbox en MongoDB | Mayor garantía entre commit y publicación | Descartadas por el profesor |

Para la reconstrucción:

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Conciliación bajo demanda tras una falla | No altera las mediciones de carga; es un paso documentado de recuperación en P8 | Requiere ejecutarla explícitamente |
| Conciliación periódica automática | Sin intervención | Carga adicional durante P6 |

## Decisión

1. El gateway genera el `event_id` antes de llamar a Registro.
2. En el envío, Sesión guarda `envio:{tarea}` con la anotación, el token y el `event_id`.
3. Si MongoDB no responde, el gateway devuelve 503 y `envio:{tarea}` se conserva; el reenvío reutiliza el `event_id`.
4. Si MongoDB confirma, Sesión agrega el evento a `eventos:confirmados`, elimina `envio:{tarea}` y el gateway responde 200. Las demás transiciones agregan su evento tras la confirmación de MongoDB.
5. Historial lee con `XREADGROUP`, publica el micro-lote (ADR-009) y solo entonces ejecuta `XACK` y `XDEL`. Al reiniciar recupera lo pendiente con `XAUTOCLAIM`.
6. Reconstrucción: el comando de conciliación del gateway pide a Registro las tareas actualizadas desde un instante dado, pregunta a Historial qué `event_id` ya existen en el datalake y reenvía al stream el `ultimo_evento` embebido de los faltantes (ADR-004).

## Justificación

El grupo de consumidores implementa el reprocesamiento que describe el profesor sin código adicional de seguimiento, y separar `envio:{tarea}` del stream garantiza que el historial solo consuma eventos confirmados. La conciliación bajo demanda cumple la reconstrucción indicada sin interferir con P6.

## Consecuencias

- La conciliación cubre también una caída del gateway entre la confirmación de MongoDB y la escritura en el stream.
- Solo se reconstruye el último evento de cada tarea, suficiente para la ventana de un segundo de AOF; se declara como limitación (§11.2).
- La entrega al historial es al menos una vez; Spark deduplica por `event_id` (§6.3).
- Registro no accede a Valkey (§4).
