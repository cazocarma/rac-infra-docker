# ADR-005 — Verificación de identidad y huella de documento

Estado: dirección técnica aprobada; proveedor, tratamiento y política D05/D08/D12 pendientes.

## Puerto y datos mínimos

User posee VerificationProvider: CreateSession, VerifyWebhook, DeleteSubjectData; adaptadores externos separados del dominio. Conservar estado, provider_subject_id opaco, resultado adulto, fechas, versión y referencia de verificación. Nunca guardar imagen de documento, número en claro ni fecha de nacimiento completa. El resultado de mayoría de edad debe proceder del proveedor, no de una casilla declarativa. El adaptador fake solo DEV/tests, con fallo de arranque si se selecciona fuera de esos ambientes; ninguna insignia pública real derivada del fake.

Webhook exige firma sobre bytes originales, timestamp con ventana, event_id contra replay y transición válida idempotente; validar destino/subject de sesión, no confiar en user_id del cliente. Secretos fuera de logs/repos. Fallos del proveedor dejan pendiente, nunca aprobado por timeout.

Renombrar `verificado` a `email_verified` en migración forward, SQL, modelos, OpenAPI, Flutter, fixtures y semillas en un corte coordinado sin alias permanente. Separar explícitamente email de KYC. Revisar campos históricos de DOB y contacto antes de suprimir; no migrarlos al nuevo proveedor sin base aprobada.

## Huella y evasión

Huella HMAC de país|tipo|documento normalizado, con separación de dominio y `key_id`; clave fuera del host/backup de aplicación. Preferir cálculo en un componente restringido del proveedor; si RAC recibe el número transitoriamente, requiere decisión jurídica y controles de memoria/telemetría, sin persistirlo ni incluirlo en trazas. Confirmar que el proveedor puede entregar un identificador estable utilizable sin almacenar el documento.

Rotación no se resuelve solo guardando key_id: al no conservar documento, no se puede recalcular una huella vieja. D12 exige estrategia de equivalencia multiclave vía proveedor, reverificación o rekey controlado con coexistencia acotada. No abrir un oráculo consultable para saber si un documento está registrado/baneado.

Coincidencia con identidad activa → revisión de duplicado. Coincidencia con identidad baneada → caso P1 y acceso a publicación/reserva retenido. El E2E-05 pide `rejected`, mientras el principio del prompt prohíbe sanción irreversible automática: propuesta `needs_review` reversible hasta confirmar identidad y posible suplantación. D12 debe aprobar el cambio o definir rejected como resultado KYC reversible, nunca ban automático de la nueva persona. No atribuir culpabilidad por una huella coincidente.

## Gates y presentación

KYC approved + adulto exigidos al publicar y antes de primera reserva, con versiones de política registradas. Un rol compa no los sustituye. Texto de insignia, derechos, proveedor, contrato/DPA, país, edad mínima, plazos y procedimiento de errores requieren aprobación. La verificación no constituye antecedentes ni garantía de conducta.

Pruebas: email true no concede KYC; fake QA/PRD denegado; menor/indeterminado; replay/firma/cuerpo alterado; duplicados concurrentes; rotación; misma huella con identidad robada; borrado del proveedor respetando hold válido y sin registrar documento en Loki.
