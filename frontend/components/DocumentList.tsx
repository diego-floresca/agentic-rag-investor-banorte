"use client";

import styles from "./DocumentList.module.css";

export interface DocumentInfo {
  doc_id: string;
  title: string;
  report_period: string;
  source_kind: string;
  pages: number;
}

interface DocumentListProps {
  documents: DocumentInfo[];
  isLoading: boolean;
}

function groupByPeriod(docs: DocumentInfo[]): Record<string, DocumentInfo[]> {
  return docs.reduce<Record<string, DocumentInfo[]>>((acc, doc) => {
    const key = doc.report_period || "Sin período";
    if (!acc[key]) acc[key] = [];
    acc[key].push(doc);
    return acc;
  }, {});
}

export default function DocumentList({ documents, isLoading }: DocumentListProps) {
  if (isLoading) {
    return (
      <div className={styles.list}>
        <div className={styles.header}>Documentos</div>
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className={styles.skeletonItem}>
            <div className={`skeleton ${styles.skeletonLine}`} />
            <div className={`skeleton ${styles.skeletonShort}`} />
          </div>
        ))}
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className={styles.list}>
        <div className={styles.header}>Documentos</div>
        <div className={styles.empty}>No hay documentos disponibles.</div>
      </div>
    );
  }

  const grouped = groupByPeriod(documents);
  const periods = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  return (
    <div className={styles.list}>
      <div className={styles.header}>Documentos</div>
      {periods.map((period) => (
        <div key={period} className={styles.group}>
          <div className={styles.periodHeader}>{period}</div>
          {grouped[period].map((doc) => (
            <div key={doc.doc_id} className={styles.docItem}>
              <span className={styles.docTitle}>{doc.title}</span>
              <div className={styles.docMeta}>
                <span className={styles.badge}>{doc.source_kind}</span>
                <span className={styles.pages}>{doc.pages} págs.</span>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
