# ADR-001. Gateway como orquestador de los servicios

| Campo | Valor |
| --- | --- |
| Proyecto | Proyecto 2. Plataforma distribuida de anotación de datos |
| Curso | TI-4601 Bases de Datos Avanzadas, Tecnológico de Costa Rica |
| Profesor | Manuel Zumbado Corrales |
| Integrantes | Emmanuel Esquivel Chavarría (2022312336); Yerik Chaves Serrano (2022437493); Jose Pablo Guerrero Duarte (2022099311) |
| Estado | Aceptada |
| Fecha | 2026-11-22 |

## Contexto

El servicio de registro no puede consultar Valkey y el servicio de sesión no puede decidir el estado definitivo de una tarea (§4). Sin embargo, `POST /tareas/siguiente` y `POST /tareas/{id}/enviar` requieren coordinar el lock en Valkey con la transición en MongoDB (§5, §6.2). El enunciado no define quién realiza esa coordinación.

## Alternativas consideradas

| Alternativa | Ventajas | Desventajas |
| --- | --- | --- |
| Gateway orquesta las llamadas a Registro y Sesión | Respeta el aislamiento de §4; un solo punto concentra la coordinación | El gateway contiene lógica adicional al enrutamiento |
| Registro llama a Sesión por HTTP | Gateway más simple | Acopla Registro a Sesión; una caída de Sesión bloquea las transiciones de estado |
| Coreografía por eventos entre servicios | Bajo acoplamiento | El cliente necesita una respuesta síncrona (200, 409, 503) que la coreografía no garantiza (§7) |

## Decisión

El gateway orquesta. Los servicios internos no se invocan entre sí.

## Justificación

Es la única opción que coordina lock y estado sin que un servicio dependa del motor de otro, y permite devolver los códigos HTTP síncronos que exige §7.

## Consecuencias

- El gateway propaga un `correlation_id` a cada servicio (§4).
- La liberación del lock cuando MongoDB falla se implementa en el gateway (§6.2).
- El comando de conciliación de eventos se ejecuta desde el gateway (ADR-007).
- El informe evidencia que ningún servicio accede al motor de otro (§4, §13).
