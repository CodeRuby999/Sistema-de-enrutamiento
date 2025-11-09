"""
WSGI configuration for PythonAnywhere deployment
Este archivo es necesario para que PythonAnywhere pueda ejecutar la aplicación Flask
"""
import sys
import os

# ===== CONFIGURACIÓN PARA PYTHONANYWHERE =====
# IMPORTANTE: Reemplaza 'TU-USUARIO' con tu nombre de usuario de PythonAnywhere
project_home = '/home/CodeRuby/Sistema-de-enrutamiento'

# Agregar el directorio del proyecto al Python path
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Importar la aplicación Flask
from app import app as application  

# Configuración para producción
application.debug = False

# Para usar este archivo en PythonAnywhere:
# 1. Ve a la pestaña "Web" en PythonAnywhere
# 2. En la sección "Code", haz click en tu archivo WSGI
# 3. Copia el contenido de este archivo allí
# 4. Asegúrate de reemplazar 'TU-USUARIO' con tu usuario real de PythonAnywhere

