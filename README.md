<p align="center">
  <img src="docs/assets/autospec-cli-banner.png" alt="AutoSpec CLI" width="100%">
</p>

# AutoSpec CLI

AutoSpec CLI es una herramienta de línea de comandos que localiza información técnica en manuales automotrices y la entrega como JSON estructurado. Está orientada a agentes de inteligencia artificial, automatizaciones y servicios backend que necesitan una interfaz predecible, sin menús interactivos.

La herramienta navega el índice público de manuales, selecciona una marca, un año y una variante exacta, clasifica las secciones relacionadas con una consulta y extrae el texto HTML disponible. No genera recomendaciones mecánicas ni sustituye la verificación contra el manual correspondiente al vehículo.

## Alcance

AutoSpec CLI puede buscar, entre otros contenidos:

- Capacidades de refrigerante y otros fluidos.
- Tipos y especificaciones de aceite.
- Carga y lubricante del sistema de aire acondicionado.
- Códigos de diagnóstico DTC.
- Pares de apriete y secciones de reparación.

La extracción se realiza sobre texto HTML. Las tablas o diagramas que solo existen como imagen se referencian en la respuesta, pero no se procesan mediante OCR.

## Características

- JSON en `stdout` para resultados correctos y errores controlados.
- Logs operativos en `stderr`, separados de la respuesta estructurada.
- Selección explícita de variantes para evitar resultados de otro modelo.
- Límite configurable de secciones recuperadas por consulta.
- Exportación opcional en JSON o JSONL.
- Identificadores y hashes SHA-256 para trazabilidad y deduplicación.
- Imagen Docker reproducible basada en Python 3.12.
- Pruebas automatizadas y workflow de integración continua.

## Requisitos

- Python 3.10 o superior para ejecución local.
- Acceso de red al sitio configurado en `BASE_URL`.
- Docker, opcionalmente, para ejecución en contenedores.

## Instalación local

Clona el repositorio y entra en el directorio:

```bash
git clone https://github.com/VMiqueles/AutoSpecCLI.git
cd AutoSpecCLI
```

Crea un entorno virtual e instala las dependencias.

En Linux o macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

En PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## Configuración

El archivo `.env.example` contiene la configuración pública:

```env
DIRECTORIO_DATOS=datos/
LIMITE_SECCIONES_POR_DEFECTO=3
BASE_URL=https://lemon-manuals.la
```

| Variable | Descripción | Valor predeterminado |
| --- | --- | --- |
| `DIRECTORIO_DATOS` | Directorio para exportaciones y datos auxiliares. | `datos/` |
| `LIMITE_SECCIONES_POR_DEFECTO` | Número máximo de secciones que se recuperan si no se indica `--limite`. | `3` |
| `BASE_URL` | Dirección raíz del catálogo de manuales. | `https://lemon-manuals.la` |

Las rutas relativas se resuelven desde la raíz del proyecto.

## Uso

La interfaz pública requiere marca, año, modelo y consulta:

```bash
python main.py \
  --marca Hyundai \
  --anio 2015 \
  --modelo "Tucson GLS, FWD" \
  --consulta "cantidad de gas refrigerante"
```

En PowerShell puede ejecutarse en una sola línea:

```powershell
python main.py --marca Hyundai --anio 2015 --modelo "Tucson GLS, FWD" --consulta "cantidad de gas refrigerante"
```

### Argumentos

| Argumento | Obligatorio | Descripción |
| --- | --- | --- |
| `--marca` | Sí | Marca tal como aparece en el catálogo. |
| `--anio` | Sí | Año del manual. |
| `--modelo` | Sí | Modelo o variante exacta. |
| `--consulta` | Sí | Tema técnico que se desea localizar. |
| `--limite` | No | Máximo de secciones recuperadas; admite valores entre 1 y 100. |
| `--salida` | No | Ruta de exportación terminada en `.json` o `.jsonl`. |
| `--json` | No | Opción conservada por compatibilidad; la salida estándar ya siempre es JSON. |

Si el nombre del modelo es ambiguo, la respuesta incluye `opciones` con las variantes disponibles. La consulta debe repetirse usando una de ellas de forma exacta.

## Consultas recomendadas

Las frases breves y específicas producen mejores resultados:

```text
capacidad de refrigerante
tipo de aceite de motor
cantidad de gas refrigerante del aire acondicionado
tipo de aceite del compresor del aire acondicionado
codigo P0301
torque de culata
```

`refrigerante` se interpreta como refrigerante del motor. Para consultar el sistema de climatización debe incluirse `aire acondicionado` o `A/C`.

## Contrato JSON para agentes

Una respuesta correcta utiliza el siguiente esquema general:

