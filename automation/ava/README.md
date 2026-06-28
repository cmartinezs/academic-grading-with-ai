# Importación de rúbricas a AVA

Automatiza Blackboard Ultra usando el export normalizado del workspace. Puede ejecutarlo una persona manualmente o un agente, siempre con validaciones previas y sin guardar cambios salvo que se use `--commit`.

El script:

- abre la página de calificación de un intento en AVA;
- busca estudiantes por nombre en la lista lateral;
- carga el feedback general;
- carga el feedback individual de cada IE;
- selecciona el desempeño de cada IE;
- verifica puntajes y comentarios antes de guardar o aceptar autoguardado;
- genera reportes locales en `automation/ava/reports/`.

## Página Requerida

`gradebookUrl` debe ser la URL de la pantalla donde AVA permite calificar el intento con rúbrica, comentarios generales y desempeños por criterio.

En Blackboard Ultra normalmente corresponde a una URL parecida a:

```text
https://campusvirtual.duoc.cl/ultra/courses/.../outline/assessment/test/.../flexible-attempt-grading?...&gradeBy=student...
```

Cómo obtenerla:

1. Entra a AVA/Blackboard Ultra.
2. Abre el curso.
3. Abre el libro de calificaciones o la evaluación.
4. Entra a calificar el intento de cualquier estudiante.
5. Verifica que la pantalla tenga:
   - lista lateral de estudiantes;
   - panel de comentarios generales;
   - botón o sección de rúbrica;
   - criterios con desempeños seleccionables.
6. Copia la URL completa desde el navegador y pégala en `automation/ava/config.json`.

También puedes sobreescribir la URL en una ejecución puntual:

```bash
npm run dry-run -- --student 19452600 --url 'https://campusvirtual.duoc.cl/.../flexible-attempt-grading?...'
```

## Seguridad

- No guardes usuario, contraseña ni cookies en el repositorio.
- `automation/ava/config.json`, `.ava-session/` y `reports/` son locales.
- Sin `--commit`, el script solo inspecciona/compara y no guarda datos.
- Con `--commit`, debes indicar `--student RUT` o `--all`.
- El proceso masivo con `--all` se detiene en el primer error.
- La política predeterminada de conversión es `exact`; si un porcentaje no coincide con un desempeño configurado, se bloquea.

## Preparación

Desde la raíz del workspace:

```bash
./scripts/workspace-status.sh
./scripts/export-results.sh
```

Luego prepara la automatización:

```bash
cd automation/ava
npm install
cp config.example.json config.json
```

Edita `automation/ava/config.json` antes de ejecutar.

## Configuración

Campos principales de `config.json`:

| Campo | Uso |
|-------|-----|
| `gradebookUrl` | URL completa de la pantalla de calificación del intento en AVA. |
| `cookieDomain` | Dominio para cookie manual, normalmente `campusvirtual.duoc.cl`. |
| `evaluationId` | Evaluación del export que se cargará, por ejemplo `EV1` o `EV3`. |
| `rubricLevels` | Nombres exactos y valores de los desempeños disponibles en AVA. |
| `conversionPolicy` | Política para mapear porcentajes a desempeños: `exact`, `floor` o `nearest`. |
| `timeoutMs` | Tiempo máximo de espera por operaciones de Playwright. |
| `windowWidth` / `windowHeight` | Tamaño de ventana para evitar que AVA colapse paneles. |
| `navigationDelayMs` / `saveDelayMs` | Esperas entre navegación y guardado. |
| `text` | Textos visibles esperados en AVA, útiles si cambia el idioma o la interfaz. |
| `selectors` | Selectores de respaldo para navegación de estudiantes. |

### Desempeños

`rubricLevels` debe coincidir con los nombres exactos que AVA muestra en cada criterio:

```json
"rubricLevels": [
  { "label": "Muy buen desempeño", "percent": 100 },
  { "label": "Buen desempeño", "percent": 80 },
  { "label": "Desempeño aceptable", "percent": 60 },
  { "label": "Desempeño incipiente", "percent": 30 },
  { "label": "Desempeño no logrado", "percent": 0 }
]
```

El script usa `label` para seleccionar el desempeño en AVA y `percent` para mapear el porcentaje exportado por IE.

Si AVA usa otros nombres o valores, cambia esta lista. Por ejemplo:

```json
"rubricLevels": [
  { "label": "Logrado", "percent": 100 },
  { "label": "No logrado", "percent": 0 }
]
```

Con `conversionPolicy: "exact"`, cada IE exportado debe tener exactamente uno de esos porcentajes.

## Variables

El roster activo se lee desde:

```text
evaluations/<SECTION_CODE>/students.json
```

Define siempre la sección antes de ejecutar:

```bash
SECTION_CODE=<codigo-seccion> npm run inspect
```

Opcionalmente puedes inyectar una cookie temporal:

```bash
AVA_JSESSIONID='valor-temporal' SECTION_CODE=<codigo-seccion> npm run inspect
```

`JSESSIONID` puede no bastar si el SSO exige cookies adicionales. La opción más estable es iniciar sesión manualmente en el navegador abierto por Playwright.

## Flujo Manual

1. Exporta resultados desde la raíz:

```bash
./scripts/export-results.sh
```

2. Configura `automation/ava/config.json`.

3. Inspecciona la página:

```bash
cd automation/ava
SECTION_CODE=<codigo-seccion> npm run inspect
```

Si AVA pide autenticación, inicia sesión en el navegador abierto. La sesión queda en:

```text
automation/ava/.ava-session/
```

