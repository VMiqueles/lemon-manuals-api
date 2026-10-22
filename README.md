<p align="center">
  <img src="docs/assets/autospec-cli-banner.png" alt="LEMON Manuals API" width="100%">
</p>

# lemon-manuals-api

API CLI y scraper de manuales automotrices basado en el catálogo público de
[LEMON Manuals](https://lemon-manuals.la). Busca una variante exacta del
vehículo, localiza secciones técnicas y devuelve JSON listo para una persona,
un script o un agente de IA.

> **Estado del proyecto:** extractor de texto HTML e imágenes referenciadas.
> No hace OCR, no interpreta la imagen automáticamente y no sustituye la
> verificación del manual, mercado, VIN o procedimiento oficial.

## Inicio rápido

### 1. Instalar

Requiere Python 3.10 o superior.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

En Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Ejecutar una consulta

```powershell
python main.py `
  --marca Hyundai `
  --anio 2015 `
  --modelo "Tucson GLS, FWD" `
  --consulta "cantidad de gas refrigerante" `
  --limite 3
```

La respuesta JSON se imprime en `stdout`. Los logs y errores operativos se
imprimen en `stderr`.

Guardar el resultado:

```powershell
python main.py --marca Toyota --anio 2015 `
  --modelo "Yaris" `
  --consulta "tipo de aceite de motor" `
  --salida datos\yaris-aceite.json
```

El archivo `.json` no se sobrescribe. Para agregar registros independientes usa
`.jsonl`.

## Qué puede buscar

Usa consultas cortas y específicas. El buscador entiende español y reconoce
también la terminología inglesa del sitio fuente.

| Necesidad | Ejemplos |
| --- | --- |
| Refrigerante del motor | `capacidad de refrigerante`, `coolant capacity` |
| Gas del A/C | `cantidad de gas refrigerante del aire acondicionado`, `refrigerant capacity` |
| Aceite de motor | `tipo de aceite de motor`, `engine oil capacity` |
| Aceite del compresor | `tipo de aceite del compresor`, `compressor oil` |
| Electricidad | `diagrama eléctrico`, `ramal eléctrico`, `wiring diagram` |
| Frenos | `despiece de frenos`, `brake caliper removal` |
| Carrocería | `desmontaje de parachoques`, `front bumper removal` |
| Diagnóstico | `código P0301`, `DTC P0301` |
| Aprietes | `torque de culata`, `cylinder head torque` |

Para distinguir el aire acondicionado del refrigerante del motor, incluye
`aire acondicionado`, `A/C`, `air conditioning` o `compressor`.

## Modelo, año y variante

El sitio contiene muchas variantes del mismo modelo. La selección debe ser
exacta para evitar mezclar motores, transmisiones o carrocerías:

```powershell
python main.py --marca Mazda --anio 2012 `
  --modelo "2 L4-1.5L" `
  --consulta "diagrama eléctrico"
```

Si el modelo es ambiguo, el programa no elige silenciosamente. Devuelve
`opciones` y código de salida `1`; repite la consulta con una opción completa.

## Contrato de salida para IA y automatizaciones

Una respuesta exitosa tiene esta forma:

```json
{
  "schema_version": 1,
  "consulta": "tipo de aceite de motor",
  "vehiculo": {
    "marca": "Toyota",
    "anio": "2015",
    "modelo": "Yaris",
    "manual_url": "https://lemon-manuals.la/..."
  },
  "secciones_coincidentes": 1,
  "documentos": [
    {
      "id": "sha256-de-la-url",
      "fuente_url": "https://lemon-manuals.la/...",
      "seccion": "Engine > Lubrication > Specifications",
      "texto": ["Texto HTML extraído"],
      "imagenes": [],
      "extraido_en": "2026-10-20T15:00:00+00:00",
      "contenido_sha256": "sha256-del-contenido",
      "metodo_extraccion": "html_sin_ocr",
      "requiere_revision_imagenes": false
    }
  ],
  "limite": 3,
  "indice_completo": true,
  "truncado": false
}
```

### Reglas para consumir la respuesta

1. Comprueba `error` antes de leer `documentos`.
2. Comprueba el código de salida del proceso.
3. Usa `fuente_url` e `id` para trazabilidad y deduplicación.
4. Si `requiere_revision_imagenes` es `true`, el texto no contiene toda la
   información: descarga o revisa las imágenes.
5. No conviertas una coincidencia en una recomendación mecánica sin verificar la
   variante exacta.
6. `secciones_coincidentes` es el total localizado; `documentos` está limitado
   por `--limite`.

## Códigos de salida

| Código | Significado |
| ---: | --- |
| `0` | Consulta completada; puede haber cero coincidencias. |
| `1` | Error de red, lectura parcial o selección ambigua. La explicación queda en JSON. |
| `2` | Argumentos inválidos o ruta de salida inválida. |

Un servidor remoto puede cerrar conexiones o devolver protección temporal. Es
un error de acceso, no una confirmación de que el dato no exista.

## Descargar diagramas e imágenes

Cuando una respuesta JSON contiene `documentos[].imagenes`, usa el descargador:

```powershell
python scripts\descargar_diagramas_ac.py `
  --entrada datos\resultado.json `
  --destino datos\imagenes `
  --solicitado "Mazda 2" `
  --pausa 1
```

También acepta el formato de lista usado por los benchmarks:

```powershell
python -m scripts.descargar_diagramas_ac `
  --entrada datos\prueba_ac_30\despues.json `
  --destino datos\prueba_ac_30\imagenes
```

Opciones:

| Opción | Predeterminado | Descripción |
| --- | --- | --- |
| `--entrada` | `datos/prueba_ac_30/despues.json` | Resultado individual o lista de casos. |
| `--destino` | `datos/prueba_ac_30/imagenes` | Carpeta para imágenes y `fuentes.json`. |
| `--solicitado` | `Mazda 2` | Prefijo del vehículo; vacío procesa todos. |
| `--pausa` | `1` | Segundos entre descargas; `0` desactiva la pausa. |

El archivo `fuentes.json` relaciona cada archivo descargado con URL, sección y
tipo. La extensión se detecta desde la URL o desde `Content-Type`.

## Configuración

Puedes usar `.env` en la raíz:

```env
DIRECTORIO_DATOS=datos/
LIMITE_SECCIONES_POR_DEFECTO=3
BASE_URL=https://lemon-manuals.la
```

También existen `AC_DIR`, `CACHE_DIR`, `IMAGES_DIR` y `OUTPUT_FILE` para los
scripts de muestra. Las rutas relativas parten de la raíz del repositorio.

## Docker

```powershell
docker build -t lemon-manuals-api .
docker run --rm lemon-manuals-api `
  --marca Honda `
  --anio 2015 `
  --modelo "Fit EX, Automatic CVT Trans" `
  --consulta "tipo de aceite del compresor"
```

## Pruebas y validación

Ejecuta las pruebas locales:

```powershell
python -m pytest -q
```

Las pruebas usan HTML simulado y no dependen de la red. La validación realizada
en este proyecto pasó **14 pruebas**.

Para una prueba real:

```powershell
python main.py --marca Mazda --anio 2012 `
  --modelo "2 L4-1.5L" `
  --consulta "body control module" `
  --salida datos\diagrama-electrico.json
```

La prueba masiva histórica está en
[datos/prueba_30_autos.json](datos/prueba_30_autos.json). Procesó 28 de 30
vehículos: 23 resultados recuperados y 5 errores de conexión remota.

## Estructura

```text
.
├── main.py                         CLI y extractor principal
├── configuracion.py                Variables de entorno y logging
├── scripts/descargar_diagramas_ac.py  Descarga de imágenes referenciadas
├── scripts/benchmark_ac.py         Benchmark y caché de consultas
├── tests/test_main.py              Pruebas de regresión
├── datos/                          Resultados locales (no son la fuente del código)
├── Dockerfile
└── requirements.txt
```

## Limitaciones y uso responsable

- El contenido depende de la disponibilidad y estructura de la fuente remota.
- El scraper no supera protecciones anti-bot ni intenta evadir límites.
- El texto se extrae de HTML; no se realiza OCR de diagramas.
- Una sección encontrada puede no contener el dato final esperado.
- Verifica año, motor, transmisión, mercado y VIN antes de usar un dato técnico.
- Respeta las condiciones de uso, derechos y frecuencia razonable del sitio
  consultado.

## Renombrar el repositorio en GitHub

El nombre objetivo de este proyecto es `lemon-manuals-api`. Para aplicar el
renombrado en GitHub, abre **Settings → General → Repository name**, escribe
`lemon-manuals-api` y confirma. Después actualiza el remoto local:

```powershell
git remote set-url origin https://github.com/VMiqueles/lemon-manuals-api.git
```

GitHub normalmente redirige la URL antigua, pero conviene actualizar el remoto
para que futuros `git push` sean explícitos.
