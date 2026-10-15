#!/usr/bin/env bash
echo "== herramientas"
for t in uv node npm git pdftotext pdfinfo pdftoppm docker gcloud claude; do
  printf "%-10s " "$t"; command -v "$t" >/dev/null && echo ok || echo FALTA
done
echo "== máquina"
if command -v nproc >/dev/null; then echo "núcleos: $(nproc)"; else echo "núcleos: $(sysctl -n hw.ncpu)"; fi
df -h ~ | tail -1
echo "== red"
for u in https://generativelanguage.googleapis.com https://pypi.org https://registry.npmjs.org https://huggingface.co https://run.googleapis.com; do
  printf "%-45s " "$u"; curl -s -o /dev/null -m 5 -w "%{http_code}\n" "$u" || echo "sin salida"
done
echo "== key de la app"
[ -f backend/.env ] && grep -q '^GOOGLE_API_KEY=.' backend/.env && ! grep -q PEGA_TU_KEY backend/.env \
  && echo "backend/.env con key" || echo "FALTA la key en backend/.env"
echo "== corpus"; total=0
for f in ~/data/*.pdf; do
  p=$(pdfinfo "$f" 2>/dev/null | awk '/^Pages/{print $2}'); s=$(pdfinfo "$f" 2>/dev/null | awk -F': *' '/^Page size/{print $2}')
  total=$((total + ${p:-0})); printf "%5s p  %-28s %s\n" "${p:-?}" "$s" "$(basename "$f")"
done
echo "TOTAL páginas: $total"