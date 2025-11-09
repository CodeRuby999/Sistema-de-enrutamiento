# 🐘 Guía de Migración a PostgreSQL

Esta guía te ayudará a migrar tu base de datos SQLite a PostgreSQL y desplegar la aplicación en PythonAnywhere.

---

## 📋 Índice

1. [¿Por qué PostgreSQL?](#por-qué-postgresql)
2. [Elegir proveedor de PostgreSQL](#elegir-proveedor)
3. [Migrar datos de SQLite a PostgreSQL](#migrar-datos)
4. [Configurar la aplicación](#configurar-aplicación)
5. [Probar localmente](#probar-localmente)
6. [Desplegar en PythonAnywhere](#desplegar-pythonanywhere)
7. [Solución de problemas](#solución-de-problemas)

---

## 🎯 ¿Por qué PostgreSQL?

### Problema con SQLite:
- ❌ Archivo de 523 MB (muy grande)
- ❌ No cabe en PythonAnywhere Free (512 MB)
- ❌ No funciona bien en serverless/cloud

### Solución con PostgreSQL:
- ✅ Base de datos en la nube (separada de la app)
- ✅ 3-5 GB gratis en proveedores cloud
- ✅ Mejor para producción
- ✅ App en PythonAnywhere Free (sin límite de BD)

---

## 📊 Elegir Proveedor

### Proveedores recomendados:

| Proveedor | Espacio Gratis | Compatibilidad | Recomendado |
|-----------|----------------|----------------|-------------|
| **Neon** | 3 GB | PostgreSQL | ⭐⭐⭐ Sí |
| **PlanetScale** | 5 GB | MySQL | ❌ No (necesitarías más cambios) |
| **Supabase** | 500 MB | PostgreSQL | ❌ No cabe (523 MB) |
| **Railway** | 1 GB | PostgreSQL | ✅ Sí |
| **ElephantSQL** | 20 MB | PostgreSQL | ❌ Muy poco |

### **Recomendación: Neon** ⭐

**Ventajas de Neon:**
- ✅ 3 GB gratis (suficiente para tu BD de 523 MB)
- ✅ PostgreSQL nativo
- ✅ No requiere tarjeta de crédito
- ✅ Fácil de usar
- ✅ SSL/TLS incluido
- ✅ Backups automáticos

**Regístrate aquí:** https://neon.tech

---

## 🔄 Migrar Datos

### Opción 1: Usando pgloader (Recomendado) ⭐

**Paso 1: Instalar pgloader**

```bash
# En Ubuntu/WSL/Debian
sudo apt-get update
sudo apt-get install pgloader

# En macOS con Homebrew
brew install pgloader
```

**Paso 2: Crear proyecto en Neon**

1. Ve a https://neon.tech
2. Crea una cuenta
3. Crea un nuevo proyecto: **"Sistema-Enrutamiento"**
4. Copia el **Connection String**, se verá así:

```
postgresql://usuario:password@ep-xxx-xxx.us-east-2.aws.neon.tech/dbname?sslmode=require
```

**Paso 3: Migrar con pgloader**

```bash
cd /home/timel_ahs/Compartidos/Buscar-direcciones

# Migrar directamente
pgloader mi_base_datos.sqlite "postgresql://usuario:password@host/dbname?sslmode=require"
```

**Esto hará:**
- ✅ Leer SQLite
- ✅ Convertir tipos de datos automáticamente
- ✅ Crear tablas en PostgreSQL
- ✅ Copiar todos los datos
- ⏱️ Tardará 5-20 minutos (por el tamaño)

**Salida esperada:**
```
table name     errors       rows      bytes      total time
-------------  ---------  ---------  ---------  --------------
         dbact          0   XXXXXX    523 MB         15.2s
-------------  ---------  ---------  ---------  --------------
         TOTAL          0   XXXXXX    523 MB         15.2s
```

---

### Opción 2: Usando Python (Alternativa)

Si pgloader no funciona, usa este script Python:

**Crear archivo `migrate_to_postgres.py`:**

```python
import sqlite3
import psycopg2
from psycopg2 import sql
import os

# Configuración
SQLITE_DB = "mi_base_datos.sqlite"
POSTGRES_URL = os.environ.get('DATABASE_URL', 'postgresql://user:pass@host/db')

def migrate():
    # Conectar a ambas bases de datos
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    postgres_conn = psycopg2.connect(POSTGRES_URL)
    
    sqlite_cursor = sqlite_conn.cursor()
    postgres_cursor = postgres_conn.cursor()
    
    print("📊 Obteniendo estructura de la tabla...")
    
    # Obtener info de la tabla
    sqlite_cursor.execute("PRAGMA table_info(DBACT)")
    columns = sqlite_cursor.fetchall()
    
    # Crear tabla en PostgreSQL
    create_table = f"""
    CREATE TABLE IF NOT EXISTS dbact (
        {', '.join([f'"{col[1]}" VARCHAR' for col in columns])}
    )
    """
    postgres_cursor.execute(create_table)
    
    print("📦 Migrando datos...")
    
    # Copiar datos
    sqlite_cursor.execute("SELECT * FROM DBACT")
    batch_size = 1000
    
    while True:
        rows = sqlite_cursor.fetchmany(batch_size)
        if not rows:
            break
            
        insert_query = f"""
        INSERT INTO dbact VALUES ({','.join(['%s'] * len(columns))})
        """
        postgres_cursor.executemany(insert_query, rows)
        postgres_conn.commit()
        print(f"✅ Migrados {len(rows)} registros...")
    
    print("🎉 Migración completada!")
    
    # Cerrar conexiones
    sqlite_conn.close()
    postgres_conn.close()

if __name__ == "__main__":
    migrate()
```

**Ejecutar:**
```bash
export DATABASE_URL="postgresql://user:pass@host/db"
python migrate_to_postgres.py
```

---

## ⚙️ Configurar Aplicación

### Paso 1: Instalar dependencias

```bash
cd /home/timel_ahs/Compartidos/Buscar-direcciones
pip install -r requirements.txt
```

**Las nuevas dependencias son:**
- `psycopg2-binary` - Driver PostgreSQL
- `SQLAlchemy` - ORM/toolkit de BD
- `python-dotenv` - Variables de entorno

### Paso 2: Configurar variables de entorno

**A) Para desarrollo local:**

Crea un archivo `.env` en la raíz del proyecto:

```bash
# Copiar el ejemplo
cp env.example .env

# Editar con tu connection string
nano .env
```

Contenido de `.env`:
```bash
DATABASE_URL=postgresql://usuario:password@host:puerto/database?sslmode=require
```

**B) Para SQLite local (desarrollo):**

Si quieres usar SQLite localmente, simplemente **NO configures** `DATABASE_URL` o deja el archivo `.env` vacío. La app usará SQLite automáticamente.

---

## 🧪 Probar Localmente

```bash
cd /home/timel_ahs/Compartidos/Buscar-direcciones

# Opción 1: Con PostgreSQL
export DATABASE_URL="postgresql://user:pass@host/db"
python app.py

# Opción 2: Con SQLite (sin DATABASE_URL)
python app.py
```

Abre http://localhost:5000 y prueba buscar un PRODUCT_ID.

**Verificar conexión:**
```python
# En Python console
from sqlalchemy import create_engine
import os

DATABASE_URL = "postgresql://user:pass@host/db"
engine = create_engine(DATABASE_URL)

# Probar conexión
with engine.connect() as conn:
    result = conn.execute("SELECT COUNT(*) FROM dbact")
    print(f"Total registros: {result.fetchone()[0]}")
```

---

## 🚀 Desplegar en PythonAnywhere

### Paso 1: Actualizar código

```bash
# En PythonAnywhere Bash console
cd ~/Sistema-de-enrutamiento

# Actualizar desde Git
git pull origin main

# Instalar nuevas dependencias
pip3.10 install --user -r requirements.txt
```

### Paso 2: Configurar variable de entorno

1. Ve a la pestaña **Web** en PythonAnywhere
2. Busca la sección **"Environment variables"**
3. Haz click en **"+ Add a new variable"**
4. Configura:
   - **Name:** `DATABASE_URL`
   - **Value:** `postgresql://usuario:password@ep-xxx.neon.tech/dbname?sslmode=require`
5. Click en **"Save"**

**IMPORTANTE:** Usa el connection string completo que obtuviste de Neon.

### Paso 3: Verificar la conexión

En la consola Bash de PythonAnywhere:

```bash
cd ~/Sistema-de-enrutamiento

# Probar conexión
python3.10 -c "
from sqlalchemy import create_engine
import os

DATABASE_URL = os.environ.get('DATABASE_URL')
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute('SELECT COUNT(*) FROM dbact')
    print(f'✅ Conectado! Registros: {result.fetchone()[0]}')
"
```

### Paso 4: Recargar la aplicación

1. Ve a la pestaña **Web**
2. Click en el botón verde **"Reload"**

### Paso 5: Probar

Abre `https://tu-usuario.pythonanywhere.com` y prueba la búsqueda.

---

## 🐛 Solución de Problemas

### Error: "no such table: dbact"

**Causa:** La tabla en PostgreSQL está en mayúsculas o no existe.

**Solución 1:** Verificar nombre de tabla
```sql
-- En psql o en Neon SQL Editor
\dt  -- Listar todas las tablas

-- Si aparece "DBACT" en mayúsculas
SELECT * FROM "DBACT" LIMIT 1;
```

**Solución 2:** Renombrar a minúsculas (recomendado)
```sql
ALTER TABLE "DBACT" RENAME TO dbact;
```

### Error: "SSL SYSCALL error"

**Causa:** Problema con conexión SSL.

**Solución:** Asegúrate de que tu connection string incluya `?sslmode=require`

```
postgresql://user:pass@host/db?sslmode=require
```

### Error: "relation does not exist"

**Causa:** Los nombres de columnas tienen mayúsculas.

**Solución:** La app ya usa comillas en las columnas:
```python
# El código ya maneja esto:
SELECT * FROM dbact WHERE "PRODUCT_ID" = %s
```

Si persiste, renombra las columnas a minúsculas:
```sql
ALTER TABLE dbact RENAME COLUMN "PRODUCT_ID" TO product_id;
-- Repetir para todas las columnas
```

### Error: "could not connect to server"

**Causa:** Firewall o IP bloqueada.

**Solución:** 
1. Verifica que tu IP esté permitida en Neon
2. PythonAnywhere puede estar bloqueado en el plan Free
3. Prueba con Railway o Render que no tienen restricciones

### La migración es muy lenta

**Normal:** 523 MB pueden tardar 10-30 minutos dependiendo de tu conexión.

**Acelerar:**
```bash
# Usar pgloader con más workers
pgloader --with workers 8 sqlite.db postgresql://...
```

### Error: "password authentication failed"

**Causa:** Credenciales incorrectas.

**Solución:**
1. Regenera la password en Neon
2. Copia el connection string completo
3. Asegúrate de no tener espacios extra

---

## 📊 Comparación de Rendimiento

| Métrica | SQLite Local | PostgreSQL Neon |
|---------|--------------|-----------------|
| Latencia | ~10ms | ~50-100ms |
| Tamaño app | 523 MB | 0 MB (BD externa) |
| Escalabilidad | ❌ Limitada | ✅ Excelente |
| Backups | Manual | Automáticos |
| Concurrencia | ❌ Baja | ✅ Alta |

---

## ✅ Checklist Final

Antes de dar por terminada la migración, verifica:

- [ ] BD migrada completamente a PostgreSQL
- [ ] Conexión local funciona
- [ ] Variable `DATABASE_URL` configurada en PythonAnywhere
- [ ] App desplegada y recargada
- [ ] Búsquedas funcionan correctamente
- [ ] No hay errores en el error log
- [ ] Tiempos de respuesta aceptables

---

## 🎯 Ventajas de la Nueva Arquitectura

✅ **App** → PythonAnywhere Free (0 MB de BD)  
✅ **Base de Datos** → Neon (3 GB gratis)  
✅ **Costo total** → $0/mes  
✅ **Escalabilidad** → Alta  
✅ **Mantenibilidad** → Excelente  

---

## 📞 Recursos Adicionales

- **Documentación Neon:** https://neon.tech/docs
- **pgloader:** https://pgloader.io/
- **SQLAlchemy:** https://www.sqlalchemy.org/
- **PythonAnywhere + PostgreSQL:** https://help.pythonanywhere.com/pages/Postgres/

---

## 🔄 Volver a SQLite (Rollback)

Si necesitas volver a SQLite:

1. Comenta `DATABASE_URL` en `.env` o elimínalo de PythonAnywhere
2. La app usará automáticamente `mi_base_datos.sqlite`
3. Recarga la aplicación

**El código es compatible con ambas bases de datos automáticamente.** 🎉

---

**¡Migración completada!** 🎊

