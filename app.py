from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
import sqlite3
import pandas as pd
import re
import time
import os
import json
from datetime import datetime
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import threading
from functools import lru_cache

app = Flask(__name__)

# ============== CONFIGURACIÓN ==============
# (Sin variables de configuración - la lógica busca solo vecinos inmediatos)

# Variables globales para control de procesamiento masivo
procesamiento_masivo_estado = {}
procesamiento_masivo_lock = threading.Lock()

def normalizar_direccion_completa(direccion):
    """
    Normaliza direcciones colombianas aplicando reglas estándar
    Basado en normalizaciones de KNIME pero mejorado para Python
    """
    if not direccion or pd.isna(direccion):
        return direccion
    
    direccion = str(direccion).upper().strip()
    
    # 1. Reemplazar guiones y caracteres especiales por espacio
    direccion = direccion.replace('-', ' - ')  # Mantener guión con espacios para identificar número puerta
    direccion = direccion.replace('#', ' ')
    direccion = direccion.replace('.', ' ')
    direccion = direccion.replace(',', '')
    
    # 2. Normalizar tipos de vía (ANTES de agregar espacios)
    tipos_via = {
        'CARRERA': 'CR', 'KRA': 'CR', 'CRA': 'CR', 'CRÂ': 'CR',
        'CALLE': 'CL', 'CLLE': 'CL', 'CLE': 'CL', 'CLL': 'CL',
        'DIAGONAL': 'DG', 'DIAG': 'DG',
        'TRANSVERSAL': 'TR', 'TRANVERSAL': 'TR', 'TRANSV': 'TR', 'TV': 'TR',
        'CARRETERA': 'CARRET', 'SZ': 'SECTOR'
    }
    
    for original, normalizado in tipos_via.items():
        direccion = direccion.replace(original, normalizado)
    
    # 3. Agregar espacios alrededor de tipos de vía para delimitarlos
    for tipo in ['CR', 'CL', 'DG', 'TR', 'NR', 'AV']:
        # Agregar espacio DESPUÉS del tipo de vía si no lo tiene
        direccion = re.sub(rf'\b{tipo}(?=[A-Z0-9])', f'{tipo} ', direccion)
        # Agregar espacio ANTES del tipo de vía si no lo tiene
        direccion = re.sub(rf'([A-Z0-9]){tipo}\b', rf'\1 {tipo}', direccion)
    
    # 4. Separar números pegados a letras (CRÍTICO para casos como 9J2, 70C)
    # Letra seguida de número: A1 -> A 1
    direccion = re.sub(r'([A-Z])([0-9])', r'\1 \2', direccion)
    # Número seguido de letra: 1A -> 1 A (pero no si la letra es parte de orientación)
    direccion = re.sub(r'([0-9])([A-Z])(?![A-Z]*(?:ESTE|OESTE|NORTE|SUR|BIS))', r'\1 \2', direccion)
    
    # 5. Normalizar sufijos (sin espacios internos)
    sufijos = {
        ' BIS ': 'BIS ', ' ESTE ': 'ESTE ', ' OESTE ': 'OESTE ', 
        ' NORTE ': 'NORTE ', ' SUR ': 'SUR '
    }
    for original, normalizado in sufijos.items():
        direccion = direccion.replace(original, normalizado)
    
    # 6. Normalizar letras individuales seguidas de número (D1, A1, etc)
    # D1 -> D 1, A1 -> A 1, etc.
    for letra in 'ABCDEFGHLNFG':
        direccion = direccion.replace(f' {letra}1 ', f' {letra} 1 ')
    
    # 7. Limpiar espacios múltiples (al final después de todas las transformaciones)
    direccion = ' '.join(direccion.split())
    
    return direccion

def corrige_utf8(df):
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).apply(lambda x: x.encode('utf-8', 'replace').decode('utf-8'))
    return df

def formato_valor_numerico(valor):
    """
    Convierte un valor a entero si es válido, sino retorna 'None'
    Maneja NaN, None (string) y valores numéricos
    """
    if pd.isna(valor):
        return None
    valor_str = str(valor).strip().upper()
    if valor_str == 'NONE' or valor_str == 'NAN':
        return None
    try:
        return int(float(valor))
    except (ValueError, TypeError):
        return None

def setup_database():
    ruta_base_datos = "/home/timel_ahs/Compartidos/Buscar-direcciones/mi_base_datos.sqlite"
    tabla_principal = "DBACT"
    return {"ruta": ruta_base_datos, "tabla": tabla_principal}

def extract_direccion_components(direccion):
    """Extrae componentes estructurados de una dirección, incluyendo intersecciones"""
    # Normalizar PRIMERO
    direccion_original = str(direccion).strip().upper()
    direccion = normalizar_direccion_completa(direccion_original)
    
    # CRÍTICO: Identificar número de puerta ANTES de extraer todos los números
    # El número de puerta es el que aparece después de " - " o como último número significativo
    numero_puerta = None
    match_puerta = re.search(r'-\s*(\d+)', direccion)
    if match_puerta:
        numero_puerta = match_puerta.group(1)
    
    # Extraer todos los números
    numeros = re.findall(r'[0-9]+', direccion)
    
    # Detectar primer tipo de vía
    tipo_via_1 = ""
    if direccion.startswith("CL ") or direccion.startswith("CALLE "): 
        tipo_via_1 = "CALLE"
    elif direccion.startswith("CR ") or direccion.startswith("CARRERA "): 
        tipo_via_1 = "CARRERA"
    elif direccion.startswith("AV ") or direccion.startswith("AVENIDA "): 
        tipo_via_1 = "AVENIDA"
    elif direccion.startswith("DG ") or direccion.startswith("DIAGONAL "): 
        tipo_via_1 = "DIAGONAL"
    elif direccion.startswith("TV ") or direccion.startswith("TRANSVERSAL "): 
        tipo_via_1 = "TRANSVERSAL"
    elif direccion.startswith("KR ") or direccion.startswith("KILOMETRO "): 
        tipo_via_1 = "KILOMETRO"
    
    # Detectar si es una intersección (tiene segundo tipo de vía)
    tipo_via_2 = ""
    via_secundaria = None
    via_secundaria_letra = None
    es_interseccion = False
    
    # Buscar segundo tipo de vía en la dirección
    if " CL " in direccion or " CALLE " in direccion:
        tipo_via_2 = "CALLE"
        es_interseccion = True
    elif " CR " in direccion or " CARRERA " in direccion:
        tipo_via_2 = "CARRERA"
        es_interseccion = True
    elif " AV " in direccion or " AVENIDA " in direccion:
        tipo_via_2 = "AVENIDA"
        es_interseccion = True
    
    # Extraer vía principal y secundaria
    via_principal = None
    via_principal_letra = None
    
    # Filtrar números que NO son el número de puerta para identificar vías
    numeros_via = [n for n in numeros if n != numero_puerta]
    
    if es_interseccion:
        # Es una intersección: CR 19 CL 126 - 10 o CL 123 CR 19 B - 11 o CR 19 J 2 CL 123
        if len(numeros_via) >= 1:
            via_principal = numeros_via[0]  # Primer número es la vía principal
            # Buscar letras/componentes después del primer número hasta encontrar el siguiente tipo de vía
            # Ejemplo: "70 C" -> letra="C", "9 J 2" -> letra="J2"
            patron_letra_1 = rf'\b{via_principal}\s+([A-Z]+(?:\s+[A-Z0-9]+)*?)(?=\s+(?:CR|CL|DG|TR|AV)\s|\s*-|$)'
            match_letra_1 = re.search(patron_letra_1, direccion)
            if match_letra_1:
                # Quitar espacios internos: "J 2" -> "J2"
                via_principal_letra = match_letra_1.group(1).replace(' ', '')
        
        if len(numeros_via) >= 2:
            via_secundaria = numeros_via[1]  # Segundo número es la vía secundaria
            # Buscar letras/componentes después del segundo número hasta el guión o final
            patron_letra_2 = rf'\b{via_secundaria}\s+([A-Z]+(?:\s+[A-Z0-9]+)*?)(?=\s*-|$)'
            match_letra_2 = re.search(patron_letra_2, direccion)
            if match_letra_2:
                via_secundaria_letra = match_letra_2.group(1).replace(' ', '')
    else:
        # Es una dirección simple: CL 45 # 23-67 o CL 45 A # 23-67 o CL 45A # 23-67
        if len(numeros_via) >= 1:
            via_principal = numeros_via[0]
            # Buscar letras después del número principal hasta el guión o final
            patron_letra = rf'\b{via_principal}\s+([A-Z]+(?:\s+[A-Z0-9]+)*?)(?=\s*-|$)'
            match_letra = re.search(patron_letra, direccion)
            if match_letra:
                via_principal_letra = match_letra.group(1).replace(' ', '')
    
    return {
        "numeros": numeros,
        "tipo_via": tipo_via_1,
        "tipo_via_2": tipo_via_2,
        "via_principal": via_principal,
        "via_principal_letra": via_principal_letra,
        "via_secundaria": via_secundaria,
        "via_secundaria_letra": via_secundaria_letra,
        "numero_puerta": numero_puerta,
        "es_interseccion": es_interseccion,
        "texto_completo": direccion
    }

