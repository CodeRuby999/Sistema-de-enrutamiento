from flask import Flask, render_template, request, jsonify
import sqlite3
import pandas as pd
import re

app = Flask(__name__)

# ============== CONFIGURACIÓN ==============
# (Sin variables de configuración - la lógica busca solo vecinos inmediatos)

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
    direccion = str(direccion).strip().upper()
    # Extraer números (permite números pegados a letras como 19A)
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
    
    # Extraer vía principal, vía secundaria y número de puerta
    via_principal = None
    via_principal_letra = None
    numero_puerta = None
    
    if es_interseccion:
        # Es una intersección: CR 19 CL 126 - 10 o CL 123 CR 19 B - 11 o CR 19A CL 123
        if len(numeros) >= 1:
            via_principal = numeros[0]  # 19 o 123
            # Buscar letras después del primer número (con o sin espacio): 19A, 19EESTE, etc
            patron_letra_1 = rf'\b{via_principal}\s*([A-Z]+)(?:\s|$|[^A-Z0-9])'
            match_letra_1 = re.search(patron_letra_1, direccion)
            if match_letra_1:
                via_principal_letra = match_letra_1.group(1)
        
        if len(numeros) >= 2:
            via_secundaria = numeros[1]  # 126 o 19
            # Buscar letras después del segundo número (con o sin espacio): 19A, 3ABIS, etc
            patron_letra_2 = rf'\b{via_secundaria}\s*([A-Z]+)(?:\s|$|[^A-Z0-9])'
            match_letra_2 = re.search(patron_letra_2, direccion)
            if match_letra_2:
                via_secundaria_letra = match_letra_2.group(1)
        
        if len(numeros) >= 3:
            numero_puerta = numeros[2]  # 10 o 11
    else:
        # Es una dirección simple: CL 45 # 23-67 o CL 45 A # 23-67 o CL 45A # 23-67
        if len(numeros) >= 1:
            via_principal = numeros[0]
            # Buscar letras después del número principal (con o sin espacio): 45A, 45BIS, etc
            patron_letra = rf'\b{via_principal}\s*([A-Z]+)(?:\s|$|[^A-Z0-9])'
            match_letra = re.search(patron_letra, direccion)
            if match_letra:
                via_principal_letra = match_letra.group(1)
        
        if len(numeros) >= 3:
            numero_puerta = numeros[2]
    
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
        AND SESUCICL != 9000
        AND SESUCICL != 4000
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
                "error": "No se encontraron productos en la misma localidad con ROUTE_ID válido",
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
        
        # Ordenar por diferencia de puerta (más cercano primero)
        if not candidatos_finales.empty:
            candidatos_finales = candidatos_finales.sort_values("diferencia_puerta", na_position='last')
        
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
                "tipo_candidato": tipo_candidato
            })
        
        # Recomendación: seleccionar el candidato más cercano (menor diferencia_puerta)
        recomendacion = None
        if candidatos_list:
            # Buscar el candidato con menor diferencia de puerta
            candidato_rec = min(candidatos_list, key=lambda x: x["diferencia_puerta"] if x["diferencia_puerta"] is not None else float('inf'))
            recomendacion = {
                "DIRECCION": candidato_rec["DIRECCION"],
                "ROUTE_ID": candidato_rec["ROUTE_ID"],
                "ITINERARIO": candidato_rec["ITINERARIO"],
                "SECUENCIA": candidato_rec["SECUENCIA"],
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
    return render_template('index.html')

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

