export interface SSEEvent {
  event: string;
  data: unknown;
}

const MOCK_EVENTS: SSEEvent[] = [
  {
    event: "status",
    data: { stage: "planner", message: "Analizando tu pregunta…" },
  },
  {
    event: "plan",
    data: {
      intent: "comparativa",
      entity: "grupo",
      subqueries: [
        {
          id: "sq1",
          query_es: "ingresos de intereses netos por periodo",
          query_en: "net interest income by period",
          filters: { prefer_periods: ["2T26", "1T26"] },
        },
      ],
    },
  },
  {
    event: "status",
    data: { stage: "researcher", message: "Buscando en 2T26…" },
  },
  {
    event: "tool_call",
    data: {
      agent: "researcher",
      subquery_id: "sq1",
      tool: "search_documents",
      args: { query: "ingresos de intereses netos" },
    },
  },
  {
    event: "tool_result",
    data: {
      agent: "researcher",
      subquery_id: "sq1",
      tool: "search_documents",
      n_results: 3,
      pages: [4, 7, 12],
    },
  },
  {
    event: "finding",
    data: { subquery_id: "sq1", sufficient: true, gap: null },
  },
  {
    event: "status",
    data: { stage: "analyst", message: "Calculando variación…" },
  },
  {
    event: "status",
    data: { stage: "verifier", message: "Verificando cifras…" },
  },
  {
    event: "verification",
    data: { verdict: "approve", issues: [] },
  },
  {
    event: "token",
    data: { text: "## Ingresos de Intereses Netos\n\n" },
  },
  {
    event: "token",
    data: { text: "| Período | Monto (Mmdp) |\n|---|---|\n" },
  },
  {
    event: "token",
    data: { text: "| 1T26 | 39,477 |\n| 2T26 | 37,614 |\n\n" },
  },
  {
    event: "token",
    data: {
      text: "La variación trimestral fue de **(5%)**, como se muestra en el reporte del 2T26 [1].",
    },
  },
  {
    event: "citations",
    data: {
      items: [
        {
          n: 1,
          chunk_id: "doc1:p4:c2",
          doc_id: "reporte-2t26",
          title: "Reporte 2T26",
          report_period: "2T26",
          page: 4,
        },
      ],
    },
  },
  {
    event: "done",
    data: {
      trace_id: "mock-001",
      latency_ms: 1800,
      llm_calls: 3,
      tool_calls: 2,
    },
  },
];

export async function* mockStream(): AsyncGenerator<SSEEvent> {
  for (const ev of MOCK_EVENTS) {
    await new Promise((resolve) => setTimeout(resolve, 150));
    yield ev;
  }
}