def obtener_numero_puerta(direccion):
    """Obtiene el número de puerta como entero"""
    comp = extract_direccion_components(direccion)
    if comp["numero_puerta"]:
        try:
            return int(comp["numero_puerta"])
        except ValueError:
            return None
    return None

def obtener_paridad_puerta(direccion):
    """Obtiene la paridad del número de puerta (par/impar)"""
    numero = obtener_numero_puerta(direccion)
    if numero is not None:
        return 'par' if numero % 2 == 0 else 'impar'
    return None

def obtener_numero_complemento(direccion):
    """
    Extrae el número del complemento de la dirección (apartamento, local, piso, oficina, etc.)
    Retorna el primer número encontrado después de palabras clave como AP, APTO, LOCAL, PISO, OF, etc.
    """
    if not direccion:
        return None
    
    direccion_upper = direccion.upper()
    
    # Patrones para buscar complementos con sus números
    # Buscar después del número de puerta (después del guión)
    patron_complementos = [
        r'(?:AP|APTO|APARTAMENTO)\s*(\d+)',
        r'(?:LC|LOCAL)\s*(\d+)',
        r'(?:PI|PISO)\s*(\d+)',
        r'(?:OF|OFICINA)\s*(\d+)',
        r'(?:CS|CASA)\s*(\d+)',
        r'(?:BL|BLOQUE)\s*(\d+)',
        r'(?:INT|INTERIOR)\s*(\d+)',
        r'(?:MZ|MANZANA)\s*(\d+)',
    ]
    
    for patron in patron_complementos:
        match = re.search(patron, direccion_upper)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    
    return None

def normalizar_direccion_base(direccion):
    """Normaliza una dirección eliminando el número de puerta"""
    direccion = str(direccion).strip().upper()
    direccion_clean = re.sub(r'[^A-Z0-9 ]', ' ', direccion)
    
    comp = extract_direccion_components(direccion)
    
    if comp["tipo_via"] and comp["via_principal"]:
        patron = f"{comp['tipo_via']}\\s*{comp['via_principal']}"
        match = re.search(patron, direccion_clean)
        if match:
            return match.group(0).strip()
    
    palabras = direccion_clean.split()
    if len(palabras) >= 2:
        return " ".join(palabras[:2])
    
    return direccion_clean

def son_direcciones_equivalentes(dir1, dir2):
    """Determina si dos direcciones son de la misma calle/carrera, incluyendo letras (19 A, 19 B, etc).
    Las intersecciones deben coincidir EXACTAMENTE en el mismo orden (CL 123 CR 19 != CR 19 CL 123)."""
    comp1 = extract_direccion_components(dir1)
    comp2 = extract_direccion_components(dir2)
    
    if not (comp1["tipo_via"] and comp1["via_principal"] and 
            comp2["tipo_via"] and comp2["via_principal"]):
        return False
    
    # Si ambas son intersecciones, deben coincidir EXACTAMENTE en ambas vías (incluyendo letras) y en el MISMO ORDEN
    if comp1["es_interseccion"] and comp2["es_interseccion"]:
        # Solo comparación directa (mismo orden) - NO se permiten inversiones
        # CL 123 CR 19B != CR 19B CL 123 (son ubicaciones diferentes)
        return (
            comp1["tipo_via"] == comp2["tipo_via"] and 
            comp1["via_principal"] == comp2["via_principal"] and
            comp1["via_principal_letra"] == comp2["via_principal_letra"] and
            comp1["tipo_via_2"] == comp2["tipo_via_2"] and
            comp1["via_secundaria"] == comp2["via_secundaria"] and
            comp1["via_secundaria_letra"] == comp2["via_secundaria_letra"]
        )
    
    # Si solo una es intersección y la otra no, NO son equivalentes
    if comp1["es_interseccion"] != comp2["es_interseccion"]:
        return False
    
    # Si ninguna es intersección (direcciones simples), comparar normalmente (incluyendo letra)
    if (comp1["tipo_via"] == comp2["tipo_via"] and 
        comp1["via_principal"] == comp2["via_principal"] and
        comp1["via_principal_letra"] == comp2["via_principal_letra"]):
        return True
    
    return False

# ============== FUNCIONES OPTIMIZADAS PARA PROCESAMIENTO MASIVO ==============

@lru_cache(maxsize=10000)
def son_direcciones_equivalentes_rapido(dir1, dir2):
    """
    Versión optimizada y simplificada de comparación de direcciones para procesamiento masivo.
    Usa caching (lru_cache) para evitar recalcular direcciones ya vistas.
    """
    # Normalizar
    d1 = dir1.upper().strip()
    d2 = dir2.upper().strip()
    
    # Extraer tipo de vía y números principales (sin parsing complejo)
    # Ejemplo: "CL 70 CR 25" -> ["CL", "70", "CR", "25"]
    tokens1 = re.findall(r'(?:CL|CR|DG|TR|AV|KR|CALLE|CARRERA|DIAGONAL|TRANSVERSAL|AVENIDA)|\d+[A-Z]*', d1)
    tokens2 = re.findall(r'(?:CL|CR|DG|TR|AV|KR|CALLE|CARRERA|DIAGONAL|TRANSVERSAL|AVENIDA)|\d+[A-Z]*', d2)
    
    if len(tokens1) < 2 or len(tokens2) < 2:
        return False
    
    # Comparar los primeros 4 tokens (tipo vía + número + tipo vía 2 + número 2)
    # Esto cubre tanto direcciones simples como intersecciones
    tokens_to_compare = min(4, len(tokens1), len(tokens2))
    return tokens1[:tokens_to_compare] == tokens2[:tokens_to_compare]

@lru_cache(maxsize=10000)
def obtener_numero_puerta_cached(direccion):
    """Versión con caché de obtener_numero_puerta"""
    return obtener_numero_puerta(direccion)

@lru_cache(maxsize=10000)
def obtener_paridad_puerta_cached(direccion):
    """Versión con caché de obtener_paridad_puerta"""
    return obtener_paridad_puerta(direccion)

def calcular_diferencia_puerta(dir1, dir2):
    """Calcula la diferencia numérica entre los números de puerta"""
    if not son_direcciones_equivalentes(dir1, dir2):
        return None
    
    comp1 = extract_direccion_components(dir1)
    comp2 = extract_direccion_components(dir2)
    
    if comp1["numero_puerta"] and comp2["numero_puerta"]:
        try:
            puerta1 = int(comp1["numero_puerta"])
            puerta2 = int(comp2["numero_puerta"])
            return abs(puerta1 - puerta2)
        except ValueError:
            return None
    
    return None

def obtener_direccion_desde_coordenadas(latitud, longitud):
    """
    Convierte coordenadas geográficas a dirección usando Nominatim (OpenStreetMap)
    
    Args:
        latitud (float): Latitud (ej: 4.6097 para Bogotá)
        longitud (float): Longitud (ej: -74.0817 para Bogotá)
    
    Returns:
        dict: Información de la dirección o None si falla
    """
    try:
        # Crear geocodificador con un user_agent único
        geolocator = Nominatim(user_agent="buscar_direcciones_app/1.0", timeout=10)
        
        # Respetar límite de 1 petición por segundo
        time.sleep(1)
        
        # Obtener ubicación desde coordenadas
        location = geolocator.reverse(f"{latitud}, {longitud}", language='es')
        
        if location:
            address = location.raw.get('address', {})
            
            # Extraer componentes relevantes de la dirección
            direccion_formateada = {
                'direccion_completa': location.address,
                'calle': address.get('road', ''),
                'numero': address.get('house_number', ''),
                'barrio': address.get('neighbourhood', address.get('suburb', '')),
                'ciudad': address.get('city', address.get('town', address.get('municipality', ''))),
                'departamento': address.get('state', ''),
                'pais': address.get('country', ''),
                'codigo_postal': address.get('postcode', ''),
                'coordenadas': {
                    'latitud': latitud,
                    'longitud': longitud
                },
                'display_name': location.address
            }
            
            return direccion_formateada
        
        return None
        
    except GeocoderTimedOut:
        print(f"Timeout al geocodificar coordenadas: {latitud}, {longitud}")
        return None
    except GeocoderServiceError as e:
        print(f"Error del servicio de geocodificación: {e}")
        return None
    except Exception as e:
        print(f"Error inesperado en geocodificación: {e}")
        return None

def obtener_coordenadas_desde_direccion(direccion):
    """
    Convierte dirección a coordenadas geográficas (geocodificación directa)
    
    Args:
        direccion (str): Dirección a geocodificar (ej: "CL 123 CR 19 - 11")
    
    Returns:
        dict: Coordenadas {'latitud': float, 'longitud': float} o None si falla
    """
    if not direccion or pd.isna(direccion):
        return None
    
    try:
        # Crear geocodificador
        geolocator = Nominatim(user_agent="buscar_direcciones_app/1.0", timeout=10)
        
        # Respetar límite de 1 petición por segundo
        time.sleep(1.1)  # 1.1 seg para estar seguros
        
        # Agregar ", Colombia" para mejorar precisión
        direccion_completa = f"{direccion}, Colombia"
        
        # Obtener coordenadas desde dirección
        location = geolocator.geocode(direccion_completa)
        
        if location:
            return {
                'latitud': location.latitude,
                'longitud': location.longitude,
                'direccion_formateada': location.address
            }
        
        return None
        
    except GeocoderTimedOut:
        print(f"Timeout al geocodificar dirección: {direccion}")
        return None
    except GeocoderServiceError as e:
        print(f"Error del servicio al geocodificar: {e}")
        return None
    except Exception as e:
        print(f"Error inesperado al geocodificar dirección: {e}")
        return None

