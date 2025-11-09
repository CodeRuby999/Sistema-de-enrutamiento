# 🚀 Guía de Despliegue en Render

## 📋 Prerequisitos

- Cuenta en [Render](https://render.com) (gratis)
- Cuenta en GitHub
- Tu base de datos `mi_base_datos.sqlite` (523MB)

## 🔧 Pasos para Desplegar

### 1. Subir el proyecto a GitHub

```bash
# Si aún no has conectado con GitHub
git remote add origin https://github.com/TU-USUARIO/TU-REPOSITORIO.git
git push -u origin main
```

### 2. Configurar en Render

1. **Ir a [Render Dashboard](https://dashboard.render.com)**
2. **Clic en "New +"** → **"Web Service"**
3. **Conectar tu repositorio de GitHub**
4. **Configurar el servicio:**
   - **Name:** `sistema-enrutamiento` (o el que prefieras)
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Plan:** Free (gratis)

5. **Clic en "Create Web Service"**

### 3. ⚠️ IMPORTANTE: Subir la Base de Datos

Como la base de datos pesa 523MB (demasiado para GitHub), tienes 2 opciones:

#### **Opción A: Subir manualmente vía Render Shell (Recomendado)**

1. Una vez desplegado, ve a tu servicio en Render
2. Clic en **"Shell"** en el menú lateral
3. Ejecuta:
   ```bash
   # Esto abrirá un shell en tu servicio
   # Sube tu archivo .sqlite usando el método de tu preferencia
   ```

#### **Opción B: Usar Render Disks (Plan de pago)**

Render Disks te permite tener almacenamiento persistente, pero requiere un plan de pago.

#### **Opción C: Usar una base de datos PostgreSQL en Render**

Si quieres migrar de SQLite a PostgreSQL:
1. En Render, crea una nueva base de datos PostgreSQL (gratis)
2. Migra tus datos de SQLite a PostgreSQL
3. Actualiza `app.py` para usar PostgreSQL en lugar de SQLite

### 4. Variables de Entorno (Opcional)

Si necesitas configurar variables:
1. En tu servicio de Render, ve a **"Environment"**
2. Agrega las variables necesarias

## 📝 Notas Importantes

### Limitaciones del Plan Free:
- ⏰ El servicio se "duerme" después de 15 minutos sin uso
- 🐌 Tarda ~30 segundos en despertar
- 💾 No tiene almacenamiento persistente (los archivos se pierden al redeploy)

### ⚠️ Problema con SQLite en Plan Free:
Cada vez que Render redeploy tu app, **perderás la base de datos** porque el sistema de archivos no es persistente.

**Soluciones:**
1. **Usar Render Disks** (requiere plan de pago $7/mes mínimo)
2. **Migrar a PostgreSQL** (incluido en plan Free)
3. **Resubir la BD manualmente** cada vez que redeploys

## 🔄 Alternativa: Migrar a PostgreSQL (Recomendado)

Si decides usar PostgreSQL (gratis en Render):

1. **Crear BD PostgreSQL en Render**
2. **Migrar datos:**
   ```bash
   # Exportar de SQLite
   sqlite3 mi_base_datos.sqlite .dump > dump.sql
   
   # Importar a PostgreSQL (con ajustes)
   psql -h [RENDER_DB_HOST] -U [USER] -d [DATABASE] -f dump.sql
   ```

3. **Actualizar app.py:**
   ```python
   # Cambiar de sqlite3 a psycopg2
   import psycopg2
   # ... configurar conexión PostgreSQL
   ```

## 🆘 Problemas Comunes

### Error de build
- Verifica que `requirements.txt` esté correcto
- Revisa los logs en Render

### App no inicia
- Verifica el Start Command: `gunicorn app:app`
- Revisa que Flask esté configurado correctamente

### Base de datos no encontrada
- Asegúrate de haber subido `mi_base_datos.sqlite`
- O migra a PostgreSQL

## 📞 Soporte

Si tienes problemas, revisa:
- [Documentación de Render](https://render.com/docs)
- Logs de tu servicio en Render Dashboard

