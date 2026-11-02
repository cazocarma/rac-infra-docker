# P09 — Similitud perceptual privada

Estado: componente local, sin catálogo activo, endpoint, carga de casos ni
sanción automática. No completa el worker ni el corte público de P08/P09.

## Implementación

`photoassets.Fingerprint` usa `goimagehash` v1.1.0 y dependencias vendorizadas,
con firmas DCT de 64 bits. La comparación perceptual mide parecido visual; no
determina significado, identidad personal ni ilicitud. Véanse el
[diseño de pHash](https://www.phash.org/docs/design.html) y la
[implementación fijada de goimagehash](https://github.com/corona10/goimagehash/blob/v1.1.0/hashcompute.go).

La versión propia `rac-goimagehash-1.1.0-crops/1` identifica biblioteca, exclusión
de baja información y seis vistas: completa y recortes centrados que conservan
98/96/94/92/90 por ciento de cada lado. No se declara compatible con otras
implementaciones/versiones de pHash. El bundle guarda SHA-256 de los bytes JPEG
exactos; las firmas se serializan como hexadecimal para evitar pérdida de uint64
en JSON de navegador.

Cada vista se excluye si su imagen de 32×32 no alcanza desviación gris 6,
entropía de 16 bins 0,75 y curvatura media 2,5. Estos cortes técnicos pertenecen a
la versión del algoritmo y evitan firmas accidentales de cuadros planos o
gradientes simples. No equivalen a una conclusión de seguridad. Una imagen no
comparable conserva ese estado y la necesidad de revisión.

`NewImageMatcher` recibe versión de política, distancia y prioridad explícitas,
sin valor productivo por defecto. Congela referencias/firmas y exige IDs no nulos
de referencia, caso y evidencia, sin duplicados ni algoritmos incompatibles.
Validar UUID no acredita un caso autorizado: el dueño de casos y su operación
staff deben comprobar esa asociación antes de activar/cargar un catálogo.

Se compara el frame completo con la familia de recortes de la otra imagen, en
ambas direcciones. No todos los recortes entre sí. Los resultados se ordenan de
forma estable y conservan referencias privadas de caso/evidencia y distancia.
El límite técnico del snapshot es 10.000 referencias; no sustituye un backend
indexado para un catálogo mayor.

## Integración y límites

`Processor` calcula firmas sobre el JPEG completo saneado. Si no recibe matcher,
registra `not_configured` y conserva el check pendiente. Un matcher configurado
puede registrar `evaluated` o `not_comparable`; una coincidencia solo eleva la
prioridad explícita de la política. La imagen sigue `needs_review`, o requiere
corregir contacto si lo detectó OCR. Nunca genera aprobación ni baneo.

Las firmas, referencias y evaluación son material privado. El catálogo requiere
casos/evidencias reales, autorización, retirada/reversión, persistencia y versión
efectiva antes de activarse. Los IDs sintéticos de pruebas no representan
decisiones humanas ni datos legales reales. Moderación de imagen externa sigue
desactivada; no hay reconocimiento facial.

## Evidencia sintética

Se generaron 24 escenas geométricas deterministas, con 144 variantes de JPEG,
resolución, recorte centrado y recortes descentrados/intermedios. Se detectaron
144/144 y hubo 0 coincidencias entre 276 pares distintos, con distancia 8 elegida
solo para el fixture. La primera versión del corpus tenía 72 variantes; se amplió
para no verificar únicamente recortes que coincidieran con las vistas internas.

Las pruebas incluyen blanco/gradientes no comparables, casos/evidencias ausentes,
políticas inválidas, cancelación, copias inmutables y cálculo concurrente. El
ensayo inicial fallido de inmutabilidad modificaba también el objeto usado como
consulta; se corrigió ese alias del fixture, manteniendo la copia del matcher.
Registros: `.local/p09-fingerprint-initial-corpus.log`,
`.local/p09-fingerprint-expanded-corpus.log`,
`.local/p09-fingerprint-query-fixture-reproduction.log`.

Esto no es un corpus humano ni valida un umbral productivo, fotografías naturales,
recortes arbitrarios, tasas generales o resistencia a adversarios. La calibración,
los negativos parecidos y la revisión humana siguen siendo gates de P09.
