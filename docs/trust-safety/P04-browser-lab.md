# Laboratorio conectado de P04

Este laboratorio construye las fuentes locales de auth, user y Flutter, con
Keycloak, PostgreSQL temporal y un proxy local. No es la suite completa del
ecosistema: match, chat, alertas y pagos no se inician aquí. Complementa las
pruebas de sus dueños y permite recorrer documentos, cuestionario e historial.

## Arranque y recursos

Desde infra:

```sh
make documents-lab-start
```

Requiere Docker/Compose y Python estándar en PATH; se puede indicar `PYTHON` como
en los otros targets. El comando imprime la URL y la ruta de `state.json`. No
lee `.env.dev`: genera credenciales propias a partir del ejemplo versionado,
limpia las variables ambientales que pudieran sobrescribirlas y usa un proyecto
aleatorio `rac-documents-e2e-...`. Solo publica dos puertos de loopback. PostgreSQL
usa tmpfs; redes, volúmenes e imágenes son propios. El modelo se valida antes de
construir, iniciar o limpiar recursos. Nunca combina el overlay DEV persistente.

Las credenciales se guardan únicamente en `.local/<proyecto>/fixture.env`, fuera
de los repositorios; no adjuntar ese archivo a reportes. Los usuarios demo del
realm desechable son los de DEV: `cliente1` y contraseña sintética `123456`.
Documentos y cuestionario son fixtures de prueba, no textos legales definitivos
ni aprobación jurídica para usuarios reales.

## Recorrido esperado

1. Entrar con cliente1 por OIDC/PKCE y abrir Sé Compa.
2. Completar descripción, tarifa, habilidad cine y horario. Intentar activar.
3. S2 muestra cinco documentos, casilla desmarcada y botón deshabilitado. La
   salida a datos/derechos permanece accesible; exportación/eliminación indican
   que aún están en construcción, sin simular una solicitud enviada.
4. Abrir cada texto sintético completo. Tras leerlos, seleccionar explícitamente
   la casilla y aceptar. Volver al formulario no publica automáticamente.
5. Intentar activar nuevamente: abre el cuestionario. Las cinco marcas y tres
   respuestas comienzan vacías. Una alternativa incorrecta es rechazada por el
   servidor y conserva las selecciones para corregirlas.
6. Contestar correctamente y continuar. Activar explícitamente otra vez: se
   publica el perfil sintético y se refresca el rol compa real en Keycloak.
7. Abrir Historial desde Documentos, o recargar `/#/document-history`. Abrir una
   versión muestra su texto y aceptación registrada, sin formulario de aceptación.
   Atrás debe regresar al inicio y no dejar una puerta de arranque dormida debajo.

Para probar una actualización material en el mismo laboratorio:

```sh
make documents-lab-change LAB_STATE="/ruta/impresa/state.json"
```

Solo funciona una vez desde el registro sintético 1. Activa una privacidad
`browser-synthetic-2` y reutiliza el cuestionario inmutable anterior. Al guardar
el perfil se debe pedir únicamente la nueva privacidad; aceptar no reenvía el
guardado. El historial debe conservar ambas versiones y la aprobación del
cuestionario no debe duplicarse.

Para reconstruir únicamente el frontend mientras se corrige una regresión:

```sh
make documents-lab-refresh LAB_STATE="/ruta/impresa/state.json"
```

Recargar la página después de reconstruir. Las aceptaciones y el perfil de la
fixture permanecen en el PostgreSQL del laboratorio hasta limpiarlo.

## Limpieza

```sh
make documents-lab-status LAB_STATE="/ruta/impresa/state.json"
make documents-lab-stop LAB_STATE="/ruta/impresa/state.json"
```

Stop vuelve a validar estado, proyecto y modelo antes de quitar únicamente sus
contenedores/volúmenes. No usa prune ni toca la instalación DEV/RustFS existente.
La matriz de pruebas `test_documents_lab.py` rechaza nombres persistentes, puertos
externos, imágenes DEV, volúmenes de datos PostgreSQL, bind mounts escribibles y
servicios de configuración ausentes. `make test-workflows` incluye esa matriz.

La evidencia de navegador y los conteos sanitizados se registran por ejecución.
Una prueba manual positiva aquí no sustituye los demás gates del plan ni prueba
funciones fuera de este laboratorio.


## Variante editorial con MFA (solo laboratorio)

`python scripts/documents_lab.py start --staff` crea otro proyecto desechable con
DB tmpfs, imágenes propias y puertos loopback. Agrega admin/match/chat reales a
las dependencias de salud, sin sustituir sus respuestas por mocks. El overlay
compose.editorial-lab.yaml habilita únicamente en ese proyecto el ingreso user
8083 interno y el proxy staff; no publica ese puerto al host ni cambia DEV.

Después de migrar, editorial_lab_fixture.py provisiona rac_editorial_lab con
USAGE y EXECUTE de once funciones exactas, sin grants de tablas, y su escritor
con cadena de auditoría propia. Habilita el cliente rac-staff de ese realm y crea
dos cuentas legales sintéticas con contraseña y OTP. No concede realm admin.
El harness captura las credenciales en .local/<proyecto>/staff-fixture.json, sin
imprimirlas. No volcar ese archivo, fixture.env ni tokens a registros/evidencias.
El estado y la URL pública se imprimen al quedar listo.

