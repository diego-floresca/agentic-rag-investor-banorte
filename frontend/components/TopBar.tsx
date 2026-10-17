"use client";

import styles from "./TopBar.module.css";

interface TopBarProps {
  onToggleSidebar: () => void;
  isDark: boolean;
  onToggleDark: () => void;
}

export default function TopBar({ onToggleSidebar, isDark, onToggleDark }: TopBarProps) {
  return (
    <header className={styles.bar}>
      <button
        className={styles.hamburger}
        onClick={onToggleSidebar}
        aria-label="Alternar menú lateral"
      >
        <span className={styles.hamburgerIcon}>&#9776;</span>
      </button>

      <div className={styles.brand}>
        <div className={styles.logoMark}>B</div>
        <div className={styles.titleGroup}>
          <span className={styles.title}>Relación con Inversionistas</span>
          <span className={styles.subtitle}>Asistente · Grupo Financiero Banorte</span>
        </div>
      </div>

      <div className={styles.actions}>
        <button
          className={styles.iconBtn}
          onClick={onToggleDark}
          aria-label={isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
          title={isDark ? "Modo claro" : "Modo oscuro"}
        >
          {isDark ? "☀" : "🌙"}
        </button>
      </div>
    </header>
  );
}
