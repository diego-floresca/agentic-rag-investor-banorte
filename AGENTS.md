# Reto 2 — Chat de inversionistas (RAG agéntico)

## Para quién y para qué
Reto 2 del proceso de selección de la Dirección de IA e Innovación de Banorte: 3 horas para construir un chat
RAG agéntico sobre los PDFs de relación con inversionistas de ~/data, desplegado en una URL pública, con un
diagrama de arquitectura que se defiende en una videollamada. Pesan igual: que funcione, que cada decisión tenga
una razón medida y que se pueda demostrar (diagrama, trazas, evals, seguridad).
Usuario final: un analista o inversionista que pregunta en lenguaje natural y espera la cifra exacta con la página
de donde sale. En finanzas una cifra inventada o del periodo equivocado es peor que "no lo encuentro". No damos
recomendaciones de inversión.

## Qué construimos
1. Indexación (backend/app/ingest, `make ingest`): por página detecta regiones (columnas) con palabras y
   coordenadas, extrae cada región con `pdftotext -layout` recortado, convierte cada fila de tabla en un registro
   con su periodo y publica un índice Qdrant versionado (denso + BM25). Nivel 1 determinista; nivel 2 opcional con
   LLM solo para páginas visuales o escaneadas.
2. Retrieval y MCP (backend/app/retrieval, backend/app/mcp_server): búsqueda híbrida con RRF, periodo como
   preferencia, diversidad por página y rerank opcional. Se publica como servidor MCP de solo lectura en /mcp.
3. Grafo agéntico (backend/app/agents, LangGraph): input_guard → planner → researcher×N → analyst → verifier →
   output_guard. El verificador comprueba cada cifra contra la evidencia.
4. API y frontend: FastAPI con SSE en /api y el frontend Next.js exportado como estático en /, en un solo
   contenedor de Cloud Run con el índice dentro de la imagen.
Qué NO es: no entrena modelos, no recomienda inversiones, no consulta nada fuera de ~/data.

## Cómo trabajamos
Tres terminales de Claude Code en el mismo árbol, rama main. Tu prompt dice cuál eres.
- Solo editas las rutas de tu terminal (SPEC.md, Propiedad). Si necesitas cambiar algo fuera, DETENTE y pídelo:
  escribe qué archivo, qué cambio y por qué. Nunca borres, renombres ni reimplementes un archivo ajeno.
- Archivos compartidos (solo P0 los crea; después solo con permiso de Diego): backend/pyproject.toml,
  backend/uv.lock, Makefile, backend/app/contracts.py, backend/app/config.py, SPEC.md, CLAUDE.md, AGENTS.md.
- git: `git add <tus rutas>` explícito y commit con mensaje convencional al pasar cada compuerta. Nunca
  `git add .`, `-A`, push, rebase ni reset. El push lo hace Diego.
- Si algo lleva 15 minutos sin avanzar: detente y reporta qué falla, qué intentaste y dos opciones con su costo.

## Documentación (docs/)
Cada prompt escribe su documento al pasar su compuerta, con cifras medidas. Plantilla: 1) qué es, en lenguaje de
negocio; 2) cómo encaja (recibe, entrega, con quién habla, enlace a architecture.md); 3) cómo funciona, con un
Mermaid pequeño; 4) decisiones y alternativas descartadas, en tabla; 5) contrato que toca (sección de SPEC);
6) límites y qué cambiaría en producción; 7) cómo probarlo. Describe lo que el código hace, nunca lo planeado.

## Reglas de ingeniería
- Generalizable: funciona con cualquier conjunto de PDFs en DATA_DIR. Nunca escribas en código, prompts o tests
  nombres de archivo, periodos, entidades ni cifras de un documento concreto. Lo único específico del corpus vive en
  evals/ y en backend/app/ingest/entities.yaml (generado desde lo observado).
- Cifras: la fuente de verdad es el texto extraído por código. Ningún LLM reescribe tablas. Una cifra leída de una
  imagen se marca como aproximada y el verificador no la acepta como evidencia exacta.
- Velocidad: una etapa determinista tarda milisegundos por página. Antes de un proceso de más de 2 minutos imprime
  su proyección (unidades × segundos medidos ÷ paralelismo); si excede el presupuesto, no lo lances: reporta.
- Progreso: todo proceso largo imprime `[etapa] hechas/total · Xs · ETA Ys` al menos cada 10 s.
- Python solo con uv (`uv run`, `uv add` solo en P0). Antes de usar la API de una librería, revisa la versión
  instalada (`uv pip show`) y su código en .venv. No escribas APIs de memoria.
- Contratos: usa los modelos de app/contracts.py; config solo con `from app.config import settings`.
- Secretos solo desde backend/.env o variables de entorno. Nunca imprimas ni leas en voz alta una key.
- Tests sin red con EMBED_PROVIDER=fake, LLM_PROVIDER=fake, RUNNER_MODE=fake. Llamadas reales solo en compuertas.
- Interfaz y respuestas en español. El corpus puede ser bilingüe.

## Lecciones medidas en el ensayo (obligatorias)
- El texto de tablas sale de `pdftotext -layout` recortado por región (-x -y -W -H). La extracción por bloques
  separa etiqueta y monto en líneas distintas.
- No clasifiques líneas como "tabla" o "texto" con regex sobre texto plano: produce fragmentos y falsos positivos.
- Un embedding por texto: antes de indexar, prueba que 3 textos devuelven 3 vectores distintos.
- `langchain-mcp-adapters` no es compatible con `mcp` 2.x: el cliente MCP usa el SDK `mcp` directo.
- Nunca LLM por página en el nivel 1.
- Sin `.gcloudignore` propio, gcloud usa el .gitignore y la imagen sale sin índice ni frontend.

## Comandos
make probe | make ingest [TIER=1|2] | make index-status | make index-use V=vN | make retrieval-eval | make mcp | make test | make api |
make web | make dev | make eval | make bundle | make deploy