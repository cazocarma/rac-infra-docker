# P09 — foto preparada vinculada al envío

Datos sintéticos, recursos desechables y sin cambios en DEV. No publica fotos ni
cierra P08/P09. Las rutas de registros siguientes son relativas a la raíz RAC,
fuera del repositorio; no se versionan registros de ejecución.

## Fuentes y alcance

User `a12f42bf2397513d0e2defc9d059ddf81ce3622d`, frontend
`c13b192b96cef9fbc5e6d88292ed9588c6265afc`. V048 liga una revisión a fuente,
propietario, intento, digest y tamaño exactos mediante claves foráneas e historial
inmutable. Una foto ajena, sin confirmar/procesar o con contacto OCR no sirve.
Las señales de imagen aumentan el triaje, sin sanción automática. Flutter permite
seleccionar explícitamente una foto preparada para el envío y quitar esa selección;
no interpreta `awaiting_review` como aprobación. V045 sigue rechazando aprobar
revisiones con foto hasta implementar la promoción completa de ADR-011.

| Verificación local | Evidencia | Resultado |
|---|---|---|
| Migraciones fresh/upgrade/repetición/checksums y pruebas user, incluida `TestListingPhotoReferencePostgres` | `.local/p09-listing-photo-links-final-2026-11-05.log` | exit 0 |
| HTTP propietario → RustFS → SQL → OCR nativo → envío con foto preparada | `.local/p09-linked-photo-rustfs-2026-11-05.log` | exit 0 |
| Flutter: formato, analyze, 272 pruebas y compilación web release desde Git archive c13b192 | `.local/p09-frontend-c13b192b96.log` | exit 0 |
| OpenAPI y 19 pruebas de contrato | `.local/p09-linked-photo-contracts-2026-11-05.log` | exit 0 |
| Nginx activo, transporte real aislado | `python scripts/test_photo_gateway.py` | exit 0 |

La prueba SQL usa el rol de aplicación real y comprueba rollback, negativa de
acceso directo, propietario/pipeline, historial y bloqueo de publicación. La
fixture del test antiguo de aprobación ahora prepara una referencia válida;
no deshabilita triggers ni elimina el rechazo `listing_photo_unapproved`.
En el test HTTP/S3 se exige 409 para contacto y 202 para la foto benigna, con
referencia persistida y ningún puntero publicado.

El proxy acepta 2 MiB sin alterar bytes, ruta, Authorization o Idempotency-Key;
rechaza más de 6 MiB y mantiene el límite de 1 MiB en rutas generales. El límite
real de imagen sigue siendo 5 MiB en user-service. El upstream de esta prueba de
transporte es sintético; no reemplaza la validación real de imágenes de la suite
HTTP/S3. La imagen del worker probada fue
`sha256:1d777409d393d58154870ee55189338dd01d941fe07c25ce9571bde1ce703b12`.

Antes de V048 se completó además la regresión congelada de la API propietaria:
`.local/rac-p09-queue-proof-599c1642026e/results.json` contiene cinco exit 0
(permisos, migraciones/user, almacenamiento, procesamiento y seguridad Go), con
fuentes infra `95226fcf238ec5aec501734b2e06b1afbf8845e0`, user `1dae264` y
frontend `70d89df`. Esa prueba no demuestra restauración de referencias V048.

La compilación web conserva una advertencia previa sobre la fuente CupertinoIcons;
analyze pasó. No se declara auditoría de dependencias nativas, prueba de navegador,
restauración con referencias V048 ni funcionamiento de promoción pública.
