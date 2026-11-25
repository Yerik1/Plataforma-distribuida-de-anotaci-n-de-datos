# ADR-003. Stack tecnológico de los servicios

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

El enunciado fija los motores (MongoDB, Valkey, Parquet, Spark) pero no el lenguaje de los servicios (§4). En la defensa, las tres personas deben explicar componentes que no implementaron (§13). P2 recomienda `concurrent.futures` de Python (§10).

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Python en todos los servicios | Un solo lenguaje para servicios, analítica y pruebas; PySpark es nativo; coincide con la recomendación de P2 | Menor rendimiento por proceso que Go |
| Go en gateway, Registro y Sesión; Python en Historial y Analítica | Mayor rendimiento en las rutas medidas en P6 | Dos lenguajes que dominar para la defensa |
| Node.js en servicios operacionales; Python en analítica | Buen manejo de E/S concurrente | Dos lenguajes; sin ventaja sobre la primera opción en las pruebas exigidas |

## Decisión

Python 3.12 en todos los componentes:

| Componente | Herramientas |
| --- | --- |
| Gateway, Registro, Sesión, Historial | FastAPI con Uvicorn; `httpx`; PyMongo; `valkey-py`; PyArrow |
| Analítica | FastAPI con PySpark contra Spark standalone |
| P2 | `concurrent.futures.ProcessPoolExecutor` (§10) |
| P6 | Locust, que reporta p50, p95 y p99 por endpoint |

## Justificación

Un solo lenguaje reduce el costo de que cada integrante entienda los componentes ajenos (§13). La rúbrica evalúa las mediciones y el análisis de cuellos de botella, no el rendimiento absoluto (§12).

## Consecuencias

- Las versiones se fijan en un `requirements.txt` por servicio (§13).
- Si P6 muestra el gateway como cuello de botella, se documenta como hallazgo (§11.2).
