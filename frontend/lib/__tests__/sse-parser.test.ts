/**
 * Tests para las funciones puras de parseo SSE.
 *
 * Verifica que tanto la variante LF (\n) como la variante CRLF (\r\n)
 * que emite sse-starlette produzcan los mismos eventos.
 *
 * Secuencia de referencia: respuesta a "hola"
 *   status(guard) · plan · status(output) · token×13 · done
 *   (sin citations ni verification, porque es intent conversacional)
 */

import { describe, it, expect } from "vitest";
import { splitSSEBuffer, parseSSEBlock } from "../sse";

// ─────────────────────────────────────────────────────────────────
// Fixture: secuencia SSE grabada de una respuesta a "hola"
// ─────────────────────────────────────────────────────────────────

const TOKEN_PARTS = [
  "token-01 ", "token-02 ", "token-03 ", "token-04 ", "token-05 ",
  "token-06 ", "token-07 ", "token-08 ", "token-09 ", "token-10 ",
  "token-11 ", "token-12 ", "token-13",
] as const; // 13 partes

const EXPECTED_EVENTS = [
  { event: "status", data: { type: "status", stage: "guard", message: "Validando pregunta" } },
  { event: "plan",   data: { type: "plan", intent: "conversacional", entity: "otro", subqueries: [] } },
  { event: "status", data: { type: "status", stage: "output", message: "Generando respuesta" } },
  ...TOKEN_PARTS.map((text) => ({
    event: "token",
    data: { type: "token", text },
  })),
  { event: "done", data: { type: "done", trace_id: "test-001", latency_ms: 1500, llm_calls: 2, tool_calls: 0 } },
];

/** Construye el string SSE raw usando el separador de línea indicado. */
function buildSSE(nl: "\n" | "\r\n"): string {
  return EXPECTED_EVENTS
    .map(({ event, data }) =>
      `event: ${event}${nl}data: ${JSON.stringify(data)}${nl}${nl}`
    )
    .join("");
}

/** Parsea un string SSE completo y devuelve la lista de eventos. */
function parseAll(raw: string): { event: string; data: unknown }[] {
  const results: { event: string; data: unknown }[] = [];
  const { blocks, remaining } = splitSSEBuffer(raw);
  for (const block of blocks) {
    const parsed = parseSSEBlock(block);
    if (parsed) results.push(parsed);
  }
  // Último fragmento sin \n\n final (simula cierre abrupto de stream)
  if (remaining.trim()) {
    const parsed = parseSSEBlock(remaining);
    if (parsed) results.push(parsed);
  }
  return results;
}

// ─────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────

describe("splitSSEBuffer + parseSSEBlock", () => {
  it("parsea 17 eventos con terminadores LF (\\n)", () => {
    const events = parseAll(buildSSE("\n"));
    expect(events).toHaveLength(17); // 3 status/plan + 13 tokens + 1 done
  });

  it("parsea 17 eventos con terminadores CRLF (\\r\\n) — formato sse-starlette", () => {
    const events = parseAll(buildSSE("\r\n"));
    expect(events).toHaveLength(17);
  });

  it("LF y CRLF producen eventos idénticos", () => {
    const lf   = parseAll(buildSSE("\n"));
    const crlf = parseAll(buildSSE("\r\n"));
    expect(lf).toEqual(crlf);
  });

  it("contiene exactamente 13 tokens en la secuencia CRLF", () => {
    const events = parseAll(buildSSE("\r\n"));
    const tokens = events.filter((e) => e.event === "token");
    expect(tokens).toHaveLength(13);
  });

  it("el último evento es done en la secuencia CRLF", () => {
    const events = parseAll(buildSSE("\r\n"));
    expect(events.at(-1)?.event).toBe("done");
  });

  it("el texto acumulado de los 13 tokens coincide con el esperado", () => {
    const events = parseAll(buildSSE("\r\n"));
    const text = events
      .filter((e) => e.event === "token")
      .map((e) => (e.data as { text: string }).text)
      .join("");
    expect(text).toBe(TOKEN_PARTS.join(""));
  });

  it("conserva el fragmento incompleto al final del buffer (sin \\n\\n)", () => {
    // Un buffer que llega cortado antes del cierre del bloque
    const partial = "event: token\r\ndata: {\"type\":\"token\",\"text\":\"parcial\"}";
    const { blocks, remaining } = splitSSEBuffer(partial);
    expect(blocks.filter(Boolean)).toHaveLength(0);
    expect(remaining).toBe("event: token\ndata: {\"type\":\"token\",\"text\":\"parcial\"}");
  });

  it("ignora bloques vacíos (pings de sse-starlette)", () => {
    // sse-starlette envía `: ping\r\n\r\n` como keepalive
    const raw = `: ping\r\n\r\nevent: done\r\ndata: {"type":"done","trace_id":"x","latency_ms":0,"llm_calls":0,"tool_calls":0}\r\n\r\n`;
    const events = parseAll(raw);
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("done");
  });
});
