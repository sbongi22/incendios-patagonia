from flask import Flask, render_template, send_from_directory, jsonify
import os
from supabase import create_client
from datetime import datetime, timedelta
from incendios_v2 import AnalizadorIncendiosHistorico

app = Flask(__name__)

# Configuración
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://sglrflawktvymwujppqt.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnbHJmbGF3a3R2eW13dWpwcHF0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk2NDIxNzksImV4cCI6MjA4NTIxODE3OX0.tDVdjdmV1FDe-SjpusA_KdWM4BLEIHE6FbfePMjz7qY")
MAP_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/')
def index():
    try:
        response = supabase.table("stats").select("*").eq("id", 1).execute()
        stats = response.data[0] if response.data else {}
        return render_template('index.html', stats=stats)
    except Exception:
        return "Error cargando Dashboard"

@app.route('/update')
def actualizar():
    try:
        analizador = AnalizadorIncendiosHistorico(MAP_KEY)
        res = analizador.generar_reporte_completo()
        if res:
            df, evo = res['datos'], res['evolucion']
            analizador.crear_mapa_interactivo(df)
            analizador.crear_graficos_evolucion(evo)
            analizador.exportar_excel_completo(df, evo, 'static/detalle_incendios.xlsx')

            # ACTUALIZACIÓN CRUCIAL: Mismas métricas que incendios_v2.py
            hectareas = f"{evo['superficie_estimada_ha'].iloc[-1]:,.0f} ha"
            frp_prom = f"{df['frp'].mean():.1f} MW"
            
            supabase.table("stats").upsert({
                "id": 1,
                "total_focos": str(len(df)),
                "riesgo_avg": df['nivel_riesgo'].mode()[0],
                "intensidad_max": frp_prom,
                "area_critica": hectareas,
                "ultima_actualizacion": (datetime.now() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
            }).execute()
            return jsonify({"status": "success", "message": "Datos actualizados"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
