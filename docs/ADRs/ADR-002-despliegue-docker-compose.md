# ADR-002. Despliegue con Docker Compose

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

Todo el sistema se ejecuta en contenedores Docker y debe iniciarse siguiendo el README en un entorno limpio (§13). El repositorio incluye `docker-compose.yml` con perfiles de ejecución (§11.1). Solo el gateway se expone al host, en el puerto 8000, y las interfaces de administración se limitan a localhost (§3). Spark se compara con uno y dos trabajadores (§8), y la carga se reporta con `docker stats` (§10). El equipo evaluó además Kubernetes como extensión.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Docker Compose con perfiles como único despliegue | Cumple §11.1 directamente; reproducible en un solo equipo; compatible con `docker stats` | Sin autorecuperación de contenedores |
| Kubernetes como despliegue principal | Autorecuperación; más cercano a producción | No aporta a la rúbrica (§12); el replica set requiere StatefulSets; aumenta el riesgo de que el README no reproduzca el sistema (§13) |
| Spark en modo `local[*]` dentro de Analítica | Menos contenedores | No permite la comparación de trabajadores de §8 |

## Decisión

Docker Compose como despliegue único, con Spark standalone:

| Perfil | Servicios |
| --- | --- |
| Núcleo | 3 nodos MongoDB, inicializador del replica set, Valkey, Registro, Sesión, Historial, Gateway |
| `analitica` | Spark master, trabajador 1, Analítica |
| `spark2` | Trabajador 2 |
| `datos` | Generador y carga (ADR-013) |
| `carga` | Simulador y pruebas |

- Dos redes: `publica`, solo con el gateway en `8000:8000`, e `interna` para el resto. La UI de Spark se publica como `127.0.0.1:<puerto>`.
- `datalake/` se monta en Historial en lectura y escritura, y en Analítica y cada trabajador de Spark en solo lectura, en la misma ruta.

## Justificación

§11.1 y §13 condicionan la calificación a la reproducibilidad con Compose, y Kubernetes no aporta a ningún criterio de §12. Spark standalone es la única forma de cumplir la comparación de trabajadores de §8. Separar las redes hace que el requisito de §3 dependa de la topología y no de omitir `ports:` en cada servicio.

## Consecuencias

- P1 incluye `docker ps` y `docker network inspect` como evidencia de exposición (§10).
- Cada trabajador de Spark tiene límites fijos de CPU y memoria, documentados con las características de la máquina (§10).
- Kubernetes queda fuera del alcance.
