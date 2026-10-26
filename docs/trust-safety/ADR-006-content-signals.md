# ADR-006 — Analizador compartido y léxico versionado

Estado: dirección técnica aprobada; D04/D09/D13 pendientes.

`rac-platform/contentsignals` será implementación Go única de normalización/evaluación. `policy` carga snapshots inmutables versionados y auditados. Resultados incluyen versión del analizador/política, categorías, scores, RuleIDs y spans sobre texto original. Reglas privadas y fragmentos se entregan solo a personal autorizado, nunca a mensajes de error públicos o logs.

Pipeline determinista: Unicode NFKC, minúsculas, diacríticos, confusables/homoglifos, variantes leet ambiguas, repeticiones, separadores/emojis y números escritos. Conservar correspondencia de spans y alternativas acotadas; no generar expansión combinatoria ni confundir cualquier palabra con droga. Límites de entrada/CPU/memoria, fuzzing de Unicode y casos benignos son parte del contrato. Interpretación contextual de unidad/peso/stock/entrega aporta señal, no veredicto jurídico.

Contacto público: reglas deterministas para teléfono, correo, URL, handles y mensajería. Exportar únicamente estas reglas públicas para un detector Flutter con vectores de paridad; no copiar el léxico privado en la app. Backend siempre revalida. Nombre, bio y notas con contacto → rechazo corregible; ilícitos sospechosos → revisión. OCR comparte analizador. Reseña con contacto → rechazo, otra sospecha → retención humana. Descripción de reporte ayuda al triaje pero no basta para ban.

El léxico de drogas del prompt es semilla pendiente de curación, versionado y pruebas. `sexual_services` y `minors` comienzan vacíos hasta revisión especializada; no inventar vocabulario. Una categoría vacía se muestra como no evaluada, nunca como detector que pasó pruebas. Cambiar léxico requiere diff, autor/aprobador, ensayo sobre corpus y activación explícita; rollback cambia versión, no reescribe historia.

Chat: `chat_server_signals_enabled=false` por defecto, protegido por gate jurídico/DPIA, no activado en esta fase. Detector cliente de contacto advierte y permite editar o enviar de todos modos. Texto de enlaces no clicable, sin previews ni cargas externas. No enviar el texto a un servidor de análisis para simular detección solo cliente.

Corpus separado entrenamiento/calibración y evaluación reservada, con etiquetas, procedencia y revisión sin conversaciones reales. Medir recall contacto ≥0,99 en evaluación etiquetada, precisión/recall por categoría y falsos positivos contra baseline aprobada. Dataset vacío, ausencia de positivos/negativos o baseline inexistente hace fallar el gate; no inventar 99 % de eficacia real. Evitar fuga entre corpus y reglas, reportar intervalos/tamaño y casos de regresión. E2E de ofuscación, contactos en palabras, OCR, falso positivo benigno y ausencia de detalles privados en errores.