def buscar_candidatos(product_id_buscar):
    """Busca candidatos para un PRODUCT_ID dado"""
    config = setup_database()
    con = sqlite3.connect(config["ruta"])
    
    try:
        # Buscar el producto
        info_producto = pd.read_sql_query(
            f"SELECT * FROM {config['tabla']} WHERE PRODUCT_ID = ?", 
            con, params=[product_id_buscar])
        info_producto = corrige_utf8(info_producto)
        
        if info_producto.empty:
            return {
                "error": "No se encontró el PRODUCT_ID en la base de datos",
                "encontrado": False
            }
        
        info_producto = info_producto.iloc[0]
        
        # Extraer componentes del producto original
        numero_puerta_original = obtener_numero_puerta(info_producto['DIRECCION'])
        paridad_original = obtener_paridad_puerta(info_producto['DIRECCION'])
        
        # Buscar en misma localidad
        query = f"""
        SELECT *, '{config['tabla']}' AS fuente 
        FROM {config['tabla']} 
        WHERE DPTO = ? 
        AND MUNICIPIO = ? 
        AND LOCALIDAD = ?
        AND PRODUCT_ID != ?
        AND ROUTE_ID IS NOT NULL
        AND SESUCICL NOT IN (9000, 4000, 6000)

        """
        
        resultados = pd.read_sql_query(
            query, con, 
            params=[info_producto['DPTO'], info_producto['MUNICIPIO'], 
                    info_producto['LOCALIDAD'], product_id_buscar])
        resultados = corrige_utf8(resultados)
        
        producto_info = {
            "PRODUCT_ID": formato_valor_numerico(info_producto['PRODUCT_ID']),
            "DPTO": info_producto['DPTO'],
            "MUNICIPIO": info_producto['MUNICIPIO'],
            "LOCALIDAD": info_producto['LOCALIDAD'],
            "DIRECCION": info_producto['DIRECCION'],
            "ROUTE_ID": formato_valor_numerico(info_producto['ROUTE_ID'])
        }
        
        if resultados.empty:
            return {
                "error": "No se encontraron productos en la misma localidad con ciclo válido (SESUCICL diferente de 9000, 4000 y 6000)",
                "encontrado": True,
                "producto": producto_info,
                "candidatos": []
            }
        
        # Filtrar por dirección equivalente (UNA SOLA VEZ)
        resultados["es_misma_direccion"] = resultados["DIRECCION"].apply(
            lambda d: son_direcciones_equivalentes(info_producto['DIRECCION'], d))
        
        candidatos_misma_calle = resultados[resultados["es_misma_direccion"] == True].copy()
        
        if candidatos_misma_calle.empty:
            return {
                "error": "No se encontraron candidatos en la misma dirección",
                "encontrado": True,
                "producto": producto_info,
                "candidatos": []
            }
        
        # Calcular métricas una sola vez
        candidatos_misma_calle["numero_puerta"] = candidatos_misma_calle["DIRECCION"].apply(obtener_numero_puerta)
        candidatos_misma_calle["diferencia_puerta"] = candidatos_misma_calle["DIRECCION"].apply(
            lambda d: calcular_diferencia_puerta(info_producto['DIRECCION'], d))
        candidatos_misma_calle["paridad"] = candidatos_misma_calle["DIRECCION"].apply(obtener_paridad_puerta)
        
        # Filtrar por paridad si existe
        if paridad_original:
            candidatos_misma_calle = candidatos_misma_calle[
                candidatos_misma_calle["paridad"] == paridad_original].copy()
        
        # Filtrar candidatos válidos (con diferencia de puerta calculable)
        candidatos_validos = candidatos_misma_calle[
            candidatos_misma_calle["diferencia_puerta"].notna()].copy()
        
        if candidatos_validos.empty:
            return {
                "error": "No se encontraron candidatos válidos",
                "encontrado": True,
                "producto": producto_info,
                "candidatos": []
            }
        
        # Lógica optimizada: buscar 2 vecinos anteriores y 2 posteriores más cercanos
        candidatos_finales = pd.DataFrame()
        vecinos_encontrados = {"anteriores": 0, "posteriores": 0}
        
        if numero_puerta_original:
            # Buscar los 2 vecinos anteriores más cercanos
            candidatos_anteriores = candidatos_validos[
                candidatos_validos["numero_puerta"] < numero_puerta_original]
            if not candidatos_anteriores.empty:
                vecinos_anteriores = candidatos_anteriores.nlargest(2, "numero_puerta")
                candidatos_finales = pd.concat([candidatos_finales, vecinos_anteriores], ignore_index=True)
                vecinos_encontrados["anteriores"] = len(vecinos_anteriores)
            
            # Buscar direcciones con el mismo número de puerta (mismo edificio/dirección base)
            candidatos_mismo_numero = candidatos_validos[
                candidatos_validos["numero_puerta"] == numero_puerta_original]
            if not candidatos_mismo_numero.empty:
                candidatos_finales = pd.concat([candidatos_finales, candidatos_mismo_numero], ignore_index=True)
            
            # Buscar los 2 vecinos posteriores más cercanos
            candidatos_posteriores = candidatos_validos[
                candidatos_validos["numero_puerta"] > numero_puerta_original]
            if not candidatos_posteriores.empty:
                vecinos_posteriores = candidatos_posteriores.nsmallest(2, "numero_puerta")
                candidatos_finales = pd.concat([candidatos_finales, vecinos_posteriores], ignore_index=True)
                vecinos_encontrados["posteriores"] = len(vecinos_posteriores)
        else:
            # Si no hay número de puerta original, tomar los 10 más cercanos
            candidatos_finales = candidatos_validos.nsmallest(10, "diferencia_puerta")
        
        # Calcular complemento para el producto original y cada candidato
        complemento_producto = obtener_numero_complemento(info_producto['DIRECCION'])
        
        # Agregar columna de complemento y diferencia de complemento
        candidatos_finales['complemento'] = candidatos_finales['DIRECCION'].apply(obtener_numero_complemento)
        
        # Calcular diferencia de complemento (solo para candidatos con mismo número de puerta)
        def calcular_diferencia_complemento(row):
            if row['numero_puerta'] == numero_puerta_original:
                if complemento_producto is not None and row['complemento'] is not None:
                    return abs(row['complemento'] - complemento_producto)
                elif row['complemento'] is None:
                    return float('inf')  # Sin complemento va al final
            return 0  # Diferentes números de puerta no consideran complemento en el orden
        
        candidatos_finales['diferencia_complemento'] = candidatos_finales.apply(calcular_diferencia_complemento, axis=1)
        
        # Ordenar por diferencia de puerta primero, luego por diferencia de complemento
        if not candidatos_finales.empty:
            candidatos_finales = candidatos_finales.sort_values(
                by=['diferencia_puerta', 'diferencia_complemento'], 
                na_position='last'
            )
        
        if candidatos_finales.empty:
            return {
                "error": "No se encontraron candidatos válidos",
                "encontrado": True,
                "producto": producto_info,
                "candidatos": []
            }
        
        # Preparar respuesta
        candidatos_list = []
        for idx, row in candidatos_finales.iterrows():
            numero_puerta_candidato = row['numero_puerta']
            tipo_candidato = ""
            
            if numero_puerta_original and numero_puerta_candidato:
                if numero_puerta_candidato < numero_puerta_original:
                    tipo_candidato = "Vecino anterior"
                elif numero_puerta_candidato == numero_puerta_original:
                    tipo_candidato = "Mismo edificio/número"
                elif numero_puerta_candidato > numero_puerta_original:
                    tipo_candidato = "Vecino posterior"
            
            candidatos_list.append({
                "PRODUCT_ID": formato_valor_numerico(row['PRODUCT_ID']),
                "DIRECCION": row['DIRECCION'],
                "DPTO": row['DPTO'],
                "MUNICIPIO": row['MUNICIPIO'],
                "LOCALIDAD": row['LOCALIDAD'],
                "ROUTE_ID": formato_valor_numerico(row['ROUTE_ID']),
                "ITINERARIO": formato_valor_numerico(row['ROUTE_ITINERARY_ID']),
                "SECUENCIA": formato_valor_numerico(row['CONSECUTIVE']),
                "CICLO": formato_valor_numerico(row['SESUCICL']),
                "diferencia_puerta": int(row['diferencia_puerta']) if pd.notna(row['diferencia_puerta']) else None,
                "diferencia_complemento": int(row['diferencia_complemento']) if pd.notna(row['diferencia_complemento']) and row['diferencia_complemento'] != float('inf') else None,
                "tipo_candidato": tipo_candidato
            })
        
        # Recomendación: seleccionar el candidato más cercano (menor diferencia_puerta)
        recomendacion = None
        if candidatos_list:
            # Buscar el candidato con menor diferencia de puerta
            candidato_rec = min(candidatos_list, key=lambda x: x["diferencia_puerta"] if x["diferencia_puerta"] is not None else float('inf'))
            
            # Calcular secuencia sugerida para el producto buscado
            secuencia_sugerida = None
            secuencia_vecino = candidato_rec["SECUENCIA"]
            
            if secuencia_vecino is not None:
                # Obtener número de puerta del vecino recomendado
                numero_puerta_vecino = obtener_numero_puerta(candidato_rec["DIRECCION"])
                
                if numero_puerta_original and numero_puerta_vecino:
                    # Si el vecino está antes (número menor), restar 1 a su secuencia
                    if numero_puerta_vecino < numero_puerta_original:
                        secuencia_sugerida = secuencia_vecino - 1
                    # Si el vecino está después (número mayor), sumar 1 a su secuencia
                    elif numero_puerta_vecino > numero_puerta_original:
                        secuencia_sugerida = secuencia_vecino + 1
                    # Si tienen el mismo número de puerta, sumar 1 a la secuencia
                    else:
                                secuencia_sugerida = secuencia_vecino + 1
            
            recomendacion = {
                "DIRECCION": candidato_rec["DIRECCION"],
                "ROUTE_ID": candidato_rec["ROUTE_ID"],
                "ITINERARIO": candidato_rec["ITINERARIO"],
                "SECUENCIA": candidato_rec["SECUENCIA"],
                "SECUENCIA_SUGERIDA": secuencia_sugerida,
                "CICLO": candidato_rec["CICLO"],
                "diferencia_puerta": candidato_rec["diferencia_puerta"]
            }
        
        # Análisis de itinerarios - TODOS los vecinos del mismo lado de la calle
        # Usar candidatos_validos que contiene TODOS los vecinos con la misma paridad
        itinerarios_contador = {}
        
        # Contar itinerarios de TODOS los vecinos con la misma paridad (mismo lado de la calle)
        for idx, row in candidatos_validos.iterrows():
            itinerario = row["ROUTE_ITINERARY_ID"]
            if itinerario is not None and pd.notna(itinerario):
                itinerario_str = str(int(itinerario)) if isinstance(itinerario, float) else str(itinerario)
                itinerarios_contador[itinerario_str] = itinerarios_contador.get(itinerario_str, 0) + 1
        
        # Preparar información de itinerarios
        itinerarios_unicos = len(itinerarios_contador)
        itinerarios_detalle = [
            {"itinerario": itinerario, "cantidad": cantidad}
            for itinerario, cantidad in sorted(itinerarios_contador.items(), key=lambda x: x[1], reverse=True)
        ]
        
        # Información adicional sobre la paridad
        paridad_info = {
            "paridad": paridad_original if paridad_original else "No determinada",
            "total_vecinos_misma_paridad": len(candidatos_validos),
            "numero_puerta_producto": numero_puerta_original
        }
        
        # Preparar mensajes de vecinos no encontrados
        mensajes_info = []
        if numero_puerta_original:
            if vecinos_encontrados["anteriores"] == 0:
                mensajes_info.append("No se encontraron vecinos anteriores")
            elif vecinos_encontrados["anteriores"] == 1:
                mensajes_info.append("Solo se encontró 1 vecino anterior")
            
            if vecinos_encontrados["posteriores"] == 0:
                mensajes_info.append("No se encontraron vecinos posteriores")
            elif vecinos_encontrados["posteriores"] == 1:
                mensajes_info.append("Solo se encontró 1 vecino posterior")
        
        # ========== GEOCODIFICACIÓN: Obtener coordenadas para mapa ==========
        print("🗺️ Iniciando geocodificación de direcciones...")
        
        # Geocodificar producto original
        print(f"Geocodificando producto {product_id_buscar}...")
        coords_producto = obtener_coordenadas_desde_direccion(info_producto['DIRECCION'])
        if coords_producto:
            producto_info['latitud'] = coords_producto['latitud']
            producto_info['longitud'] = coords_producto['longitud']
            print(f"✓ Producto: {coords_producto['latitud']}, {coords_producto['longitud']}")
        else:
            producto_info['latitud'] = None
            producto_info['longitud'] = None
            print("✗ No se pudo geocodificar el producto")
        
        # Geocodificar candidatos (limitado a los primeros para no exceder tiempo de espera)
        # Nota: Esto puede ser lento (1+ segundo por dirección)
        max_geocodificar = 10  # Limitar a 10 candidatos para no hacer esperar demasiado
        for i, candidato in enumerate(candidatos_list[:max_geocodificar]):
            print(f"Geocodificando candidato {i+1}/{min(len(candidatos_list), max_geocodificar)}...")
            coords = obtener_coordenadas_desde_direccion(candidato['DIRECCION'])
            if coords:
                candidato['latitud'] = coords['latitud']
                candidato['longitud'] = coords['longitud']
                print(f"✓ Candidato {i+1}: {coords['latitud']}, {coords['longitud']}")
            else:
                candidato['latitud'] = None
                candidato['longitud'] = None
                print(f"✗ No se pudo geocodificar candidato {i+1}")
        
        # Para candidatos restantes (si hay más de max_geocodificar), poner coordenadas en None
        for candidato in candidatos_list[max_geocodificar:]:
            candidato['latitud'] = None
            candidato['longitud'] = None
        
        print("✓ Geocodificación completada")
        
        return {
            "encontrado": True,
            "producto": producto_info,
            "candidatos": candidatos_list,
            "recomendacion": recomendacion,
            "vecinos_info": {
                "anteriores_encontrados": vecinos_encontrados["anteriores"],
                "posteriores_encontrados": vecinos_encontrados["posteriores"],
                "mensajes": mensajes_info
            },
            "itinerarios_info": {
                "total_unicos": itinerarios_unicos,
                "detalle": itinerarios_detalle,
                "paridad_info": paridad_info
            }
        }
        
    finally:
        con.close()

