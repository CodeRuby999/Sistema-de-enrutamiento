# 🚀 Guía de Despliegue en PythonAnywhere

Esta guía te ayudará a desplegar la aplicación **Sistema de Enrutamiento** en PythonAnywhere de forma gratuita.

---

## 📋 Pre-requisitos

- [ ] Cuenta gratuita en [PythonAnywhere](https://www.pythonanywhere.com)
- [ ] Código del proyecto en un repositorio Git (GitHub, GitLab, etc.)
- [ ] Archivo `mi_base_datos.sqlite` disponible

---

## 🎯 Paso 1: Crear Cuenta en PythonAnywhere

1. Ve a https://www.pythonanywhere.com
2. Click en **"Start running Python online in less than a minute!"**
3. Crea una cuenta gratuita (Beginner account)
4. Confirma tu correo electrónico

**Plan Gratuito incluye:**
- ✅ 512 MB de espacio en disco
- ✅ 1 aplicación web
- ✅ Python 3.10
- ✅ Dominio: `tu-usuario.pythonanywhere.com`
- ✅ Siempre activa (no se duerme como Heroku/Render)

---

## 📂 Paso 2: Subir el Código

### Opción A: Clonar desde Git (Recomendado)

1. En PythonAnywhere, ve a la pestaña **"Consoles"**
2. Click en **"Bash"** para abrir una consola
3. Ejecuta los siguientes comandos:

```bash
# Clonar el repositorio
git clone https://github.com/TU-USUARIO/TU-REPOSITORIO.git

# Navegar al directorio
cd Buscar-direcciones

# Verificar que los archivos estén ahí
ls -la
```

### Opción B: Subir archivos manualmente

1. Ve a la pestaña **"Files"**
2. Crea una carpeta `Buscar-direcciones`
3. Sube estos archivos:
   - `app.py`
   - `wsgi.py`
   - `requirements.txt`
   - Carpeta `templates/` con `index.html`

---

## 🗄️ Paso 3: Subir la Base de Datos

### Opción A: Desde tu computadora

1. Ve a **"Files"** en PythonAnywhere
2. Navega a `/home/tu-usuario/Buscar-direcciones/`
3. Click en **"Upload a file"**
4. Selecciona `mi_base_datos.sqlite`

### Opción B: Desde la consola (si está en otro servidor)

```bash
cd ~/Buscar-direcciones
wget URL_DE_TU_BASE_DE_DATOS
# o usa scp, rsync, etc.
```

---

## 📦 Paso 4: Instalar Dependencias

En la consola Bash de PythonAnywhere:

```bash
cd ~/Buscar-direcciones

# Instalar dependencias
pip3.10 install --user -r requirements.txt

# Verificar instalación
pip3.10 list | grep -E "Flask|pandas"
```

Deberías ver:
```
Flask           3.0.0
pandas          2.1.0
```

---

## 🌐 Paso 5: Crear Web App

1. Ve a la pestaña **"Web"**
2. Click en **"Add a new web app"**
3. Click **"Next"** (acepta el dominio gratuito)
4. Selecciona **"Manual configuration"** (NO Flask)
5. Selecciona **Python 3.10**
6. Click **"Next"**

Tu aplicación ahora está en: `https://tu-usuario.pythonanywhere.com`

---

## ⚙️ Paso 6: Configurar WSGI

1. En la pestaña **"Web"**, busca la sección **"Code"**
2. Click en el enlace del archivo WSGI:
   ```
   /var/www/tu-usuario_pythonanywhere_com_wsgi.py
   ```
3. **BORRA TODO** el contenido del archivo
4. Pega el siguiente código (reemplaza `TU-USUARIO` con tu usuario real):

```python
import sys
import os

# ===== IMPORTANTE: REEMPLAZA 'TU-USUARIO' CON TU USUARIO REAL =====
project_home = '/home/TU-USUARIO/Buscar-direcciones'

# Agregar el directorio del proyecto al Python path
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Importar la aplicación Flask
from app import app as application

# Configuración para producción
application.debug = False
```

5. Click en **"Save"** (arriba a la derecha)

---

## 🔄 Paso 7: Recargar la Aplicación

1. Vuelve a la pestaña **"Web"**
2. Scroll hasta arriba
3. Click en el botón verde grande: **"Reload tu-usuario.pythonanywhere.com"**

---

## ✅ Paso 8: Verificar que Funciona

1. Abre tu navegador
2. Ve a: `https://tu-usuario.pythonanywhere.com`
3. Deberías ver la interfaz del Sistema de Enrutamiento
4. Prueba buscar un PRODUCT_ID

---

## 🐛 Solución de Problemas

### Error: "Something went wrong :("

**Ver logs de error:**
1. En la pestaña **"Web"**, busca **"Log files"**
2. Click en **"Error log"**
3. Lee el último error

**Errores comunes:**

#### 1. `ModuleNotFoundError: No module named 'app'`
**Solución:** Verifica que el path en el archivo WSGI sea correcto:
```bash
# En la consola Bash
pwd
# Debe mostrar: /home/tu-usuario/Buscar-direcciones
```

#### 2. `ModuleNotFoundError: No module named 'flask'` o `'pandas'`
**Solución:** Reinstala las dependencias:
```bash
cd ~/Buscar-direcciones
pip3.10 install --user -r requirements.txt
```

#### 3. Base de datos no encontrada
**Solución:** Verifica que el archivo exista:
```bash
cd ~/Buscar-direcciones
ls -lh mi_base_datos.sqlite
```

#### 4. Error de permisos en la base de datos
**Solución:** Verifica permisos:
```bash
chmod 644 mi_base_datos.sqlite
```

---

## 🔧 Mantenimiento y Actualizaciones

### Actualizar el código

```bash
cd ~/Buscar-direcciones
git pull origin main

# Recargar la aplicación desde la pestaña "Web"
```

### Ver logs en tiempo real

```bash
# En la consola Bash
tail -f /var/log/tu-usuario.pythonanywhere.com.error.log
```

### Reiniciar la aplicación

En la pestaña **"Web"**, click en **"Reload"**

---

## 📊 Limitaciones del Plan Gratuito

| Característica | Plan Free |
|----------------|-----------|
| Aplicaciones web | 1 |
| Espacio en disco | 512 MB |
| CPU por día | Limitado |
| Dominio personalizado | ❌ No |
| HTTPS | ✅ Sí (en .pythonanywhere.com) |
| Siempre activa | ✅ Sí |
| Acceso SSH | ✅ Sí (consola Bash) |

---

## 🎉 ¡Listo!

Tu aplicación ahora está desplegada en:
```
https://tu-usuario.pythonanywhere.com
```

---

## 📞 Soporte

- **Documentación oficial:** https://help.pythonanywhere.com/
- **Foros:** https://www.pythonanywhere.com/forums/
- **Email:** support@pythonanywhere.com

---

## 🚀 Mejoras Futuras

Para mejorar el rendimiento o capacidades:

1. **Upgrade a plan pago** ($5/mes):
   - Más CPU
   - Más espacio
   - Dominio personalizado

2. **Optimizaciones:**
   - Agregar caché con Flask-Caching
   - Comprimir respuestas con gzip
   - Indexar la base de datos SQLite

3. **Monitoreo:**
   - Configurar alertas de errores
   - Agregar analytics
   - Logs estructurados

---

**¡Disfruta tu aplicación en producción!** 🎊

