# Servicio de analítica

Interno, sin puertos publicados. Ejecuta Q1 a Q5 con Spark sobre el datalake montado en solo lectura; no consulta MongoDB ni el servicio de historial (§8). Reporta su estado en `salud:analitica`.

| Método y ruta | Uso | Respuestas |
| --- | --- | --- |
| `GET /consultas/{q1..q5}?conjunto=&fecha_referencia=` | Resultados de la consulta y su tiempo de ejecución | 200, 404, 422 |
| `GET /consultas/{q1..q5}/plan?conjunto=` | Plan físico de Spark en formato `formatted` | 200, 404, 422 |

| Conjunto | Ruta |
| --- | --- |
| `principal` | `/opt/datalake/eventos` |
| `ampliado` | `/opt/datalake/ampliado/eventos` |
| `validacion` | `/opt/analitica/datos_prueba/parquet/eventos` |

Las definiciones de cada consulta están en ADR-010 y en `servicios/analitica/spark/consultas.py`. La sesión de Spark del servicio usa como máximo `ANALITICA_CORES` núcleos del clúster.
