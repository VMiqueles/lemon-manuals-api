"""Descarga las imágenes de especificaciones recuperadas para Mazda2 en la prueba."""
import json
import logging
from pathlib import Path
import time
from urllib.parse import urlsplit
import httpx

from configuracion import AC_DIR, IMAGES_DIR, configurar_logging

logger = logging.getLogger(__name__)


def descargar() -> None:
    configurar_logging()
    carpeta = AC_DIR
    datos = json.loads((carpeta / 'despues.json').read_text(encoding='utf-8'))
    destino = IMAGES_DIR
    destino.mkdir(parents=True, exist_ok=True)
    manifest = []
    vistos = set()
    for caso in datos:
        if caso['solicitado'] != 'Mazda 2':
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
                    archivo.write_bytes(respuesta.content)
                    time.sleep(1)
                manifest.append({'archivo': str(archivo), 'url': url, 'seccion': doc['seccion'], 'tipo': caso['tipo']})
                logger.info('%s %s', archivo, doc['seccion'])
    (destino / 'fuentes.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == "__main__":
    try:
        descargar()
    except Exception:
        logger.exception("Falló la descarga de diagramas")
        raise SystemExit(1)
