---
name: banorte-ui
description: Sistema visual del chat de inversionistas: paleta, tipografía, componentes y reglas de tablas y
  citas, inspirado en el sitio de Banorte. Úsalo en cualquier pantalla o componente de frontend/.
---

# Sistema visual — Asistente de Relación con Inversionistas

Sobrio, financiero y legible: fondo claro, un solo color de acento (rojo) y gris para la estructura. La cifra
y su fuente son lo más importante de la pantalla.

## Tokens (CSS variables en :root)
--rojo: #EB0029;          /* acento de marca: barra superior, botón primario, foco */
--rojo-web: #D82E34;      /* variante web para superficies grandes */
--rojo-oscuro: #83181D;   /* hover y estado activo */
--gris-900: #343E47;      /* texto principal y títulos */
--gris-700: #5D666F;      /* panel del asistente, texto secundario */
--gris-200: #E0E0E0;      /* chips, bordes, separadores */
--gris-100: #EBEFF1;      /* fondo de la página, filas alternas */
--blanco: #FFFFFF;
--verde-ok: #2E7D32;      /* badge Verificado */
--ambar: #B26A00;         /* badge Parcial */
Contraste: texto blanco solo sobre --rojo, --rojo-web, --rojo-oscuro o --gris-700 (todos AA).

## Tipografía
system-ui (sin fuentes externas). Títulos 600, cuerpo 400, 15 px base. Cifras con
font-variant-numeric: tabular-nums.

## Estructura de la pantalla
- Barra superior --rojo de 56 px con el texto "Relación con Inversionistas · Asistente" en blanco. Sin logotipos
  ni imágenes de la marca.
- Columna izquierda plegable: documentos agrupados por periodo (GET /api/documents).
- Centro: conversación en tarjeta blanca con radio 12 px sobre fondo --gris-100.
- Derecha (o cajón en móvil): visor del PDF en la página citada.
- Pie fijo: "Información pública de relación con inversionistas. No es una recomendación de inversión."

## Componentes
- Mensaje del asistente: fondo blanco, borde izquierdo de 3 px --rojo. Mensaje del usuario: fondo --gris-200.
- Sugerencias: chips redondos (radio 999 px) --gris-200, texto --gris-900; hover --gris-700 con texto blanco.
  Cuatro: un dato puntual, una comparativa, un cálculo y una pregunta fuera de alcance.
- Citas [n]: chip pequeño con borde --rojo y texto --rojo; al hacer clic abre el visor en esa página.
- "Cómo llegué a esta respuesta": acordeón plegado con subconsultas, búsquedas (filtros y páginas) y si la
  evidencia fue suficiente.
- Badge de verificación: Verificado (--verde-ok), Parcial (--ambar), Con advertencias (--rojo-oscuro).
- Entrada: campo con borde --gris-200, foco con anillo --rojo de 2 px y botón de envío --rojo.
- Estado: línea discreta "Buscando en 2T26…", "Verificando cifras…" mientras llega el SSE; skeletons al cargar.

## Tablas en respuestas
Encabezado --gris-900 con texto blanco, filas alternas --gris-100, cifras alineadas a la derecha con
tabular-nums, negativos entre paréntesis como vienen del documento. Nunca uses rojo para negativos.

## No hacer
Gradientes, sombras grandes, animaciones decorativas, fotos, emojis, más de un color de acento, logotipos.
Debe verse bien a 390 px de ancho.