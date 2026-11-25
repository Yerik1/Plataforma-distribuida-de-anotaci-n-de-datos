# ADR-010. Definiciones operativas de Q2 a Q5

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

§8 no define "tipo de tarea" (Q3), el equipo de Q2 ni la toma usada en Q5 cuando hubo rechazo. Las consultas deben validarse con casos controlados (§8). Las definiciones principales se consultaron al profesor; las restantes las fija el equipo.

## Definiciones del profesor

| Consulta | Definición |
| --- | --- |
| Q2 | Equipo del anotador (uno de los 30). Universo: tareas con decisión de revisión. Cuenta la decisión final: rechazada y luego aprobada entra como aprobada |
| Q3 | Tipo de tarea = geometría (`span`, `bbox`, `poligono`, `bbox_video`, `cuboide_3d`). Duración de cada toma, de `abierta` a `anotada` |
| Q4 | Se cuentan las filas `rechazada` del datalake |
| Q5 | 48 horas desde la primera toma hasta la aprobación; un rechazo no reinicia el reloj. Universo: tareas aprobadas; porcentaje de ellas que superó 48 horas |

## Decisiones del equipo

| Punto | Alternativas | Decisión | Justificación |
| --- | --- | --- | --- |
| Denominador de Q4 | Filas `aprobada` + `rechazada`; tareas revisadas | Filas `aprobada` + `rechazada` | Misma unidad (filas) en numerador y denominador |
| Mes en Q2 | Mes de la decisión final; mes de la primera toma | Mes de la decisión final | Es la decisión que se contabiliza |
| Equipo en Q2 con varios anotadores | Anotador de la decisión final; primer anotador | Anotador de la toma que recibió la decisión final | Es la toma evaluada por esa decisión |

## Consecuencias

- Q2 selecciona por `tarea_id` la última fila `aprobada` o `rechazada` con una función de ventana.
- Q5 usa `ts_primera_toma` de las filas `aprobada` (ADR-008).
- El conjunto de validación incluye una tarea rechazada y luego aprobada (ADR-013).
