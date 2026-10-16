# SKILL: Contabilidad Bancaria — Lectura de Estados Financieros

Cargado por el analista antes de interpretar tablas del corpus.

## 1. Saldos vs. flujos
- **Saldo** (stock): valor en un punto en el tiempo; vive en el balance (activo, pasivo, capital). Ejemplo: cartera total al 2T26 = 1,042,000 mdp.
- **Flujo** (variación periódica): valor acumulado en un periodo; vive en el estado de resultados. Ejemplo: ingresos de intereses netos del 2T26 = 37,614 mdp.
- Nunca sumes saldos de periodos distintos. Nunca compares un flujo con un saldo directamente sin ajustar por el periodo de referencia.

## 2. MIN (Margen de Interés Neto)
- Fórmula: `MIN = Ingresos de Intereses Netos / Activos Productivos Promedio`
- Se expresa en porcentaje anualizado.
- Un MIN reportado como "6.2%" en un trimestre ya está anualizado.
- No dividas ingresos trimestrales entre activos sin anualizar × 4.

## 3. Etapas de crédito (IFRS 9)
- **Etapa 1**: Créditos vigentes sin deterioro significativo. Reserva = PD × LGD × EAD (12 meses).
- **Etapa 2**: Incremento significativo en riesgo crediticio. Reserva = PD × LGD × EAD (vida útil).
- **Etapa 3**: Créditos en incumplimiento / cartera vencida. Reserva cubre pérdida esperada total.
- El "costo de riesgo" o "costo crediticio" es la provisión del periodo / cartera promedio, anualizado.

## 4. Costo de riesgo
- `Costo de riesgo = Provisiones del periodo / Cartera bruta promedio × (12 / meses del periodo)`
- Se expresa en porcentaje. Un valor de 1.2% es distinto de 1.2 mdp.
- Las provisiones son un flujo (gasto del periodo); la cartera bruta es un saldo.

## 5. Índice de eficiencia
- `Eficiencia = Gastos de administración / Ingresos totales`
- **Menor es mejor**: 30% significa que de cada peso de ingreso se gastan 30 centavos en operación.
- Ingresos totales = Ingresos de intereses netos + Comisiones netas + Resultado por intermediación + Otros ingresos.

## 6. ICAP (Índice de Capitalización)
- `ICAP = Capital neto / Activos ponderados por riesgo (APR)`
- Mínimo regulatorio en México: 8% (Tier 1 + Tier 2) o 10.5% con colchón de conservación.
- Un ICAP de 16.8% significa capital holgado.
- Tier 1 = capital básico (acciones + utilidades retenidas); Tier 2 = instrumentos subordinados.

## 7. ROE y ROTE
- `ROE = Utilidad neta / Capital contable promedio` (anualizado si es trimestral)
- `ROTE = Utilidad neta / (Capital contable – Activos intangibles) promedio` (anualizado)
- ROTE > ROE cuando hay goodwill o intangibles significativos.
- Ambos se anualizan multiplicando por (12 / meses del periodo).

## 8. Cuentas de orden
- No forman parte del balance principal. Aparecen al pie del balance o en nota.
- Ejemplos: avales, garantías otorgadas, fideicomisos.
- No sumes cuentas de orden a activos del balance al calcular totales.

## 9. Cómo leer un subtotal en el formato de registro
- `Créditos comerciales (subtotal) | 1T26: 710,000 | 2T26: 715,000` → 710,000 es la suma de los renglones hijos para 1T26.
- Si ves `(subtotal)` en el text del registro, ese valor ya incluye los hijos; no los vuelvas a sumar.
- Si header_ok=false, los valores no tienen encabezado; confirma el periodo con get_page antes de citarlos como exactos.

## 10. Señales de alerta en evidencia
- `approximate=true` → cifra leída de imagen; cítala como "aproximadamente" y no la uses como insumo exacto en cálculos.
- `header_ok=false` → encabezados no fiables; usa get_page para confirmar qué columna corresponde a qué periodo.
- `units` nulo pero cifras grandes → preguntar al analista si la escala es mdp, miles o pesos.