@app.route('/')
def index():
    """Página de inicio con selección de tipo de búsqueda"""
    return render_template('index.html')

@app.route('/buscar-product')
def buscar_product_page():
    """Página de búsqueda por Product_ID"""
    return render_template('buscar_product.html')

@app.route('/buscar-coordenadas')
def buscar_coordenadas_page():
    """Página de búsqueda por Coordenadas"""
    return render_template('buscar_coordenadas.html')

@app.route('/buscar', methods=['POST'])
def buscar():
    try:
        data = request.json
        product_id = int(data.get('product_id'))
        
        resultado = buscar_candidatos(product_id)
        return jsonify(resultado)
    
    except ValueError:
        return jsonify({"error": "PRODUCT_ID debe ser un número válido", "encontrado": False}), 400
    except Exception as e:
        return jsonify({"error": str(e), "encontrado": False}), 500

@app.route('/api/obtener-vecinos-itinerario', methods=['POST'])
def obtener_vecinos_itinerario():
    """
    Obtiene TODOS los vecinos de un itinerario específico que comparten
    la misma dirección base y paridad con el producto buscado
    """
    try:
        data = request.json
        product_id = int(data.get('product_id'))
        itinerario = str(data.get('itinerario'))
        
        if not product_id or not itinerario:
            return jsonify({"error": "PRODUCT_ID e ITINERARIO requeridos"}), 400
        
        config = setup_database()
        conn = sqlite3.connect(config["ruta"])
        
        # Obtener información del producto original
        df_producto = pd.read_sql_query(
            f"SELECT * FROM {config['tabla']} WHERE PRODUCT_ID = ?",
            conn, params=[product_id]
        )
        
        if df_producto.empty:
            conn.close()
            return jsonify({"error": "Producto no encontrado"}), 404
        
        producto = df_producto.iloc[0]
        direccion_producto = producto['DIRECCION']
        numero_puerta_producto = obtener_numero_puerta(direccion_producto)
        paridad_producto = obtener_paridad_puerta(direccion_producto)
        
        # Buscar TODOS los vecinos del itinerario especificado
        query = f"""
        SELECT PRODUCT_ID, DIRECCION, ROUTE_ID, 
               ROUTE_ITINERARY_ID AS ITINERARIO, 
               CONSECUTIVE AS SECUENCIA, 
               SESUCICL AS CICLO
        FROM {config['tabla']}
        WHERE ROUTE_ITINERARY_ID = ?
        AND DPTO = ?
        AND MUNICIPIO = ?
        AND LOCALIDAD = ?
        AND PRODUCT_ID != ?
        AND SESUCICL NOT IN (9000, 4000, 6000)
        ORDER BY CONSECUTIVE
        """
        
        df_vecinos = pd.read_sql_query(
            query, conn, 
            params=[itinerario, producto['DPTO'], producto['MUNICIPIO'], 
                   producto['LOCALIDAD'], product_id]
        )
        
        conn.close()
        
        # Filtrar por dirección equivalente y paridad
        vecinos_filtrados = []
        for idx, row in df_vecinos.iterrows():
            if son_direcciones_equivalentes(direccion_producto, row['DIRECCION']):
                paridad_vecino = obtener_paridad_puerta(row['DIRECCION'])
                if paridad_vecino == paridad_producto:
                    numero_puerta_vecino = obtener_numero_puerta(row['DIRECCION'])
                    diferencia = abs(numero_puerta_vecino - numero_puerta_producto) if numero_puerta_vecino and numero_puerta_producto else None
                    
                    vecinos_filtrados.append({
                        "PRODUCT_ID": formato_valor_numerico(row['PRODUCT_ID']),
                        "DIRECCION": row['DIRECCION'],
                        "ROUTE_ID": formato_valor_numerico(row['ROUTE_ID']),
                        "ITINERARIO": formato_valor_numerico(row['ITINERARIO']),
                        "SECUENCIA": formato_valor_numerico(row['SECUENCIA']),
                        "CICLO": formato_valor_numerico(row['CICLO']),
                        "diferencia_puerta": diferencia,
                        "numero_puerta": numero_puerta_vecino
                    })
        
        # Ordenar por diferencia de puerta
        vecinos_filtrados.sort(key=lambda x: x.get('diferencia_puerta', 999999) if x.get('diferencia_puerta') is not None else 999999)
        
        return jsonify({
            "success": True,
            "vecinos": vecinos_filtrados,
            "total": len(vecinos_filtrados),
            "itinerario": itinerario
        })
        
    except Exception as e:
        return jsonify({"error": f"Error al obtener vecinos: {str(e)}"}), 500

