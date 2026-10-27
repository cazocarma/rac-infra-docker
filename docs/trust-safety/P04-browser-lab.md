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
