# ADR-010: coordinación documental en la topología actual

Estado: en integración P04. No habilitado en DEV persistente.

El bootstrap valida que las identidades de servicio apunten al mismo host,
puerto y base PostgreSQL (`scripts/database_roles.py`). Los roles aíslan permisos;
no hay todavía una base física independiente por servicio. La fuente documental
pertenece a user y los otros servicios la consultan por HTTP autenticado.

Para impedir que una activación cambie las reglas entre la validación final y
el commit de una reserva/mensaje, V031 expone `documents.lock_registry` a user,
match y chat. Es una función SECURITY DEFINER de search_path fijo que devuelve
solo revisión y referencia de política mientras mantiene un bloqueo compartido
de cabecera en la transacción del escritor. No permite elegir una revisión
vieja ni devuelve contenido, identidad, aceptación o información de otros
usuarios. Los servicios no obtienen SELECT de tablas documentales.

El SDK consulta la autoridad autenticada bajo ese bloqueo y exige que su revisión
y política coincidan con las bloqueadas. Una discrepancia, un permiso ausente,
una migración faltante, un error de transporte o una respuesta vencida deniegan
la operación. Las cancelaciones y acciones protectoras no adquieren este bloqueo
ni dependen de la autoridad documental.

Esta decisión depende de la base compartida validada por la configuración actual.
No es un bloqueo distribuido ni sirve para separar las bases manteniendo solo
los números de versión. Antes de una separación física se debe reemplazar por
un protocolo de coordinación con garantías equivalentes y pruebas de partición,
vencimiento y commit; quitar el bloqueo o usar solo una caché no conserva la
propiedad. No habilitar documental con URLs de autoridad/base ajenas al despliegue
validado, ni promover restauraciones aisladas como autoridades paralelas.

El registro de P04 detalla los comandos y evidencias de validación. El rollout
requiere migraciones, clientes técnicos y todos los escritores coordinados; no
se activa por publicar una etiqueta del SDK.