@app.route('/geocodificar', methods=['POST'])
def geocodificar():
    """
    Endpoint para convertir coordenadas geográficas a dirección
    y buscar productos cercanos en la base de datos
    """
    try:
        data = request.json
        latitud = float(data.get('latitud'))
        longitud = float(data.get('longitud'))
        
        # Validar que las coordenadas estén dentro del rango razonable para Colombia
        if not (1.0 <= latitud <= 12.5):
            return jsonify({
                "error": "Latitud fuera del rango válido para Colombia (1.0 - 12.5)"
            }), 400
        
        if not (-79.0 <= longitud <= -66.0):
            return jsonify({
                "error": "Longitud fuera del rango válido para Colombia (-79.0 - -66.0)"
            }), 400
        
        # Obtener dirección desde coordenadas
        info_direccion = obtener_direccion_desde_coordenadas(latitud, longitud)
        
        if not info_direccion:
            return jsonify({
                "error": "No se pudo geocodificar las coordenadas. Verifica que sean correctas."
            }), 404
        
        # Buscar productos en la base de datos con direcciones similares
        config = setup_database()
        conn = sqlite3.connect(config["ruta"])
        
        productos_encontrados = []
        direccion_buscar = info_direccion.get('calle', '')
        
        if direccion_buscar:
            # Normalizar la dirección obtenida
            direccion_normalizada = normalizar_direccion_completa(direccion_buscar)
            
            # Buscar productos con direcciones similares
            query = f"""
                SELECT * FROM {config['tabla']} 
                WHERE DIRECCION LIKE ? 
                LIMIT 20
            """
            
            try:
                resultados = pd.read_sql_query(
                    query, 
                    conn, 
                    params=[f"%{direccion_normalizada}%"]
                )
                resultados = corrige_utf8(resultados)
                
                if not resultados.empty:
                    productos_encontrados = resultados.to_dict('records')
            except Exception as e:
                print(f"Error al buscar productos: {e}")
        
        conn.close()
        
        return jsonify({
            "success": True,
            "direccion": info_direccion,
            "productos_cercanos": productos_encontrados,
            "total_productos": len(productos_encontrados),
            "mensaje": f"Se encontraron {len(productos_encontrados)} productos en esta zona" if productos_encontrados else "Dirección encontrada, pero no hay productos registrados en esta zona"
        })
    
    except ValueError:
        return jsonify({
            "error": "Coordenadas inválidas. Deben ser números decimales."
        }), 400
    except Exception as e:
        return jsonify({
            "error": f"Error al procesar la solicitud: {str(e)}"
        }), 500

@app.route('/buscar-direccion')
def buscar_direccion_page():
    """Renderiza la página de búsqueda por dirección estructurada"""
    return render_template('buscar_direccion.html')

@app.route('/api/obtener-ubicaciones', methods=['GET'])
def obtener_ubicaciones():
    """
    Obtiene listas únicas de municipios, localidades y corregimientos de la base de datos
    para usarlas en el autocompletado
    """
    try:
        config = setup_database()
        conn = sqlite3.connect(config["ruta"])
        cursor = conn.cursor()
        
        # Obtener municipios únicos
        cursor.execute("""
            SELECT DISTINCT MUNICIPIO 
            FROM DBACT 
            WHERE MUNICIPIO IS NOT NULL AND MUNICIPIO != '' 
            ORDER BY MUNICIPIO
        """)
        municipios = [row[0] for row in cursor.fetchall()]
        
        # Obtener localidades únicas
        cursor.execute("""
            SELECT DISTINCT LOCALIDAD 
            FROM DBACT 
            WHERE LOCALIDAD IS NOT NULL AND LOCALIDAD != '' 
            ORDER BY LOCALIDAD
        """)
        localidades = [row[0] for row in cursor.fetchall()]
        
        # Obtener corregimientos únicos
        cursor.execute("""
            SELECT DISTINCT CORREGIMIENTO 
            FROM DBACT 
            WHERE CORREGIMIENTO IS NOT NULL AND CORREGIMIENTO != '' 
            ORDER BY CORREGIMIENTO
        """)
        corregimientos = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        
        # En lugar de un diccionario, se devuelve una lista para garantizar el orden
        ubicaciones_ordenadas = [
            {"tipo": "Municipios", "items": municipios},
            {"tipo": "Localidades", "items": localidades},
            {"tipo": "Corregimientos", "items": corregimientos}
        ]
        
        return jsonify({
            "success": True,
            "ubicaciones": ubicaciones_ordenadas
        })
    
    except Exception as e:
        return jsonify({
            "error": f"Error al obtener ubicaciones: {str(e)}"
        }), 500

@app.route('/api/buscar-por-direccion', methods=['POST'])
def buscar_por_direccion():
    """
    Busca productos por dirección construida a partir de componentes estructurados
    """
    try:
        data = request.json
        
        # Construir dirección a partir de los componentes
        direccion_construida = ""
        
        # Vía principal
        if data.get('tipoVia1') and data.get('numeroVia1'):
            direccion_construida += f"{data['tipoVia1']} {data['numeroVia1']}"
            if data.get('letraVia1'):
                direccion_construida += f" {data['letraVia1'].upper()}"
        
        # Vía secundaria (intersección)
        if data.get('tipoVia2') and data.get('numeroVia2'):
            direccion_construida += f" {data['tipoVia2']} {data['numeroVia2']}"
            if data.get('letraVia2'):
                direccion_construida += f" {data['letraVia2'].upper()}"
        
        # Número de puerta
        if data.get('numeroPuerta'):
            direccion_construida += f" - {data['numeroPuerta']}"
        
        # Complemento
        if data.get('complemento'):
            direccion_construida += f" {data['complemento'].upper()}"
        
        if not direccion_construida:
            return jsonify({
                "error": "Debe proporcionar al menos el tipo de vía y número principal"
            }), 400
        
        # Normalizar la dirección construida
        direccion_normalizada = normalizar_direccion_completa(direccion_construida)
        
        # Buscar en la base de datos
        config = setup_database()
        conn = sqlite3.connect(config["ruta"])
        
        # Construir query base
        query = f"""
            SELECT PRODUCT_ID, DIRECCION, ROUTE_ID, 
                   ROUTE_ITINERARY_ID AS ITINERARIO, 
                   CONSECUTIVE AS SECUENCIA, 
                   SESUCICL AS CICLO, 
                   MUNICIPIO, LOCALIDAD, CORREGIMIENTO
            FROM {config["tabla"]}
            WHERE 1=1
            AND SESUCICL NOT IN (9000, 4000, 6000)
        """
        
        params = []
        
        # Filtrar por dirección normalizada (búsqueda flexible)
        if direccion_normalizada:
            # Extraer componentes principales para búsqueda más flexible
            componentes = direccion_normalizada.split()
            if len(componentes) >= 2:
                tipo_via = componentes[0]
                numero_via = componentes[1]
                query += " AND DIRECCION LIKE ?"
                params.append(f"%{tipo_via}%{numero_via}%")
        
        # Filtros opcionales de ubicación
        if data.get('municipio'):
            query += " AND UPPER(MUNICIPIO) LIKE ?"
            params.append(f"%{data['municipio'].upper()}%")
        
        if data.get('localidad'):
            query += " AND UPPER(LOCALIDAD) LIKE ?"
            params.append(f"%{data['localidad'].upper()}%")
        
        if data.get('corregimiento'):
            query += " AND UPPER(CORREGIMIENTO) LIKE ?"
            params.append(f"%{data['corregimiento'].upper()}%")
        
        # Filtro de paridad si se especifica
        if data.get('paridad') and data.get('numeroPuerta'):
            numero_puerta = int(data['numeroPuerta'])
            if data['paridad'] == 'par':
                query += " AND CAST(SUBSTR(DIRECCION, INSTR(DIRECCION, '-') + 1) AS INTEGER) % 2 = 0"
            elif data['paridad'] == 'impar':
                query += " AND CAST(SUBSTR(DIRECCION, INSTR(DIRECCION, '-') + 1) AS INTEGER) % 2 = 1"
        
        query += " ORDER BY SECUENCIA LIMIT 100"
        
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        if df.empty:
            return jsonify({
                "success": True,
                "productos": [],
                "direccion_buscada": direccion_construida,
                "direccion_normalizada": direccion_normalizada,
                "mensaje": "No se encontraron productos para esta dirección"
            })
        
        # Convertir a lista de diccionarios
        productos = df.to_dict('records')
        
        # Si hay número de puerta, ordenar por proximidad
        if data.get('numeroPuerta'):
            try:
                numero_puerta_buscado = int(data['numeroPuerta'])
                
                # Calcular diferencia de número de puerta para cada producto
                for producto in productos:
                    dir_producto = producto['DIRECCION']
                    match_puerta = re.search(r'-\s*(\d+)', dir_producto)
                    if match_puerta:
                        num_puerta_producto = int(match_puerta.group(1))
                        producto['diferencia_puerta'] = abs(num_puerta_producto - numero_puerta_buscado)
                    else:
                        producto['diferencia_puerta'] = 999999  # Sin número de puerta
                
                # Ordenar por diferencia de puerta
                productos.sort(key=lambda x: x.get('diferencia_puerta', 999999))
                
                # Limpiar campo temporal
                for producto in productos:
                    if 'diferencia_puerta' in producto:
                        del producto['diferencia_puerta']
            
            except ValueError:
                pass  # Si no se puede convertir el número de puerta, no ordenar
        
        return jsonify({
            "success": True,
            "productos": productos,
            "total": len(productos),
            "direccion_buscada": direccion_construida,
            "direccion_normalizada": direccion_normalizada,
            "mensaje": f"Se encontraron {len(productos)} productos"
        })
    
    except Exception as e:
        return jsonify({
            "error": f"Error al buscar por dirección: {str(e)}"
        }), 500

