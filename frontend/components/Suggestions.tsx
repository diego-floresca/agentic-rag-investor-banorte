"use client";

import styles from "./Suggestions.module.css";

interface SuggestionsProps {
  onSelect: (text: string) => void;
}

const SUGGESTIONS = [
  "¿Cuáles fueron los ingresos de intereses netos en el 2T26?",
  "Compara la utilidad neta del 1T26 vs 2T26",
  "¿Cuánto creció la cartera de crédito en el último año?",
  "¿Recomiendas comprar acciones de Banorte?",
];

export default function Suggestions({ onSelect }: SuggestionsProps) {
  return (
    <div className={styles.container}>
      <p className={styles.hint}>Preguntas frecuentes:</p>
      <div className={styles.chips}>
        {SUGGESTIONS.map((text) => (
          <button
            key={text}
            className={styles.chip}
            onClick={() => onSelect(text)}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}
