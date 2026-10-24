# P03 — Ensayo completo en Compose

Ejecutar desde infra: `python -u scripts/test_standing_e2e.py`. Requiere Docker
Compose con soporte de `!reset`, imágenes base accesibles y los checkouts de
user, match, chat y alert. CI usa las revisiones inmutables de su manifiesto.

## Aislamiento antes de empezar

El runner genera un proyecto `rac-standing-e2e-<12 hex>`, un archivo temporal de
credenciales independientes y la BD `rac_standing_e2e`. Combina la configuración
base, el overlay de standing y `compose.standing-tests.yaml`; no carga el overlay
DEV ni su realm/volúmenes. Retira las variables heredadas que podrían sustituir
los valores del fixture. El modelo efectivo se valida antes de construir,
arrancar o borrar recursos.

No admite puertos publicados, volúmenes/redes externos o de otro proyecto,
opciones de volumen que monten datos existentes, nombres fijos de contenedor,
modo de red host, contenedores privilegiados ni binds de escritura al host.
`test_standing_lab.py` prueba estos rechazos sin iniciar Docker. El cleanup usa
únicamente el modelo aleatorio ya validado; no usa `prune`, ni el `.env` real.
El estado temporal con tokens se guarda en un volumen exclusivo que se elimina
al terminar. Las imágenes del laboratorio tienen etiquetas propias.

## Recorrido real

- Keycloak real emite tokens por Authorization Code + PKCE antes de cualquier
  sanción. Los mismos tokens se reutilizan durante todo el ensayo. No hay mocks
  de identidad ni una cabecera de usuario de prueba en las APIs.
- Dos instancias reales de user, match y chat comparten sus bases y credenciales
  limitadas. Las peticiones apuntan explícitamente a cada instancia, sin deducir
  cobertura a partir del balanceo DNS. Alert y todos los relays/consumidores son
  los binarios e imágenes reales.
- Primero se ejercitan escrituras permitidas: perfil y alias legacy, publicación,
  habilidades, foto PNG normalizada, agenda, time-off, reserva, aceptación,
  extensión, mensaje y reseña elegible.
- Con el consumidor de efectos de reservas detenido se sanciona al compa y al
  cliente. Así una cancelación derivada no oculta el control de autorización
  detrás de un conflicto de estado. Ambas instancias rechazan las escrituras con
  los JWT previos. Se conservan perfil propio, bandeja/leído, historial, reportes,
  bloqueo/desbloqueo, borrado propio de foto y cancelación propia durante ban.
  Un tercero continúa sin acceso al historial.
- Triggers exclusivamente del fixture pausan escrituras SQL después de adquirir
  permiso y antes del commit. Se observa la espera real en `pg_locks`, se confirma
  una sanción auditada y se libera la escritura. User, match y chat, en ambas
  instancias, responden 403 y revierten datos; chat también conserva sin cambios
  mensaje, cursor y outbox. No se añaden hooks de prueba a las aplicaciones.
- Al reanudar el consumidor, las reservas futuras antiguas se cancelan y la
  actividad ya iniciada permanece activa con efecto durable `safety_review`.
- Se detiene RabbitMQ y se aplica otra sanción. La autoridad sigue denegando;
  la recuperación HTTP independiente cancela y entrega el aviso original.
  Se marca leído mientras el broker está apagado. Tras volver el broker y
  reiniciar workers se espera la publicación de outboxes y el vaciado real de
  todas las colas, incluidas las fallidas, antes de comprobar un solo aviso y
  la misma fecha de lectura. Una autorización más nueva permite una nueva reserva.
- Se detienen ambas instancias de la autoridad. Match y chat deniegan escrituras
  comerciales en ambas instancias, manteniendo historial, seguridad y cancelación
  propia. Reiniciar la autoridad restaura las escrituras permitidas con el JWT
  original.

La función de sanción se invoca con un principal de auditoría del operador del
fixture. Ningún rol de aplicación recibe permiso de mutación. Esto prueba el
recorrido de enforcement; no inventa el ingreso humano de casos/acciones de P11.

## Evidencia y límites

La ejecución local del 24-10-2026 pasó el recorrido completo, incluidas las seis
carreras de commit y los controles protectores. La suite forma parte del job
integrado de CI, después de mensajería y antes del DEV efímero de sus otros tests.
Los mensajes PASS identifican cada fase y no contienen tokens, contraseñas ni
contenido de casos.

Es una prueba funcional con fallos y varias instancias. Todavía no es la medición
estadística bajo carga de revocación p99 ≤5 s ni del camino caliente p99 ≤2 ms.
No prepara el respaldo del DEV persistente y no lo activa. Tampoco cierra el
efecto pendiente de terminar sesiones en Keycloak con un mecanismo acotado.