@app.route('/buscar-cuenta')
def buscar_cuenta_page():
    """Página de búsqueda por Cuenta (SUBSCRIPTION_ID)"""
    return render_template('buscar_cuenta.html')

@app.route('/api/buscar-por-cuenta', methods=['POST'])
def buscar_por_cuenta():
    """
    Busca productos por número de cuenta (SUBSCRIPTION_ID)
    """
    try:
        data = request.json
        subscription_id = data.get('subscription_id', '').strip()
        
        if not subscription_id:
            return jsonify({
                "error": "Debe proporcionar un número de cuenta",
                "success": False
            }), 400
        
        config = setup_database()
        conn = sqlite3.connect(config["ruta"])
        
        # Buscar productos con este SUBSCRIPTION_ID
        query = f"""
            SELECT PRODUCT_ID, SUBSCRIPTION_ID, DIRECCION, DPTO, MUNICIPIO, LOCALIDAD, 
                   ROUTE_ID, SESUCICL, ROUTE_ITINERARY_ID, CONSECUTIVE
            FROM {config["tabla"]}
            WHERE SUBSCRIPTION_ID = ?
            ORDER BY PRODUCT_ID
        """
        
        df = pd.read_sql_query(query, conn, params=[subscription_id])
        df = corrige_utf8(df)
        conn.close()
        
        if df.empty:
            return jsonify({
                "error": f"No se encontraron productos para la cuenta: {subscription_id}",
                "success": False
            })
        
        # Convertir a lista de diccionarios
        productos = df.to_dict('records')
        
        # Formatear valores numéricos
        for producto in productos:
            producto['PRODUCT_ID'] = formato_valor_numerico(producto.get('PRODUCT_ID'))
            producto['ROUTE_ID'] = formato_valor_numerico(producto.get('ROUTE_ID'))
            producto['SESUCICL'] = formato_valor_numerico(producto.get('SESUCICL'))
            producto['ROUTE_ITINERARY_ID'] = formato_valor_numerico(producto.get('ROUTE_ITINERARY_ID'))
            producto['CONSECUTIVE'] = formato_valor_numerico(producto.get('CONSECUTIVE'))
        
        return jsonify({
            "success": True,
            "productos": productos,
            "total": len(productos),
            "mensaje": f"Se encontraron {len(productos)} producto(s) para la cuenta {subscription_id}"
        })
    
    except Exception as e:
        return jsonify({
            "error": f"Error al buscar por cuenta: {str(e)}",
            "success": False
        }), 500

def buscar_candidatos_rapido(product_id_buscar, conn):
    """
    Versión optimizada de buscar_candidatos sin geocodificación
    Recibe una conexión existente para mejor performance
    """
    config = setup_database()
    tiempo_inicio = time.time()
    
    try:
        # Buscar el producto
        info_producto = pd.read_sql_query(
            f"SELECT * FROM {config['tabla']} WHERE PRODUCT_ID = ?", 
            conn, params=[product_id_buscar])
        info_producto = corrige_utf8(info_producto)
        
        if info_producto.empty:
            return {
                "error": "No se encontró el PRODUCT_ID en la base de datos",
                "encontrado": False
            }
        
        info_producto = info_producto.iloc[0]
        direccion_original = info_producto['DIRECCION']
        
        # Extraer componentes del producto original (con caché)
        numero_puerta_original = obtener_numero_puerta_cached(direccion_original)
        paridad_original = obtener_paridad_puerta_cached(direccion_original)
        
        # Buscar en misma localidad
        query = f"""
        SELECT *, '{config['tabla']}' AS fuente 
        FROM {config['tabla']} 
        WHERE DPTO = ? 
        AND MUNICIPIO = ? 
        AND LOCALIDAD = ?
        AND PRODUCT_ID != ?
        AND ROUTE_ID IS NOT NULL
        AND SESUCICL NOT IN (9000, 4000, 6000)
        """
        
        resultados = pd.read_sql_query(
            query, conn, 
            params=[info_producto['DPTO'], info_producto['MUNICIPIO'], 
                    info_producto['LOCALIDAD'], product_id_buscar])
        resultados = corrige_utf8(resultados)
        
        if resultados.empty:
            return {
                "error": "No se encontraron productos en la misma localidad",
                "encontrado": True,
                "recomendacion": None
            }
        
        # Filtrar por dirección equivalente (versión rápida)
        resultados["es_misma_direccion"] = resultados["DIRECCION"].apply(
            lambda d: son_direcciones_equivalentes_rapido(direccion_original, d))
        
        candidatos_misma_calle = resultados[resultados["es_misma_direccion"] == True].copy()
        
        if candidatos_misma_calle.empty:
            return {
                "error": "No se encontraron candidatos en la misma dirección",
                "encontrado": True,
                "recomendacion": None
            }
        
        # Calcular métricas (con versiones cacheadas)
        candidatos_misma_calle["numero_puerta"] = candidatos_misma_calle["DIRECCION"].apply(obtener_numero_puerta_cached)
        candidatos_misma_calle["paridad"] = candidatos_misma_calle["DIRECCION"].apply(obtener_paridad_puerta_cached)
        
        # Calcular diferencia de puerta de forma eficiente
        if numero_puerta_original:
            candidatos_misma_calle["diferencia_puerta"] = candidatos_misma_calle["numero_puerta"].apply(
                lambda np: abs(np - numero_puerta_original) if np else None)
        else:
            candidatos_misma_calle["diferencia_puerta"] = None
        
        # Filtrar por paridad
        if paridad_original:
            candidatos_misma_calle = candidatos_misma_calle[
                candidatos_misma_calle["paridad"] == paridad_original].copy()
        
        # Filtrar candidatos válidos
        candidatos_validos = candidatos_misma_calle[
            candidatos_misma_calle["diferencia_puerta"].notna()].copy()
        
        if candidatos_validos.empty:
            return {
                "error": "No se encontraron candidatos válidos",
                "encontrado": True,
                "recomendacion": None
            }
        
        # Buscar el vecino más cercano
        candidato_mas_cercano = candidatos_validos.nsmallest(1, "diferencia_puerta").iloc[0]
        
        # Calcular secuencia sugerida
        secuencia_sugerida = None
        secuencia_vecino = formato_valor_numerico(candidato_mas_cercano['CONSECUTIVE'])
        numero_puerta_vecino = candidato_mas_cercano['numero_puerta']
        
        if secuencia_vecino is not None and numero_puerta_original and numero_puerta_vecino:
            if numero_puerta_vecino < numero_puerta_original:
                secuencia_sugerida = secuencia_vecino - 1
            elif numero_puerta_vecino > numero_puerta_original:
                secuencia_sugerida = secuencia_vecino + 1
            else:
                secuencia_sugerida = secuencia_vecino + 1
        
        recomendacion = {
            "DIRECCION": candidato_mas_cercano['DIRECCION'],
            "ROUTE_ID": formato_valor_numerico(candidato_mas_cercano['ROUTE_ID']),
            "ITINERARIO": formato_valor_numerico(candidato_mas_cercano['ROUTE_ITINERARY_ID']),
            "SECUENCIA": secuencia_vecino,
            "SECUENCIA_SUGERIDA": secuencia_sugerida,
            "CICLO": formato_valor_numerico(candidato_mas_cercano['SESUCICL']),
            "diferencia_puerta": int(candidato_mas_cercano['diferencia_puerta']) if pd.notna(candidato_mas_cercano['diferencia_puerta']) else None
        }
        
        tiempo_total = time.time() - tiempo_inicio
        if tiempo_total > 2.0:  # Solo logear si toma más de 2 segundos
            print(f"[PERF] PRODUCT_ID {product_id_buscar} procesado en {tiempo_total:.2f}s")
        
        return {
            "encontrado": True,
            "recomendacion": recomendacion,
            "candidatos": [],  # No necesitamos la lista completa para masivo
            "itinerarios_info": {"total_unicos": 0}  # Simplificado
        }
        
    except Exception as e:
        return {
            "error": f"Error al procesar: {str(e)}",
            "encontrado": False,
            "recomendacion": None
        }

