# Trazabilidad de aceptación

Estado: **programa en desarrollo**. La evidencia de E2E-04 está en [P03-close](P03-close.md); las demás filas expresan criterios requeridos, no pruebas aprobadas. Los tests globales corresponden a la sección 10 del prompt; no confundir A1–A15 de amenazas con A1–A9 de consola.

| E2E | Criterio | PR / módulos | Evidencia requerida |
|---|---|---|---|
| 01 | Descripción ofuscada retenida; señal privada; nada nuevo público | P07/P08; M3–M5 | API, BD y UI; conservar revisión aprobada anterior |
| 02 | Teléfono escrito/abreviatura de contacto rechazados con mensaje público | P07; M5 | Vectores Flutter/Go positivos y benignos; 422 estable |
| 03 | Foto con handle detectado por OCR no publicada | P09; M6 | Imagen sintética, cuarentena y visibilidad de asset/version |
| 04 | JWT viejo no publica, acepta ni envía después de suspensión ≤5 s | P03; M1 | Medición desde commit; varias instancias, cache fría/caliente, fallos y p99 |
| 05 | Identidad de baneado no obtiene acceso; caso P1 | P05/P11; M2/M10 | Replay/rotación/suplantación; resultado definitivo pendiente D12 |
| 06 | Reserva 20 min o con 30 min anticipación devuelve 422/código | P13; M7 | Límites exactos, reloj servidor y zonas/DST |
| 07 | P0 activa protección reversible, caso/SLA/alerta | P11; M10/M11 | Decisión D06 antes de fijar automatismo; controles A11 de abuso |
| 08 | Ban sin segundo revisor distinto es rechazado | P02/P11; M11/M14 | API y constraints BD; NULL/reintento/actor propio denegados |
| 09 | Staff no puede leer chat sin reporte/contexto/justificación | P02/P10/P11; M10/M14/M15 | Ruta directa inexistente o denegada; límites históricos preservados; auditoría previa |
| 10 | Supresión con hold elimina resto y aísla mínimo retenido | P12; M12 | Todos los dueños/proveedor/objetos; saga idempotente y aprobaciones |
| 11 | Restore antiguo no revive datos suprimidos | P12; M12 | Red aislada; tombstone externo reciente aplicado antes de APIs/workers |
| 12 | Manipular auditoría hace fallar verify | P01/P15; M15 | Edición, inserción, reorder, truncamiento y anclaje independiente |
| 13 | Loki sin canarios de documento/email/mensaje | Todos/P15; M16 | Fixtures sintéticas y búsqueda exacta en ventana del ensayo; también errores/trazas |
| 14 | Corpus cumple umbrales sin baseline/dataset vacíos | P07/P15; M5 | Versiones, positivos/negativos, recall contacto ≥0,99, FP y precisión por categoría |

## Cobertura de módulos y UX

| Módulo | Entrega | Comprobación complementaria |
|---|---|---|
| M1 standing | P03; banner S14 | Versiones monotónicas, expiraciones, conciliación y deny ante desconocido |
| M2 identidad | P05; S3/S7/S17 | Email separado, fake DEV, webhook firmado, fingerprint sin documento |
| M3 catálogo | P06; S4/S6/S8 | API libre retirada, categoría retirada, comuna, sin búsqueda sensible |
| M4 publicaciones | P08; S4/S5/S7/A4 | Snapshot inmutable, aprobación carrera, sin bypass por nombre/foto |
| M5 señales | P07; S4/S12/A7 | Léxico/versionado, límites recursos, spans originales, reglas privadas |
| M6 fotos | P09; S4/A4 | EXIF/IAM/cuarentena/OCR/pHash, URLs breves, rostro según política |
| M7 reservas | P13; S8/S9/S11 | Tiempo/lugar/velocidad, check-in y cancelación segura; no despacho de emergencia |
| M8 chat | P14; S10 | Aviso permite enviar, servidor off, rate limits, sin preview/enlaces activos |
| M9 reseñas | P14; S16/S7 | Finalizada, una por reserva, held/hidden, reporte, texto de procedencia |
| M10 reportes/casos | P11; S12/A1/A2 | Dedup/SLA, snapshot, acceso limitado, migración y retirada legacy |
| M11 acciones/apelación | P11; S13–S15/A3/A5 | Cuatro ojos, revisor diferente, aviso versionado y reversión histórica |
| M12 evidencia/privacidad | P10/P12; S17/A6 | COMPLIANCE probado, holds, autoridad, borrado/restore y claves externas |
| M13 documentos | P04; S1/S2/S4/S17 | Versiones/hash/aceptaciones, 428 sin bloquear derechos, sin casillas premarcadas |
| M14 staff | P02/P15; A1–A8 | RBAC separado, ACR/amr, step-up, conflicto de interés y acceso por propósito |
| M15 auditoría | P01/P15; A8 | Append concurrente, clave/anclaje externo, verify y no PII |
| M16 métricas/logs | Transversal/P15; A9 | Cardinalidad acotada, latencia/lag/alertas, canarios Loki |
| M17 infraestructura | P02/P15 | Credenciales mínimas, secreto/digest, TLS interno, CSP, tokens web/PKCE y CI |

S1–S17 y A1–A9 se validarán en web y tamaños móviles, incluyendo navegación directa, lector de pantalla/foco, errores de red, estado pendiente/vacío, reintento e información de permisos. No basta una captura visual para afirmar autorización correcta.

El expediente de cada PR registrará revisión exacta, comandos, entorno y resultados, artefactos de migración/restore sin PII y decisiones resueltas. Si una dependencia jurídica o externa no está aprobada, se marca bloqueada y su flag sigue desactivado. No sustituir pruebas pendientes por una afirmación de conformidad.
