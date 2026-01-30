import os
from flask import Flask, render_template, redirect
from supabase import create_client
from datetime import datetime, timedelta

app = Flask(__name__)

# CONFIGURACIÓN SUPABASE
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://sglrflawktvymwujppqt.supabase.co")
# Nota: Es recomendable usar variables de entorno para la KEY en Render
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnbHJmbGF3a3R2eW13dWpwcHF0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk2NDIxNzksImV4cCI6MjA4NTIxODE3OX0.tDVdjdmV1FDe-SjpusA_KdWM4BLEIHE6FbfePMjz7qY") 

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# URL base para acceder a los archivos públicos en tu Bucket (API URL)
STORAGE_URL = f"{SUPABASE_URL}/storage/v1/object/public/archivos_incendios"

def subir_a_storage(ruta_local, nombre_destino):
    """Sube el archivo a Supabase Storage con upsert para sobrescribir el anterior."""
    try:
        with open(ruta_local, 'rb') as f:
            supabase.storage.from_("archivos_incendios").upload(
                path=nombre_destino,
                file=f,
                file_options={"x-upsert": "true"}
            )
        print(f"✅ {nombre_destino} subido correctamente.")
    except Exception as e:
        print(f"❌ Error subiendo {nombre_destino}: {e}")

@app.route('/')
def index():
    try:
        response = supabase.table("stats").select("*").eq("id", 1).execute()
        stats = response.data[0] if response.data else {
            "total_focos": "0", 
            "riesgo_avg": "N/A", 
            "intensidad_max": "0", 
            "area_critica": "Patagonia", 
            "ultima_actualizacion": "Pendiente"
        }
    except Exception as e:
        print(f"Error Supabase: {e}")
        stats = {
            "total_focos": "Error", 
            "riesgo_avg": "N/A", 
            "intensidad_max": "---", 
            "area_critica": "N/A", 
            "ultima_actualizacion": "Revisar logs"
        }
    return render_template('index.html', stats=stats)

@app.route('/mapa_embed')
def mapa_embed():
    # Redirigimos al archivo persistente en Supabase
    return redirect(f"{STORAGE_URL}/mapa_generado.html")

@app.route('/evolucion_embed')
def evolucion_embed():
    # Redirigimos al archivo persistente en Supabase
    return redirect(f"{STORAGE_URL}/evolucion_historica.html")

@app.route('/descargar')
def descargar():
    # Redirigimos a la descarga del Excel en Supabase
    return redirect(f"{STORAGE_URL}/detalle_incendios.xlsx")

@app.route('/update_dashboard')
def update():
    try:
        from incendios_v2 import AnalizadorIncendiosHistorico
        
        # 1. Ejecutar análisis
        MAP_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
        analizador = AnalizadorIncendiosHistorico(MAP_KEY)
        
        print("Obteniendo datos...")
        resultados = analizador.generar_reporte_completo()
        df = resultados['datos']
        evolucion = resultados['evolucion']
        
        # 2. Generar archivos locales temporales
        # Quitamos 'static/' para que se guarden en la raíz temporal de Render
        analizador.crear_mapa_interactivo(df, nombre_archivo='mapa_generado.html')
        analizador.crear_graficos_evolucion(evolucion, nombre_archivo='evolucion_historica.html')
        analizador.exportar_excel_completo(df, evolucion, nombre_archivo='detalle_incendios.xlsx')
        
        # 3. Subir archivos a Supabase Storage
        subir_a_storage('mapa_generado.html', 'mapa_generado.html')
        subir_a_storage('evolucion_historica.html', 'evolucion_historica.html')
        subir_a_storage('detalle_incendios.xlsx', 'detalle_incendios.xlsx')
        
        # 4. Actualizar tabla de estadísticas en la base de datos
        total = len(df)
        superficie_total = evolucion['superficie_estimada_ha'].iloc[-1] if not evolucion.empty else 0
        frp_promedio = df['frp'].mean() if not df.empty else 0
        riesgo = df['nivel_riesgo'].mode()[0] if not df.empty else "N/A"
        
        ahora_argentina = datetime.now() - timedelta(hours=3)
        fecha_dashboard = ahora_argentina.strftime("%d/%m/%Y %H:%M")

        nuevos_stats = {
            "id": 1,
            "total_focos": str(total),
            "riesgo_avg": riesgo,
            "intensidad_max": f"{frp_promedio:.1f} MW",    
            "area_critica": f"{superficie_total:,.0f} ha",  
            "ultima_actualizacion": fecha_dashboard
        }
        
        supabase.table("stats").upsert(nuevos_stats).execute()
        
        return "<h1>🚀 Dashboard y Almacenamiento actualizados</h1><p>Los archivos ya están seguros en Supabase Storage.</p><a href='/'>Volver al inicio</a>"

    except Exception as e:
        print(f"Error en update: {e}")
        return f"<h1>❌ Error en la actualización</h1><p>{str(e)}</p>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
