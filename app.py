import os, requests, pandas as pd, folium, numpy as np, json
from folium.plugins import HeatMap, MarkerCluster
from datetime import datetime, timedelta
from io import StringIO
from flask import Flask, render_template, send_file

app = Flask(__name__)

class AnalizadorPro:
    def __init__(self):
        self.map_key = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
        self.zona = "-72.5,-47,-69,-42"
        self.excel_path = "static/detalle_incendios.xlsx"
        self.stats_path = "static/stats.json"
        self.map_path = "templates/mapa_base.html"

    def procesar_actualizacion_diaria(self):
        """Función que corre a las 6 AM"""
        # 1. Obtener datos de la NASA
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{self.map_key}/VIIRS_SNPP_NRT/{self.zona}/10"
        res = requests.get(url)
        if res.status_code != 200: return
        
        df = pd.read_csv(StringIO(res.text))
        
        # Limpieza de confianza (basado en errores previos)
        df['confidence'] = pd.to_numeric(df['confidence'], errors='coerce').fillna(50)
        df = df[df['confidence'] >= 70].copy()

        # 2. Generar Estadísticas Relevantes
        stats = {
            "total_focos": len(df),
            "riesgo_avg": "ALTO" if df['frp'].mean() > 40 else "MODERADO",
            "intensidad_max": round(df['frp'].max(), 1),
            "area_critica": "Chubut/Río Negro", # Simplificado para el ejemplo
            "ultima_actualizacion": datetime.now().strftime("%d/%m/%Y %H:%M")
        }
        
        # 3. Guardar el Excel detallado (estilo incendios_v2)
        with pd.ExcelWriter(self.excel_path) as writer:
            df.to_excel(writer, sheet_name='Detalle Completo')
            df.describe().to_excel(writer, sheet_name='Resumen Estadístico')

        # 4. Guardar JSON para el Dashboard
        with open(self.stats_path, 'w') as f:
            json.dump(stats, f)

        # 5. Generar Mapa
        m = folium.Map(location=[-44.5, -71], zoom_start=7, tiles="cartodb dark_matter")
        HeatMap(df[['latitude', 'longitude']].values).add_to(m)
        m.save(self.map_path)

analizador = AnalizadorPro()

@app.route('/')
def index():
    # Leer stats del archivo JSON generado a las 6 AM
    try:
        with open('static/stats.json', 'r') as f:
            data_stats = json.load(f)
    except:
        data_stats = {"total_focos": "0", "riesgo_avg": "---", "intensidad_max": "0", "area_critica": "N/A", "ultima_actualizacion": "Pendiente"}
    
    return render_template('index.html', stats=data_stats)

@app.route('/descargar')
def descargar():
    return send_file(analizador.excel_path, as_attachment=True)

@app.route('/mapa')
def mapa():
    return send_file(analizador.map_path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)