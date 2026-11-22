# ADR-012. Catálogo de códigos de motivo de rechazo

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

El rechazo debe incluir un código de motivo (§5, §7), pero el enunciado no define un catálogo. El profesor indicó que el equipo define un conjunto corto y documentado, y que un rechazo sin código responde 400.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Catálogo cerrado de cuatro códigos | Agregable en Q4; validable en el gateway | Un motivo no previsto se asigna al código más cercano |
| Texto libre | Sin restricciones | No permite agrupar ni validar |

## Decisión

| Código | Descripción |
| --- | --- |
| `geometria_invalida` | La geometría no corresponde a la modalidad o está mal formada |
| `etiqueta_fuera_taxonomia` | La etiqueta no pertenece a la taxonomía del proyecto |
| `objeto_omitido` | Falta anotar un objeto presente en el dato |
| `instruccion_no_seguida` | Se incumple una instrucción de la etiqueta; por ejemplo, un skater clasificado como `lidar#peaton` (§1) |

Un rechazo sin código o con un código fuera del catálogo responde 400.

## Justificación

Los cuatro códigos son los sugeridos por el profesor. Rechazar también los códigos desconocidos evita valores no agregables en el datalake.

## Consecuencias

- El gateway valida el código antes de llamar a Registro.
- `motivo_rechazo` solo toma valores del catálogo (ADR-008).
