# Dashboard administrativo y agenda

## Entrega

`rac-admin-service` agrega tres APIs propietarias con OIDC admin y deadline de
cuatro segundos. No recibe DATABASE_URL ni lee tablas ajenas. La pantalla está en
`/admin`, accesible desde el menú para administradores; la URL directa vuelve a
comprobar el rol en servidor. Comunidad cuenta perfiles RAC y compas publicados;
reservas cuenta todos los estados; moderación excluye los casos donde participa el
administrador. No hay cifras de ingresos ni supuestos pagos completados.

Cada fuente observa su propia instantánea. Un fallo devuelve 503 sin cifras
parciales; el frontend limpia cifras anteriores y permite reintentar. No se guardan
respuestas administrativas en caché. Readiness consulta las tres fuentes; métricas
permanecen internas. ADMIN_IMAGE se incorpora a los manifiestos inmutables y gates
QA/PRD. El CI integrado requiere siete repositorios de aplicación seleccionados en
la App de lectura, con revisiones completas fijadas.

## Días libres

Desde Mis reservas → Mis días libres, un compa bloquea fechas completas. El primer
y último día son inclusivos, interpretados en su zona IANA actual. PostgreSQL
convierte límites locales a instantes UTC, incluyendo medianoches con cambio de
hora. Cada bloqueo conserva su zona y sus instantes aunque luego cambie la agenda
semanal. El listado devuelve hasta 100 bloqueos vigentes, ordenados por inicio/ID;
se permiten hasta 100 vigentes y un período de hasta 366 días dentro de dos años.
No se incluyen motivos personales en la API, eventos ni logs.

Solo el propietario o un admin pueden listar, crear o quitar bloqueos. Repetir la
misma creación devuelve el mismo ID; quitarlo es idempotente. Un bloqueo que se
cruza con una reserva pendiente/confirmada devuelve 409 y no cancela reservas.
Las consultas de slots incorporan sus intervalos; un trigger y el mismo bloqueo
transaccional por compa protegen ambas direcciones incluso ante concurrencia.
Quitar un bloqueo recupera la disponibilidad semanal, no crea nuevas franjas.

## Vencimiento de solicitudes

Decisión del usuario: una solicitud sin aceptar vence al llegar su inicio. La falta
de suscripción no la rechaza antes. `booking-maintenance` procesa lotes de 100 con
FOR UPDATE SKIP LOCKED cada cinco segundos, recuperando atrasos tras un reinicio.
Solo cambia pendientes a expirada; no toca confirmadas, cupos o derechos de pago.
La regla temporal usa el reloj PostgreSQL. Una aceptación tardía se rechaza también
en un trigger; varios workers no duplican el cambio ni su evento de outbox.

La fecha límite es exacta para aceptar; la visualización del nuevo estado y los
avisos son eventuales. Un worker detenido puede dejar pendientes vencidas hasta
su recuperación. Readiness exige un ciclo reciente y Prometheus expone cantidad y
antigüedad de vencimientos pendientes y fallos. Los estados existentes mantienen
eventos v1; expirada usa v2. Desplegar el consumidor compatible v1/v2 antes de
habilitar el scheduler. Las notificaciones usan inbox/outbox e idempotencia
existentes; no se activa correo o push.

## Migraciones y validación

V015 agrega días libres y sus guardas. V016 agrega el valor de enum y lo confirma
antes de V017, que usa ese valor y adapta el outbox. No editar migraciones
aplicadas. Verificar instalación vacía, legado, repetición, checksum y permisos.
Pruebas PostgreSQL: bloqueo/reserva concurrentes; protección directa de BD;
propietario al quitar; reintento; medianoche DST; dos workers; aceptación vencida;
evento atómico. Flutter verifica ancho estrecho, errores, reintento y confirmación
antes de quitar. Navegador comprueba login real, aislamiento y cifras de propietarios.
