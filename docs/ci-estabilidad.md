# Regresiones de CI: diagnóstico y comprobación local

Revisión del 27 de octubre de 2026. En las últimas 25 ejecuciones de infraestructura revisadas hubo 5 fallidas, 11 canceladas y 9 correctas. Es una muestra de este repositorio, no una tasa global. La configuración `cancel-in-progress: true` cancela una ejecución anterior cuando llega otro cambio a la misma referencia.

## Causas verificadas

- [Ejecución 40434233460](https://github.com/cazocarma/rac-infra-docker/actions/runs/40434233460): la prueba de fotos también ejecutaba pruebas HTTP de documentos. Ambas heredaban `RAC_ONBOARDING_TEST_DATABASE_URL`, pero documentos exige una base desechable específica de migraciones. El rechazo de seguridad era correcto. Documentos usa ahora `RAC_DOCUMENT_TEST_DATABASE_URL`, inyectada únicamente por su fixture de migraciones. Se conserva la comprobación del nombre de la base y la ejecución efectiva de la prueba documental.
- [Ejecución 40376432456](https://github.com/cazocarma/rac-infra-docker/actions/runs/40376432456): misma colisión de fixtures.
- [Ejecución 40385317015](https://github.com/cazocarma/rac-infra-docker/actions/runs/40385317015): el token administrativo de Keycloak venció antes de la última operación (HTTP 401). El emisor anuncia 60 segundos. La herramienta renueva según `expires_in`, con reloj monotónico y margen; no amplía la duración ni reintenta errores de autorización.

## Puerta local antes de enviar cambios

Desde `rac-infra-docker`:

```sh
make test-ci-regressions
```

Requiere Docker, Python, los clones hermanos y el RustFS local ya configurado y saludable en `rac-dev-storage_default`, con `envs/.env.storage`. Las pruebas de identidad y migraciones crean recursos desechables. Fotos usa RustFS real y una base desechable. El comando no ejecuta las migraciones sobre la base persistente DEV. Las credenciales locales no se imprimen ni se versionan.

Se puede seleccionar Python con `make test-ci-regressions PYTHON=/ruta/a/python`. El objetivo ejecuta secuencialmente pruebas unitarias de renovación, identidad real, migraciones de usuario y fotos. No sustituye la CI completa: los demás servicios, Flutter y navegador requieren sus comprobaciones correspondientes según el cambio.

## Evidencia local

Las cuatro pruebas unitarias de la concesión del token pasaron. Los tres scripts de integración pasaron localmente: renovación real con TTL de 60 segundos y dos adquisiciones, documentos con consentimiento por hash y activación concurrente en su fixture, y fotos/migración contra RustFS. No se desactivaron las comprobaciones de aislamiento ni las denegaciones de permisos.

La validación remota del nuevo código sigue pendiente hasta enviarlo y observar su ejecución. Evitar relanzar revisiones antiguas que todavía contienen los fallos y agrupar cambios ya comprobados antes de hacer push.
