# Perfil personal y promoción entre ambientes

## Perfil personal

`GET /api/user/me` sincroniza identidad, correo verificado y rol desde el token firmado, pero conserva y devuelve el nombre visible guardado en RAC. `PUT /api/user/me` reemplaza únicamente nombre, biografía, teléfono, país, región, ciudad e intereses del usuario autenticado. El nombre tiene entre 2 y 120 caracteres; se permiten hasta 15 intereses de 40 caracteres. Teléfono y ubicación son opcionales. Los valores vacíos permiten borrarlos.

El endpoint usa el subject verificado como propietario y rechaza campos desconocidos, identificadores ajenos, correo, roles y cuerpos excesivos. Los datos de contacto no se incorporan al catálogo público. El perfil compa, sus habilidades, descripción, tarifa y disponibilidad conservan su contrato separado.

La pantalla permite guardar, descartar, reintentar y conservar cambios si hay un error. Al recargar una ruta válida como /profile se recupera esa pantalla después de verificar la sesión; una sesión ausente sigue pasando por el login. Correo es de solo lectura. La evolución con fotos, biografía y vista previa se documenta en [perfiles públicos y fotos](perfiles-publicos-y-fotos.md); utiliza la migración V007 y un volumen persistente de imágenes. No se aceptan URLs externas como fotos.

Las pruebas cubren validación, asignación indebida de campos, persistencia tras login, aislamiento de cuentas, guardado/reintento en navegador y layout móvil. Los fixtures se crean y eliminan únicamente en DEV.

## Auditoría de promote (19 de octubre de 2026)

El flujo existente se llama **Approved deployment**, en `.github/workflows/deploy.yml`; no hay un workflow independiente llamado promote. La API de GitHub muestra que aún no existen environments, despliegues previos ni manifiestos JSON reales en `releases/`. Las ramas remotas QA/PRD todavía conservan una versión anterior a main. No se ejecutó ningún despliegue ni se actualizaron esas ramas como parte de esta revisión.

Por ello una promoción ahora no podría completarse. Antes de usarla se requiere:

1. Revisar y llevar el código aprobado a las ramas QA/PRD mediante PR, sin recompilar las imágenes al promoverlas.
2. Disponer de hosts Linux separados con Docker, Make, Python y runners etiquetados `rac-qa` / `rac-prd`.
3. Configurar los environments GitHub `qa` y `prd`, sus reviewers y la variable `RAC_ENV_FILE` con la ruta del archivo de secretos del host.
4. Crear y revisar un manifiesto con los cinco digests (auth, user, match, chat y frontend) reales publicados. Conceder al repositorio de infra acceso Actions a los paquetes privados necesarios en GHCR.
5. Provisionar secretos, OIDC/realm/clientes/cuenta de servicio, TLS y proxy externo en cada ambiente. El configurador y tema montado actuales son DEV; QA/PRD no se aprovisionan copiando usuarios demo.
6. Completar un despliegue QA exitoso. PRD exige las mismas imágenes y el mismo hash de infraestructura.

Se corrigieron dos defectos de la preparación: ahora el manifiesto y los reviewers se comprueban en un runner hospedado antes de esperar el runner del host; y la evidencia QA cubre también los archivos de bootstrap de base de datos y los archivos Compose que usa Make, antes omitidos del hash. Cambiar esos archivos invalida la evidencia previa y exige repetir QA. Las pruebas de estas reglas no usan credenciales ni crean despliegues.

Validar modelos Compose y reglas con pruebas locales no demuestra todavía la operación en hosts QA/PRD: siguen pendientes el ensayo de despliegue completo, el acceso real a paquetes privados, la provisión OIDC y las aprobaciones. También deben ensayarse respaldo/restauración y recuperación ante fallos antes de PRD.

Referencia: [GitHub Environments y protección de despliegues](https://docs.github.com/en/actions/deployment/targeting-different-environments/managing-environments-for-deployment).
