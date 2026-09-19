# AutoSpec CLI 🚗⚙️

AutoSpec CLI es un motor de extracción de datos de línea de comandos (CLI) que navega, filtra y recupera información técnica específica de manuales automotrices.

Está diseñado bajo la arquitectura de **Tool Use** para integrarse directamente con agentes de Inteligencia Artificial o backends de gestión automotriz. Su ejecución es determinista: recibe parámetros estructurados y devuelve exclusivamente un objeto JSON validado por la salida estándar (`stdout`), suprimiendo cualquier log interno para evitar errores de decodificación.

## 🚀 Características Principales

* **Salida JSON Pura:** Diseñado para integraciones *machine-to-machine*. Sin menús interactivos ni *prompts* que bloqueen el hilo de ejecución.
* **Aislamiento Dockerizado:** Empaquetado para ejecutarse en contenedores efímeros, garantizando que el entorno sea idéntico en cualquier servidor.
* **Gestión de Errores Inteligente:** Si no se encuentra un manual o variante, retorna un JSON estructurado con `secciones_coincidentes: 0` en lugar de romper el proceso.
* **Extracción de Precisión:** Capaz de buscar capacidades de fluidos, tipos de aceites, códigos DTC y torques de componentes específicos.

## 🛠️ Requisitos del Entorno

Si deseas ejecutarlo de forma local sin Docker, necesitas Python 3.10 o superior.
Configura las variables de entorno creando un archivo `.env` en la raíz (usa `.env.example` como referencia):

```env
DIRECTORIO_DATOS=datos/
LIMITE_SECCIONES_POR_DEFECTO=3
BASE_URL=https://lemon-manuals.la
```

## 📦 Instalación y Uso

### Opción A: Ejecución Local

1. Instala las dependencias:

```bash
pip install -r requirements.txt
```

2. Ejecuta una consulta directa:

```bash
python main.py --marca Hyundai --anio 2015 --modelo "Tucson GLS, FWD" --consulta "cantidad de gas refrigerante" --json
```

### Opción B: Ejecución con Docker (Recomendado para Producción)

Construye la imagen del contenedor:

```bash
docker build -t autospec-cli .
```

Ejecuta un contenedor efímero pasando los parámetros de búsqueda:

```bash
docker run --rm autospec-cli --marca Honda --anio 2015 --modelo "Fit EX, Automatic CVT Trans" --consulta "tipo de aceite del compresor" --json
```

## 📄 Estructura de Salida (JSON)

El script garantiza que el `stdout` sea decodificable de forma directa. Ejemplo de respuesta exitosa:

```json
{
  "schema_version": 1,
  "consulta": "cantidad de gas refrigerante",
  "vehiculo": {
    "marca": "Hyundai",
    "anio": "2015",
    "modelo": "Tucson GLS, FWD"
  },
  "secciones_coincidentes": 1,
  "documentos": [
    {
      "id": "dbce9eb5ce07d5a2f15a3...",
      "seccion": "Heating, Ventilation & A/C (HVAC) > System Charging",
      "texto": [
        "Charge the system with 19.4 ± 0.88 oz. (550 ± 25g) of R-134a refrigerant."
      ],
      "fuente_url": "https://...",
      "imagenes": []
    }
  ]
}
```

## 🧪 Pruebas Unitarias

El proyecto incluye un conjunto de validaciones para asegurar que las reglas de extracción HTML y filtrado se mantengan estables ante cambios en la fuente.

```bash
python -m pytest tests/test_main.py -v
```
