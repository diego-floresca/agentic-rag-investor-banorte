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

  const updateLastAssistant = useCallback((updater: (m: Message) => Message) => {
    setMessages((prev) => {
      const next = [...prev];
      const idx = next.length - 1;
      if (idx >= 0 && next[idx].role === "assistant") {
        next[idx] = updater({ ...next[idx] });
      }
      return next;
    });
  }, []);

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

      // Add user message
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
        // Use mock stream
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

      // Real fetch
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

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const reader = res.body?.getReader();
        if (!reader) throw new Error("No readable stream");

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Split on double newlines to get SSE blocks
          const blocks = buffer.split(/\n\n/);
          buffer = blocks.pop() ?? "";

          for (const block of blocks) {
            if (!block.trim()) continue;
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

            if (dataStr) {
              try {
                const parsed = JSON.parse(dataStr);
                processEvent(eventName, parsed);
              } catch {
                // ignore malformed JSON
              }
            }
          }
        }
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
