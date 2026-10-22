#!/usr/bin/env python3
"""
CLI JSON para consultar manuales automotrices.

Requisitos: Python 3.10+
Instalación:
    python -m pip install -r requirements.txt

Ejecución:
    python main.py

Selecciona marca, año, modelo y carpetas desde los enlaces del sitio.
No descarga archivos automáticamente.
La búsqueda es local a la página seleccionada y no realiza OCR.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import unicodedata
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit

import httpx
from lxml import etree
from lxml import html as lxml_html


from configuracion import (
    BASE_URL,
    LIMITE_SECCIONES_POR_DEFECTO,
    OUTPUT_FILE,
    configurar_logging,
)

logger = logging.getLogger(__name__)
for nombre_logger in ('httpx', 'httpcore', 'scrapling', 'urllib3'):
    logging.getLogger(nombre_logger).setLevel(logging.WARNING)

EXTENSIONES_ARCHIVO = {
    ".pdf", ".zip", ".rar", ".7z", ".jpg", ".jpeg",
    ".png", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff",
}


class ResultadoXPath(list):
    """Compatibilidad mínima con la API usada por el extractor."""

    def getall(self) -> list[str]:
        return [item.get() if isinstance(item, Selector) else str(item) for item in self]


class Selector:
    """Envoltorio pequeño de lxml para HTML y fixtures de prueba."""

    def __init__(self, contenido: str, *, url: str = '', status: int | None = 200) -> None:
        self._elemento = lxml_html.fromstring(contenido or '<html></html>')
        self.url = url
        self.status = status

    @classmethod
    def _desde_elemento(cls, elemento: etree._Element, url: str) -> 'Selector':
        instancia = cls.__new__(cls)
        instancia._elemento = elemento
        instancia.url = url
        instancia.status = 200
        return instancia

    @property
    def attrib(self) -> dict[str, str]:
        return self._elemento.attrib

    def css(self, consulta: str) -> list['Selector']:
        resultados: list[Selector] = []
        for selector in consulta.split(','):
            selector = selector.strip()
            coincidencia = re.fullmatch(r'([\w-]+)(?:\[([\w-]+)\])?', selector)
            if not coincidencia:
                raise ValueError(f'Selector CSS no soportado: {selector}')
            etiqueta, atributo = coincidencia.groups()
            xpath = f'descendant-or-self::{etiqueta}' + (f'[@{atributo}]' if atributo else '')
            resultados.extend(self._desde_elemento(nodo, self.url) for nodo in self._elemento.xpath(xpath))
        return resultados

    def xpath(self, consulta: str) -> ResultadoXPath:
        return ResultadoXPath(
            self._desde_elemento(valor, self.url) if isinstance(valor, etree._Element) else valor
            for valor in self._elemento.xpath(consulta)
        )

    def get(self) -> str:
        return etree.tostring(self._elemento, encoding='unicode', method='html')


class ErrorAcceso(RuntimeError):
    """Error de conexión, protección o respuesta HTTP inválida."""

    def __init__(self, mensaje: str, estado: int | None = None, opciones: list[str] | None = None) -> None:
        super().__init__(mensaje)
        self.estado = estado
        self.opciones = opciones or []


class AnalizadorArgumentosJSON(argparse.ArgumentParser):
    """Convierte errores de sintaxis CLI en JSON válido para consumidores IA."""

    def error(self, message: str) -> None:
        sys.stdout.write(json.dumps({
            'schema_version': 1,
            'secciones_coincidentes': 0,
            'documentos': [],
            'error': message,
        }, ensure_ascii=False) + '\n')
        raise SystemExit(2)


@dataclass(frozen=True)
class Enlace:
    texto: str
    url: str


def estado_http(objeto: object) -> int | None:
    """Obtiene el estado tanto de respuestas como de excepciones HTTP."""
    for candidato in (objeto, getattr(objeto, "response", None)):
        for atributo in ("status", "status_code"):
            valor = getattr(candidato, atributo, None)
            if isinstance(valor, (int, str)):
                try:
                    return int(valor)
                except ValueError:
                    pass
    return None


class Cliente:
    """Cliente con caché y una pausa mínima entre solicitudes."""

    def __init__(self, pausa: float = 1.0) -> None:
        self.cache: dict[str, Selector] = {}
        self.pausa = pausa
        self.ultima_peticion = 0.0
        self.http = httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            transport=httpx.HTTPTransport(retries=2),
            headers={'User-Agent': 'autospec-cli/1.0'},
        )

    def esperar(self) -> None:
        restante = self.pausa - (time.monotonic() - self.ultima_peticion)
        if restante > 0:
            time.sleep(restante)
        self.ultima_peticion = time.monotonic()

    def obtener(self, url: str) -> Selector:
        if url in self.cache:
            return self.cache[url]

        self.esperar()

        try:
            respuesta = self.http.get(url)
        except httpx.HTTPError as exc:
            raise ErrorAcceso(
                f"No se pudo consultar {url}: {exc}", estado_http(exc)
            ) from exc

        estado = respuesta.status_code
        if estado is None or not 200 <= estado < 300:
            raise ErrorAcceso(
                f"Respuesta HTTP {estado or 'desconocida'} en {url}.", estado
            )

        pagina = Selector(respuesta.text, url=str(respuesta.url), status=estado)
        self.cache[url] = pagina
        return pagina


def texto_completo(elemento: Selector) -> str:
    """Incluye texto de elementos anidados como <strong> y <span>."""
    return " ".join(
        " ".join(elemento.xpath(".//text()").getall()).split()
    )


def url_absoluta(base: str, referencia: str) -> str | None:
    """Resuelve enlaces relativos, elimina fragmentos y codifica espacios."""
    referencia = referencia.strip()
    if not referencia or referencia.startswith("#"):
        return None
    url = urldefrag(urljoin(base, referencia))[0]
    if urlsplit(url).scheme not in {"http", "https"}:
        return None
    return quote(url, safe=":/%?=&+#@!$'()*;,~[]")


def base_documento(pagina: Selector, solicitada: str) -> str:
    """Considera redirecciones y la etiqueta HTML <base>."""
    efectiva = str(getattr(pagina, "url", "") or solicitada)
    referencias = pagina.css("base[href]")
    if referencias:
        return url_absoluta(efectiva, referencias[0].attrib["href"]) or efectiva
    return efectiva


def extraer_enlaces(pagina: Selector, url: str) -> list[Enlace]:
    base = base_documento(pagina, url)
    encontrados: dict[str, Enlace] = {}

    for nodo in pagina.css("a[href]"):
        destino = url_absoluta(base, nodo.attrib.get("href", ""))
        if destino:
            nombre = texto_completo(nodo)
            if not nombre:
                nombre = unquote(urlsplit(destino).path.rstrip("/").split("/")[-1])
            encontrados.setdefault(destino, Enlace(nombre or destino, destino))

    return list(encontrados.values())


def dentro_del_manual(url: str, raiz: str) -> bool:
    destino, origen = urlsplit(url), urlsplit(raiz)
    ruta = unquote(destino.path)
    prefijo = unquote(origen.path).rstrip("/") + "/"
    return (
        destino.netloc.lower() == origen.netloc.lower()
        and ruta.startswith(prefijo)
    )


def es_archivo(url: str) -> bool:
    ruta = urlsplit(url).path.lower()
    return any(ruta.endswith(extension) for extension in EXTENSIONES_ARCHIVO)


def mostrar_enlaces(enlaces: list[Enlace]) -> None:
    if not enlaces:
        logger.info("No se encontraron enlaces.")
    for numero, enlace in enumerate(enlaces, start=1):
        nombre = enlace.texto
        if nombre.startswith(("https://", "http://")):
            nombre = unquote(urlsplit(enlace.url).path.rstrip("/").split("/")[-1]) or "Inicio"
        logger.info(f"{numero}. {nombre}")


def extraer_imagenes(pagina: Selector, url: str) -> list[str]:
    """Extrae src y atributos habituales de imágenes con carga diferida."""
    base = base_documento(pagina, url)
    imagenes: dict[str, None] = {}

    for nodo in pagina.css("img"):
        for atributo in ("src", "data-src", "data-original", "data-lazy-src"):
            referencia = nodo.attrib.get(atributo, "")
            destino = url_absoluta(base, referencia)
            if destino:
                imagenes.setdefault(destino, None)

    return list(imagenes)


def analizar_pagina(pagina: Selector, url: str) -> None:
    """Muestra diagramas y busca una palabra o frase literal mediante regex."""
    nombre = unquote(urlsplit(url).path.rstrip("/").split("/")[-1]) or "Inicio"
    logger.info(f"\nPágina seleccionada: {nombre}")
    imagenes = extraer_imagenes(pagina, url)
    logger.info(f"\nImágenes/diagramas encontrados: {len(imagenes)}")
    for numero, imagen in enumerate(imagenes, start=1):
        logger.info(f"{numero}. {unquote(urlsplit(imagen).path.split('/')[-1]) or 'Imagen'}")

    bloques = list(dict.fromkeys(
        texto
        for nodo in pagina.css("p, li, td")
        if (texto := texto_completo(nodo))
    ))
    logger.info(f"\nBloques de texto encontrados: {len(bloques)}")

    while True:
        palabra = input(
            "\nPalabra o frase a buscar (Enter para volver): "
        ).strip()
        if not palabra:
            return

        # Escapar evita interpretar la entrada como una expresión arbitraria.
        patron = re.compile(re.escape(palabra), flags=re.IGNORECASE)
        coincidencias = [texto for texto in bloques if patron.search(texto)]

        logger.info(f"\nCoincidencias: {len(coincidencias)}")
        for numero, texto in enumerate(coincidencias, start=1):
            logger.info(f"\n[{numero}] {texto}")

        if not coincidencias:
            logger.warning("No hay coincidencias en el texto HTML de esta página.")


def normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto.casefold())
                   if not unicodedata.combining(c))


def segmentos_url(url: str) -> list[str]:
    """Decodifica después de separar: A%2FC no son dos carpetas."""
    return [unquote(s) for s in urlsplit(url).path.split('/') if s]


def opciones_directorio(pagina: Selector, url: str) -> list[Enlace]:
    """Muestra rutas relativas completas para distinguir modelo y motor."""
    nivel = len(segmentos_url(url))
    opciones = []
    for e in extraer_enlaces(pagina, url):
        if not dentro_del_manual(e.url, url) or es_archivo(e.url) or urlsplit(e.url).query:
            continue
        partes = segmentos_url(e.url)[nivel:]
        if not partes or 'about' in normalizar(e.texto) or 'about' in normalizar(partes[0]):
            continue
        if nivel == 1 and not re.fullmatch(r'\d{4}', partes[0]):
            continue
        opciones.append(Enlace(' > '.join(partes), e.url))
    return opciones


def coincidir_opciones(opciones: list[Enlace], nombre: str) -> list[Enlace]:
    clave = normalizar(nombre.strip())
    exactas = [e for e in opciones if normalizar(e.texto) == clave]
    if exactas:
        return exactas
    return [e for e in opciones if any(
        re.search(r'(?<!\w)' + re.escape(clave) + r'(?!\w)', normalizar(s))
        for s in e.texto.split(' > '))]


def elegir_opcion(opciones: list[Enlace], entrada: str) -> Enlace | None:
    coincidencias = coincidir_opciones(opciones, entrada)
    if len(coincidencias) == 1:
        return coincidencias[0]
    if len(coincidencias) > 1:
        logger.warning('Hay varias variantes; selecciona el número o el nombre completo.')
        return None
    if entrada.isdecimal() and 1 <= int(entrada) <= len(opciones):
        return opciones[int(entrada) - 1]
    return None


def indice_reparacion(pagina: Selector, url: str) -> Enlace | None:
    alternativo = None
    for enlace in extraer_enlaces(pagina, url):
        titulo = normalizar(enlace.texto)
        if ("repair and diagnosis" in titulo and "all links" in titulo
                and dentro_del_manual(enlace.url, url)):
            return enlace
        if titulo.strip() == 'repair and diagnosis' and dentro_del_manual(enlace.url, url):
            alternativo = enlace
    return alternativo


def cargar_indice(cliente: Cliente, indice: Enlace, raiz: str) -> Selector:
    """Usa el índice completo o explora hasta 25 páginas de A/C en manuales antiguos."""
    pagina = cliente.obtener(indice.url)
    if 'all links' in normalizar(indice.texto):
        return pagina
    pendientes = [(indice.url, pagina)]
    visitadas = {indice.url}
    enlaces: dict[str, Enlace] = {}
    # Alternativa acotada: no descarga el árbol completo del vehículo.
    while pendientes:
        url, actual = pendientes.pop(0)
        for e in extraer_enlaces(actual, url):
            if not dentro_del_manual(e.url, raiz) or es_archivo(e.url):
                continue
            enlaces[e.url] = e
            nombre = normalizar(e.texto)
            if e.url in visitadas or len(visitadas) >= 25:
                continue
            if not re.search(r'air conditioning|heating and|hvac|refrigerant|compressor|specification|capacit|fluid type', nombre):
                continue
            if re.search(r'diagnos|testing|wiring|sensor|clutch|removal|replacement', nombre):
                continue
            visitadas.add(e.url)
            try:
                pendientes.append((e.url, cliente.obtener(e.url)))
            except ErrorAcceso:
                continue
    return Selector('<html><body>' + ''.join(
        f'<a href="{html.escape(e.url, quote=True)}">{html.escape(e.texto)}</a>'
        for e in enlaces.values()) + '</body></html>')


def buscar_secciones(pagina: Selector, url: str, raiz: str, consulta: str) -> list[Enlace]:
    """Exige el tema principal; capacidad/especificaciones sólo refinan el tema."""
    consulta = normalizar(consulta)
    alias = {
        'electrico': 'electrical',
        'electrica': 'electrical',
        'electricos': 'electrical',
        'electricas': 'electrical',
        'diagrama': 'diagram',
        'diagramas': 'diagram',
        'ramal': 'wiring',
        'ramales': 'wiring',
        'cableado': 'wiring',
        'freno': 'brake',
        'frenos': 'brake',
        'pinza': 'caliper',
        'pastilla': 'pad',
        'pastillas': 'pad',
        'despiece': 'removal',
        'desmontaje': 'removal',
        'aceite': 'oil',
        'motor': 'engine',
        'tipo': 'type',
        'cantidad': 'quantity',
        'capacidad': 'capacity',
    }
    consulta = ' '.join(alias.get(palabra, palabra) for palabra in consulta.split())
    ac = bool(re.search(r"aire acondicionado|air conditioning|\ba/?c\b|refrigerant\b|r134|r1234|gas refrigerante|compresor|compressor", consulta))
    refrigerante = bool(re.search(r"refrigerante|coolant|anticongelante", consulta))
    aceite = bool(re.search(r"aceite|\boil\b|lubric", consulta))
    capacidad = bool(re.search(r"cantidad|capacidad|cuanto|litros|quantity|amount|capacity|capacities", consulta))
    recomendado = bool(re.search(r"recomienda|recomendado|tipo|grado|viscosidad|type|grade|viscosity", consulta))
    codigos = re.findall(r"\b[pbcu][0-9a-f]{4}\b", consulta)
    if ac and not codigos:
        return buscar_ac(pagina, url, raiz, aceite=aceite)
    stop = set("que cual cuanto de del la el los las un una usa lleva para por se es en y mi auto coche vehiculo busca buscar cantidad capacidad recomendado recomienda tipo motor".split())
    palabras = set(re.findall(r"[a-z0-9]+", consulta)) - stop
    resultados: list[tuple[int, Enlace]] = []
    for enlace in extraer_enlaces(pagina, url):
        if not dentro_del_manual(enlace.url, raiz) or es_archivo(enlace.url) or enlace.url == url:
            continue
        partes = segmentos_url(enlace.url)[len(segmentos_url(raiz)):]
        contenido = normalizar(enlace.texto + " " + " ".join(partes))
        hoja = normalizar(" ".join(partes[-2:]) + " " + enlace.texto)
        tabla_fluidos = bool(re.search(r"fluid capacit|capacities.*fluid", hoja)) and not bool(
            re.search(r"transmission|transfer case|brake|battery", contenido))
        if codigos and not all(re.search(r"\b" + re.escape(c) + r"\b", contenido) for c in codigos):
            continue
        if ac:
            tema = bool(re.search(r"refrigerant|air conditioning|a/c", contenido))
        elif refrigerante:
            tema = bool(re.search(r"coolant|engine cooling|cooling system", contenido)) or (capacidad and tabla_fluidos)
            tema = tema and not bool(re.search(r"seat|refrigerant|air conditioning|hvac", contenido))
        elif aceite:
            tema = bool(re.search(r"engine oil|lubrication|\boil\b", contenido))
            if not re.search(r"transmision|transmission|diferencial|differential", consulta):
                tema = tema and not bool(re.search(r"transmission|differential", contenido))
        else:
            sinonimos = {'fusible': 'fuse', 'rele': 'relay', 'apriete': 'torque'}
            terminos = {sinonimos.get(p, p) for p in palabras}
            encontrados = {
                termino for termino in terminos
                if re.search(r"\b" + re.escape(termino) + r"\b", contenido)
            }
            tema = bool(encontrados)
            if {'wiring', 'electrical'} & terminos or 'diagram' in terminos:
                tema = bool(re.search(r"\belectrical\b|\bwiring\b|\bcircuit\b|\bconnector\b|\brelay\b|\bfuse\b", contenido))
                tema = tema and bool({'wiring', 'electrical', 'diagram'} & encontrados)
            if 'brake' in terminos:
                tema = tema and bool(re.search(r"brake|caliper|rotor|pad|disc", contenido))
            if 'oil' in terminos and 'engine' in terminos:
                tema = tema and bool(re.search(r"engine oil|engine lubrication|oil capacity|oil type", contenido))
                tema = tema and not bool(re.search(r"oil pressure sensor|oil control valve", contenido))
        if not tema:
            continue
        if (capacidad or recomendado) and re.search(r"fastener|tightening|connector|wiring|pressure sensor", contenido):
            continue
        if capacidad and not re.search(r"capacit|specification|filling|refilling|fluid amount|charge", hoja):
            continue
        if recomendado and not re.search(r"specification|viscosity|fluid type|recommended|oil type|oil grade", hoja):
            continue
        puntos = 10
        if capacidad:
            puntos += 35 if re.search(r"capacit|fluid amount|charge", hoja) else 0
            puntos += 10 if 'specification' in hoja else 0
        if recomendado:
            puntos += 30 if re.search(r"fluid type|viscosity|recommended|specification", hoja) else 0
        puntos += sum(2 for p in palabras if re.search(r"\b" + re.escape(p) + r"\b", hoja))
        nombre = ' > '.join(p for p in partes if not p.startswith('Repair and Diagnosis')) or enlace.texto
        resultados.append((puntos, Enlace(nombre, enlace.url)))
    resultados.sort(key=lambda item: (-item[0], item[1].texto))
    if resultados and (capacidad or recomendado):
        resultados = [item for item in resultados if item[0] >= resultados[0][0] - 20]
    return [enlace for _, enlace in resultados]


def buscar_ac(pagina: Selector, url: str, raiz: str, *, aceite: bool) -> list[Enlace]:
    """Separa carga de refrigerante y lubricante; omite duplicados del índice."""
    resultados: list[tuple[int, Enlace]] = []
    vistas: set[tuple[str, ...]] = set()
    for enlace in extraer_enlaces(pagina, url):
        if enlace.url == url or not dentro_del_manual(enlace.url, raiz) or es_archivo(enlace.url):
            continue
        partes = segmentos_url(enlace.url)[len(segmentos_url(raiz)):]
        ruta = normalizar(' '.join(partes))
        hoja = normalizar(' '.join(partes[-3:]) + ' ' + enlace.texto)
        if not re.search(r'air conditioning|a/c|hvac|refrigerant|compressor', ruta):
            continue
        if 'map - ' in ruta:
            continue
        if re.search(r'\bdtc\b|trouble|torque|tightening|fastener|wiring|connector|sensor|relay|clutch|diagnosis|tools|video|temperature|pressure test|sealant|for (automatic|manual) transaxle', hoja):
            continue
        lubricante = bool(re.search(r'\boil\b|lubricant|lubrication', hoja))
        especificacion = bool(re.search(r'specification|capacit|fluid type|service data|technical data', hoja))
        puntos = 0
        if aceite:
            if lubricante:
                puntos = 60
                puntos += 45 if re.search(r'specification|fluid type|oil type|recommended|lubricant', hoja) else 0
                puntos += 20 if re.search(r'check|capacit|quantity|amount', hoja) else 0
                puntos -= 45 if re.search(r'handling|return operation|replacement of component|precaution', hoja) else 0
            elif especificacion:
                puntos = 95
        else:
            if lubricante:
                continue
            if especificacion:
                puntos = 65
                puntos += 40 if re.search(r'refrigerant|capacit|fluid type', hoja) else 0
            if re.search(r'(system|refrigerant) charg|recharging|charge amount|charge refrigerant|refrigerant.*charging', hoja):
                puntos = max(puntos, 95)
            if normalizar(partes[-1]) == 'refrigerant':
                puntos = max(puntos, 50)
        if re.search(r'service data|technical data', hoja):
            puntos = max(puntos, 95)
        if aceite and lubricante:
            puntos += 20
        if not aceite and especificacion and re.search(r'refrigerant|technical data', hoja):
            puntos += 20
        if puntos < 50:
            continue
        profundidad = 2 if 'technical data' in normalizar(partes[-1]) else 4
        clave = tuple(normalizar(s) for s in partes[-profundidad:])
        if clave in vistas:
            continue
        vistas.add(clave)
        nombre = ' > '.join(p for p in partes if not p.startswith('Repair and Diagnosis')) or enlace.texto
        resultados.append((puntos, Enlace(nombre, enlace.url)))
    resultados.sort(key=lambda item: (-item[0], item[1].texto))
    return [e for _, e in resultados]


def leer_seccion(cliente: Cliente, enlace: Enlace) -> dict[str, object]:
    pagina = cliente.obtener(enlace.url)
    bloques = list(dict.fromkeys(
        texto_completo(nodo) for nodo in pagina.css("h1, h2, h3, p, li, tr")
        if texto_completo(nodo)
    ))
    fuente = str(getattr(pagina, 'url', '') or enlace.url)
    return {"id": hashlib.sha256(fuente.encode()).hexdigest(),
            "fuente_url": fuente, "seccion": enlace.texto, "texto": bloques,
            "contenido_sha256": hashlib.sha256('\n'.join(bloques).encode()).hexdigest(),
            "extraido_en": datetime.now(timezone.utc).isoformat(),
            "metodo_extraccion": "html_sin_ocr",
            "requiere_revision_imagenes": bool(extraer_imagenes(pagina, enlace.url)) and sum(map(len, bloques)) < 120,
            "imagenes": [{"nombre": unquote(urlsplit(u).path.split('/')[-1]), "url": u}
                         for u in extraer_imagenes(pagina, enlace.url)]}


def crear_resultado(raiz: str, consulta: str, total: int, documentos: list[dict]) -> dict:
    partes = segmentos_url(raiz)
    return {"schema_version": 1, "consulta": consulta,
            "vehiculo": {"marca": partes[0] if partes else '',
                         "anio": partes[1] if len(partes) > 1 else '',
                         "modelo": ' > '.join(partes[2:]), "manual_url": raiz},
            "secciones_coincidentes": total, "documentos": documentos,
            "alcance": "Títulos y rutas del índice. Texto HTML sin OCR ni respuesta generada."}


def guardar_resultado(salida: dict, destino: str) -> None:
    """JSON crea un archivo nuevo; JSONL agrega un registro por documento."""
    ruta = Path(destino)
    if ruta.suffix.lower() not in {'.json', '.jsonl'}:
        raise ValueError('La salida debe terminar en .json o .jsonl.')
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.suffix.lower() == '.jsonl':
        # ID estable permite deduplicar/upsert al importar; no carga el corpus en RAM.
        with ruta.open('a', encoding='utf-8') as archivo:
            for documento in salida['documentos']:
                registro = {k: v for k, v in salida.items() if k != 'documentos'}
                registro.update(documento)
                archivo.write(json.dumps(registro, ensure_ascii=False) + '\n')
    else:
        with ruta.open('x', encoding='utf-8') as archivo:
            json.dump(salida, archivo, ensure_ascii=False, indent=2)


def sin_urls(valor: object) -> object:
    """Conserva fuentes en archivos; oculta direcciones en la terminal."""
    if isinstance(valor, dict):
        return {k: sin_urls(v) for k, v in valor.items() if k not in {'url', 'fuente_url', 'manual_url'}}
    if isinstance(valor, list):
        return [sin_urls(v) for v in valor]
    if isinstance(valor, str):
        return re.sub(r'https?://\S+', '[fuente]', valor)
    return valor


def consultar_manual(cliente: Cliente, raiz: str, indice: Enlace) -> str:
    pagina = cargar_indice(cliente, indice, raiz)
    if 'all links' not in normalizar(indice.texto):
        logger.warning('Este manual no tiene índice completo; se exploran hasta 25 páginas de A/C y especificaciones.')
    logger.info("\nManual preparado. Busca, por ejemplo: capacidad de refrigerante, aceite recomendado o P0301.")
    logger.info("Refrigerante se interpreta como refrigerante del motor; escribe 'aire acondicionado' para el A/C.")
    while True:
        consulta = input("\n¿Qué necesitas? (V: cambiar modelo, S: salir): ").strip()
        if consulta.casefold() in {"v", "s"}:
            return consulta.casefold()
        if not consulta:
            continue
        resultados = buscar_secciones(pagina, indice.url, raiz, consulta)
        if not resultados:
            logger.warning("No hay secciones coincidentes en el índice. Prueba otro término o su nombre en inglés.")
            continue
        offset = 0
        leidos: dict[str, dict] = {}
        while True:
            lote = resultados[offset:offset + 8]
            logger.info(f"\nSecciones {offset + 1}–{offset + len(lote)} de {len(resultados)}:")
            mostrar_enlaces(lote)
            opcion = input("Número: leer | G: guardar leídos | M: más | N: nueva consulta | V: cambiar modelo | S: salir: ").strip().casefold()
            if opcion in {"v", "s"}:
                return opcion
            if opcion == "n":
                break
            if opcion == "m":
                offset = offset + 8 if offset + 8 < len(resultados) else 0
            elif opcion == 'g':
                if not leidos:
                    logger.info('Lee al menos una sección antes de guardar.')
                    continue
                destino = input(f'Archivo .json o .jsonl [{OUTPUT_FILE}]: ').strip() or str(OUTPUT_FILE)
                try:
                    guardar_resultado(crear_resultado(raiz, consulta, len(resultados), list(leidos.values())), destino)
                    logger.info(f'Guardadas {len(leidos)} secciones en {destino}.')
                except (OSError, ValueError) as exc:
                    logger.error(f'No se pudo guardar: {exc}')
            elif opcion.isdecimal() and 1 <= int(opcion) <= len(lote):
                try:
                    datos = leer_seccion(cliente, lote[int(opcion) - 1])
                    leidos[datos['id']] = datos
                    logger.info(f"\n--- {datos['seccion']} ---")
                    logger.info("\n".join(datos["texto"]) or "Esta página no contiene texto extraíble; puede contener diagramas.")
                    if datos["imagenes"]:
                        logger.info("Imágenes: " + ", ".join(i['nombre'] for i in datos["imagenes"]))
                except ErrorAcceso as exc:
                    logger.error(f"No se pudo leer la sección (HTTP {exc.estado or 'desconocido'}).")
            else:
                logger.warning("Opción inválida.")


def navegar(cliente: Cliente, raiz: str, pagina: Selector) -> None:
    """Navegación iterativa con historial; permite analizar cualquier nivel."""
    historial: list[tuple[str, Selector]] = [(raiz, pagina)]

    while True:
        url, pagina = historial[-1]
        indice = indice_reparacion(pagina, url)
        if indice:
            try:
                accion = consultar_manual(cliente, url, indice)
                if accion == "s":
                    return
                if len(historial) > 1:
                    historial.pop()
                    continue
            except ErrorAcceso as exc:
                logger.error(f"No se pudo abrir el índice (HTTP {exc.estado or 'desconocido'}). Puedes navegar manualmente.")
        enlaces = extraer_enlaces(pagina, url)
        visitadas = {direccion for direccion, _ in historial}
        categorias = [
            enlace for enlace in opciones_directorio(pagina, url)
            if dentro_del_manual(enlace.url, raiz)
            and enlace.url not in visitadas
            and not es_archivo(enlace.url)
            and urlsplit(enlace.url).path != urlsplit(url).path
        ]

        segmentos = [s for s in unquote(urlsplit(url).path).split("/") if s]
        etapa = {0: "marca", 1: "año", 2: "modelo"}.get(len(segmentos), "carpeta o página")
        ruta = " > ".join(segmentos) or "Inicio"
        logger.info(f"\n--- {ruta} ---")
        logger.info(f"Selecciona {etapa} entre las opciones de esta página:")
        mostrar_enlaces(categorias)

        if not categorias:
            logger.warning("No hay más subcategorías navegables en esta página.")

        logger.info("\nNúmero: entrar | B: buscar texto/ver imágenes")
        logger.info("L: ver todos los enlaces | V: volver | I: inicio | S: salir")
        opcion = input(f"Escribe {etapa}, su número o un comando: ").strip().casefold()
        elegida = elegir_opcion(categorias, opcion)

        if opcion == "s":
            return
        if opcion == "v":
            if len(historial) > 1:
                historial.pop()
            else:
                logger.info("Ya estás en el inicio.")
        elif opcion == "i":
            historial = historial[:1]
        elif opcion == "b":
            analizar_pagina(pagina, url)
        elif opcion == "l":
            mostrar_enlaces(enlaces)
        elif elegida is not None:
            destino = elegida.url
            try:
                siguiente = cliente.obtener(destino)
                efectiva = str(getattr(siguiente, "url", "") or destino)
                if not dentro_del_manual(efectiva, raiz):
                    logger.info("El enlace redirige fuera del sitio seleccionado.")
                    continue
                if efectiva in visitadas:
                    logger.info("Esa página ya está en el historial; utiliza V.")
                    continue
                historial.append((efectiva, siguiente))
            except ErrorAcceso as exc:
                logger.error(f"Error: {exc}\nPuedes elegir otra categoría.")
        else:
            logger.warning("Opción inválida.")


def main() -> int:
    configurar_logging()
    parser = AnalizadorArgumentosJSON(description="Consulta manuales por vehículo y tema.")
    parser.add_argument("--marca")
    parser.add_argument("--anio")
    parser.add_argument("--modelo")
    parser.add_argument("--consulta")
    parser.add_argument("--salida", help="Archivo .json nuevo o .jsonl al que agregar registros.")
    parser.add_argument(
        "--limite", type=int, default=LIMITE_SECCIONES_POR_DEFECTO,
        help=f"Máximo de secciones a leer (1–100, predeterminado {LIMITE_SECCIONES_POR_DEFECTO}).",
    )
    parser.add_argument("--json", action="store_true", help="Compatibilidad: la salida siempre es JSON.")
    args = parser.parse_args()

    def error_argumentos(mensaje: str) -> int:
        sys.stdout.write(json.dumps({
            'schema_version': 1,
            'consulta': args.consulta or '',
            'vehiculo': {
                'marca': args.marca or '',
                'anio': args.anio or '',
                'modelo': args.modelo or '',
            },
            'secciones_coincidentes': 0,
            'documentos': [],
            'error': mensaje,
        }, ensure_ascii=False) + '\n')
        return 2

    if not 1 <= args.limite <= 100:
        return error_argumentos('--limite debe estar entre 1 y 100.')
    parametros = (args.marca, args.anio, args.modelo, args.consulta)
    if not all(parametros):
        return error_argumentos('Indica --marca, --anio, --modelo y --consulta.')
    if args.salida:
        ruta = Path(args.salida)
        if ruta.suffix.lower() not in {'.json', '.jsonl'}:
            return error_argumentos('--salida debe terminar en .json o .jsonl.')
        if ruta.suffix.lower() == '.json' and ruta.exists():
            return error_argumentos('El archivo JSON ya existe; usa otro nombre o JSONL para agregar.')
    cliente = Cliente()
    try:
        pagina = cliente.obtener(BASE_URL)
        raiz = str(getattr(pagina, "url", "") or BASE_URL)
        for nombre in (args.marca, args.anio, args.modelo):
            disponibles = opciones_directorio(pagina, raiz)
            opciones = coincidir_opciones(disponibles, nombre)
            if len(opciones) != 1:
                raise ErrorAcceso(
                    f"Selecciona la variante completa de {nombre!r}." if opciones else f"No se encontró {nombre!r}.",
                    opciones=[e.texto for e in (opciones or disponibles)],
                )
            raiz = opciones[0].url
            pagina = cliente.obtener(raiz)
        indice = indice_reparacion(pagina, raiz)
        if indice is None:
            raise ErrorAcceso("El modelo no publica el índice Repair and Diagnosis, all links.")
        pagina = cargar_indice(cliente, indice, raiz)
        resultados = buscar_secciones(pagina, indice.url, raiz, args.consulta)
        documentos = []
        for enlace in resultados[:args.limite]:
            try:
                documentos.append(leer_seccion(cliente, enlace))
            except ErrorAcceso as exc:
                logger.error("No se pudo leer %s: %s", enlace.url, exc)
                documentos.append({"id": hashlib.sha256(enlace.url.encode()).hexdigest(),
                                   "fuente_url": enlace.url, "seccion": enlace.texto,
                                   "error": "No se pudo leer", "http": exc.estado})
        salida = crear_resultado(raiz, args.consulta, len(resultados), documentos)
        salida['limite'] = args.limite
        salida['indice_completo'] = 'all links' in normalizar(indice.texto)
        salida['truncado'] = len(resultados) > args.limite
        if args.salida:
            guardar_resultado(salida, args.salida)
        sys.stdout.write(json.dumps(salida, ensure_ascii=False, indent=2) + "\n")
        return 1 if any('error' in d for d in documentos) else 0
    except (ErrorAcceso, OSError, ValueError) as exc:
        mensaje = re.sub(r"https?://\S+", "[página]", str(exc))
        logger.error("%s", mensaje)
        sys.stdout.write(json.dumps({
            'schema_version': 1,
            'consulta': args.consulta,
            'vehiculo': {'marca': args.marca, 'anio': args.anio, 'modelo': args.modelo},
            'secciones_coincidentes': 0,
            'documentos': [],
            'error': mensaje,
            'http': getattr(exc, 'estado', None),
            'opciones': getattr(exc, 'opciones', []),
        }, ensure_ascii=False) + "\n")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        logger.info("\nConsulta finalizada.")
        sys.exit(0)