El registro comienza en versión cero: no se usa documents_e2e_fixture.py ni SQL
para simular decisiones/publicaciones. Las acciones seed/material-change se
rechazan en esta variante. La autoría, revisión por otra cuenta, publicación y
activación deberán recorrer la consola y sus APIs. stop/status/refresh-web usan
el --state del proyecto; no repetir --staff en esas acciones.

La configuración staff admite post-logout únicamente hacia sus redirectUris
registradas y Nginx aplica no-store a ambos callbacks mediante la misma regla.
La sintaxis Nginx pasa y los dos tests de aislamiento incluyen las imágenes
extra y el rechazo de publicar 8083. Esto prepara el ensayo; todavía no acredita
un recorrido conectado ni la persistencia cifrada observada en navegador.


### Correcciones verificadas al preparar el arranque editorial

El bootstrap real revoca CONNECT/TEMP a PUBLIC. La fixture inicial solo otorgaba
USAGE/EXECUTE y el ingreso de user no arrancaba. Se agregó CONNECT exclusivamente
sobre rac_documents_e2e y una preflight que abre una conexión como
rac_editorial_lab y exige editorial_ready(), antes de iniciar las APIs. El
siguiente arranque pasó user: el registro vacío no era la causa de ese fallo.

La variante ahora configura DOCUMENTS_AUTHORITY_URL explícita para match/chat al
habilitar el gate documental. Omitirla causaba rechazo de arranque de chat, como
corresponde al diseño fail-closed. No se deshabilitó el control. Ante un fallo,
el harness captura diagnósticos de user/admin/match/chat redactados antes de
retirar el proyecto, en startup-diagnostic.log; no preserva el cluster fallido.
Los dos tests de aislamiento siguen pasando. El nuevo arranque se está validando;
aún no se declara prueba conectada exitosa ni ensayo de MFA en navegador.


### Privacidad de callbacks y reautenticación

Frontend 3f3b768 evita id_token_hint opcional en la autorización staff; mantiene
PKCE, prompt=login, max_age=0 y verificaciones servidor. El hint no es necesario
para renovar MFA y no debe transportar un ID token en la URL de ese acceso.
El logout conserva su protocolo OIDC (no se ha cambiado ese intercambio).

El gateway y el servidor estático del frontend desactivan access_log únicamente
para /redirect.html y /staff/redirect.html y aplican no-store/no-referrer.
`make test-oidc-callbacks` ensaya dos Nginx reales, sin puertos de host, con
sentinelas sintéticos en code/state: ambos callbacks responden 200 con headers,
no aparecen en logs de ninguno de los saltos y /index.html sí queda registrado.
Prueba aprobada en .local/p04-oidc-callback-privacy.log. No se está afirmando que
el resto de M17/logs/observabilidad esté completo ni que este target ya esté
incorporado al workflow remoto con los pins coordinados pendientes.

Siete pruebas de autenticación y análisis sin incidencias de copia fija pasan
en .local/p04-oidc-privacy-flutter.log. Imagen frontend release construida en
.local/p04-oidc-privacy-image.log, todavía sin recrear el servicio en el ensayo
mientras el navegador mantiene una confirmación pendiente. Se está esperando
el vencimiento real de MFA para probar persistencia y retorno con el mismo
comando; no se alteran relojes, tokens ni límites del servidor.


### Preparación reproducible por API autenticada (2026-10-29)

El laboratorio desechable `rac-documents-e2e-3144e30ffce4` se recreó tras
perderse el cluster tmpfs anterior. No se reutilizan sus datos ni sus puertos.
`scripts/editorial_fixture_api.py` permite preparar exclusivamente cinco
textos sintéticos fijos mediante PKCE, contraseña y OTP reales, proxy admin
y API dueña. Una cuenta crea; otra revisa y publica. No escribe SQL ni activa
el registro. Rechaza estados ajenos a `.local/rac-documents-e2e-*`, contenedores
sin el proyecto esperado y manifiestos alterados; conserva UUID para replay.

Ejecutar `make test-editorial-api LAB_STATE=<ruta absoluta al state.json>`.
Las credenciales generadas y los tokens no se imprimen ni se guardan en el
manifiesto. El cliente no utiliza proxies de entorno. La excepción de cookies
Secure sobre HTTP se limita al puerto localhost exacto del laboratorio para
reproducir el comportamiento del navegador; no cambia Keycloak ni sus cookies.

Primera ejecución y repetición aprobadas en
`.local/p04-reproducible-document-api.log` y
`.local/p04-reproducible-document-api-replay.log`. Consulta independiente tras
repetir: 15 eventos, cinco revisiones y registro es todavía en cero: no se
duplicaron los eventos ni se activó contenido. Cuatro pruebas de seguridad del
harness pasan también con Python `-O`; las comprobaciones de protocolo usan
excepciones explícitas, no assert removibles.

Esta preparación por API no prueba la creación del cuestionario ni la
activación por navegador. Ambas siguen pendientes, junto con la publicación
coordinada y los demás gates de P04. Los textos son fixtures, sin aprobación
jurídica ni aplicación sobre la base persistente DEV.
