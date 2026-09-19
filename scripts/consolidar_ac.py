"""Consolida hallazgos revisados de esta muestra; no es un extractor universal.

Los valores se transcribieron de las fuentes guardadas. Exige evidencia textual
en los documentos, salvo Mazda2, cuyas dos imágenes se revisaron visualmente.
"""
import hashlib
import json
import logging
import re
from pathlib import Path

import main

from configuracion import AC_DIR, CACHE_DIR, IMAGES_DIR, configurar_logging

CARPETA = AC_DIR
logger = logging.getLogger(__name__)
# Modelo: carga mínima/máxima (g), aceite, expresión de evidencia de carga/aceite.
HALLAZGOS = {
    'Hyundai Tucson': (525, 575, 'PAG (grado de viscosidad no indicado)', r'550\s*[±+]\s*25', r'PAG OIL'),
    'Hyundai Elantra': (475, 525, 'PAG (grado de viscosidad no indicado)', r'500\s*[±+]\s*25', r'PAG OIL'),
    'Mazda 2': (445, 495, 'ATMOS GU10', None, None),
    'Hyundai Accent': (395, 445, 'PAG (grado de viscosidad no indicado)', r'420\s*[±+]\s*25', r'PAG OIL'),
    'Kia Rio': (445, 495, 'PAG (grado de viscosidad no indicado)', r'470\s*[±+]\s*25', r'PAG OIL'),
    'Kia Sportage': (485, 535, 'PAG (grado de viscosidad no indicado)', r'510\s*[±+]\s*25', r'PAG OIL'),
    'Toyota Yaris': (330, 390, 'ND-OIL 8 o equivalente', r'330 to 390', r'ND-OIL\s*8'),
    'Toyota Corolla': (400, 500, 'ND-OIL 8 o equivalente', r'400 to 500', r'ND-OIL\s*8'),
    'Toyota RAV4': (470, 530, 'ND-OIL 8 o equivalente', r'470 to 530', r'ND-OIL\s*8'),
    'Nissan Versa': (400, 400, 'A/C System Oil Type DH-PR', r'Capacity 0\.4 kg', r'DH\s*-\s*PR'),
    'Nissan Sentra': (400, 500, 'Genuine NISSAN A/C System Oil Type S o equivalente', r'0\.45\s*\+-\s*0\.05 kg', r'Oil Type S'),
    'Suzuki Swift': (580, 620, 'PAG: Union Carbide 488', r'600\+/-20 g', r'Union Carbide 488'),
    'Honda Fit': (375, 425, 'DENSO ND-OIL 8 (P/N 38897-PR7-A01AH)', r'375 to 425', r'ND-OIL\s*8'),
    'Mazda 3': (465, 515, 'FD46XG', r'465-515', r'FD46XG'),
    'Chevrolet Spark': (430, 430, 'PAG Oil ISU 105', r'Refrigerant Charge 430 g', r'ISU 105'),
}


def evidencias(caso: dict, patron: str) -> list[dict]:
    pruebas = []
    for doc in caso.get('documentos', []):
        for parrafo in doc.get('texto', []):
            if re.search(patron, parrafo, re.I):
                pruebas.append({'documento_id': doc['id'], 'fuente_url': doc['fuente_url'], 'texto': parrafo})
                break
    return pruebas


def consolidar() -> None:
    configurar_logging()
    despues = json.loads((CARPETA / 'despues.json').read_text(encoding='utf-8'))
    antes = json.loads((CARPETA / 'antes.json').read_text(encoding='utf-8'))
    assert len(antes) == len(despues) == 30
    imagenes = json.loads((IMAGES_DIR / 'fuentes.json').read_text(encoding='utf-8'))
    registros = []
    aciertos_antes = 0
    for caso in despues:
        minimo, maximo, aceite, regex_gas, regex_aceite = HALLAZGOS[caso['solicitado']]
        patron = regex_gas if caso['tipo'] == 'gas' else regex_aceite
        if patron:
            pruebas = evidencias(caso, patron)
            if not pruebas:
                raise ValueError(f'Falta evidencia para {caso["solicitado"]} {caso["tipo"]}')
            metodo = 'revision_de_texto_html'
            previo = next(r for r in antes if r['solicitado'] == caso['solicitado'] and r['tipo'] == caso['tipo'])
            aciertos_antes += bool(evidencias(previo, patron))
        else:
            imagen = next(i for i in imagenes if i['tipo'] == caso['tipo'])
            pruebas = [{'fuente_url': imagen['url'], 'archivo': imagen['archivo'],
                        'transcripcion': 'Refrigerant type R-134a; Regular amount 445–495 g' if caso['tipo'] == 'gas'
                        else 'A/C compressor oil type ATMOS GU10; approximate quantity 110 ml'}]
            metodo = 'revision_visual_manual_por_asistente; no OCR del script'
        partes = main.segmentos_url(caso['seleccion']['url'])
        resultado = ({'cantidad_min': minimo, 'cantidad_max': maximo, 'unidad': 'g'}
                     if caso['tipo'] == 'gas' else {'tipo_aceite': aceite})
        if caso['solicitado'] == 'Suzuki Swift' and caso['tipo'] == 'gas':
            resultado['condicion'] = 'Valor general 600 ±20 g; para RHD el manual indica 650 ±20 g.'
            resultado['alternativa_rhd'] = {'cantidad_min': 630, 'cantidad_max': 670, 'unidad': 'g'}
        clave = caso['seleccion']['url'] + '#' + caso['tipo']
        registros.append({'schema_version': 1, 'id': hashlib.sha256(clave.encode()).hexdigest(),
                         'caso': caso['caso'], 'vehiculo': {'marca': partes[0], 'anio': partes[1], 'variante': ' > '.join(partes[2:])},
                         'consulta': caso['consulta'], 'resultado': resultado, 'metodo_verificacion': metodo,
                         'fuentes': pruebas, 'aplicabilidad': 'Sólo el año y variante del manual seleccionado; mercado/VIN no verificados.',
                         'nota_aceite': 'PAG sin grado no permite inferir PAG 46/100/150.' if aceite.startswith('PAG (') else None})
    resumen = {'consultas': 30, 'vehiculos': 15,
               'antes_con_evidencia_del_dato_en_top3': aciertos_antes,
               'despues_con_evidencia_textual_en_top3': 28,
               'despues_con_dato_en_imagen_revisada': 2,
               'criterio': 'Evidencia de carga o tipo de aceite revisada; no equivale a precisión general fuera de esta muestra.',
               'sin_modelo_en_anios_revisados': ['Hyundai i10', 'Mazda Demio'],
               'limitaciones': ['No es ranking de popularidad de Iquique.', 'i10 y Demio se buscaron en 2015, 2010, 2020, 2005 y 2012.',
                               'Mazda2 no se usa como sustituto del Demio.', 'Las dos lecturas de imagen se hicieron fuera del script.']}
    (CARPETA / 'resultados_revisados.json').write_text(json.dumps({'resumen': resumen, 'registros': registros}, ensure_ascii=False, indent=2), encoding='utf-8')
    with (CARPETA / 'resultados_revisados.jsonl').open('w', encoding='utf-8') as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    logger.info(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        consolidar()
    except Exception:
        logger.exception("Falló la consolidación")
        raise SystemExit(1)
