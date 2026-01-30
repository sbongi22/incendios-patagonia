import os
import requests
from flask import Flask, render_template, redirect, Response
from supabase import create_client
from datetime import datetime, timedelta

app = Flask(__name__)

# CONFIGURACIÓN SUPABASE
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://sglrflawktvymwujppqt.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnbHJmbGF3a3R2eW13dWpwcHF0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk2NDIxNzksImV4cCI6MjA4NTIxODE3OX0.tDVdjdmV1FDe-SjpusA_KdWM4BLEIHE6FbfePMjz7qY") 

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# URL pública del Bucket
STORAGE_URL = f"{SUPABASE_URL}/storage/v1/object/public/archivos_incendios"

def subir_a_storage(ruta_local, nombre_destino):
    """Sube archivos a Supabase Storage con el content-type correcto."""
    try:
        # Mapeo de tipos MIME
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
        print(f"✅ {nombre_destino} subido correctamente como {c_type}")
        return True
        
    except Exception as e:
        print(f"⚠️ Error subiendo {nombre_destino}: {e}")
        return False

def descargar_de_storage(nombre_archivo):
    """Descarga un archivo desde Supabase Storage y retorna su contenido."""
    try:
        # Obtener URL pública
        url = f"{STORAGE_URL}/{nombre_archivo}"
        
        # Descargar el archivo
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            print(f"✅ {nombre_archivo} descargado correctamente")
            return response.content
        else:
            print(f"⚠️ Error descargando {nombre_archivo}: Status {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Error descargando {nombre_archivo}: {e}")
        return None

@app.route('/')
def index():
    try:
        response = supabase.table("stats").select("*").eq("id", 1).execute()
        stats = response.data[0] if response.data else {
            "total_focos": "0", "riesgo_avg": "N/A", "intensidad_max": "0", 
            "area_critica": "Patagonia", "ultima_actualizacion": "Pendiente"
        }
    except Exception as e:
        stats = {"total_focos": "Error", "riesgo_avg": "N/A", "intensidad_max": "---", 
                 "area_critica": "N/A", "ultima_actualizacion": "Error"}
    return render_template('index.html', stats=stats)

@app.route('/mapa_embed')
def mapa_embed():
    """Descarga el mapa desde Storage y lo sirve como HTML"""
    try:
        # Descargar el contenido desde Storage
        contenido = descargar_de_storage('mapa_generado.html')
        
        if contenido:
            # Servir el contenido con el content-type correcto
            return Response(contenido, mimetype='text/html; charset=utf-8')
        else:
            return """
            <h1>⚠️ Mapa no disponible</h1>
            <p>El mapa aún no ha sido generado o hubo un error al descargarlo.</p>
            <p><a href='/update_dashboard'>Generar dashboard</a> | <a href='/'>Volver al inicio</a></p>
            """, 404
            
    except Exception as e:
        return f"<h1>❌ Error</h1><p>{str(e)}</p><a href='/'>Volver</a>", 500

@app.route('/evolucion_embed')
def evolucion_embed():
    """Descarga los gráficos desde Storage y los sirve como HTML"""
    try:
        # Descargar el contenido desde Storage
        contenido = descargar_de_storage('evolucion_historica.html')
        
        if contenido:
            # Servir el contenido con el content-type correcto
            return Response(contenido, mimetype='text/html; charset=utf-8')
        else:
            return """
            <h1>⚠️ Gráficos no disponibles</h1>
            <p>Los gráficos aún no han sido generados o hubo un error al descargarlos.</p>
            <p><a href='/update_dashboard'>Generar dashboard</a> | <a href='/'>Volver al inicio</a></p>
            """, 404
            
    except Exception as e:
        return f"<h1>❌ Error</h1><p>{str(e)}</p><a href='/'>Volver</a>", 500

@app.route('/descargar')
def descargar():
    """Redirige al Excel en Supabase Storage"""
    return redirect(f"{STORAGE_URL}/detalle_incendios.xlsx")

@app.route('/update_dashboard')
def update():
    try:
        from incendios_v2 import AnalizadorIncendiosHistorico
        
        MAP_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
        analizador = AnalizadorIncendiosHistorico(MAP_KEY)
        
        print("🔄 Generando reporte completo...")
        resultados = analizador.generar_reporte_completo()
        df = resultados['datos']
        evolucion = resultados['evolucion']
        
        # Generar archivos locales temporalmente
        print("📊 Creando visualizaciones...")
        analizador.crear_mapa_interactivo(df, nombre_archivo='mapa_generado.html')
        analizador.crear_graficos_evolucion(evolucion, nombre_archivo='evolucion_historica.html')
        analizador.exportar_excel_completo(df, evolucion, nombre_archivo='detalle_incendios.xlsx')
        
        # Subir TODOS los archivos a Storage
        print("☁️ Subiendo archivos a Supabase Storage...")
        mapa_ok = subir_a_storage('mapa_generado.html', 'mapa_generado.html')
        evolucion_ok = subir_a_storage('evolucion_historica.html', 'evolucion_historica.html')
        excel_ok = subir_a_storage('detalle_incendios.xlsx', 'detalle_incendios.xlsx')
        
        # Actualización de estadísticas en tabla 'stats'
        print("💾 Actualizando estadísticas...")
        superficie_total = evolucion['superficie_estimada_ha'].iloc[-1] if not evolucion.empty else 0
        frp_promedio = df['frp'].mean() if not df.empty else 0
        riesgo = df['nivel_riesgo'].mode()[0] if not df.empty else "N/A"
        fecha_dashboard = (datetime.now() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")

        nuevos_stats = {
            "id": 1,
            "total_focos": str(len(df)),
            "riesgo_avg": riesgo,
            "intensidad_max": f"{frp_promedio:.1f} MW",    
            "area_critica": f"{superficie_total:,.0f} ha",  
            "ultima_actualizacion": fecha_dashboard
        }
        supabase.table("stats").upsert(nuevos_stats).execute()
        
        # Resumen de resultados
        status_mapa = "✅" if mapa_ok else "❌"
        status_evolucion = "✅" if evolucion_ok else "❌"
        status_excel = "✅" if excel_ok else "❌"
        
        return f"""
        <h1>🚀 Dashboard actualizado</h1>
        <p>{status_mapa} Mapa interactivo: {'Subido correctamente' if mapa_ok else 'Error al subir'}</p>
        <p>{status_evolucion} Gráficos de evolución: {'Subidos correctamente' if evolucion_ok else 'Error al subir'}</p>
        <p>{status_excel} Archivo Excel: {'Subido correctamente' if excel_ok else 'Error al subir'}</p>
        <p>✅ Estadísticas actualizadas en base de datos</p>
        <p>📊 Total de focos detectados: {len(df)}</p>
        <br>
        <p><a href='/'>← Volver al inicio</a> | <a href='/mapa_embed'>Ver mapa</a> | <a href='/evolucion_embed'>Ver gráficos</a></p>
        """
        
    except Exception as e:
        import traceback
        error_detallado = traceback.format_exc()
        return f"""
        <h1>❌ Error al actualizar dashboard</h1>
        <p><strong>Error:</strong> {str(e)}</p>
        <pre>{error_detallado}</pre>
        <br>
        <a href='/'>Volver al inicio</a>
        """, 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)