@app.route('/buscar-masivo')
def buscar_masivo_page():
    """Página de búsqueda masiva (Excel)"""
    return render_template('buscar_masivo.html')

@app.route('/api/procesar-masivo', methods=['POST'])
def procesar_masivo():
    """
    Inicia el procesamiento masivo en background y retorna un ID de sesión
    """
    try:
        # Verificar que se haya subido un archivo
        if 'file' not in request.files:
            return jsonify({"error": "No se ha subido ningún archivo"}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({"error": "Nombre de archivo vacío"}), 400
        
        # Verificar extensión
        if not file.filename.lower().endswith(('.xlsx', '.xls')):
            return jsonify({"error": "El archivo debe ser Excel (.xlsx o .xls)"}), 400
        
        # Leer el archivo Excel
        try:
            df_input = pd.read_excel(file)
        except Exception as e:
            return jsonify({"error": f"Error al leer el archivo Excel: {str(e)}"}), 400
        
        # Verificar que exista la columna PRODUCT_ID
        if 'PRODUCT_ID' not in df_input.columns:
            return jsonify({"error": "El archivo debe contener una columna llamada 'PRODUCT_ID'"}), 400
        
        # Generar ID de sesión único
        session_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        
        # Inicializar estado
        with procesamiento_masivo_lock:
            procesamiento_masivo_estado[session_id] = {
                'status': 'iniciando',
                'procesados': 0,
                'total': len(df_input),
                'cancelado': False,
                'completado': False,
                'error': None,
                'filename': None
            }
            print(f"[INICIO] Sesión {session_id} creada. Total productos: {len(df_input)}")
            print(f"[INICIO] Sesiones activas: {list(procesamiento_masivo_estado.keys())}")
        
        # Iniciar procesamiento en thread separado
        thread = threading.Thread(
            target=procesar_masivo_background,
            args=(session_id, df_input)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "total_productos": len(df_input)
        })
    
    except Exception as e:
        return jsonify({
            "error": f"Error al iniciar procesamiento: {str(e)}",
            "success": False
        }), 500

def obtener_secuencias_existentes(route_id, itinerario, conn):
    """
    Obtiene todas las secuencias ya existentes en la BD para un itinerario.
    Esto evita conflictos con productos ya enrutados.
    """
    try:
        cursor = conn.cursor()
        query = """
            SELECT DISTINCT CAST(CONSECUTIVE AS INTEGER) as SEC
            FROM PRODUCT_DATA
            WHERE ROUTE_ID = ? 
              AND ROUTE_ITINERARY_ID = ?
              AND CONSECUTIVE IS NOT NULL
              AND CONSECUTIVE != ''
              AND CONSECUTIVE != 'None'
        """
        cursor.execute(query, (route_id, itinerario))
        resultados = cursor.fetchall()
        return [r[0] for r in resultados if r[0] is not None]
    except Exception as e:
        print(f"[ERROR] obtener_secuencias_existentes: {e}")
        return []

def resolver_conflicto_secuencia(route_id, itinerario, secuencia_vecino, 
                                  secuencia_sugerida_inicial, secuencias_ocupadas, conn):
    """
    Resuelve conflictos de secuencia duplicada en procesamiento masivo.
    
    Parámetros:
    - route_id: ROUTE_ID del itinerario
    - itinerario: ROUTE_ITINERARY_ID
    - secuencia_vecino: Secuencia original del vecino
    - secuencia_sugerida_inicial: Secuencia inicialmente calculada (vecino ±1)
    - secuencias_ocupadas: Dict {(route_id, itinerario): set(secuencias)}
    - conn: Conexión a la BD
    
    Retorna:
    - Secuencia final sin conflictos
    """
    # Si algún valor es None o vacío, retornar el inicial
    if not route_id or not itinerario or secuencia_sugerida_inicial == '':
        return secuencia_sugerida_inicial
    
    try:
        route_id = int(route_id) if route_id else None
        itinerario = int(itinerario) if itinerario else None
        secuencia_vecino = int(secuencia_vecino) if secuencia_vecino else None
        secuencia_inicial = int(secuencia_sugerida_inicial) if secuencia_sugerida_inicial else None
        
        if route_id is None or itinerario is None or secuencia_inicial is None:
            return secuencia_sugerida_inicial
        
    except (ValueError, TypeError):
        return secuencia_sugerida_inicial
    
    # Clave para el diccionario
    clave_itinerario = (route_id, itinerario)
    
    # Inicializar set si no existe
    if clave_itinerario not in secuencias_ocupadas:
        # Obtener secuencias ya existentes en la BD para este itinerario
        secuencias_existentes = obtener_secuencias_existentes(route_id, itinerario, conn)
        secuencias_ocupadas[clave_itinerario] = set(secuencias_existentes)
    
    # Obtener set de secuencias ocupadas
    ocupadas = secuencias_ocupadas[clave_itinerario]
    
    # Si no hay conflicto, usar la secuencia inicial
    if secuencia_inicial not in ocupadas:
        ocupadas.add(secuencia_inicial)
        return secuencia_inicial
    
    # 🔥 HAY CONFLICTO - Buscar siguiente disponible
    # Determinar dirección: ¿estamos sumando o restando?
    direccion = 1 if secuencia_inicial > secuencia_vecino else -1
    
    # Buscar siguiente secuencia libre
    secuencia_candidata = secuencia_inicial
    intentos = 0
    max_intentos = 10000  # Máximo 10000 intentos
    
    while secuencia_candidata in ocupadas and intentos < max_intentos:
        secuencia_candidata += direccion
        intentos += 1
        
        # Verificar límites relativos (no absolutos)
        if secuencia_candidata <= 0:
            # Llegamos a 0, cambiar a sumar
            direccion = 1
            secuencia_candidata = secuencia_inicial + 1
        elif abs(secuencia_candidata - secuencia_inicial) > 50000:
            # Nos alejamos demasiado (más de 50000 posiciones)
            print(f"[WARN] No se encontró secuencia libre cerca de {secuencia_inicial} para Route {route_id}, Itinerario {itinerario}")
            # Usar la secuencia candidata actual aunque esté lejos
            break
    
    # Verificar si realmente encontramos una secuencia libre
    if secuencia_candidata in ocupadas:
        # Si después de todos los intentos aún está ocupada, forzar una secuencia única
        print(f"[ERROR] No se pudo encontrar secuencia libre para Route {route_id}, Itinerario {itinerario}. Forzando secuencia.")
        # Buscar el máximo y agregar 1
        secuencia_candidata = max(ocupadas) + 1 if ocupadas else secuencia_inicial
    
    # Marcar como ocupada y retornar
    ocupadas.add(secuencia_candidata)
    
    # Log si hubo ajuste significativo
    if abs(secuencia_candidata - secuencia_inicial) > 1:
        print(f"[SECUENCIA] Ajuste: {secuencia_inicial} → {secuencia_candidata} "
              f"(Route {route_id}, Itinerario {itinerario})")
    
    return secuencia_candidata

