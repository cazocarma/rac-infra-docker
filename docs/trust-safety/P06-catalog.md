# P06 — Catálogo cerrado de actividades (en desarrollo)

Sigue M3 y [ADR-002](ADR-002-listing-revisions.md). Rama `feat/activity-catalog`
en user, frontend, contratos e infra, apilada sobre P05. Lo que no está en el
catálogo no puede ofrecerse: desaparece la superficie de texto libre como canal
de oferta.

## Incremento 1: catálogo, retiro de habilidades libres y descubrimiento

V040 crea `activity_categories` con slug, claves i18n de nombre y descripción,
estado, aprobación, edad mínima (nunca menor a 18), tipo de lugar y orden.
Siembra las 12 propuestas del prompt con `approval='proposed'`: cine, teatro,
conciertos, museos, running, trekking, ciclismo, juegos de mesa, karaoke,
conversación en idiomas, fotografía urbana y gastronomía en restaurante. D04
debe aprobar actividades y lugares. Lo prohibido se define por ausencia: no hay
salud, masajes, transporte, cuidado de niños o dependientes, alcohol, fiestas
privadas ni "compañía" genérica.

`compa_activities` liga perfil y categoría, con una nota opcional de hasta 140
caracteres. La migración desde habilidades:

- solo mapea coincidencias exactas de nombre, sin distinguir mayúsculas ni
  tildes;
- lo no mapeable ("música", "asado") queda en `legacy_compa_skills`, no público y
  sin acceso para `rac_user`, para revisión: nunca se borra suponiendo que DEV
  no tiene datos;
- elimina en el mismo corte `skill`, `compa_perfil_skill`, la columna
  `habilidades_cache`, su índice, trigger y funciones.

`rac_user` lee el catálogo y gestiona solo `compa_activities`; el catálogo
cambia únicamente por migración.

En user, `PUT /me/compa` recibe `actividades [{slug, nota}]`. Solo acepta
categorías activas: propuestas únicamente con `RAC_ENV` dev o test, aprobadas en
otros ambientes. El máximo es `CATALOG_MAX_PER_COMPA` (5 por defecto, entre 1 y
12), sin duplicados ni caracteres de control en la nota. `GET /activities`
publica el catálogo. Descubrimiento, detalle público y reseñas públicas
comparten una regla: el compa debe ofrecer al menos una actividad visible. El
filtro es `categoria` con slug exacto; otro formato devuelve 400. No hay
búsqueda de texto libre sobre descripciones. Se retiran `GET /skills`,
`POST /compas/:id/skills` y sus funciones. Esa ruta era la única por la que
staff editaba el perfil de otro usuario.

El frontend elimina la caja de búsqueda y filtra con chips del catálogo.
Tarjetas y detalle muestran nombres localizados y notas; una clave futura
desconocida muestra "Actividad". Sé Compa ofrece chips de selección (1 a máximo),
conserva las notas existentes y envía `actividades`. Son 25 claves ARB nuevas
pending y se eliminan las de habilidades y búsqueda. El contrato OpenAPI y las
pruebas de contrato reflejan rutas retiradas, filtro y catálogo.

Pruebas:

- `test_migrations.py` sube una base real hasta V039 con habilidades y luego
  aplica V040. Verifica el mapeo exacto, que lo demás se conserva, que no quedan
  tablas, columna ni funciones antiguas, las 12 propuestas y que se rechazan
  nota larga o vacía, edad menor a 18, lugar desconocido, slug libre, escritura
  del catálogo por `rac_user` y lectura del legado.
- user: validación unitaria y política por ambiente. En PostgreSQL real con
  `rac_user`, se rechazan actividad fuera del catálogo, exceso, nota larga y
  texto libre sin escribir nada. El catálogo trae 12 propuestas en dev y queda
  vacío fuera de dev, donde el perfil deja de ser público. Las rutas de
  habilidades responden 404.
- Hallazgo: los fixtures de foto y reseñas creaban compas sin actividades, y la
  nueva regla de visibilidad los ocultó. Ahora reciben una actividad del
  catálogo.
- Hallazgo del laboratorio de navegador: la primera V040 creaba tablas
  temporales para el mapeo. El migrador real de Compose no es superusuario y no
  tiene privilegio TEMP, mientras que `test_migrations.py` migra como
  superusuario y no lo detectaba. La migración usa ahora `VALUES` en línea y
  `test_database_permissions.py` (migrador no superusuario, fresh y upgrade)
  pasó con ella.
- El laboratorio detectó además tres problemas que las pruebas como
  superusuario no veían:
  - El seed DEV corre como `rac_seed`, que tenía permisos sobre las habilidades
    pero no sobre el catálogo. V040 le da lectura del catálogo e inserción de
    actividades.
  - Al borrar un usuario se borra en cascada `compa_perfil`, pero
    `compa_activities` y `legacy_compa_skills` lo impedían. Ahora pertenecen al
    perfil (`ON DELETE CASCADE`).
  - Los compas de demostración no tenían actividades y la nueva regla de
    visibilidad los ocultaba, así que match no podía reservar con ellos. El seed
    ahora les asigna `cine`.
- Laboratorio `rac-browser-e2e-7d3c50dc7021` con los pins P06: pasaron las siete
  suites reales, incluido onboarding con chips del catálogo, y se retiró sin
  recursos.
- Frontend: 232 pruebas, análisis y build (`.local/p06-catalog-frontend-full.log`).
- Scripts de integración, permisos, onboarding, agenda y standing usan
  `actividades`. Las rutas retiradas se comprueban como 404 y el test de
  navegador de onboarding usa chips del catálogo.

Pendiente en P06: geografía normalizada a comuna sin direcciones. Requiere la
fuente oficial (CUT de comunas) y D04, sin inventar códigos. También quedan el
filtro por disponibilidad en descubrimiento, la aprobación D04 del catálogo y la
revisión de `legacy_compa_skills` (P08). Si se mantiene una búsqueda por nombre
visible, debe devolver cero resultados y aviso de reglas ante léxico prohibido
(P07), con solo una métrica agregada.
