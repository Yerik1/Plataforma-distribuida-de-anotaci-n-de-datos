function indiceUsado(etapa) {
  if (!etapa) return null;
  if (etapa.indexName) return etapa.indexName;
  if (etapa.inputStage) return indiceUsado(etapa.inputStage);
  if (etapa.inputStages) {
    for (const hija of etapa.inputStages) {
      const nombre = indiceUsado(hija);
      if (nombre) return nombre;
    }
  }
  return null;
}

function resumen(consulta, explicacion) {
  const plan = explicacion.queryPlanner.winningPlan;
  const stats = explicacion.executionStats;
  return {
    consulta,
    indice: indiceUsado(plan.queryPlan || plan) || "COLLSCAN",
    documentos_examinados: stats.totalDocsExamined,
    claves_examinadas: stats.totalKeysExamined,
    devueltos: stats.nReturned,
    ms: stats.executionTimeMillis,
  };
}

const muestra = db.tareas.findOne({}, { proyecto_id: 1, batch_id: 1 });
if (!muestra) {
  print(JSON.stringify({ error: "la colección tareas está vacía" }));
  quit(1);
}
const p = muestra.proyecto_id;

const resultados = [
  resumen(
    "candidatas: disponibles por prioridad",
    db.tareas.find({ proyecto_id: p, estado: "disponible" }).sort({ prioridad: -1 }).limit(20).explain("executionStats")
  ),
  resumen(
    "tareas abiertas de un anotador",
    db.tareas.find({ "asignacion.anotador_id": "anotador-explain", estado: "abierta" }).explain("executionStats")
  ),
  resumen("tareas de un lote", db.tareas.find({ batch_id: muestra.batch_id }).explain("executionStats")),
  resumen(
    "proyectos activos de un cliente",
    db.proyectos.find({ cliente_id: "cliente-explain", estado: "activo" }).explain("executionStats")
  ),
  resumen(
    "exportación por cursor",
    db.tareas.find({ proyecto_id: p, estado: "aprobada" }).sort({ _id: 1 }).limit(101).explain("executionStats")
  ),
  resumen(
    "exportación con skip sin índice de cursor",
    db.tareas
      .find({ proyecto_id: p, estado: "aprobada" })
      .sort({ _id: 1 })
      .skip(400)
      .limit(101)
      .hint("proyecto_estado_prioridad")
      .explain("executionStats")
  ),
];

print(JSON.stringify({ fecha: new Date().toISOString(), proyecto_muestra: p, resultados }, null, 2));
