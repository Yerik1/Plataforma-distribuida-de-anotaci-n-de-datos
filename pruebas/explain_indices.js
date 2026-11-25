function indiceUsado(etapa) {
  if (!etapa) return null;
  if (etapa.indexName) return etapa.indexName;
  if (etapa.inputStage) return indiceUsado(etapa.inputStage);
  for (const hija of etapa.inputStages || []) {
    const nombre = indiceUsado(hija);
    if (nombre) return nombre;
  }
  return null;
}

function etapas(etapa, lista = []) {
  if (!etapa) return lista;
  lista.push(etapa.stage);
  etapas(etapa.inputStage, lista);
  (etapa.inputStages || []).forEach((hija) => etapas(hija, lista));
  return lista;
}

function resumen(consulta, explicacion) {
  const plan = explicacion.queryPlanner.winningPlan;
  const raiz = plan.queryPlan || plan;
  const stats = explicacion.executionStats;
  const lista = etapas(raiz);
  return {
    consulta,
    indice: indiceUsado(raiz) || "COLLSCAN",
    etapas: lista,
    orden_en_memoria: lista.includes("SORT"),
    documentos_examinados: stats.totalDocsExamined,
    claves_examinadas: stats.totalKeysExamined,
    devueltos: stats.nReturned,
    ms: stats.executionTimeMillis,
  };
}

const proyecto = db.proyectos.findOne({ nombre: "Proyecto 001" });
if (!proyecto) {
  print(JSON.stringify({ error: "no se encontró el catálogo; ejecute el generador del catálogo" }));
  quit(1);
}
const p = proyecto._id;
const tarea = db.tareas.findOne({ proyecto_id: p });
const abierta = db.tareas.findOne({ estado: "abierta" });
const anotador = abierta ? abierta.asignacion.anotador_id : db.anotadores.findOne({ rol: "anotador" })._id;
const filtroPagina = { proyecto_id: p, estado: "disponible" };
const corte = db.tareas.find(filtroPagina).sort({ _id: 1 }).skip(399).limit(1).next()._id;
const haceUnaHora = new Date(Date.now() - 3600 * 1000);
const filtroConciliacion = { actualizada_en: { $gte: haceUnaHora }, ultimo_evento: { $ne: null } };

const resultados = [
  resumen(
    "candidatas: disponibles por prioridad",
    db.tareas.find({ proyecto_id: p, estado: "disponible" }).sort({ prioridad: -1 }).limit(20).explain("executionStats")
  ),
  resumen(
    "tareas abiertas de un anotador",
    db.tareas.find({ "asignacion.anotador_id": anotador, estado: "abierta" }).explain("executionStats")
  ),
  resumen("tareas de un lote", db.tareas.find({ batch_id: tarea.batch_id }).explain("executionStats")),
  resumen(
    "proyectos activos de un cliente",
    db.proyectos.find({ cliente_id: proyecto.cliente_id, estado: "activo" }).explain("executionStats")
  ),
  resumen(
    "pagina 5 por cursor (indice proyecto_estado_id)",
    db.tareas.find({ ...filtroPagina, _id: { $gt: corte } }).sort({ _id: 1 }).limit(101).explain("executionStats")
  ),
  resumen(
    "pagina 5 por skip (indice proyecto_estado_id)",
    db.tareas.find(filtroPagina).sort({ _id: 1 }).skip(400).limit(101).explain("executionStats")
  ),
  resumen(
    "pagina 5 por skip sin indice de cursor",
    db.tareas
      .find(filtroPagina)
      .sort({ _id: 1 })
      .skip(400)
      .limit(101)
      .hint("proyecto_estado_prioridad")
      .explain("executionStats")
  ),
  resumen(
    "conciliacion: tareas actualizadas en la ultima hora (indice actualizada)",
    db.tareas.find(filtroConciliacion).sort({ actualizada_en: 1, _id: 1 }).limit(1000).explain("executionStats")
  ),
  resumen(
    "conciliacion sin indice",
    db.tareas
      .find(filtroConciliacion)
      .sort({ actualizada_en: 1, _id: 1 })
      .limit(1000)
      .hint({ $natural: 1 })
      .explain("executionStats")
  ),
];

print(
  JSON.stringify(
    {
      fecha: new Date().toISOString(),
      proyecto_muestra: p,
      tareas_del_proyecto: db.tareas.countDocuments({ proyecto_id: p }),
      tareas_totales: db.tareas.estimatedDocumentCount(),
      resultados,
    },
    null,
    2
  )
);