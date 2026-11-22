# ADR-013. Generador y carga del conjunto de datos

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

El equipo escribe el generador, lo incluye en el repositorio y documenta los conteos y comandos para cargar todo desde cero (§3, §9). §9 fija los volúmenes: 60 clientes, 180 proyectos (60 cerrados solo en el historial), 600 lotes, 60 000 tareas con distribución 30/30/20/20 por modalidad, 300 anotadores en 30 equipos con 10 % de revisores, y unos 800 000 eventos para doce meses y 100 000 tareas. Las consultas se validan con datos conocidos (§8). El enunciado no define el método de generación ni de carga.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Script con semilla fija que carga MongoDB y escribe el historial directo a Parquet | Reproducible; cubre clientes y anotadores, que no tienen ruta en el gateway | La carga del registro no pasa por la API |
| Cargar proyectos y lotes por el gateway y el resto directo | Ejercita la API | Igual requiere carga directa para el resto; dos mecanismos |
| Generar el historial con el simulador | Eventos del flujo real | Doce meses de fechas no se producen en tiempo real |

## Decisión

Script con semilla fija en `proyecto2/dataset/`:

1. Catálogo en MongoDB con los volúmenes de §9; las 60 000 tareas inician en `disponible`.
2. Historial de 100 000 tareas de los 180 proyectos, escrito en pocos archivos por mes con el esquema de ADR-008.
3. Duraciones por modalidad, probabilidad de rechazo e incumplimientos de SLA parametrizados y documentados.
4. Un conjunto `validacion` pequeño con resultados de Q1 a Q5 calculados a mano, seleccionado con `?conjunto=validacion`.

## Justificación

La semilla fija hace los conteos exactos y repetibles, como exige §9. Escribir el historial directo a Parquet es la única forma de cubrir doce meses de fechas.

## Consecuencias

- Cada ciclo de una tarea produce 4 eventos; llegar a unos 800 000 eventos con 100 000 tareas exige un promedio de 8 por tarea. La probabilidad de rechazo se calibra para ese total y se documenta.
- Si las pruebas de carga agotan las tareas, se vuelve a correr el generador y se anotan fecha, motivo y efecto sobre la comparabilidad (§9).
- El conjunto ampliado de hasta 10 millones de eventos usa el mismo generador con otro factor de escala (§8).
