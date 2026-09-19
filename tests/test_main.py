import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from main import Selector


class RegressionTests(unittest.TestCase):
    def test_configuration_and_logging_in_subprocess(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {**os.environ, 'DIRECTORIO_DATOS': temp, 'AC_DIR': '',
                   'CACHE_DIR': '', 'IMAGES_DIR': '', 'OUTPUT_FILE': '',
                   'BASE_URL': 'https://example.test',
                   'LIMITE_SECCIONES_POR_DEFECTO': '7'}
            result = subprocess.run(
                [sys.executable, '-c',
                 'import configuracion as c; '
                 'c.configurar_logging(); c.configurar_logging(); '
                 'assert c.BASE_URL == "https://example.test/"; '
                 'assert c.AC_DIR == c.DATA_DIR / "prueba_ac_30"; '
                 'assert c.CACHE_DIR == c.AC_DIR / "cache"; '
                 'assert c.IMAGES_DIR == c.AC_DIR / "imagenes"; '
                 'assert c.OUTPUT_FILE == c.DATA_DIR / "resultados.jsonl"; '
                 'assert c.LIMITE_SECCIONES_POR_DEFECTO == 7'],
                cwd=Path(__file__).resolve().parent.parent, env=env,
                capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, '')

    def test_year_by_value_and_index(self):
        options = [main.Enlace('1992', '/1992/'), main.Enlace('2010', '/2010/')]
        self.assertEqual(main.elegir_opcion(options, '2010'), options[1])
        self.assertEqual(main.elegir_opcion(options, '2'), options[1])

    def test_variant_labels_and_about_filtered(self):
        page = Selector('<a href="H3%20Alpha/">Alpha</a><a href="H3T%20Alpha/">Alpha</a>'
                        '<a href="About/">About LEMON Manuals</a>')
        options = main.opciones_directorio(page, main.BASE_URL + 'Hummer/2010/')
        self.assertEqual([e.texto for e in options], ['H3 Alpha', 'H3T Alpha'])

    def test_ambiguous_model(self):
        options = [main.Enlace('430i 2D Coupe', 'a'), main.Enlace('430i Gran Coupe', 'b'),
                   main.Enlace('M430i', 'c')]
        self.assertEqual(len(main.coincidir_opciones(options, '430i')), 2)
        self.assertEqual(main.coincidir_opciones(options, '430i Gran Coupe'), [options[1]])

    def test_search_subject_and_dtc(self):
        root = main.BASE_URL + 'Hummer/2010/H3/'
        page = Selector('<a href="Engine/Coolant/Capacities/">Capacity</a>'
                        '<a href="Seats/Cooling/Specifications/">Specifications</a>'
                        '<a href="HVAC/Refrigerant/Capacities/">Capacity</a>'
                        '<a href="Engine/Cooling%20System/Fastener/">Tightening</a>'
                        '<a href="DTC/P0301/">P0301</a><a href="DTC/P0302/">P0302</a>')
        result = main.buscar_secciones(page, root + 'index.html', root, 'capacidad de refrigerante')
        self.assertEqual(len(result), 1)
        self.assertIn('Coolant', result[0].url)
        result = main.buscar_secciones(page, root + 'index.html', root, 'codigo P0301')
        self.assertEqual(len(result), 1)
        self.assertIn('P0301', result[0].url)

    def test_encoded_slash(self):
        self.assertEqual(main.segmentos_url('https://test/A%2FC/'), ['A/C'])

    def test_ac_gas_does_not_return_compressor_oil(self):
        root = main.BASE_URL + 'Hyundai/2015/Tucson/'
        page = Selector('<a href="HVAC/Compressor%20Oil/Oil%20Specification/">Oil Specification</a>'
                        '<a href="HVAC/Refrigerant/System%20Charging/">System Charging</a>'
                        '<a href="HVAC/DTC%20B1204/Specifications/">Specifications</a>')
        gas = main.buscar_secciones(page, root+'index.html', root, 'cantidad de gas refrigerante')
        self.assertEqual(len(gas), 1)
        self.assertIn('Charging', gas[0].url)
        oil = main.buscar_secciones(page, root+'index.html', root, 'tipo de aceite compresor')
        self.assertIn('Oil', oil[0].url)
        self.assertFalse(any('DTC' in e.url for e in oil))

    def test_ac_repeated_index_branches(self):
        root = main.BASE_URL + 'Hyundai/2015/Tucson/'
        page = Selector('<a href="HVAC/A/System/Compressor%20Oil/Specification/Notes/">Notes</a>'
                        '<a href="HVAC/B/System/Compressor%20Oil/Specification/Notes/">Notes</a>')
        result = main.buscar_secciones(page, root+'index.html', root, 'aceite del compresor')
        self.assertEqual(len(result), 1)

    def test_ac_specification_beats_generic_oil_procedure(self):
        root = main.BASE_URL + 'Chevrolet/2015/Spark/'
        page = Selector('<a href="HVAC/Specifications/Refrigerant%20System%20Specifications/">Refrigerant System Specifications</a>'
                        '<a href="HVAC/Repair/Compressor%20Oil%20Balancing/">Compressor Oil Balancing</a>'
                        '<a href="HVAC/Map%20-%20AC/Refrigerant%20Oil/">Refrigerant Oil</a>'
                        '<a href="HVAC/Service%20Data/For%20Automatic%20Transaxle/">For Automatic Transaxle</a>')
        result = main.buscar_secciones(page, root+'index.html', root, 'tipo aceite compresor')
        self.assertIn('Specifications', result[0].url)
        self.assertFalse(any('Map' in e.url or 'Transaxle' in e.url for e in result))

    def test_old_manual_ac_fallback(self):
        root = main.BASE_URL + 'Mazda/2012/2/'
        model = Selector('<a href="Repair/">Repair and Diagnosis</a>')
        pages = {root+'Repair/': Selector('<a href="Heating%20and%20Air%20Conditioning/">Heating and Air Conditioning</a>'),
                 root+'Repair/Heating%20and%20Air%20Conditioning/': Selector('<a href="Specifications/">Specifications</a>'),
                 root+'Repair/Heating%20and%20Air%20Conditioning/Specifications/': Selector('<p>Spec</p>')}
        index = main.indice_reparacion(model, root)
        self.assertIsNotNone(index)
        with patch.object(main.Cliente, 'obtener', side_effect=lambda url: pages[url]) as fetch:
            page = main.cargar_indice(main.Cliente(), index, root)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(len(main.extraer_enlaces(page, index.url)), 2)

    def test_general_fluid_table_over_filling_and_sensors(self):
        root = main.BASE_URL + 'Hummer/2010/H3/'
        page = Selector('<a href="Maintenance/Specifications/Approximate%20Fluid%20Capacities/">Fluid Capacities</a>'
                        '<a href="Engine/Cooling%20System/Filling/">Filling</a>'
                        '<a href="Engine/Coolant/Temperature%20Sensor/">Sensor</a>'
                        '<a href="Transmission/Fluid%20Capacities/">Fluid Capacities</a>')
        result = main.buscar_secciones(page, root + 'index.html', root, 'capacidad de refrigerante')
        self.assertEqual(len(result), 1)
        self.assertIn('Maintenance', result[0].url)

    def test_export_append_id_and_no_overwrite(self):
        link = main.Enlace('Capacity', main.BASE_URL + 'Hummer/2010/H3/Capacity/')
        with patch.object(main.Cliente, 'obtener', return_value=Selector('<p>Fixture only</p><img src="a.png">')):
            doc = main.leer_seccion(main.Cliente(), link)
            again = main.leer_seccion(main.Cliente(), link)
        self.assertEqual(doc['id'], again['id'])
        result = main.crear_resultado(main.BASE_URL + 'Hummer/2010/H3/', 'capacidad', 1, [doc])
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'docs.jsonl')
            main.guardar_resultado(result, path)
            main.guardar_resultado(result, path)
            records = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]['vehiculo']['modelo'], 'H3')
            self.assertEqual(records[0]['fuente_url'], link.url)
            self.assertIn('url', records[0]['imagenes'][0])
            path = str(Path(temp) / 'docs.json')
            main.guardar_resultado(result, path)
            with self.assertRaises(FileExistsError):
                main.guardar_resultado(result, path)
        self.assertNotIn('https://', json.dumps(main.sin_urls(result)))

    def test_json_ambiguity_has_options(self):
        pages = iter([Selector('<a href="BMW/">BMW</a>'), Selector('<a href="2020/">2020</a>'),
                      Selector('<a href="430i%20Coupe/">Coupe</a><a href="430i%20Convertible/">Convertible</a>')])
        args = ['main.py', '--marca', 'BMW', '--anio', '2020', '--modelo', '430i', '--consulta', 'aceite', '--json']
        output = io.StringIO()
        with patch('sys.argv', args), patch.object(main.Cliente, 'obtener', side_effect=lambda u: next(pages)), contextlib.redirect_stdout(output):
            self.assertEqual(main.main(), 1)
        self.assertEqual(json.loads(output.getvalue())['opciones'], ['430i Coupe', '430i Convertible'])


if __name__ == '__main__':
    unittest.main()
