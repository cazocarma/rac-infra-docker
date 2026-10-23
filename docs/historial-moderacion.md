# Historial de moderación

La cola de casos abiertos y el historial de casos resueltos pertenecen a chat,
que conserva sus permisos y auditoría. La pantalla de moderación ofrece filtros
Abiertos, Atendidos, Desestimados y Todos, fechas de creación/cierre y navegación
por páginas. Los casos cerrados son informativos; no tienen acción para consultar
conversaciones ni reabrirlos. Las consultas justificadas de casos abiertos y las
resoluciones mantienen sus restricciones actuales.

## Contrato y privacidad

GET `/api/chat/moderation/reports` requiere OIDC y rol admin. `estado` acepta
`abierto` (predeterminado), `atendido`, `desestimado` o `todos`. La respuesta incluye
`items`, `has_more` y `next_cursor`. Cada item contiene exactamente `id`, `sesion_id`,
`motivo`, `creado_en`, `estado` y `resuelto_en`. Esta última fecha sale de la última
resolución auditada; si no existe, devuelve null, sin inventar una fecha.

La consulta excluye todas las reservas donde participa el moderador, en cada página
y filtro. No devuelve descripción del reporte, mensajes, justificaciones ni subjects
de otros administradores. Usa `Cache-Control: no-store`. Los endpoints de acceso y
resolución siguen rechazando casos cerrados, incluso con URL directa.

## Paginación

El orden es fecha de creación e ID ascendentes, con prioridad para los reportes más
antiguos. `next_cursor` se reutiliza como `despues` manteniendo el mismo filtro. El
cursor contiene versión, filtro y la pareja fecha/ID; es un punto de navegación,
no una autorización ni una instantánea entre solicitudes. La identidad se vuelve a
comprobar contra PostgreSQL en cada página.

La comparación por pareja evita saltos por desplazamiento cuando se cierra un caso
de una página anterior. Cambiar de filtro o actualizar vuelve a la primera página.
La app conserva una pila de cursores para volver atrás, ignora respuestas tardías de
filtros anteriores y retira los resultados viejos durante carga/error. Un reintento
conserva el filtro y página actuales. Las modificaciones concurrentes pueden cambiar
los resultados al volver a una página; actualizar recompone la vista vigente.

`offset` 0–10000 sigue disponible para clientes antiguos, sin mezclarlo con `despues`.
Estado desconocido, parámetros repetidos, cursor inválido o de otro filtro devuelven
400. La página terminal contiene `next_cursor` vacío y `has_more=false`.

V014 agrega un índice por fecha/ID para el historial de todos los estados. Los
filtros específicos usan el índice existente `(estado,creado_en,id)` de V011.
Las migraciones aplicadas no se editan. El contrato OpenAPI documenta el listado;
no convierte la lectura de metadatos en permiso para acceder al contenido.

## Entrega y validación

Desplegar el frontend y chat coordinados con las revisiones fijadas en CI integrado.
El índice es aditivo y no cambia datos ni estados. El módulo de administración puede
usar esta API en el futuro; no necesita copiar conversaciones ni abrir una segunda
base de reportes.

Se verifica: roles/anonimato; exclusión por conflicto de interés en todos los filtros;
metadatos sin contenido privado; fechas auditadas; empates de fecha y páginas de 20;
cierre de un caso anterior entre páginas; cursores incompatibles; respuesta tardía de
otro filtro; navegación, reinicio y ancho móvil. El recorrido de navegador usa tres
identidades OIDC y comprueba el caso atendido dentro del historial.
