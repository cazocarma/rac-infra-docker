# ADR-004 — Evidencia, retención, legal holds y supresión

Estado: dirección técnica aprobada. Proveedor efectivo, plazos y base jurídica D08/D10/D11 pendientes. No activar retención irreversible de datos reales durante desarrollo.

## Diseño

Puerto `EvidenceStore`: capturar bytes/versiones, obtener metadata de retención, comprobar hash, emitir acceso acotado y verificar capacidad del backend. Dominio no importa SDK S3. Adaptador fake DEV no se presenta como WORM. Cada snapshot guarda bucket/key/version_id, SHA-256, captured_at, actor/procedencia, propósito y política aplicada; no URLs firmadas persistentes. La captura fija solo el contenido relevante permitido por el límite del reporte. Descripciones y evidencia privadas cifradas con claves administradas fuera del host de aplicación.

Separar cuarentena, medios aprobados y evidencia con IAM distinto. Usuarios no tienen acceso directo a evidencia. Auditoría y AccessGuard también cubren previews, descargas y exports. La evidencia no autoriza recopilar chats completos ni documentos de identidad. Minimización antes de la captura y aislamiento de datos ajenos no necesarios; acceso al original indispensable queda restringido y trazado.

## Prueba de capacidad obligatoria

Con el digest RustFS configurado, crear un bucket de prueba aislado con versioning y Object Lock habilitados al crearlo. Retención COMPLIANCE corta y objetos sintéticos. Verificar Put/GetObjectRetention y hora servidor; intentar borrar la **versión protegida**, acortar retención y eludirla con credencial privilegiada. Comprobar que sobrescritura crea otra versión y no altera bytes/version_id antiguos. DeleteObject sin versionId puede crear delete marker: comprobar que la versión protegida sigue íntegra, no confundir marcador con destrucción. Probar expiración, reinicio, restore y holds según las capacidades reales del proveedor.

Resultado y versiones deben adjuntarse al gate. Si falla una propiedad requerida, el adaptador rechaza activar evidencia real; elegir proveedor alternativo con aprobación. No degradar silenciosamente a bucket mutable ni confundir S3 compatible con COMPLIANCE verificado. WORM no protege contra pérdida del disco/host: necesita copia independiente y recuperación ensayada.

## Retención y derechos

Motor versionado por clase, finalidad y estado. Los 90 días de chat, plazos de evidencia/apelación y cualquier año de retención son propuestas no activas. Legal revisa necesidad, base, excepciones y fecha de aplicación normativa. COMPLIANCE puede impedir borrar antes del plazo: aprobar antes de escribir datos y evitar sobreconservación. Holds jurídicos son específicos, mínimos, revisables, con dos aprobadores legal distintos, justificación cifrada y evento auditable; no son una excusa para congelar toda la cuenta indefinidamente.

Saga de privacidad: user, match, chat, alert, T&S, Keycloak, objetos y proveedor KYC. Exportación y supresión autenticadas, con estados/reintentos/idempotencia; eliminar lo no retenido y aislar solo lo necesario. No borrar claves compartidas que hagan ilegibles pruebas sujetas a hold. Los identificadores HMAC son seudónimos, siguen requiriendo protección y política de retención. La auditoría canónica no contendrá PII; referencias privadas se pueden criptosuprimir donde proceda sin romper hashes, dejando eventos de supresión verificables.

## Restauración

Tombstones mínimos y watermark firmado en almacenamiento independiente del backup que se restaura. Restore en red aislada; verificar cadena/anclajes y catálogo de objetos; recuperar el registro de supresiones más reciente; `reapply-erasures` en todos los dueños antes de habilitar APIs, workers, relay o broker. Si falta registro confiable o hay divergencia, no abrir tráfico. Probar restore anterior a una supresión y una combinación con legal hold. La copia externa sigue sin activar por instrucción previa; producción queda bloqueada mientras no exista un destino aprobado y el ensayo.

## Requerimientos de autoridad

Validar legalmente identidad, competencia y alcance; dos aprobaciones distintas. Paquete mínimo cifrado con manifiesto de hashes, fecha, propósito, acceso temporal y cadena de custodia. No crear una API de exportación arbitraria para admins ni enviar nada automáticamente a terceros. Entrega real requiere el proceso humano autorizado, no solo un botón técnico.
