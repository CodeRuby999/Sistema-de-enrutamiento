# 🚀 Guía Rápida: Migrar a Neon con el Script Python

## 📋 Pasos para Migrar

### **Paso 1: Configurar DATABASE_URL**

Copia tu connection string de Neon y configúralo:

```bash
export DATABASE_URL="postgresql://neondb_owner:npg_zH9iV0uhYeDA@ep-round-silence-ahwvzp15-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require"
```

### **Paso 2: Instalar dependencia (si no la tienes)**

```bash
pip install psycopg2-binary
```

### **Paso 3: Ejecutar la migración**

```bash
cd /home/timel_ahs/Compartidos/Buscar-direcciones
python3 migrate_to_neon.py
```

### **Paso 4: Confirmar**

El script te preguntará si quieres continuar. Escribe `s` y presiona Enter.

---

## 📊 ¿Qué hace el script?

1. ✅ Se conecta a SQLite y PostgreSQL
2. ✅ Crea la tabla `dbact` en Neon
3. ✅ Migra los datos en lotes de 1,000 registros
4. ✅ Muestra progreso en tiempo real
5. ✅ Verifica que todos los registros se migraron
6. ✅ Muestra estadísticas finales

---

## ⏱️ Tiempo Estimado

- **523 MB de datos** → ~10-20 minutos
- Depende de tu conexión a internet

---

## 🎯 Resultado Esperado

```
🐘 MIGRACIÓN SQLite → PostgreSQL (Neon)
============================================================

📁 Archivo SQLite: mi_base_datos.sqlite
🔗 PostgreSQL: postgresql://neondb_owner:...
📋 Tabla origen: DBACT
📋 Tabla destino: dbact

🔌 Conectando a SQLite...
✅ Conectado a SQLite
🔌 Conectando a PostgreSQL...
✅ Conectado a PostgreSQL

📊 Columnas encontradas: XX
📋 Creando tabla 'dbact' en PostgreSQL...
✅ Tabla 'dbact' creada correctamente

⚠️  Se migrarán XXX,XXX registros
¿Continuar? (s/n): s

📦 Iniciando migración de XXX,XXX registros...
💾 Tamaño de lote: 1,000 registros
⏳ Progreso: XXX,XXX/XXX,XXX (100.0%) - XXX reg/s
✅ Migración completada: XXX,XXX registros en XX.Xs
📊 Promedio: XXX registros/segundo

🔍 Verificando migración...
📊 SQLite: XXX,XXX registros
📊 PostgreSQL: XXX,XXX registros
✅ Verificación exitosa: Todos los registros migrados

🎉 ¡Migración completada exitosamente!
🔌 Conexiones cerradas
```

---

## 🐛 Solución de Problemas

### Error: "No module named 'psycopg2'"
```bash
pip install psycopg2-binary
```

### Error: "DATABASE_URL not set"
Asegúrate de exportar la variable:
```bash
export DATABASE_URL="tu_connection_string"
```

### Error: "could not connect to server"
Verifica que el connection string sea correcto y tengas internet.

---

## ✅ Después de Migrar

1. Verifica que funcionó conectándote a Neon:
```bash
psql "$DATABASE_URL"
# Luego ejecuta:
SELECT COUNT(*) FROM dbact;
\q
```

2. Configura la app para usar PostgreSQL:
```bash
# Crear archivo .env
echo "DATABASE_URL=$DATABASE_URL" > .env
```

3. Prueba la app localmente:
```bash
python app.py
```

4. Despliega en PythonAnywhere con el `DATABASE_URL` configurado.

---

**¡Listo para migrar!** 🎊

