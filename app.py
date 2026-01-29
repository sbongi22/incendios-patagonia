import os
from flask import Flask, render_template, send_file
from supabase import create_client

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)