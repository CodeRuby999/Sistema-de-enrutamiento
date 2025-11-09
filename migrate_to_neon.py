#!/usr/bin/env python3
"""
Script de migración de SQLite a PostgreSQL (Neon)
Migra la tabla DBACT de forma segura y con progreso visible.
"""

import sqlite3
import psycopg2
from psycopg2 import sql
import sys
import os
from datetime import datetime

# ============== CONFIGURACIÓN ==============
SQLITE_DB = "mi_base_datos.sqlite"
POSTGRES_URL = os.environ.get('DATABASE_URL')

if not POSTGRES_URL:
    print("❌ Error: Necesitas configurar la variable DATABASE_URL")
    print("\nEjecuta:")
    print('export DATABASE_URL="postgresql://usuario:password@host/db?sslmode=require"')
    sys.exit(1)

BATCH_SIZE = 1000  # Registros por lote
TABLE_SOURCE = "DBACT"  # Tabla en SQLite
TABLE_TARGET = "dbact"  # Tabla en PostgreSQL (minúsculas)

# ============== FUNCIONES ==============

def get_table_info(sqlite_cursor):
    """Obtiene información de columnas de la tabla SQLite"""
    sqlite_cursor.execute(f"PRAGMA table_info({TABLE_SOURCE})")
    columns = sqlite_cursor.fetchall()
    return columns

