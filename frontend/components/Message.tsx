"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import VerificationBadge from "./VerificationBadge";
import TraceAccordion from "./TraceAccordion";
import styles from "./Message.module.css";
import type { Message as MessageType, Citation } from "../lib/sse";

interface MessageProps {
  message: MessageType;
  onCitationClick: (docId: string, page: number) => void;
}

interface CitationChipProps {
  n: number;
  citation: Citation | undefined;
  onClick: () => void;
}

function CitationChip({ n, citation, onClick }: CitationChipProps) {
  return (
    <button
      className={styles.citationChip}
      onClick={onClick}
      title={citation ? `${citation.title} p. ${citation.page}` : `Cita ${n}`}
      aria-label={
        citation
          ? `Ver cita ${n}: ${citation.title}, página ${citation.page}`
          : `Cita ${n}`
      }
    >
      {n}
    </button>
  );
}

function renderTextWithCitations(
  text: string,
  citations: Citation[],
  onCitationClick: (docId: string, page: number) => void
): React.ReactNode[] {
  // Match [N] patterns
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (match) {
      const n = parseInt(match[1], 10);
      const citation = citations.find((c) => c.n === n);
      return (
        <CitationChip
          key={i}
          n={n}
          citation={citation}
          onClick={() => {
            if (citation) onCitationClick(citation.doc_id, citation.page);
          }}
        />
      );
    }
    return part;
  });
}

export default function Message({ message, onCitationClick }: MessageProps) {
  const isUser = message.role === "user";

  const markdownComponents: Components = {
    p({ children }) {
      // Process text nodes inside paragraphs for citation chips
      const processChildren = (
        nodes: React.ReactNode
      ): React.ReactNode => {
        if (typeof nodes === "string") {
          const rendered = renderTextWithCitations(
            nodes,
            message.citations,
            onCitationClick
          );
          // If nothing changed, return string
          if (rendered.length === 1 && rendered[0] === nodes) return nodes;
          return rendered;
        }
        if (Array.isArray(nodes)) {
          return nodes.map((child, i) => {
            if (typeof child === "string") {
              const rendered = renderTextWithCitations(
                child,
                message.citations,
                onCitationClick
              );
              if (rendered.length === 1 && rendered[0] === child) return child;
              return <span key={i}>{rendered}</span>;
            }
            return child;
          });
        }
        return nodes;
      };

      return <p>{processChildren(children)}</p>;
    },
    table({ children }) {
      return (
        <div className={styles.tableWrapper}>
          <table>{children}</table>
        </div>
      );
    },
  };

  return (
    <div className={`${styles.message} ${isUser ? styles.user : styles.assistant}`}>
      <div className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble}`}>
        {isUser ? (
          <p className={styles.userText}>{message.content}</p>
        ) : (
          <>
            <div className={styles.markdownBody}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {message.content || (message.error ? "" : "")}
              </ReactMarkdown>
            </div>

            {message.error && (
              <div className={styles.errorMsg}>{message.error}</div>
            )}

            {message.verification && (
              <div className={styles.footer}>
                <VerificationBadge
                  verdict={message.verification.verdict}
                  issues={message.verification.issues}
                />
              </div>
            )}

            {message.citations.length > 0 && (
              <div className={styles.citationsList}>
                {message.citations.map((c) => (
                  <button
                    key={c.n}
                    className={styles.citationEntry}
                    onClick={() => onCitationClick(c.doc_id, c.page)}
                  >
                    <span className={styles.citationNum}>[{c.n}]</span>
                    <span className={styles.citationLabel}>
                      {c.title} · p.{c.page} · {c.report_period}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {message.traceEvents.length > 0 && (
              <TraceAccordion traceEvents={message.traceEvents} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
