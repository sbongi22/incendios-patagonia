import os, requests, pandas as pd, folium, numpy as np, time
from folium.plugins import HeatMap, MarkerCluster
from datetime import datetime, timedelta
from io import StringIO, BytesIO
from flask import Flask, render_template, send_file

# ==========================================
# CLASE DE PROCESAMIENTO (Analizador)
# ==========================================
class AnalizadorIncendiosHistorico:
    def __init__(self, map_key):
        self.map_key = map_key
        self.zona_bounds = "-72.5,-47,-69,-42"
        self.fecha_inicio_incendios = datetime(2026, 1, 1)
        self.archivo_excel = "reporte_incendios_patagonia.xlsx"
        self.archivo_mapa = "templates/mapa_generado.html"
        self.archivo_stats = "stats_actuales.csv"

    def obtener_datos_meteorologicos(self, lat, lon):
        try:
            params = {'latitude': lat, 'longitude': lon, 'hourly': 'temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation', 'past_days': 7, 'forecast_days': 0, 'timezone': 'auto'}
            res = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10).json()
            h = res['hourly']
            return {'viento_kmh': round(h['wind_speed_10m'][-1] * 3.6, 1), 'humedad_relativa': h['relative_humidity_2m'][-1], 'temperatura_c': h['temperature_2m'][-1], 'lluvia_7d_mm': sum(h['precipitation'])}
        except: return {'viento_kmh': 10, 'humedad_relativa': 50, 'temperatura_c': 20, 'lluvia_7d_mm': 0}

    def procesar_todo(self):
        """Esta función se ejecutará a las 6 AM"""
        # 1. Descarga NASA
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{self.map_key}/VIIRS_SNPP_NRT/{self.zona_bounds}/10"
        res = requests.get(url)
        if res.status_code != 200: return False
        
        df = pd.read_csv(StringIO(res.text))
        
        # 2. Limpieza y Clima
        df['confidence'] = pd.to_numeric(df['confidence'], errors='coerce').fillna(60)
        df = df[df['confidence'] >= 70].copy()
        
        # Meteorología para los primeros 50 focos (por velocidad)
        meteo_data = []
        for i, row in df.head(50).iterrows():
            m = self.obtener_datos_meteorologicos(row['latitude'], row['longitude'])
            meteo_data.append(m)
        
        df_meteo = pd.DataFrame(meteo_data)
        for col in ['temperatura_c', 'humedad_relativa', 'viento_kmh']:
            df[col] = df_meteo[col].mean() if not df_meteo.empty else 0

        # 3. Guardar Excel
        df.to_excel(self.archivo_excel, index=False)
        
        # 4. Guardar Stats para la web
        stats = pd.DataFrame([{
            'total': len(df),
            'temp': round(df['temperatura_c'].mean(), 1),
            'hum': round(df['humedad_relativa'].mean(), 1),
            'riesgo': "ALTO" if df['viento_kmh'].mean() > 20 else "MODERADO"
        }])
        stats.to_csv(self.archivo_stats, index=False)

        # 5. Guardar Mapa
        mapa = folium.Map(location=[df['latitude'].mean(), df['longitude'].mean()], zoom_start=7, tiles="cartodb dark_matter")
        HeatMap(df[['latitude', 'longitude']].values).add_to(mapa)
        mapa.save(self.archivo_mapa)
        return True

# ==========================================
# APP FLASK
# ==========================================
app = Flask(__name__)
NASA_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
analizador = AnalizadorIncendiosHistorico(NASA_KEY)

@app.route('/')
def index():
    if os.path.exists(analizador.archivo_stats):
        stats_df = pd.read_csv(analizador.archivo_stats)
        stats = stats_df.iloc[0].to_dict()
    else:
        stats = {'total': 0, 'temp': 0, 'hum': 0, 'riesgo': 'N/A'}
    return render_template('index.html', stats=stats)

@app.route('/mapa_embed')
def mapa_embed():
    if os.path.exists(analizador.archivo_mapa):
        return send_file('mapa_generado.html')
    return "Generando mapa..."

@app.route('/download')
def download():
    if os.path.exists(analizador.archivo_excel):
        return send_file(analizador.archivo_excel, as_attachment=True)
    return "Archivo no disponible"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)