# Parche local de Go y dependencias — 2026-11-02

Estado: código/recetas locales, sin push ni despliegue. Actualizar fuentes no
parchea binarios ya construidos. Se conserva la evidencia de versiones anteriores.

## Hallazgo y corrección

Al incorporar similitud se ejecutó govulncheck v1.9.0. El paquete de fotos no
reportó vías afectadas, pero el servicio completo sí: nueve avisos a nivel de
símbolos y otros a nivel de paquete/módulo. El SDK mostró además el aviso de
normalización Unicode. Un camino del análisis estático no prueba explotación,
un incidente ni que una función esté expuesta en la configuración actual.

| Componente | Versión corregida elegida | Fuente primaria |
|---|---|---|
| Toolchain/biblioteca estándar | Go 1.27.3 en módulos, builders y pruebas | [GO-2026-6809](https://pkg.go.dev/vuln/GO-2026-6809) |
| JOSE | v4.1.4 | [GO-2026-4945](https://pkg.go.dev/vuln/GO-2026-4945) |
| HTTP/2 / HTML x/net | v0.62.0 | [GO-2026-6617](https://pkg.go.dev/vuln/GO-2026-6617), [GO-2026-6866](https://pkg.go.dev/vuln/GO-2026-6866) |
| HTTP/3 quic-go | v0.59.1 | [GO-2026-5676](https://pkg.go.dev/vuln/GO-2026-5676) |
| Normalización x/text del SDK | v0.43.0 | [GO-2026-5970](https://pkg.go.dev/vuln/GO-2026-5970) |

`rac-platform` tiene un nuevo tag local **v0.16.1**, commit
`40fb847be7abee7d62c6394495065aca2b6d248d`. No se cambió v0.16.0 ni otra versión
existente. La actualización Unicode incrementa `AnalyzerVersion` a
`contentsignals/2`; los resultados históricos de versión 1 no se reescriben. Los
cinco consumidores se regeneraron desde el nuevo tag local y su zip exacto.
Auth/payment, que no dependen de ese SDK, se actualizaron separadamente.

## Verificación y alcance

`make test-go-security` ejecuta el escáner fijado sobre SDK, auth y los cinco
consumidores; añade payment si está clonado. No usa credenciales privadas ni
sube fuentes; consulta la base pública de avisos de Go. No oculta avisos de
módulos no importados, como el paquete OpenPGP obsoleto dentro de x/crypto: se
mantienen en el reporte y no se confunden con rutas llamadas por la aplicación.

El primer escaneo completo posterior a los parches terminó exit 0 en los ocho
módulos locales, sin símbolos/paquetes afectados reportados
(`.local/p09-go-security-all.log`). El SDK pasó vet/race y escaneo; auth/payment
pasaron vet/race. La matriz restante y la regresión integrada se registran al
terminar, junto al nuevo corpus de fotos.

Reportes originales: `.local/p09-user-vulnerabilities-verbose.log` y
`.local/p09-platform-vulnerabilities.log`. No se borraron ni se añadieron
excepciones para convertirlos en verde. Esto no sustituye pentest, escaneo de
imágenes, SBOM, revisión de permisos ni los gates restantes de P15.
