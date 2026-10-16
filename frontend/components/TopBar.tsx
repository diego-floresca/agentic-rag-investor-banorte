"use client";

import styles from "./TopBar.module.css";

interface TopBarProps {
  onToggleSidebar: () => void;
}

export default function TopBar({ onToggleSidebar }: TopBarProps) {
  return (
    <header className={styles.bar}>
      <button
        className={styles.hamburger}
        onClick={onToggleSidebar}
        aria-label="Alternar menú lateral"
      >
        <span className={styles.hamburgerIcon}>&#9776;</span>
      </button>
      <span className={styles.title}>
        Relación con Inversionistas &middot; Asistente
      </span>
    </header>
  );
}
