"use client";

import { useEffect, useState } from "react";
import TopBar from "../components/TopBar";
import DocumentList from "../components/DocumentList";
import Chat from "../components/Chat";
import PdfViewer from "../components/PdfViewer";
import type { DocumentInfo } from "../components/DocumentList";
import { API_BASE } from "../lib/config";

interface PdfView {
  docId: string;
  page: number;
}

export default function Home() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [pdfView, setPdfView] = useState<PdfView | null>(null);
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("theme");
    if (saved === "dark") {
      setIsDark(true);
      document.documentElement.setAttribute("data-theme", "dark");
    }
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/documents`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: DocumentInfo[]) => {
        setDocuments(data);
        setDocsLoading(false);
      })
      .catch(() => {
        // Graceful: show empty list
        setDocuments([]);
        setDocsLoading(false);
      });
  }, []);

  function handleCitationClick(docId: string, page: number) {
    setPdfView({ docId, page });
  }

  function handleToggleDark() {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.setAttribute("data-theme", next ? "dark" : "");
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  function handleToggleSidebar() {
    setSidebarOpen((v) => !v);
  }

  return (
    <div className="app-shell">
      <TopBar onToggleSidebar={handleToggleSidebar} isDark={isDark} onToggleDark={handleToggleDark} />

      <div className="app-body">
        <aside
          className={`app-sidebar${sidebarOpen ? "" : " collapsed"}`}
          aria-hidden={!sidebarOpen}
        >
          <DocumentList documents={documents} isLoading={docsLoading} />
        </aside>

        <main className="app-main">
          <Chat onCitationClick={handleCitationClick} />
        </main>

        {pdfView && (
          <aside className="app-pdf">
            <PdfViewer
              docId={pdfView.docId}
              page={pdfView.page}
              onClose={() => setPdfView(null)}
            />
          </aside>
        )}
      </div>

      <footer className="app-footer">
        Informacion publica de relacion con inversionistas. No es una recomendacion de inversion.
      </footer>
    </div>
  );
}
