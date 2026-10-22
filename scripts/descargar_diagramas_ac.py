"""Descarga imágenes de especificaciones desde un resultado JSON."""
import argparse
import json
import logging
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import httpx

# Permite ejecutar el archivo directamente desde la raíz del repositorio:
# ``python scripts\descargar_diagramas_ac.py``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from configuracion import AC_DIR, IMAGES_DIR, configurar_logging

logger = logging.getLogger(__name__)


def extension_imagen(url: str, respuesta: httpx.Response) -> str:
    extension = Path(urlsplit(url).path).suffix.lower()
    if extension in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tif', '.tiff'}:
        return extension
    tipo = respuesta.headers.get('content-type', '').split(';', 1)[0].lower()
    return {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'image/svg+xml': '.svg',
        'image/bmp': '.bmp',
        'image/tiff': '.tiff',
    }.get(tipo, '.bin')


def descargar(entrada: Path | None = None, destino: Path | None = None,
              solicitado: str = 'Mazda 2', pausa: float = 1.0) -> None:
    configurar_logging()
    entrada = entrada or AC_DIR / 'despues.json'
    destino = destino or IMAGES_DIR
    datos = json.loads(entrada.read_text(encoding='utf-8'))
    if isinstance(datos, dict):
        vehiculo = datos.get('vehiculo', {})
        datos = [{
            'solicitado': f"{vehiculo.get('marca', '')} {vehiculo.get('modelo', '')}".strip(),
            'tipo': 'resultado',
            'documentos': datos.get('documentos', []),
        }]
    if not isinstance(datos, list):
        raise ValueError('El JSON de entrada debe ser un resultado o una lista de casos.')
    destino.mkdir(parents=True, exist_ok=True)
    manifest = []
    vistos = set()
    for caso in datos:
        if solicitado and not caso['solicitado'].casefold().startswith(solicitado.casefold()):
            continue
        for doc in caso['documentos']:
            for imagen in doc.get('imagenes', []):
                url = imagen['url']
                if url in vistos:
                    continue
                vistos.add(url)
                extension = Path(urlsplit(url).path).suffix or '.png'
                archivo = destino / f'mazda2_{len(vistos)}{extension}'
                if not archivo.exists():
                    respuesta = httpx.get(url, timeout=30, follow_redirects=True)
                    if respuesta.status_code != 200:
                        raise RuntimeError(f'HTTP {respuesta.status_code}')
                    archivo = archivo.with_suffix(extension_imagen(url, respuesta))
                    archivo.write_bytes(respuesta.content)
                    if pausa > 0:
                        time.sleep(pausa)
                manifest.append({'archivo': str(archivo), 'url': url, 'seccion': doc['seccion'], 'tipo': caso['tipo']})
                logger.info('%s %s', archivo, doc['seccion'])
    (destino / 'fuentes.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Descarga imágenes referenciadas por un resultado JSON.')
    parser.add_argument('--entrada', type=Path, default=AC_DIR / 'despues.json',
                        help='JSON con los documentos recuperados.')
    parser.add_argument('--destino', type=Path, default=IMAGES_DIR,
                        help='Carpeta donde se guardan imágenes y fuentes.json.')
    parser.add_argument('--solicitado', default='Mazda 2',
                        help='Vehículo a filtrar; usa "" para procesar todos.')
    parser.add_argument('--pausa', type=float, default=1.0,
                        help='Segundos entre descargas (0 desactiva la pausa).')
    try:
        args = parser.parse_args()
        descargar(args.entrada, args.destino, args.solicitado, args.pausa)
    except Exception:
        logger.exception("Falló la descarga de diagramas")
        raise SystemExit(1)
