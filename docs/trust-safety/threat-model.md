# Modelo de amenazas

Estado: propuesto. Actores: usuario oportunista, reincidente, reportante abusivo, staff malicioso, cuenta técnica comprometida y operador con acceso a BD/host. Activos: integridad física, privacidad, catálogo permitido, mensajes, decisiones, evidencia y disponibilidad de derechos.

Fronteras: cliente no confiable → gateway → API dueña → BD/outbox → broker/consumidor; consola staff → autenticación reforzada → autorización por caso → evidencia; proveedor KYC → webhook firmado; backup → restauración aislada. Ningún claim enviado por Flutter, rol comercial ni evento sin validación autoriza por sí solo un acceso sensible.

| ID / abuso | Superficie | Control propuesto | Módulos / dueño | Prueba prevista |
|---|---|---|---|---|
| A1 drogas explícitas/ofuscadas | Nombre, descripción, nota, foto | Catálogo cerrado; revisión previa; normalización/señales; OCR; reporte | M3–M6, M10; user/admin | Corpus positivo y negativo, edición ofuscada retenida; GET públicos nunca muestran revisión pendiente; E2E-01 |
| A2 servicios sexuales encubiertos | Perfil, foto, tarifa, lugar | Categorías permitidas; primera actividad pública; precio anómalo solo señal; revisión humana | M3–M7; user/match/admin | Categoría excluida rechazada, privado inicial 422, señal no causa ban; léxico especializado inicialmente vacío |
| A3 menores | Registro y reserva | Puerto KYC adulto aprobado; gate publicar/primera reserva; reporte P0 | M2, M10; user/admin | Menor/no verificado/fake fuera DEV no puede avanzar; webhook repetido o firma inválida no cambia estado |
| A4 encuentros cortos reiterados | Reserva | Mínimo duración/anticipación, velocidad, señales agregadas | M7; match | Límites exactos ±1, concurrencia, DST, reloj de servidor, idempotencia; E2E-06 |
| A5 desvío externo | Perfil/reseña/foto/chat | Contacto público bloqueado; OCR; aviso cliente chat | M5, M6, M8, M9 | Números en palabras, handles/URLs, falsos positivos; enviar de todos modos en chat permitido; E2E-02/03 |
| A6 evadir ban | Registro/KYC | Huella HMAC con clave externa; revisión relacionada; no exponer coincidencias | M2, M14 | Misma identidad y distintas cuentas, rotación, suplantación; caso P1 y acceso retenido; E2E-05 pendiente decisión |
| A7 JWT anterior a suspensión | Todas las escrituras | Standing autoritativo, versión, proyección con frescura acotada, comprobación al commit | M1, M17; todos | JWT viejo, duplicados/desorden, partición, carrera publish/ban, expiración de cache; E2E-04 y carga p99 |
| A8 amenaza/violencia | Reserva activa | Seguridad, check-in, reporte urgente, canales públicos de emergencia revisados | M7, M10; match/admin/Flutter | Check-in una vez y con reloj servidor; ayuda genera caso/alerta; sin promesa de despacho; enlaces jurisdicción revisados |
| A9 reseña falsa/difamatoria/contacto | Reseñas | Procedencia de reserva finalizada, señales, retención y reporte; decisión humana | M9, M10; user/admin | No reseñar reserva ajena/incompleta; contacto rechazado; ocultar preserva original; pares reiterados no causan sanción automática |
| A10 fraude/suplantación | Perfil/chat/cobros | Identidad, avisos, reportes y límites; cobros externos desactivados | M2, M5, M8, M10 | Ningún badge de email significa KYC; reportar fraude no abre otros chats; proveedor pago no habilitado |
| A11 reportes para acosar | Reportes | Dedup abierta por reportante/objetivo, límites, confiabilidad y triaje | M10; admin | Concurrencia no duplica; spam no produce bans; alerta urgente legítima no se pierde; suspensión automática pendiente decisión D06 |
| A12 staff curioseando | Consola/API/evidencia | Roles separados, MFA/step-up, AccessGuard, justificación vinculada y auditoría previa | M14, M15; admin y dueños | Roles cliente/admin comercial denegados; staff fuera caso/autocaso denegado; E2E-08/09 |
| A13 pérdida/manipulación | BD/S3/host | Snapshot con versión+hash, COMPLIANCE probado, claves fuera host y anclajes independientes | M12, M15; infra/admin | Alterar/reordenar/truncar cadena detectado; borrar versión/retención negado; restauración evidencia; E2E-12 |
| A14 backup revive supresiones | Restore | Tombstones duraderos externos al backup, watermark, reapply antes de tráfico | M12; infra y dueños | Restore anterior a borrado vuelve a eliminar antes de API/workers; respeta holds mínimos; E2E-10/11 |
| A15 actividades reguladas | Catálogo/búsqueda | Lista positiva versionada, sin habilidades libres ni bypass alternativo | M3; user | Categorías retiradas no admiten nueva reserva; desconocidas no se publican; API legacy retirada y negativo de autorización |

Riesgos residuales: falsos negativos y contexto humano; identidad robada o proveedor caído; compromiso de host/DBA; pérdida del anclaje externo; colusión de revisores; falta de atención de casos; amenazas fuera de RAC. Las señales son ayudas reversibles. El alcance no incluye vigilancia general del chat ni análisis de antecedentes.

No se activará un SLA sin responsable y cobertura operativa. Las métricas no usarán nombres, IDs de usuario/caso ni consultas como etiquetas. La jurisdicción, mayoría de edad, base de tratamiento y retención requieren validación profesional antes de usuarios reales.
