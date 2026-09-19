"""Configuración compartida; las rutas relativas parten del directorio del proyecto."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

PROYECTO = Path(__file__).resolve().parent
load_dotenv(PROYECTO / '.env', override=False)


def ruta_entorno(nombre: str, defecto: Path) -> Path:
    ruta = Path(os.getenv(nombre) or defecto).expanduser()
    return ruta if ruta.is_absolute() else PROYECTO / ruta


BASE_URL = (os.getenv('BASE_URL') or 'https://lemon-manuals.la').rstrip('/') + '/'
DATA_DIR = ruta_entorno('DIRECTORIO_DATOS', Path('datos'))
try:
    LIMITE_SECCIONES_POR_DEFECTO = int(os.getenv('LIMITE_SECCIONES_POR_DEFECTO', '3'))
except ValueError as exc:
    raise ValueError('LIMITE_SECCIONES_POR_DEFECTO debe ser un entero.') from exc
if not 1 <= LIMITE_SECCIONES_POR_DEFECTO <= 100:
    raise ValueError('LIMITE_SECCIONES_POR_DEFECTO debe estar entre 1 y 100.')
AC_DIR = ruta_entorno('AC_DIR', DATA_DIR / 'prueba_ac_30')
CACHE_DIR = ruta_entorno('CACHE_DIR', AC_DIR / 'cache')
IMAGES_DIR = ruta_entorno('IMAGES_DIR', AC_DIR / 'imagenes')
OUTPUT_FILE = ruta_entorno('OUTPUT_FILE', DATA_DIR / 'resultados.jsonl')


def configurar_logging() -> None:
    """Mantiene stdout reservado para JSON y silencia detalles de red."""
    logging.basicConfig(level=logging.ERROR, stream=None)
    for nombre in ('httpx', 'httpcore', 'scrapling', 'urllib3'):
        logging.getLogger(nombre).setLevel(logging.WARNING)
