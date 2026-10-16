"use client";

import { useEffect, useRef, useState } from "react";
import { useChatStream } from "../lib/sse";
import Message from "./Message";
import Suggestions from "./Suggestions";
import StatusLine from "./StatusLine";
import styles from "./Chat.module.css";

interface ChatProps {
  onCitationClick: (docId: string, page: number) => void;
}

export default function Chat({ onCitationClick }: ChatProps) {
  const { messages, isStreaming, statusMsg, sendMessage, abort } =
    useChatStream();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, statusMsg]);

  function handleSend() {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    sendMessage(text);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    // Auto-resize textarea
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }

  const showSuggestions = messages.length === 0 && !isStreaming;

  return (
    <div className={styles.chat}>
      <div className={styles.messageArea}>
        {showSuggestions && (
          <div className={styles.welcome}>
            <p className={styles.welcomeTitle}>
              Asistente de Relacion con Inversionistas
            </p>
            <p className={styles.welcomeSubtitle}>
              Consulta información publica de los reportes trimestrales y anuales.
            </p>
            <Suggestions onSelect={(text) => sendMessage(text)} />
          </div>
        )}

        {messages.map((msg, i) => (
          <Message key={i} message={msg} onCitationClick={onCitationClick} />
        ))}

        {isStreaming && <StatusLine message={statusMsg} />}
        <div ref={bottomRef} />
      </div>

      <div className={styles.inputArea}>
        <div className={styles.inputRow}>
          <textarea
            ref={textareaRef}
            className={styles.textarea}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Escribe tu pregunta sobre los reportes de inversionistas…"
            rows={1}
            disabled={isStreaming}
            aria-label="Mensaje"
          />
          {isStreaming ? (
            <button
              className={`${styles.btn} ${styles.stopBtn}`}
              onClick={abort}
              aria-label="Detener"
            >
              Detener
            </button>
          ) : (
            <button
              className={`${styles.btn} ${styles.sendBtn}`}
              onClick={handleSend}
              disabled={!input.trim()}
              aria-label="Enviar"
            >
              Enviar
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
