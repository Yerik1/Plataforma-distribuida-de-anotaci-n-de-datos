# Conjunto de prueba para Q1 a Q5

46 eventos únicos de 9 tareas, más un evento duplicado de `t01` para verificar la deduplicación por `event_id` (§6.3). Fecha de referencia de Q1: 2026-11-20. SLA: 48 horas.

| Tarea | Proyecto (cliente, modalidad) | Recorrido | Caso que cubre |
| --- | --- | --- | --- |
| t01 | p1 (c1, lidar) | a1 anota 30 min, aprobada a las 2 h | Caso base; su evento `aprobada` está duplicado |
| t02 | p1 (c1, lidar) | a2 anota 60 min, rechazada; a3 anota 20 min, aprobada 49 h después de la primera toma | Rechazo y retrabajo; el reloj del SLA no se reinicia (Q5); cuenta como aprobada en Q2 y como rechazo en Q4 |
| t03 | p2 (c1, imagen) | a1 anota 10 min, aprobada a las 2 h | Caso base |
| t04 | p2 (c1, imagen) | a4 anota 45 min, rechazada sin retrabajo | Decisión final rechazada (Q2) |
| t05 | p3 (c2, texto) | a3 anota 5 min, aprobada a las 50 h | Incumple el SLA (Q5) |
| t06 | p3 (c2, texto) | a2 anota 15 min, aprobada a las 1,5 h | Caso base |
| t07 | p1 (c1, lidar) | a1, aprobada el 2026-07-01 | Fuera de la ventana de 90 días de Q1; mes distinto en Q2 |
| t08 | p3 (c2, texto) | a4 anota 30 min, sin revisión | Entra en Q3; no entra en Q2, Q4 ni Q5 |
| t09 | p2 (c1, imagen) | Dos rechazos (a2, a1) y aprobación con a4 | Varias filas `rechazada` en Q4; equipo de la toma final en Q2 |

Equipos: `eqA` (a1, a2) y `eqB` (a3, a4).

Los resultados esperados están en `esperados.json`. Los percentiles siguen la definición de rango más cercano, que coincide con `percentile_approx` sobre conjuntos pequeños.