4. Simula un estudiante:

```bash
SECTION_CODE=<codigo-seccion> npm run dry-run -- --student 19452600
```

5. Carga un estudiante y verifica manualmente:

```bash
SECTION_CODE=<codigo-seccion> npm run import -- --student 19452600
```

6. Solo cuando el resultado sea correcto, carga todos:

```bash
SECTION_CODE=<codigo-seccion> npm run import -- --all
```

## Flujo con Agente

Un agente puede ejecutar el mismo flujo, pero debe respetar estas condiciones:

- primero correr `./scripts/workspace-status.sh` y `./scripts/export-results.sh`;
- pedir o confirmar `SECTION_CODE`;
- verificar que `automation/ava/config.json` tenga `gradebookUrl`, `evaluationId` y `rubricLevels`;
- usar `npm run inspect` o `npm run dry-run` antes de cualquier `npm run import`;
- no usar `--all` sin validación previa de un estudiante;
- no guardar credenciales ni cookies en archivos del repositorio.

El agente puede abrir Playwright y esperar que el docente complete el login. Después puede continuar usando la sesión local.

Una instrucción típica para el agente es:

```text
Realiza la actualización automática de los desempeños y feedbacks en AVA, para el alumno <studentId>.
```

Con esa instrucción, el agente debe interpretar `<studentId>` como el RUT o identificador usado en el export y ejecutar primero una validación sin guardado:

```bash
SECTION_CODE=<codigo-seccion> npm run dry-run -- --student <studentId>
```

Ojo: AVA normalmente no muestra el `studentId` en la lista lateral. El `studentId` se usa para buscar el resultado exportado localmente; después el script selecciona al alumno en AVA por el nombre visible. Ese nombre se construye desde `evaluations/<SECTION_CODE>/students.json` con este formato:

```text
<lastName> <secondLastName>, <names>
```

Por eso, si AVA muestra nombres con otro orden, abreviaturas, tildes, segundos apellidos faltantes o diferencias respecto del export original, la automatización puede no encontrar al alumno aunque el `studentId` exista. En ese caso corrige el roster efectivo o el roster maestro antes de importar.

Si la simulación coincide con AVA y el docente autoriza el guardado, entonces ejecuta:

```bash
SECTION_CODE=<codigo-seccion> npm run import -- --student <studentId>
```

## Comandos

Ayuda directa:

```bash
node ava-import.mjs --help
```

Inspección:

```bash
npm run inspect
npm run inspect -- --student 19452600
```

Simulación sin guardar:

```bash
npm run dry-run -- --student 19452600
npm run dry-run -- --evaluation EV3 --student 19452600
```

Importación con guardado:

```bash
npm run import -- --student 19452600
npm run import -- --evaluation EV3 --student 19452600
npm run import -- --all
```

Solo feedback general:

```bash
npm run import -- --evaluation EV3 --student 21053679 --feedback-only
```

URL puntual:

```bash
npm run dry-run -- --student 19452600 --url 'https://campusvirtual.duoc.cl/...'
```

## Políticas de Conversión

La política define qué hacer cuando el porcentaje exportado para un IE no coincide exactamente con un desempeño de AVA.

```bash
# Solo acepta coincidencias exactas; opción segura predeterminada
npm run import -- --evaluation EV3 --student 19703214 --conversion exact

# Selecciona el nivel configurado inmediatamente inferior
npm run import -- --evaluation EV3 --student 19703214 --conversion floor

# Selecciona el nivel configurado con menor distancia
npm run import -- --evaluation EV3 --student 19703214 --conversion nearest
```

Para carga académica oficial, usa `exact` salvo que el docente haya decidido explícitamente otra política.

## Validaciones

Antes de guardar, el script comprueba:

- que el estudiante exista en `evaluations/<SECTION_CODE>/students.json`;
- que el estudiante tenga resultado `Evaluada` en `exports/publication-input/course/results.json`;
- que la cantidad de IE exportados coincida con los criterios visibles en AVA;
- que todos los desempeños configurados existan en cada IE visible;
- que el feedback individual se haya escrito en cada IE;
- que el puntaje parcial mostrado por AVA coincida con el puntaje exportado;
- que el total visible en AVA coincida con el resultado esperado sobre 100.

## Reportes

Cada ejecución genera un JSON local en:

```text
automation/ava/reports/
```

Los reportes incluyen estudiante, URL usada, cantidad de IE, niveles detectados, política de conversión, modo `commit` y errores si los hubo.

## Problemas Frecuentes

`define gradebookUrl en automation/ava/config.json`:

La URL no fue configurada. Copia la URL completa de la pantalla de calificación de intento.

`no se encontró en AVA como "..."`

El nombre esperado se arma como:

```text
<lastName> <secondLastName>, <names>
```

Revisa `evaluations/<SECTION_CODE>/students.json` y cómo AVA muestra el nombre.
El `studentId` no basta para seleccionar al alumno dentro de AVA, porque la interfaz lateral se navega por nombre visible.

`AVA "...desempeño..." = 0`

El texto en `rubricLevels[].label` no coincide exactamente con AVA o la rúbrica no está abierta para esa evaluación.

`porcentaje ... no existe en AVA`

El export produjo un porcentaje que no está en `rubricLevels`. Revisa la corrección o usa una política de conversión aprobada.

`no se encontró el botón Abrir rúbrica`

La URL puede no ser la pantalla correcta de calificación de intento, o AVA cambió la interfaz. Ejecuta `npm run inspect` y revisa el reporte textual.
