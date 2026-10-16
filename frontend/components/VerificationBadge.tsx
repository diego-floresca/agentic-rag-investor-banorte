"use client";

import { useState } from "react";
import styles from "./VerificationBadge.module.css";

interface VerificationBadgeProps {
  verdict: string;
  issues: string[];
}

export default function VerificationBadge({
  verdict,
  issues,
}: VerificationBadgeProps) {
  const [expanded, setExpanded] = useState(false);

  let label: string;
  let variantClass: string;

  if (verdict === "approve") {
    label = "Verificado";
    variantClass = styles.approve;
  } else if (verdict === "partial") {
    label = "Parcial";
    variantClass = styles.partial;
  } else {
    label = "Con advertencias";
    variantClass = styles.warn;
  }

  const icon = verdict === "approve" ? "✓" : verdict === "partial" ? "!" : "!";

  return (
    <div className={styles.wrapper}>
      <button
        className={`${styles.badge} ${variantClass}`}
        onClick={() => issues.length > 0 && setExpanded((v) => !v)}
        aria-expanded={issues.length > 0 ? expanded : undefined}
        disabled={issues.length === 0}
      >
        <span className={styles.icon}>{icon}</span>
        <span>{label}</span>
        {issues.length > 0 && (
          <span className={styles.chevron}>{expanded ? "▲" : "▼"}</span>
        )}
      </button>
      {expanded && issues.length > 0 && (
        <ul className={styles.issues}>
          {issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
