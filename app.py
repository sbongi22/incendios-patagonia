import os
from flask import Flask, render_template, send_file
from supabase import create_client
from datetime import datetime, timedelta


app = Flask(__name__)

# CONFIGURACIÓN SUPABASE
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://sglrflawktvymwujppqt.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnbHJmbGF3a3R2eW13dWpwcHF0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk2NDIxNzksImV4cCI6MjA4NTIxODE3OX0.tDVdjdmV1FDe-SjpusA_KdWM4BLEIHE6FbfePMjz7qY") 

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/')
def index():
    try:
        response = supabase.table("stats").select("*").eq("id", 1).execute()
        stats = response.data[0] if response.data else {"total_focos": "0", "riesgo_avg": "N/A", "intensidad_max": "0", "area_critica": "Patagonia", "ultima_actualizacion": "Pendiente"}
    except Exception as e:
        print(f"Error Supabase: {e}")
        stats = {"total_focos": "Error", "riesgo_avg": "N/A", "intensidad_max": "---", "area_critica": "N/A", "ultima_actualizacion": "Revisar logs"}
    
    return render_template('index.html', stats=stats)

@app.route('/mapa_embed')
def mapa_embed():
    map_path = os.path.join(app.root_path, 'static', 'mapa_generado.html')
    if os.path.exists(map_path):
        return send_file(map_path)
    return "<h3>El mapa se está generando...</h3>"

@app.route('/evolucion_embed')
def evolucion_embed():
    chart_path = os.path.join(app.root_path, 'static', 'evolucion_historica.html')
    if os.path.exists(chart_path):
        return send_file(chart_path)
    return "<h3>Gráficos de evolución no disponibles.</h3>"

@app.route('/descargar')
def descargar():
    excel_path = os.path.join(app.root_path, 'static', 'detalle_incendios.xlsx')
    if os.path.exists(excel_path):
        return send_file(excel_path, as_attachment=True)
    return "Archivo no encontrado", 404

@app.route('/update_dashboard_secreto')
def update():
    try:
        from incendios_v2 import AnalizadorIncendiosHistorico
        
        # 1. Configuración
        MAP_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
        analizador = AnalizadorIncendiosHistorico(MAP_KEY)
        
        # 2. Ejecutar el motor
        resultados = analizador.generar_reporte_completo()
        df = resultados['datos']
        evolucion = resultados['evolucion']
        
        # 3. Guardar archivos en static
        analizador.crear_mapa_interactivo(df, nombre_archivo='static/mapa_generado.html')
        analizador.crear_graficos_evolucion(evolucion, nombre_archivo='static/evolucion_historica.html')
        analizador.exportar_excel_completo(df, evolucion, nombre_archivo='static/detalle_incendios.xlsx')
        
        # 4. Actualizar Supabase (Reutilizamos la conexión de app.py)
        total = len(df)
        intensidad = df['frp'].max() if not df.empty else 0
        riesgo = df['nivel_riesgo'].mode()[0] if not df.empty else "N/A"
        
        ahora_argentina = datetime.now() - timedelta(hours=3)
        fecha_dashboard = ahora_argentina.strftime("%d/%m/%Y %H:%M")

        nuevos_stats = {
            "id": 1,
            "total_focos": str(total),
            "riesgo_avg": riesgo,
            "intensidad_max": f"{intensidad:.1f}",
            "area_critica": "Patagonia",
            "ultima_actualizacion": fecha_dashboard
        }
        
        supabase.table("stats").upsert(nuevos_stats).execute()
        
        return "<h1>🚀 Dashboard actualizado con éxito</h1><p>Podés volver al <a href='/'>inicio</a>.</p>"
    except Exception as e:
        return f"<h1>❌ Error</h1><p>{str(e)}</p>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)