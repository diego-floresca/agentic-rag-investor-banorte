"use client";

import styles from "./StatusLine.module.css";

interface StatusLineProps {
  message: string;
}

export default function StatusLine({ message }: StatusLineProps) {
  if (!message) return null;
  return (
    <div className={styles.line}>
      <span className={styles.spinner} aria-hidden="true" />
      <span className={styles.text}>{message}</span>
    </div>
  );
}
