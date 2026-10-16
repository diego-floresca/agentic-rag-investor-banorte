"use client";

import { useCallback, useRef, useState } from "react";
import { API_BASE } from "./config";
import { mockStream } from "./mock";

export interface Citation {
  n: number;
  chunk_id: string;
  doc_id: string;
  title: string;
  report_period: string;
  page: number;
}

export interface TraceEvent {
  type: string;
  data: unknown;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  verification: { verdict: string; issues: string[] } | null;
  traceEvents: TraceEvent[];
  status: string;
  done: boolean;
  error: string | null;
}

// ─────────────────────────────────────────────────────────────────
// Funciones puras de parseo SSE (exportadas para tests)
// ─────────────────────────────────────────────────────────────────

/**
 * Normaliza \r\n y \r sueltos a \n, luego parte el buffer en bloques SSE
 * completos (separados por \n\n) devolviendo el fragmento incompleto restante.
 * Esto corrige sse-starlette, que usa \r\n como terminador de línea.
 */
export function splitSSEBuffer(
  buffer: string
): { blocks: string[]; remaining: string } {
  const normalized = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const parts = normalized.split("\n\n");
  const remaining = parts.pop() ?? "";
  return { blocks: parts, remaining };
}

/**
 * Parsea un bloque SSE ya completo (sin separadores de bloque).
 * Devuelve { event, data } o null si no hay campo data válido.
 */
export function parseSSEBlock(
  block: string
): { event: string; data: unknown } | null {
  if (!block.trim()) return null;
  const lines = block.split("\n");
  let eventName = "message";
  let dataStr = "";
  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataStr = line.slice(5).trim();
    }
  }
  if (!dataStr) return null;
  try {
    return { event: eventName, data: JSON.parse(dataStr) };
  } catch {
    return null;
  }
}

// ─────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────

const USE_MOCK = process.env.NEXT_PUBLIC_MOCK === "1";

function newAssistantMessage(): Message {
  return {
    role: "assistant",
    content: "",
    citations: [],
    verification: null,
    traceEvents: [],
    status: "",
    done: false,
    error: null,
  };
}

export function useChatStream(apiBase: string = API_BASE) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const sessionId = useRef(`web-${Date.now()}`);

  const updateLastAssistant = useCallback(
    (updater: (m: Message) => Message) => {
      setMessages((prev) => {
        const next = [...prev];
        const idx = next.length - 1;
        if (idx >= 0 && next[idx].role === "assistant") {
          next[idx] = updater({ ...next[idx] });
        }
        return next;
      });
    },
    []
  );

  const processEvent = useCallback(
    (event: string, data: unknown) => {
      switch (event) {
        case "token": {
          const d = data as { text: string };
          updateLastAssistant((m) => ({ ...m, content: m.content + d.text }));
          break;
        }
        case "citations": {
          const d = data as { items: Citation[] };
          updateLastAssistant((m) => ({ ...m, citations: d.items }));
          break;
        }
        case "verification": {
          const d = data as { verdict: string; issues: string[] };
          updateLastAssistant((m) => ({ ...m, verification: d }));
          break;
        }
        case "status": {
          const d = data as { message: string };
          setStatusMsg(d.message);
          updateLastAssistant((m) => ({ ...m, status: d.message }));
          break;
        }
        case "plan":
        case "tool_call":
        case "tool_result":
        case "finding": {
          updateLastAssistant((m) => ({
            ...m,
            traceEvents: [...m.traceEvents, { type: event, data }],
          }));
          break;
        }
        case "done": {
          updateLastAssistant((m) => ({ ...m, done: true }));
          setIsStreaming(false);
          setStatusMsg("");
          break;
        }
        case "error": {
          const d = data as { message?: string } | string;
          const msg =
            typeof d === "string" ? d : d.message ?? "Error desconocido";
          updateLastAssistant((m) => ({ ...m, error: msg, done: true }));
          setIsStreaming(false);
          setStatusMsg("");
          break;
        }
      }
    },
    [updateLastAssistant]
  );

  const sendMessage = useCallback(
    async (text: string) => {
      if (isStreaming) return;

      const userMsg: Message = {
        role: "user",
        content: text,
        citations: [],
        verification: null,
        traceEvents: [],
        status: "",
        done: true,
        error: null,
      };

      setMessages((prev) => [...prev, userMsg, newAssistantMessage()]);
      setIsStreaming(true);
      setStatusMsg("Iniciando…");

      if (USE_MOCK) {
        try {
          for await (const ev of mockStream()) {
            processEvent(ev.event, ev.data);
          }
        } catch {
          updateLastAssistant((m) => ({
            ...m,
            error: "Error en modo de prueba",
            done: true,
          }));
          setIsStreaming(false);
          setStatusMsg("");
        }
        return;
      }

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      try {
        const res = await fetch(`${apiBase}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId.current,
            message: text,
          }),
          signal: ctrl.signal,
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const reader = res.body?.getReader();
        if (!reader) throw new Error("No readable stream");

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();

          if (value) {
            buffer += decoder.decode(value, { stream: true });
            const { blocks, remaining } = splitSSEBuffer(buffer);
            buffer = remaining;
            for (const block of blocks) {
              const parsed = parseSSEBlock(block);
              if (parsed) processEvent(parsed.event, parsed.data);
            }
          }

          if (done) {
            // Último fragmento si el stream cerró sin \n\n final
            if (buffer.trim()) {
              const parsed = parseSSEBlock(buffer);
              if (parsed) processEvent(parsed.event, parsed.data);
            }
            break;
          }
        }

        // Garantía: si done nunca llegó (corte de red), limpiar estado
        setIsStreaming(false);
        setStatusMsg("");
        updateLastAssistant((m) => (m.done ? m : { ...m, done: true }));
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          updateLastAssistant((m) => ({ ...m, done: true }));
        } else {
          const msg =
            err instanceof Error ? err.message : "Error de conexión";
          updateLastAssistant((m) => ({ ...m, error: msg, done: true }));
        }
        setIsStreaming(false);
        setStatusMsg("");
      }
    },
    [isStreaming, apiBase, processEvent, updateLastAssistant]
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setStatusMsg("");
  }, []);

  return { messages, isStreaming, statusMsg, sendMessage, abort };
}
