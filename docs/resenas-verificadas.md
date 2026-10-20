# Resenas de reservas verificadas

El cliente que contrato una reserva puede valorarla una sola vez cuando su estado
es finalizada y su fecha_fin ya paso. Puntuacion entera entre 1 y 5; comentario
opcional de hasta 1000 caracteres, sin controles salvo saltos de linea. Compa y
admin tambien pueden contratar, pero solo valoran sus propias contrataciones;
no pueden valorarse a si mismos ni escribir por otro cliente.

La interfaz ofrece Dejar una resena desde Mis reservas. Pide estrellas, explica
que sera publica e inmutable y conserva el comentario si falla el envio. Despues
de guardar, muestra la resena y deja de ofrecer otra. Antes del fin del horario
muestra una indicacion aunque la reserva se haya marcado finalizada anticipadamente.
El perfil publico muestra promedio, cantidad y resenas paginadas de 20 en 20.
No expone identidades, correo, telefono, fechas de la reserva ni ID de contratacion.

## API del servicio de usuarios

- POST /api/user/bookings/:id/review: token OIDC, puntuacion y comentario. El
  propietario proviene del token; no se aceptan IDs de autor/compa en el cuerpo.
  201 al crear, 200 al repetir exactamente el contenido normalizado, 409 si ya
  existe otra resena o aun no es elegible. Otro cliente obtiene 404.
- GET /api/user/bookings/:id/review: solo participantes; resena o null, 404 ajenos.
- GET /api/user/compas/:id/reviews?offset=0: publico, maximo 20 por pagina.
- DTO compa: cantidad_resenas y rating_promedio calculados de resenas verificadas.

V008 agrega reserva_resena con PK por sesion, claves foraneas, checks e indice
por compa/fecha. Un trigger verifica en la base la relacion con cliente/compa y
el estado/fecha de la reserva. La escritura bloquea la reserva; las solicitudes
simultaneas no generan dos resenas. No se mantiene una media acumulada susceptible
a perder actualizaciones: las consultas calculan AVG/COUNT bajo MVCC.

RAC conserva por ahora una base compartida. Esta implementacion consulta la tabla
sesion dentro de esa arquitectura; al separar bases por servicio necesitaremos
un contrato/evento verificado de reserva completada y una proyeccion local.
No se agrego un microservicio adicional solo para estas tres rutas.

No se implementaron edicion, respuestas del compa, reportes de contenido ni
moderacion. No se generan valoraciones ficticias ni se migran las antiguas
columnas calificacion_cliente/compa como si fueran resenas verificadas.

## Verificacion

Tests Go con PostgreSQL desechable: anonimato rechazado, propiedad, estados no
elegibles, horario futuro, limites, campos falsificados, concurrencia/reintento,
media real y privacidad publica. Tests Flutter verifican seleccion obligatoria,
conservacion del comentario ante errores y reintento en pantalla movil.
El navegador usa una identidad y reserva propias, finaliza por API y solo mueve
las fechas de ese fixture para simular el paso del tiempo. Se limpia al terminar.