def procesar_masivo_background(session_id, df_input):
    """
    Procesa el archivo en background con actualizaciones de progreso
    """
    print(f"[BACKGROUND] Thread iniciado para sesión {session_id}")
    config = setup_database()
    conn = None
    
    try:
        # Abrir conexión
        conn = sqlite3.connect(config["ruta"])
        print(f"[BACKGROUND] Conexión a BD establecida para sesión {session_id}")
        
        resultados = []
        total_productos = len(df_input)
        
        # 🔑 NUEVO: Diccionario para rastrear secuencias usadas por itinerario
        # Estructura: {(ROUTE_ID, ROUTE_ITINERARY_ID): set(secuencias_usadas)}
        secuencias_ocupadas = {}
        
        # Actualizar estado
        with procesamiento_masivo_lock:
            if session_id not in procesamiento_masivo_estado:
                print(f"[BACKGROUND ERROR] Sesión {session_id} desapareció antes de iniciar procesamiento!")
                return
            procesamiento_masivo_estado[session_id]['status'] = 'procesando'
            print(f"[BACKGROUND] Estado cambiado a 'procesando' para sesión {session_id}")
        
        # Variables de métricas
        tiempo_inicio_procesamiento = time.time()
        tiempo_total_busquedas = 0
        
        # Procesar cada producto
        for idx, row in df_input.iterrows():
            # Verificar si fue cancelado
            with procesamiento_masivo_lock:
                if procesamiento_masivo_estado[session_id]['cancelado']:
                    procesamiento_masivo_estado[session_id]['status'] = 'cancelado'
                    return
            
            product_id = row['PRODUCT_ID']
            tiempo_inicio_producto = time.time()
            
            # Buscar candidatos
            resultado_busqueda = buscar_candidatos_rapido(str(product_id), conn)
            tiempo_total_busquedas += (time.time() - tiempo_inicio_producto)
            
            # Preparar fila de resultado - SOLO con datos originales + recomendación
            fila_resultado = {}
            
            # Copiar TODAS las columnas del Excel original
            for columna in df_input.columns:
                fila_resultado[columna] = row[columna]
            
            # Agregar columnas de resultado (del vecino más cercano)
            if resultado_busqueda.get('encontrado') and resultado_busqueda.get('recomendacion'):
                rec = resultado_busqueda['recomendacion']
                
                # Obtener valores básicos
                route_id = rec.get('ROUTE_ID', '')
                itinerario = rec.get('ITINERARIO', '')
                secuencia = rec.get('SECUENCIA', '')
                secuencia_sugerida_inicial = rec.get('SECUENCIA_SUGERIDA', '')
                
                # Debug: Log si los valores están vacíos o None
                if not route_id or not itinerario:
                    print(f"[DEBUG] PRODUCT_ID {product_id}: ROUTE_ID={route_id}, ITINERARIO={itinerario}")
                    print(f"[DEBUG] Recomendación completa: {rec}")
                
                # 🔑 NUEVO: Resolver conflictos de secuencia
                secuencia_final = resolver_conflicto_secuencia(
                    route_id=route_id,
                    itinerario=itinerario,
                    secuencia_vecino=secuencia,
                    secuencia_sugerida_inicial=secuencia_sugerida_inicial,
                    secuencias_ocupadas=secuencias_ocupadas,
                    conn=conn
                )
                
                # Convertir None a cadena vacía para Excel
                # IMPORTANTE: Usar nombres diferentes para no sobrescribir las columnas originales
                fila_resultado.update({
                    'ROUTE_ID_VECINO': str(route_id) if route_id is not None else '',
                    'ROUTE_ITINERARY_ID_VECINO': str(itinerario) if itinerario is not None else '',
                    'SECUENCIA_VECINO': str(secuencia) if secuencia is not None else '',
                    'SECUENCIA_SUGERIDA': str(secuencia_final) if secuencia_final is not None else '',
                    'OBSERVACION': 'ENCONTRADO'
                })
            else:
                error_msg = resultado_busqueda.get('error', 'No se encontraron candidatos')
                fila_resultado.update({
                    'ROUTE_ID_VECINO': '',
                    'ROUTE_ITINERARY_ID_VECINO': '',
                    'SECUENCIA_VECINO': '',
                    'SECUENCIA_SUGERIDA': '',
                    'OBSERVACION': error_msg
                })
            
            resultados.append(fila_resultado)
            
            # Actualizar progreso y mostrar estadísticas cada 50 productos
            with procesamiento_masivo_lock:
                procesamiento_masivo_estado[session_id]['procesados'] = idx + 1
                
                # Log detallado cada 50 productos
                if (idx + 1) % 50 == 0:
                    tiempo_transcurrido = time.time() - tiempo_inicio_procesamiento
                    promedio_por_producto = tiempo_total_busquedas / (idx + 1)
                    productos_restantes = total_productos - (idx + 1)
                    tiempo_estimado_restante = promedio_por_producto * productos_restantes
                    
                    print(f"[{session_id}] Progreso: {idx + 1}/{total_productos} ({((idx + 1)/total_productos*100):.1f}%)")
                    print(f"[{session_id}] Tiempo promedio: {promedio_por_producto:.2f}s/producto")
                    print(f"[{session_id}] Tiempo estimado restante: {tiempo_estimado_restante/60:.1f} minutos")
                elif (idx + 1) % 10 == 0:
                    print(f"[{session_id}] Procesado {idx + 1}/{total_productos}")
        
        # Métricas finales
        tiempo_total_procesamiento = time.time() - tiempo_inicio_procesamiento
        promedio_final = tiempo_total_busquedas / total_productos if total_productos > 0 else 0
        
        # Calcular estadísticas de secuencias
        total_itinerarios_unicos = len(secuencias_ocupadas)
        total_secuencias_asignadas = sum(len(secuencias) for secuencias in secuencias_ocupadas.values())
        
        print(f"[{session_id}] ============ MÉTRICAS FINALES ============")
        print(f"[{session_id}] Total productos: {total_productos}")
        print(f"[{session_id}] Tiempo total: {tiempo_total_procesamiento/60:.2f} minutos")
        print(f"[{session_id}] Promedio por producto: {promedio_final:.2f}s")
        print(f"[{session_id}] Itinerarios únicos procesados: {total_itinerarios_unicos}")
        print(f"[{session_id}] Secuencias asignadas (incluye ajustes): {total_secuencias_asignadas}")
        print(f"[{session_id}] ==========================================")
        
        # Crear DataFrame con resultados
        df_resultado = pd.DataFrame(resultados)
        
        # 🔍 VERIFICACIÓN DE DUPLICADOS
        # Filtrar solo los productos con vecinos encontrados
        df_encontrados = df_resultado[df_resultado['OBSERVACION'] == 'ENCONTRADO'].copy()
        
        if not df_encontrados.empty:
            # Verificar duplicados por cada itinerario
            duplicados_encontrados = False
            for (route_id, itinerario), grupo in df_encontrados.groupby(['ROUTE_ID_VECINO', 'ROUTE_ITINERARY_ID_VECINO']):
                secuencias = grupo['SECUENCIA_SUGERIDA'].tolist()
                secuencias_unicas = set(secuencias)
                
                if len(secuencias) != len(secuencias_unicas):
                    duplicados_encontrados = True
                    duplicados = [s for s in secuencias if secuencias.count(s) > 1]
                    print(f"[ERROR] Duplicados detectados en Route {route_id}, Itinerario {itinerario}:")
                    print(f"        Secuencias duplicadas: {set(duplicados)}")
                    print(f"        Total productos en este itinerario: {len(secuencias)}")
                    print(f"        Secuencias únicas: {len(secuencias_unicas)}")
            
            if not duplicados_encontrados:
                print(f"[{session_id}] ✅ No se detectaron secuencias duplicadas")
            else:
                print(f"[{session_id}] ⚠️  Se detectaron secuencias duplicadas (ver logs arriba)")
        
        # Generar nombre de archivo
        output_filename = f'resultados_masivos_{session_id}.xlsx'
        output_path = os.path.join('/tmp', output_filename)
        
        # Guardar archivo Excel
        df_resultado.to_excel(output_path, index=False, engine='openpyxl')
        
        # Actualizar estado final
        with procesamiento_masivo_lock:
            procesamiento_masivo_estado[session_id]['status'] = 'completado'
            procesamiento_masivo_estado[session_id]['completado'] = True
            procesamiento_masivo_estado[session_id]['filename'] = output_filename
        
        print(f"[{session_id}] Procesamiento completado: {total_productos} productos")
        
    except Exception as e:
        error_message = f"Error en el procesamiento de fondo: {str(e)}"
        print(f"[{session_id}] {error_message}")
        import traceback
        traceback.print_exc()  # Imprimir el traceback completo para depuración
        with procesamiento_masivo_lock:
            if session_id in procesamiento_masivo_estado:
                procesamiento_masivo_estado[session_id]['status'] = 'error'
                procesamiento_masivo_estado[session_id]['error'] = error_message
            else:
                print(f"[{session_id}] No se pudo actualizar el estado a 'error' porque la sesión ya no existe.")
    
    finally:
        if conn:
            conn.close()

@app.route('/api/progreso-masivo/<session_id>')
def progreso_masivo(session_id):
    """
    Retorna el progreso actual del procesamiento
    """
    with procesamiento_masivo_lock:
        if session_id not in procesamiento_masivo_estado:
            print(f"[PROGRESO] Sesión {session_id} NO encontrada. Sesiones activas: {list(procesamiento_masivo_estado.keys())}")
            return jsonify({"error": "Sesión no encontrada"}), 404
        
        estado = procesamiento_masivo_estado[session_id].copy()
        print(f"[PROGRESO] Sesión {session_id}: {estado['procesados']}/{estado['total']} - Status: {estado['status']}")
    
    return jsonify(estado)

@app.route('/api/cancelar-masivo/<session_id>', methods=['POST'])
def cancelar_masivo(session_id):
    """
    Cancela el procesamiento masivo
    """
    with procesamiento_masivo_lock:
        if session_id not in procesamiento_masivo_estado:
            return jsonify({"error": "Sesión no encontrada"}), 404
        
        procesamiento_masivo_estado[session_id]['cancelado'] = True
    
    return jsonify({"success": True, "mensaje": "Cancelación solicitada"})

@app.route('/descargar-resultado/<filename>')
def descargar_resultado(filename):
    """
    Descarga el archivo de resultados generado
    """
    try:
        # Validar filename para seguridad
        if not filename.startswith('resultados_masivos_') or not filename.endswith('.xlsx'):
            return jsonify({"error": "Nombre de archivo inválido"}), 400
        
        filepath = os.path.join('/tmp', filename)
        
        if not os.path.exists(filepath):
            return jsonify({"error": "Archivo no encontrado"}), 404
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    
    except Exception as e:
        return jsonify({"error": f"Error al descargar archivo: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

