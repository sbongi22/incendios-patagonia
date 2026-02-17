import os
import requests
import traceback
from flask import Flask, render_template, redirect, Response
from supabase import create_client
from datetime import datetime, timedelta

app = Flask(__name__)

# --- CONFIGURACIÓN DE SEGURIDAD ---
# Usamos os.environ.get para no exponer las llaves en el código
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://sglrflawktvymwujppqt.supabase.co")
# Toma automáticamente la 'service_role' key del panel de Render
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") 

if not SUPABASE_KEY:
    print("⚠️ ADVERTENCIA: No se encontró SUPABASE_KEY en las variables de entorno.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# URL pública del Bucket para redirecciones
STORAGE_URL = f"{SUPABASE_URL}/storage/v1/object/public/archivos_incendios"

# --- FUNCIONES DE UTILIDAD ---

def subir_a_storage(ruta_local, nombre_destino):
    """Sube archivos a Supabase Storage con el content-type correcto."""
    try:
        # Mapeo de tipos MIME para que el navegador los abra correctamente
        if nombre_destino.endswith(".html"):
            c_type = "text/html; charset=utf-8"
        elif nombre_destino.endswith(".xlsx"):
            c_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            c_type = "application/octet-stream"

        with open(ruta_local, 'rb') as f:
            supabase.storage.from_("archivos_incendios").upload(
                path=nombre_destino,
                file=f,
                file_options={
                    "x-upsert": "true",
                    "content-type": c_type,
                    "cache-control": "public, max-age=0"
                }
            )
        print(f"✅ {nombre_destino} subido correctamente.")
        return True
    except Exception as e:
        print(f"⚠️ Error subiendo {nombre_destino}: {e}")
        return False

def descargar_de_storage(nombre_archivo):
    """Descarga contenido desde Storage para servirlo en el dashboard."""
    try:
        url = f"{STORAGE_URL}/{nombre_archivo}"
        response = requests.get(url, timeout=10)
        return response.content if response.status_code == 200 else None
    except Exception as e:
        print(f"❌ Error descargando {nombre_archivo}: {e}")
        return None

# --- RUTAS ---

@app.route('/')
def index():
    """Muestra la página principal con estadísticas de la base de datos."""
    try:
        # Consulta a la tabla 'stats' del proyecto de monitoreo de incendios
        response = supabase.table("stats").select("*").eq("id", 1).execute()
        stats = response.data[0] if response.data else {
            "total_focos": "0", "riesgo_avg": "N/A", "intensidad_max": "0", 
            "area_critica": "N/A", "ultima_actualizacion": "Pendiente"
        }
    except Exception:
        stats = {"total_focos": "Error", "riesgo_avg": "N/A", "intensidad_max": "---", 
                 "area_critica": "N/A", "ultima_actualizacion": "Error de conexión"}
    return render_template('index.html', stats=stats)

@app.route('/mapa_embed')
@app.route('/evolucion_embed')
def servir_html_storage():
    """Ruta unificada para servir mapas y gráficos dinámicos."""
    import flask
    archivo = 'mapa_generado.html' if 'mapa' in flask.request.path else 'evolucion_historica.html'
    contenido = descargar_de_storage(archivo)
    
    if contenido:
        return Response(contenido, mimetype='text/html; charset=utf-8')
    return "<h1>⚠️ Archivo no disponible</h1>", 404

@app.route('/descargar')
def descargar():
    """Descarga del reporte Excel directamente desde Storage."""
    return redirect(f"{STORAGE_URL}/detalle_incendios.xlsx")

@app.route('/update_dashboard')
def update():
    """Proceso principal de actualización de datos y archivos."""
    try:
        from incendios_v2 import AnalizadorIncendiosHistorico
        
        # Uso de la MAP_KEY desde el entorno para el proyecto de visualización
        MAP_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
        analizador = AnalizadorIncendiosHistorico(MAP_KEY)
        
        print("🔄 Procesando datos de incendios...")
        resultados = analizador.generar_reporte_completo()
        df, evolucion = resultados['datos'], resultados['evolucion']
        
        # Generación de archivos temporales locales
        analizador.crear_mapa_interactivo(df, 'mapa_generado.html')
        analizador.crear_graficos_evolucion(evolucion, 'evolucion_historica.html')
        analizador.exportar_excel_completo(df, evolucion, 'detalle_incendios.xlsx')
        
        # Subida a la nube (Supabase Storage)
        subir_a_storage('mapa_generado.html', 'mapa_generado.html')
        subir_a_storage('evolucion_historica.html', 'evolucion_historica.html')
        subir_a_storage('detalle_incendios.xlsx', 'detalle_incendios.xlsx')
        
        # Cálculo de estadísticas finales
        sup_total = evolucion['superficie_estimada_ha'].iloc[-1] if not evolucion.empty else 0
        frp_avg = df['frp'].mean() if not df.empty else 0
        riesgo = df['nivel_riesgo'].mode()[0] if not df.empty else "N/A"
        fecha = (datetime.now() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")

        # El uso de la service_role key permite este upsert sin errores de RLS
        nuevos_stats = {
            "id": 1,
            "total_focos": str(len(df)),
            "riesgo_avg": riesgo,
            "intensidad_max": f"{frp_avg:.1f} MW",    
            "area_critica": f"{sup_total:,.0f} ha",  
            "ultima_actualizacion": fecha
        }
        supabase.table("stats").upsert(nuevos_stats).execute()
        
        return "<h1>Dashboard actualizado con éxito</h1><p><a href='/'>Volver</a></p>"
        
    except Exception as e:
        return f"<h1>Error</h1><pre>{traceback.format_exc()}</pre>", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)