```json
{
  "schema_version": 1,
  "consulta": "cantidad de gas refrigerante",
  "vehiculo": {
    "marca": "Hyundai",
    "anio": "2015",
    "modelo": "Tucson GLS, FWD",
    "manual_url": "https://example.invalid/manual"
  },
  "secciones_coincidentes": 1,
  "documentos": [
    {
      "id": "sha256-de-la-url-fuente",
      "fuente_url": "https://example.invalid/seccion",
      "seccion": "Heating, Ventilation & A/C > System Charging",
      "texto": [
        "Charge the system with 550 ± 25 g of refrigerant."
      ],
      "imagenes": [],
      "extraido_en": "2026-01-01T12:00:00+00:00",
      "contenido_sha256": "sha256-del-contenido",
      "metodo_extraccion": "html_sin_ocr",
      "requiere_revision_imagenes": false
    }
  ],
  "alcance": "Títulos y rutas del índice. Texto HTML sin OCR ni respuesta generada.",
  "limite": 3,
  "indice_completo": true,
  "truncado": false
}
```

Las URLs del ejemplo usan el dominio reservado `example.invalid`; una ejecución real devuelve las fuentes consultadas.

### Respuesta de error

Los errores esperados también se escriben como JSON:

```json
{
  "schema_version": 1,
  "consulta": "tipo de aceite",
  "vehiculo": {
    "marca": "BMW",
    "anio": "2020",
    "modelo": "430i"
  },
  "secciones_coincidentes": 0,
  "documentos": [],
  "error": "Selecciona la variante completa de '430i'.",
  "http": null,
  "opciones": [
    "430i Coupe",
    "430i Convertible"
  ]
}
```

### Códigos de salida

| Código | Significado |
| --- | --- |
| `0` | Consulta completada sin errores de lectura. |
| `1` | Fallo de acceso, extracción o lectura parcial. La explicación permanece disponible como JSON. |
| `2` | Argumentos o configuración de línea de comandos inválidos. |

Una integración debe interpretar el JSON y comprobar también el código de salida del proceso.

## Exportación

Para crear un archivo JSON nuevo:

```bash
python main.py --marca Hummer --anio 2010 --modelo "H3 Alpha" --consulta "capacidad de refrigerante" --salida datos/hummer.json
```

Los archivos `.json` se crean de forma exclusiva: la herramienta no sobrescribe un archivo existente.

Para acumular documentos como registros independientes:

```bash
python main.py --marca Hummer --anio 2010 --modelo "H3 Alpha" --consulta "capacidad de refrigerante" --salida datos/manuales.jsonl
```

JSONL añade una línea por documento. Una consulta sin documentos no añade líneas. Los consumidores pueden usar `id` para deduplicación y `contenido_sha256` para detectar cambios.

## Docker

Construye la imagen:

```bash
docker build -t autospec-cli .
```

Ejecuta una consulta en un contenedor efímero:

```bash
docker run --rm autospec-cli \
  --marca Honda \
  --anio 2015 \
  --modelo "Fit EX, Automatic CVT Trans" \
  --consulta "tipo de aceite del compresor"
```

Para conservar exportaciones, monta un volumen y configura el directorio interno:

```bash
docker run --rm \
  -e DIRECTORIO_DATOS=/app/datos \
  -v "$PWD/datos:/app/datos" \
  autospec-cli \
  --marca Hummer \
  --anio 2010 \
  --modelo "H3 Alpha" \
  --consulta "capacidad de refrigerante" \
  --salida /app/datos/hummer.json
```

## Pruebas

Ejecuta la suite completa:

```bash
python -m pytest tests/test_main.py -v
```

Las pruebas usan documentos HTML simulados y no requieren acceso al sitio remoto.

## Estructura del repositorio

```text
AutoSpecCLI/
├── .github/workflows/    Integración continua
├── docs/assets/          Recursos gráficos del repositorio
├── scripts/              Benchmark y utilidades de consolidación
├── tests/                Pruebas automatizadas
├── configuracion.py      Variables de entorno y logging
├── main.py               CLI y motor de extracción
├── Dockerfile            Imagen de ejecución
└── requirements.txt      Dependencias fijadas
```

## Integración continua

El workflow `.github/workflows/pruebas.yml` instala las dependencias y ejecuta pytest en cada push o pull request dirigido a `main` o `master`.

## Limitaciones operativas

- Los resultados dependen de la estructura y disponibilidad de un sitio remoto; una misma consulta puede variar si la fuente cambia.
- El cliente HTTP no intenta superar protecciones anti-bot. Un HTTP 403 se devuelve como error estructurado.
- La búsqueda clasifica títulos y rutas del índice; no interpreta semánticamente el manual completo.
- No se realiza OCR. Los documentos basados en imágenes pueden requerir revisión manual.
- Una coincidencia identifica una sección potencialmente relevante; no garantiza que contenga el dato esperado.
- La aplicabilidad técnica debe comprobarse contra año, variante, mercado y VIN cuando corresponda.

## Uso responsable

Respeta las condiciones de uso, las restricciones de acceso y los derechos sobre el contenido de la fuente configurada. Mantén una frecuencia de solicitudes razonable y verifica la información antes de utilizarla en un procedimiento técnico.
