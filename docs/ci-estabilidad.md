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


## Regresión de directorio del workflow (ejecución 40513744887)

[El job migrations](https://github.com/cazocarma/rac-infra-docker/actions/runs/40513744887/job/122222111398)
falló en `test_ci_access.py`: `Start directory is not importable: 'scripts'`.
El checkout estaba en `rac-infra-docker`, pero al insertar la nueva prueba del
token se dejó la prueba anterior sin `working-directory`. La suite local previa
se había ejecutado dentro del repositorio y no cubría el contexto del runner.
Las migraciones, permisos, auditoría y sesiones anteriores de ese job pasaron;
la integración fue omitida por la dependencia fallida, no ejecutada con éxito.

El job usa ahora `defaults.run.working-directory: rac-infra-docker`, evitando
copiar ese atributo a cada paso. La nueva etapa `workflow-policy`, previa a
migraciones/integración, ejecuta el mismo `make test-workflows` que se usa localmente:

- actionlint para sintaxis/expresiones del workflow (sin shellcheck; los comandos
  de shell no se presentan como analizados por esta comprobación).
- Validador de directorios: para comandos que referencian scripts locales,
  compara la ruta del checkout propio con el contexto efectivo del paso,
  respetando precedencia paso > job > workflow.
- Cuatro pruebas de contexto, siete pruebas de acceso con fakes y cuatro del
  token. No contacta GitHub ni usa credenciales de la App.

Las imágenes de las herramientas se fijan por digest y PyYAML por versión.
El validador de contexto se limita a referencias locales `scripts`; no ejecuta
GitHub Actions completo ni demuestra cobertura de shell o de todos sus recursos.
`make test-ci-regressions` depende de esta puerta rápida antes de crear fixtures.

Verificación: el error original se reprodujo desde la raíz del workspace; el
validador rechazó el YAML real de `86748bf` y aceptó el corregido. La puerta local
completa pasó con 15 pruebas; la política existente de Actions también pasó.
El resultado remoto de esta corrección requiere observar una nueva ejecución.


Seguimiento de [40516304223](https://github.com/cazocarma/rac-infra-docker/actions/runs/40516304223):
workflow-policy, acceso, storage y migrations aprobados. La integración pasó
Keycloak, las bases/autoridad documental, standing, preparación DEV, fotos y API;
se observó instalando el runtime del navegador. Esto verifica las etapas de las
regresiones anteriores, pero todavía no demuestra la ejecución completa en verde.


Resultado confirmado: la ejecución `40516304223`, revisión `752e9b1`, terminó en
**Success** con los cinco jobs aprobados: workflow-policy 15 s, repository-access
9 s, storage 31 s, migrations 5 min 8 s e integration 27 min 45 s. Duración total
33 min 16 s. Incluyó las pruebas web. Los incrementos posteriores de P04 siguen
locales y este verde no se atribuye a esos commits todavía no enviados.
