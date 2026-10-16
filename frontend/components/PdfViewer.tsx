"use client";

import styles from "./PdfViewer.module.css";
import { API_BASE } from "../lib/config";

interface PdfViewerProps {
  docId: string;
  page: number;
  onClose: () => void;
}

export default function PdfViewer({ docId, page, onClose }: PdfViewerProps) {
  const src = `${API_BASE}/files/${encodeURIComponent(docId)}#page=${page}`;

  return (
    <div className={styles.viewer}>
      <div className={styles.header}>
        <div className={styles.info}>
          <span className={styles.docId}>{docId}</span>
          <span className={styles.pageLabel}>p. {page}</span>
        </div>
        <button className={styles.closeBtn} onClick={onClose} aria-label="Cerrar visor">
          &#x2715;
        </button>
      </div>
      <div className={styles.frameWrapper}>
        <iframe
          className={styles.frame}
          src={src}
          title={`${docId} página ${page}`}
        />
      </div>
    </div>
  );
}
