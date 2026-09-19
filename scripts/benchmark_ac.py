"""30 consultas reales de A/C, reproducibles con caché y sin elegir vehículos equivalentes."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import re
from pathlib import Path

import main
from main import Selector


MUESTRA = [
    ('Hyundai', 'Tucson'), ('Hyundai', 'Elantra'), ('Hyundai', 'i10'),
    ('Mazda', 'Demio'), ('Mazda', '2'), ('Hyundai', 'Accent'),
    ('Kia', 'Rio'), ('Kia', 'Sportage'), ('Toyota', 'Yaris'),
    ('Toyota', 'Corolla'), ('Toyota', 'RAV4'), ('Nissan', 'Versa'),
    ('Nissan', 'Sentra'), ('Suzuki', 'Swift'), ('Honda', 'Fit'),
    ('Mazda', '3'), ('Chevrolet', 'Spark'), ('Kia', 'Soul'),
    ('Hyundai', 'Santa Fe'), ('Toyota', 'Camry'), ('Honda', 'Civic'),
]
CONSULTAS = [
    ('gas', 'cantidad de gas refrigerante del aire acondicionado'),
    ('aceite', 'tipo de aceite del compresor del aire acondicionado'),
]
from configuracion import AC_DIR, CACHE_DIR, IMAGES_DIR, configurar_logging

CARPETA = AC_DIR
logger = logging.getLogger(__name__)


def buscar_antes(pagina: Selector, url: str, raiz: str, consulta: str) -> list[main.Enlace]:
    """Ranking previo conservado para las dos consultas de esta prueba."""
    consulta = main.normalizar(consulta)
    capacidad = bool(re.search(r'cantidad|capacidad|cuanto|litros|capacity|capacities', consulta))
    recomendado = bool(re.search(r'recomienda|recomendado|tipo|grado|viscosidad', consulta))
    stop = set('que cual cuanto de del la el los las un una usa lleva para por se es en y mi auto coche vehiculo busca buscar cantidad capacidad recomendado recomienda tipo motor'.split())
    palabras = set(re.findall(r'[a-z0-9]+', consulta)) - stop
    resultados = []
    for enlace in main.extraer_enlaces(pagina, url):
        if not main.dentro_del_manual(enlace.url, raiz) or main.es_archivo(enlace.url) or enlace.url == url:
            continue
        partes = main.segmentos_url(enlace.url)[len(main.segmentos_url(raiz)):]
        contenido = main.normalizar(enlace.texto + ' ' + ' '.join(partes))
        hoja = main.normalizar(' '.join(partes[-2:]) + ' ' + enlace.texto)
        if not re.search(r'refrigerant|air conditioning|a/c', contenido):
            continue
        if re.search(r'fastener|tightening|connector|wiring|pressure sensor', contenido):
            continue
        if capacidad and not re.search(r'capacit|specification|filling|refilling|fluid amount|charge', hoja):
            continue
        if recomendado and not re.search(r'specification|viscosity|fluid type|recommended|oil type|oil grade', hoja):
            continue
        puntos = 10
        if capacidad:
            puntos += 35 if re.search(r'capacit|fluid amount|charge', hoja) else 0
            puntos += 10 if 'specification' in hoja else 0
        if recomendado:
            puntos += 30 if re.search(r'fluid type|viscosity|recommended|specification', hoja) else 0
        puntos += sum(2 for p in palabras if re.search(r'\b' + re.escape(p) + r'\b', hoja))
        nombre = ' > '.join(p for p in partes if not p.startswith('Repair and Diagnosis')) or enlace.texto
        resultados.append((puntos, main.Enlace(nombre, enlace.url)))
    resultados.sort(key=lambda item: (-item[0], item[1].texto))
    return [e for puntos, e in resultados if puntos >= resultados[0][0] - 20]


class ClienteCache(main.Cliente):
    """Caché en disco para comparar versiones sin repetir peticiones."""
    def __init__(self, offline: bool = False):
        super().__init__(pausa=1.0)
        self.offline = offline
        self.carpeta = CACHE_DIR
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def obtener(self, url: str) -> Selector:
        archivo = self.carpeta / (hashlib.sha256(url.encode()).hexdigest() + '.json.gz')
        if archivo.exists():
            with gzip.open(archivo, 'rt', encoding='utf-8') as f:
                datos = json.load(f)
            if 'error' in datos:
                raise main.ErrorAcceso(datos['error'], datos.get('http'))
            pagina = Selector(datos['html'])
            # Selector sin URL: los callers pasan la URL solicitada como base.
            return pagina
        if self.offline:
            raise main.ErrorAcceso('Página no disponible en caché')
        try:
            pagina = super().obtener(url)
        except main.ErrorAcceso as exc:
            if exc.estado == 404:
                with gzip.open(archivo, 'wt', encoding='utf-8') as f:
                    json.dump({'error': str(exc), 'http': exc.estado}, f)
            raise
        with gzip.open(archivo, 'wt', encoding='utf-8') as f:
            json.dump({'html': str(pagina.get()), 'url': url}, f)
        # Evita retener índices completos de todos los vehículos en memoria.
        self.cache.clear()
        return pagina


def descubrir(cliente: ClienteCache, marca: str, modelo: str) -> tuple[str | None, dict]:
    raiz = main.BASE_URL
    marcas = main.opciones_directorio(cliente.obtener(raiz), raiz)
    opciones = main.coincidir_opciones(marcas, marca)
    if len(opciones) != 1:
        return None, {'motivo': 'Marca no disponible', 'anios_revisados': []}
    url_marca = opciones[0].url
    anios = main.opciones_directorio(cliente.obtener(url_marca), url_marca)
    disponibles = {e.texto: e.url for e in anios}
    revisados = []
    for anio in ('2015', '2010', '2020', '2005', '2012'):
        if anio not in disponibles:
            continue
        revisados.append(anio)
        opciones = main.opciones_directorio(cliente.obtener(disponibles[anio]), disponibles[anio])
        variantes = [e for e in opciones if re.match(
            r'^' + re.escape(main.normalizar(modelo)) + r'(?:\s|$)', main.normalizar(e.texto))]
        variantes = [e for e in variantes if not re.search(r'fuel cell|electric|hybrid|\bev\b', e.texto, re.I)]
        if variantes:
            # Elección reproducible para la muestra, NO equivalencia para el auto del usuario.
            variantes.sort(key=lambda e: (bool(re.search(r'4wd|awd|coupe', e.texto, re.I)), e.texto))
            return variantes[0].url, {'anios_revisados': revisados,
                'variante_elegida': variantes[0].texto,
                'criterio': 'Primer año entre 2015, 2010, 2020, 2005, 2012; sin Fuel Cell/EV/híbrido, prioriza 2WD/FWD sin Coupe; desempate alfabético.',
                'variantes_disponibles': [e.texto for e in variantes]}
    return None, {'motivo': 'Modelo no encontrado en los años revisados; no se sustituyó por otro modelo.',
                  'anios_revisados': revisados}


def ejecutar(fase: str, offline: bool = False) -> None:
    configurar_logging()
    CARPETA.mkdir(parents=True, exist_ok=True)
    cliente = ClienteCache(offline)
    manifiesto_path = CARPETA / 'vehiculos.json'
    manifiesto = json.loads(manifiesto_path.read_text(encoding='utf-8')) if manifiesto_path.exists() else {}
    registros = []
    for numero, (marca, modelo) in enumerate(MUESTRA):
        if len(registros) >= 30:
            break
        clave = f'{marca} {modelo}'
        if clave not in manifiesto:
            try:
                url, detalles = descubrir(cliente, marca, modelo)
                manifiesto[clave] = {'url': url, **detalles}
                manifiesto_path.write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding='utf-8')
            except main.ErrorAcceso as exc:
                logger.error(f'Error de descubrimiento {clave}: {exc}')
                raise
        seleccionado = manifiesto[clave]
        url = seleccionado['url']
        if not url:
            logger.warning(f'{clave}: no disponible; queda en manifiesto, no se contabiliza como búsqueda de contenido.')
            continue
        logger.warning(f'{len(registros) // 2 + 1}/15: {clave} — {seleccionado.get("variante_elegida", "no disponible")}')
        indice = None
        pagina = None
        error_indice = None
        if url:
            try:
                indice = main.indice_reparacion(cliente.obtener(url), url)
                if indice:
                    if fase == 'antes':
                        pagina = cliente.obtener(indice.url) if 'all links' in main.normalizar(indice.texto) else None
                    else:
                        pagina = main.cargar_indice(cliente, indice, url)
            except main.ErrorAcceso as exc:
                error_indice = str(exc)
        for tipo, consulta in CONSULTAS:
            registro = {'caso': len(registros) + 1, 'fase': fase,
                        'solicitado': clave, 'tipo': tipo, 'consulta': consulta,
                        'seleccion': seleccionado, 'documentos': []}
            if not url:
                registro['estado'] = 'modelo_no_disponible'
            elif pagina is None:
                registro.update(estado='indice_no_disponible', error=error_indice)
            else:
                buscador = buscar_antes if fase == 'antes' else main.buscar_secciones
                resultados = buscador(pagina, indice.url, url, consulta)
                registro['coincidencias'] = len(resultados)
                registro['candidatos'] = [{'seccion': e.texto, 'url': e.url} for e in resultados[:8]]
                for enlace in resultados[:3]:
                    try:
                        registro['documentos'].append(main.leer_seccion(cliente, enlace))
                    except main.ErrorAcceso as exc:
                        registro['documentos'].append({'seccion': enlace.texto, 'fuente_url': enlace.url, 'error': str(exc)})
                registro['estado'] = 'recuperado' if resultados else 'sin_coincidencias'
            registros.append(registro)
            # Checkpoint por consulta: conserva fallos y ausencia de modelos.
            (CARPETA / f'{fase}.json').write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding='utf-8')
            with (CARPETA / f'{fase}.jsonl').open('w', encoding='utf-8') as f:
                for r in registros:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
            logger.info(f'  Consulta {registro["caso"]:02}: {tipo}: {registro["estado"]}, {registro.get("coincidencias", 0)} coincidencias')
    logger.info(f'Terminadas {len(registros)} consultas. Archivos: {CARPETA / fase}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fase', default='antes')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    ejecutar(args.fase, args.offline)