def create_postgres_table(pg_cursor, columns):
    """Crea la tabla en PostgreSQL si no existe"""
    print(f"📋 Creando tabla '{TABLE_TARGET}' en PostgreSQL...")
    
    # Mapeo de tipos SQLite → PostgreSQL
    type_mapping = {
        'INTEGER': 'INTEGER',
        'TEXT': 'TEXT',
        'REAL': 'REAL',
        'BLOB': 'BYTEA',
        'NUMERIC': 'NUMERIC',
        'VARCHAR': 'VARCHAR',
    }
    
    # Construir definición de columnas
    column_defs = []
    for col in columns:
        col_name = col[1]  # Nombre de columna
        col_type = col[2].upper()  # Tipo de dato
        
        # Mapear tipo
        pg_type = 'TEXT'  # Por defecto
        for sqlite_type, postgres_type in type_mapping.items():
            if sqlite_type in col_type:
                pg_type = postgres_type
                break
        
        column_defs.append(f'"{col_name}" {pg_type}')
    
    # Crear tabla
    create_query = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_TARGET} (
        {', '.join(column_defs)}
    )
    """
    
    try:
        pg_cursor.execute(create_query)
        print(f"✅ Tabla '{TABLE_TARGET}' creada correctamente")
    except Exception as e:
        print(f"⚠️  Tabla ya existe o error: {e}")

def count_records(sqlite_cursor):
    """Cuenta registros en SQLite"""
    sqlite_cursor.execute(f"SELECT COUNT(*) FROM {TABLE_SOURCE}")
    return sqlite_cursor.fetchone()[0]

def migrate_data(sqlite_cursor, pg_cursor, pg_conn, total_records, columns):
    """Migra los datos en lotes"""
    print(f"\n📦 Iniciando migración de {total_records:,} registros...")
    print(f"💾 Tamaño de lote: {BATCH_SIZE:,} registros")
    
    # Nombres de columnas
    column_names = [col[1] for col in columns]
    
    # Query de selección
    select_query = f"SELECT * FROM {TABLE_SOURCE}"
    
    # Query de inserción
    placeholders = ', '.join(['%s'] * len(column_names))
    quoted_columns = ', '.join([f'"{col}"' for col in column_names])
    insert_query = f"INSERT INTO {TABLE_TARGET} ({quoted_columns}) VALUES ({placeholders})"
    
    # Ejecutar migración
    sqlite_cursor.execute(select_query)
    
    migrated = 0
    start_time = datetime.now()
    
    while True:
        rows = sqlite_cursor.fetchmany(BATCH_SIZE)
        if not rows:
            break
        
        try:
            # Insertar lote
            pg_cursor.executemany(insert_query, rows)
            pg_conn.commit()
            
            migrated += len(rows)
            percentage = (migrated / total_records) * 100
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = migrated / elapsed if elapsed > 0 else 0
            
            # Mostrar progreso
            print(f"⏳ Progreso: {migrated:,}/{total_records:,} ({percentage:.1f}%) "
                  f"- {rate:.0f} reg/s", end='\r')
            
        except Exception as e:
            print(f"\n❌ Error insertando lote: {e}")
            pg_conn.rollback()
            raise
    
    elapsed_total = (datetime.now() - start_time).total_seconds()
    print(f"\n✅ Migración completada: {migrated:,} registros en {elapsed_total:.1f}s")
    print(f"📊 Promedio: {migrated/elapsed_total:.0f} registros/segundo")

def verify_migration(sqlite_cursor, pg_cursor):
    """Verifica que la migración fue exitosa"""
    print("\n🔍 Verificando migración...")
    
    # Contar en SQLite
    sqlite_cursor.execute(f"SELECT COUNT(*) FROM {TABLE_SOURCE}")
    sqlite_count = sqlite_cursor.fetchone()[0]
    
    # Contar en PostgreSQL
    pg_cursor.execute(f"SELECT COUNT(*) FROM {TABLE_TARGET}")
    pg_count = pg_cursor.fetchone()[0]
    
    print(f"📊 SQLite: {sqlite_count:,} registros")
    print(f"📊 PostgreSQL: {pg_count:,} registros")
    
    if sqlite_count == pg_count:
        print("✅ Verificación exitosa: Todos los registros migrados")
        return True
    else:
        print(f"❌ Error: Faltan {sqlite_count - pg_count:,} registros")
        return False

def main():
    """Función principal de migración"""
    print("=" * 60)
    print("🐘 MIGRACIÓN SQLite → PostgreSQL (Neon)")
    print("=" * 60)
    print(f"\n📁 Archivo SQLite: {SQLITE_DB}")
    print(f"🔗 PostgreSQL: {POSTGRES_URL[:50]}...")
    print(f"📋 Tabla origen: {TABLE_SOURCE}")
    print(f"📋 Tabla destino: {TABLE_TARGET}")
    
    # Conectar a SQLite
    print(f"\n🔌 Conectando a SQLite...")
    try:
        sqlite_conn = sqlite3.connect(SQLITE_DB)
        sqlite_cursor = sqlite_conn.cursor()
        print("✅ Conectado a SQLite")
    except Exception as e:
        print(f"❌ Error conectando a SQLite: {e}")
        sys.exit(1)
    
    # Conectar a PostgreSQL
    print(f"🔌 Conectando a PostgreSQL...")
    try:
        pg_conn = psycopg2.connect(POSTGRES_URL)
        pg_cursor = pg_conn.cursor()
        print("✅ Conectado a PostgreSQL")
    except Exception as e:
        print(f"❌ Error conectando a PostgreSQL: {e}")
        print("\nVerifica tu DATABASE_URL")
        sqlite_conn.close()
        sys.exit(1)
    
    try:
        # Obtener información de la tabla
        columns = get_table_info(sqlite_cursor)
        print(f"\n📊 Columnas encontradas: {len(columns)}")
        
        # Crear tabla en PostgreSQL
        create_postgres_table(pg_cursor, columns)
        pg_conn.commit()
        
        # Contar registros
        total_records = count_records(sqlite_cursor)
        
        # Preguntar confirmación
        print(f"\n⚠️  Se migrarán {total_records:,} registros")
        response = input("¿Continuar? (s/n): ").lower()
        
        if response != 's':
            print("❌ Migración cancelada")
            return
        
        # Migrar datos
        migrate_data(sqlite_cursor, pg_cursor, pg_conn, total_records, columns)
        
        # Verificar
        if verify_migration(sqlite_cursor, pg_cursor):
            print("\n🎉 ¡Migración completada exitosamente!")
        else:
            print("\n⚠️  Migración completada con advertencias")
        
    except Exception as e:
        print(f"\n❌ Error durante la migración: {e}")
        import traceback
        traceback.print_exc()
        pg_conn.rollback()
        sys.exit(1)
    
    finally:
        # Cerrar conexiones
        sqlite_conn.close()
        pg_conn.close()
        print("\n🔌 Conexiones cerradas")

if __name__ == "__main__":
    main()

