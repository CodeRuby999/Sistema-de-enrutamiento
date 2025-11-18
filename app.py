from flask import Flask, render_template, request, jsonify
import sqlite3
import pandas as pd
import re
import time
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

app = Flask(__name__)

# ============== CONFIGURACIÓN ==============
# (Sin variables de configuración - la lógica busca solo vecinos inmediatos)

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
                "error": "No se encontraron productos en la misma localidad con ciclo válido (SESUCICL diferente de 9000 y 4000)",
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
                    # Si el vecino está después (número mayor), restar 1 a su secuencia
                    if numero_puerta_vecino > numero_puerta_original:
                        secuencia_sugerida = secuencia_vecino - 1
                    # Si el vecino está antes (número menor), sumar 1 a su secuencia
                    elif numero_puerta_vecino < numero_puerta_original:
                        secuencia_sugerida = secuencia_vecino + 1
                    # Si tienen el mismo número de puerta, analizar el complemento (apto, local, etc.)
                    else:
                        complemento_producto = obtener_numero_complemento(info_producto['DIRECCION'])
                        complemento_vecino = obtener_numero_complemento(candidato_rec["DIRECCION"])
                        
                        if complemento_producto is not None and complemento_vecino is not None:
                            # Si el complemento del vecino es mayor (está después), restar 1
                            if complemento_vecino > complemento_producto:
                                secuencia_sugerida = secuencia_vecino - 1
                            # Si el complemento del vecino es menor (está antes), sumar 1
                            elif complemento_vecino < complemento_producto:
                                secuencia_sugerida = secuencia_vecino + 1
                            # Si son exactamente iguales, usar la misma secuencia (caso muy raro)
                            else:
                                secuencia_sugerida = secuencia_vecino
                        else:
                            # Si no hay complemento para comparar, usar la misma secuencia
                            secuencia_sugerida = secuencia_vecino
            
            recomendacion = {
                "DIRECCION": candidato_rec["DIRECCION"],
                "ROUTE_ID": candidato_rec["ROUTE_ID"],
                "ITINERARIO": candidato_rec["ITINERARIO"],
                "SECUENCIA": candidato_rec["SECUENCIA"],
                "SECUENCIA_SUGERIDA": secuencia_sugerida,
                "CICLO": candidato_rec["CICLO"],
                "diferencia_puerta": candidato_rec["diferencia_puerta"]
            }
        
        # Análisis de itinerarios
        itinerarios_contador = {}
        for candidato in candidatos_list:
            itinerario = candidato["ITINERARIO"]
            if itinerario is not None:
                itinerarios_contador[itinerario] = itinerarios_contador.get(itinerario, 0) + 1
        
        # Preparar información de itinerarios
        itinerarios_unicos = len(itinerarios_contador)
        itinerarios_detalle = [
            {"itinerario": itinerario, "cantidad": cantidad}
            for itinerario, cantidad in sorted(itinerarios_contador.items(), key=lambda x: x[1], reverse=True)
        ]
        
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
                "detalle": itinerarios_detalle
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
        
        return jsonify({
            "success": True,
            "municipios": municipios,
            "localidades": localidades,
            "corregimientos": corregimientos
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
            SELECT PRODUCT_ID, DIRECCION, ROUTE_ID, ITINERARIO, SECUENCIA, CICLO, 
                   SESUCICL, MUNICIPIO, LOCALIDAD, CORREGIMIENTO
            FROM {config["tabla"]}
            WHERE 1=1
            AND SESUCICL NOT IN (9000, 4000)
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

