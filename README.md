# Sistema de Enrutamiento - Búsqueda de Candidatos

Aplicación web para buscar candidatos de enrutamiento basados en direcciones cercanas.

## Características

- ✅ Búsqueda por PRODUCT_ID
- ✅ Filtrado por mismo lado de la calle (paridad)
- ✅ Detección de intersecciones
- ✅ Búsqueda de vecinos inmediatos (anterior y posterior)
- ✅ Solo muestra candidatos con ROUTE_ID válido
- ✅ Recomendación automática basada en el candidato más cercano
- ✅ Interfaz web moderna y responsive

## Requisitos

- Python 3.7 o superior
- pip (gestor de paquetes de Python)

## Instalación

1. **Instalar dependencias:**

```bash
pip install -r requirements.txt
```

O instalar manualmente:

```bash
pip install Flask pandas
```

## Uso

### Ejecutar la aplicación web

```bash
python app.py
```

La aplicación estará disponible en: http://localhost:5000

### Ejecutar el script de consola

```bash
python encontrar_candidatosV2.py
```

## Estructura del Proyecto

```
Buscar-direcciones/
├── app.py                      # Aplicación Flask (backend)
├── encontrar_candidatosV2.py   # Script de consola
├── mi_base_datos.sqlite        # Base de datos SQLite
├── requirements.txt            # Dependencias
├── README.md                   # Este archivo
└── templates/
    └── index.html             # Interfaz web (frontend)
```

## Algoritmo

El sistema busca candidatos siguiendo estos criterios:

1. **Misma localidad**: Solo busca en la misma localidad del producto
2. **Misma dirección**: Valida que sean de la misma calle/carrera
3. **Misma paridad**: Solo números pares con pares, impares con impares
4. **ROUTE_ID válido**: Excluye candidatos sin ROUTE_ID
5. **Vecinos cercanos**: Prioriza el vecino anterior y posterior más cercano
6. **Intersecciones**: Detecta y valida intersecciones de calles

## Funcionalidades Web

- Búsqueda en tiempo real
- Visualización de información del producto
- Lista de candidatos con detalles
- Recomendación destacada
- Indicadores visuales (vecino anterior/posterior)
- Responsive design (funciona en móviles)

## Funcionalidades Consola

- Entrada interactiva de PRODUCT_ID
- Información detallada de debug
- Análisis de componentes de dirección
- Distribución de ROUTE_IDs
- Recomendación con justificación

## Tecnologías

- **Backend**: Flask (Python)
- **Frontend**: HTML5, CSS3, JavaScript (Vanilla)
- **Base de datos**: SQLite
- **Procesamiento**: Pandas, Regex

## Notas

- La base de datos debe estar en la ruta especificada en `setup_database()`
- El algoritmo prioriza precisión sobre cantidad de resultados
- Los candidatos sin ROUTE_ID válido son automáticamente excluidos



