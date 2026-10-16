"use client";

import { useState } from "react";
import styles from "./TraceAccordion.module.css";
import type { TraceEvent } from "../lib/sse";

interface TraceAccordionProps {
  traceEvents: TraceEvent[];
}

function formatEventSummary(ev: TraceEvent): string {
  const d = ev.data as Record<string, unknown>;
  switch (ev.type) {
    case "plan": {
      const subs = (d.subqueries as Array<{ query_es: string }>) ?? [];
      return `Plan: ${subs.map((s) => s.query_es).join("; ")}`;
    }
    case "tool_call": {
      const args = d.args as Record<string, unknown> | undefined;
      const argsStr = args ? JSON.stringify(args).slice(0, 60) : "";
      return `Herramienta: ${d.tool} ${argsStr}`;
    }
    case "tool_result": {
      return `Resultado: ${d.n_results ?? "?"} resultados, páginas: ${
        Array.isArray(d.pages) ? (d.pages as number[]).join(", ") : "—"
      }`;
    }
    case "finding": {
      const sufficient = d.sufficient ? "Suficiente" : "Insuficiente";
      const gap = d.gap ? ` · Brecha: ${d.gap}` : "";
      return `Hallazgo (${d.subquery_id}): ${sufficient}${gap}`;
    }
    default:
      return JSON.stringify(d).slice(0, 80);
  }
}

export default function TraceAccordion({ traceEvents }: TraceAccordionProps) {
  const [open, setOpen] = useState(false);

  if (traceEvents.length === 0) return null;

  return (
    <div className={styles.accordion}>
      <button
        className={styles.trigger}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>Como llegue a esta respuesta</span>
        <span className={styles.chevron}>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <ul className={styles.list}>
          {traceEvents.map((ev, i) => (
            <li key={i} className={styles.item}>
              <span className={styles.typeTag}>{ev.type}</span>
              <span className={styles.summary}>{formatEventSummary(ev)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
