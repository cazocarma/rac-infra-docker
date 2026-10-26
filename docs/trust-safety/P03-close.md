# P03 — Expediente de cierre

26-10-2026. Implementación y gates locales completos; falta confirmar el CI
del commit final antes de fusionar. Este expediente no declara completado el
programa Trust & Safety ni sus módulos posteriores.

| Requisito | Evidencia y resultado |
|---|---|
| Autoridad, capacidades y restricciones temporales comunes | platform v0.9.1; vet/race, leases originales, invalidación/versiones y relojes desfazados; P03-time y P03-performance |
| Escritores, JWT anterior y dos instancias | Matriz Compose completa: perfil/publicación, skills/foto/reseña, agenda/time-off, creación/aceptación/extensión y envío; rollback previo al commit |
| E2E-04 y presupuesto caliente | JSON final: 100 sanciones, ocho sondas, aceptación real, peor primer rechazo p99 93.273 ms; 1184/1184 hits <=2 ms |
| Versiones obsoletas, fallas y recuperación | PostgreSQL/RabbitMQ/Compose: outbox/inbox, eventos originales, claim fencing, recuperación sin broker y autoridad fail-closed |
| D02: accesos protectores | Perfil/estado, historial, seguridad/reportes, avisos y cancelación propia conservados según autenticación/propiedad; no bypass comercial |
| D03: efectos y reversión | Solo reservas futuras se cancelan; cupo de contraparte, actividad iniciada a safety_review; reversión no reabre reservas ni borra evidencia |
| Sesiones de identidad | V027, worker scoped y proveedor Keycloak real: online/offline, pérdida de ACK, reversión concurrente, caída/reinicio, login nuevo preservado |
| Mínimo privilegio y operación | Flyway sin superusuario, rol separado por dueño, credencial de sesiones exclusiva, permisos negativos y modelos DEV/QA/PRD |
| Recuperación del DEV real | Backup físico cifrado y boot de copia aislada; backup lógico de ambas BD/objetos referenciados, restore y upgrade V017→V027 repetible, conteos conservados |
| Verificación remota previa | CI 40348571328 aprobó los cuatro jobs de 0583dfd, incluyendo sesiones y recuperación; el commit final amplía medición y corrige el relay |

La [evidencia de rendimiento](evidence/p03-final-performance.json) conserva
revisiones, hash del harness y hardware. La
[atestación de restore](evidence/p03-dev-restore-attestation.json) referencia
mediante SHA256 los comprobantes privados del directorio local de respaldos.
No se publican dumps, filas, secretos, rutas privadas ni contenidos de usuarios.

El PostgreSQL persistente se encontró detenido en V017. Antes de arrancarlo se
respaldó su volumen en modo lectura y se verificó una restauración en otro
volumen, sin red. Después se detuvieron los workers antiguos, se conservaron
las credenciales de operador y se provisionaron identidades separadas, sin
aplicar migraciones a la BD original. El upgrade se ensayó sobre la copia
lógica restaurada, con migrador sin superusuario. Los helpers reproducibles son
`make backup-cold-postgres` (requiere fuente detenida) y
`make backup-restore-upgrade-test`. La copia externa sigue aplazada.

## Límite de esta entrega y siguiente funcionalidad

P04 incorpora documentos inmutables, versiones, hashes y aceptaciones con 428
en las acciones cubiertas. No debe bloquear derechos ni presentar textos aún
sin revisión como definitivos. KYC/identidades baneadas son P05; publicaciones
moderadas, P08; casos, apelaciones y decisión humana, P11; privacidad, P12.
Esas dependencias no se presentan como funciones terminadas de P03.

El rollout persistente debe usar el manifiesto de companions y V027 de manera
coordinada. No volver a Keycloak 24 contra su BD actualizada ni arrancar workers
viejos contra el esquema nuevo. La reversa usa los respaldos verificados y una
ventana de recuperación; el cold snapshot previo al bootstrap se conserva
separado de la retención del backup lógico.
