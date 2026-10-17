import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Asistente de Inversionistas · Banorte",
  description:
    "Consulta información pública de relación con inversionistas de Banorte.",
};

interface RootLayoutProps {
  children: React.ReactNode;
}

// Script inline: aplica data-theme desde localStorage antes de que React hidrate,
// evitando el flash de tema incorrecto en la carga inicial.
const themeScript = `try{var t=localStorage.getItem('theme');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}catch(e){}`;

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="es" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
