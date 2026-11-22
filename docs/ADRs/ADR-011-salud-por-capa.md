# ADR-011. Salud por capa

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

`/salud` informa operativo, degradado o caído por capa, con mensajes de estado almacenados en Valkey, sin que una capa caída afecte al gateway (§7). Registro no consulta Valkey (§4). Ante esa tensión, el profesor indicó que el gateway revisa Registro y escribe su estado en Valkey, que Sesión, Historial y Analítica escriben el suyo, y que `/salud` solo lee Valkey. El enunciado no define qué condiciones corresponden a cada estado.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Caído solo si ninguna capa responde | Criterio simple | Reporta degradado un sistema que no puede completar ninguna tarea |
| Caído si falla una capa sin la cual ninguna tarea se completa; degradado si falla una capa que solo retrasa resultados | Refleja el impacto real sobre el flujo de §5 | Requiere clasificar las capas |

## Decisión

| Estado | Condición |
| --- | --- |
| Operativo | Todas las capas reportan y el replica set tiene sus tres miembros |
| Degradado | MongoDB con primario y un miembro caído, o Historial o Analítica sin reportar |
| Caído | MongoDB sin primario, Registro sin respuesta o Valkey sin respuesta |

Cada capa reporta cada 5 s en `salud:<capa>` con TTL de 15 s. Si Valkey no responde, el gateway informa caído sin dejar de atender `/salud`.

## Justificación

Sin Valkey no hay locks y sin mayoría en MongoDB no hay transiciones, así que ninguna tarea puede completarse. Historial y Analítica caídos solo retrasan el historial o las consultas. El TTL de tres intervalos evita marcar como caída una capa que solo se atrasó.

## Consecuencias

- P1 verifica los tres estados deteniendo capas de forma controlada (§10).
- P8 registra el estado reportado durante cada falla de MongoDB (§10).
