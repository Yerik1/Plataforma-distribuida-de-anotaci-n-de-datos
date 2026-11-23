# Plataforma distribuida de anotación de datos

Proyecto 2 de TI-4601 Bases de Datos Avanzadas (Tecnológico de Costa Rica). Capa de datos de una plataforma de anotación basada en servicios REST y contenedores: registro operacional en MongoDB, sesiones y eventos pendientes en Valkey, historial en Parquet y consultas analíticas con Apache Spark. Las decisiones de arquitectura están en `docs/adr/` y los contratos de cada servicio en `endpoints/`.

| Servicio | Responsabilidad | Tecnología |
| --- | --- | --- |
| `gateway` | Único punto de entrada (puerto 8000); orquesta registro y sesión | FastAPI |
| `registro` | Estado vigente de proyectos, lotes y tareas | MongoDB, réplica de 3 nodos |
| `sesion` | Locks, borradores, sesiones, envíos pendientes y stream de eventos | Valkey con AOF `everysec` |
| `historial` | Consume eventos confirmados y publica el datalake | Parquet |
| `analitica` | Q1 a Q5 sobre el datalake en solo lectura | Apache Spark |
| `simulador/` | Anotadores y revisores simulados; solo usa HTTP contra el gateway | httpx |

## Requisitos

- Docker Desktop con Docker Compose v2.
- Python 3.12 o superior en el host, para el simulador y las pruebas.
- Para Spark con dos workers, memoria suficiente en Docker Desktop: cada worker está limitado a 3 GB (`SPARK_WORKER_LIMITE`) y los demás servicios se suman a eso.

## Inicio y detención

```powershell
docker compose up -d --build                                          # registro, sesión, historial, gateway y almacenes
docker compose --profile analitica up -d --build                      # agrega Spark (master y worker 1) y el servicio de analítica
docker compose --profile analitica --profile spark2 up -d             # agrega el worker 2
docker compose ps -a
Invoke-RestMethod http://localhost:8000/salud | ConvertTo-Json -Depth 6
```

`mongo-init` debe terminar con `Exited (0)` después de elegir el primario.

```powershell
docker compose --profile analitica --profile spark2 down             # detiene y conserva los datos
```

`docker compose down -v` además elimina los volúmenes de MongoDB y Valkey: se pierden el catálogo, las tareas, las sesiones y los eventos pendientes. El datalake está en la carpeta `datalake/` del repositorio y no se borra con ese comando.

## Carga de datos

Desde cero, en este orden:

```powershell
docker compose --profile datos run --rm --build generador-catalogo           # MongoDB: 60 clientes, 120 proyectos, 600 lotes, 60 000 tareas, 300 anotadores
docker compose --profile datos run --rm generador-historial                  # Parquet: unos 800 000 eventos de 100 000 tareas en 12 meses
docker compose exec spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 /opt/analitica/preparar_datos_prueba.py   # conjunto de validación
```

Ambos generadores usan semilla fija y dejan sus conteos en `evidence/`. Si los datos ya existen se detienen; para regenerarlos se agrega `--limpiar` al final del comando, lo que elimina los documentos de las cinco colecciones de `plataforma` (catálogo) o los archivos `part-hist-*` del datalake (historial).

Conjunto ampliado (opcional, §8):

```powershell
docker compose --profile datos run --rm --entrypoint python generador-historial generador_historial.py --salida /datalake/ampliado/eventos --tareas 1250000 --evidencia /evidence
```

## Simulador

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r simulador/requirements.txt -r pruebas/requirements.txt
python simulador/simulador.py --anotadores 10 --revisores 2 --duracion 60 --evidencia evidence
```

Lee los proyectos y anotadores de `dataset/salida/simulacion.json`, que produce el generador del catálogo.

## Consultas analíticas

```powershell
Invoke-RestMethod "http://localhost:8000/analitica/q1?conjunto=principal" | ConvertTo-Json -Depth 6
Invoke-RestMethod "http://localhost:8000/analitica/q5?conjunto=validacion" | ConvertTo-Json -Depth 6
```

`conjunto` acepta `principal`, `ampliado` y `validacion`. Para medir tiempos y obtener los planes de Q1 y Q3 directamente en el clúster:

```powershell
docker compose exec spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 /opt/analitica/consultas.py --datos /opt/datalake/eventos --repeticiones 3 --planes --evidencia /opt/evidence
```

## Pruebas

Todas guardan su resultado en `evidence/` con fecha, objetivo, configuración, comando y máquina.

| Prueba | Comando | Requiere |
| --- | --- | --- |
| P1 rutas, puertos y salud | `python pruebas/p1_api_salud.py` | Sistema base |
| P2 concurrencia | `python pruebas/p2_concurrencia.py` | Sistema base |
| P3 sesión | `python pruebas/p3_sesion.py` | Sistema base (unos 2,5 min) |
| P4 datalake | `python pruebas/p4_historial.py` | Sistema base |
| P4 frescura hasta Q1 | `python pruebas/p4_frescura_spark.py` | Perfil `analitica` |
| P5 Spark | `python pruebas/p5_spark.py` | Perfiles `analitica` y `spark2` |
| Verificación de Q1 a Q5 | `python pruebas/verificar_consultas.py --spark evidence/spark_consultas_<fecha>.json` | Una corrida de `consultas.py` |
| P6 carga | `python pruebas/p6_carga.py` | Catálogo cargado (unos 15 min) |
| P8 fallas | `python pruebas/p8_fallas.py` | Sistema completo (varios minutos) |
| Índices | `Get-Content pruebas/explain_indices.js \| docker compose exec -T mongo1 mongosh "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/plataforma?replicaSet=rs0" --quiet \| Out-File -Encoding utf8 evidence/indices_explain.json` | Catálogo cargado |

Conciliación de eventos perdidos y compactación de un mes cerrado:

```powershell
docker compose exec gateway python -m app.conciliar --desde 2026-11-22T00:00:00+00:00
docker compose exec historial python -m app.compactar --mes 2026-10
```

## Solución de problemas

| Síntoma | Causa y solución |
| --- | --- |
| `failed to connect to the docker API` | Docker Desktop no está abierto; iniciarlo y esperar a que `docker info` responda |
| `mongo-init` no termina con `Exited (0)` | Revisar `docker compose logs mongo-init`; repetir `docker compose up -d` |
| `/salud` reporta `caido` con `registro` en `caido` | MongoDB sin primario; esperar la elección o levantar los nodos detenidos |
| El generador dice que ya hay datos | Es la protección contra cargas duplicadas; usar `--limpiar` si se quiere recargar |
| El worker no aparece en `http://localhost:8080` | Levantar con el perfil correspondiente; el worker 2 necesita `--profile analitica --profile spark2` |
| `spark-submit` queda esperando recursos | El servicio de analítica ocupa núcleos del clúster; detenerlo con `docker compose stop analitica` o aumentar `SPARK_WORKER_CORES` |
| `/analitica/...` responde 404 | El conjunto pedido no tiene datos; cargar el historial o preparar el conjunto de validación |
| Puerto 8000 ocupado | Liberar el puerto en el host; es el único que publica el sistema |
