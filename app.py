import os
import requests
import pandas as pd
import folium
from folium.plugins import HeatMap, MarkerCluster
from datetime import datetime, timedelta
import numpy as np
from io import StringIO
from flask import Flask, render_template, send_file

# ==========================================
# CLASE DE PROCESAMIENTO
# ==========================================
class AnalizadorIncendiosHistorico:
    def __init__(self, map_key):
        self.map_key = map_key
        self.zona_bounds = "-72.5,-47,-69,-42" # Patagonia
        self.fecha_inicio_incendios = datetime(2026, 1, 1)
        self.openmeteo_url = "https://api.open-meteo.com/v1/forecast"

    def obtener_datos_meteorologicos(self, lat, lon):
        try:
            params = {
                'latitude': lat, 'longitude': lon,
                'hourly': 'temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation',
                'past_days': 7, 'forecast_days': 0, 'timezone': 'auto'
            }
            response = requests.get(self.openmeteo_url, params=params, timeout=10)
            data = response.json()
            hourly = data['hourly']
            last_idx = len(hourly['time']) - 1
            return {
                'viento_kmh': round(hourly['wind_speed_10m'][last_idx] * 3.6, 1),
                'humedad_relativa': round(hourly['relative_humidity_2m'][last_idx], 1),
                'temperatura_c': round(hourly['temperature_2m'][last_idx], 1),
                'lluvia_7d_mm': round(sum(hourly['precipitation'][:last_idx+1]), 1)
            }
        except Exception:
            return {'viento_kmh': 10.0, 'humedad_relativa': 50.0, 'temperatura_c': 20.0, 'lluvia_7d_mm': 0.0}

    def calcular_riesgo_fwi(self, viento, humedad, lluvia, temperatura):
        v_norm = min(viento / 50, 1.0)
        h_norm = (100 - humedad) / 100
        l_norm = max(0, 1 - (lluvia / 50))
        t_norm = min((temperatura - 10) / 30, 1.0)
        indice = (v_norm * 0.4 + h_norm * 0.3 + l_norm * 0.2 + t_norm * 0.1) * 100
        return round(max(0, min(indice, 100)), 1)

    def clasificar_riesgo(self, indice):
        if indice < 20: return "BAJO"
        elif indice < 40: return "MODERADO"
        elif indice < 60: return "ALTO"
        elif indice < 80: return "MUY ALTO"
        else: return "EXTREMO"

    def agregar_datos_meteorologicos_rapido(self, df):
        df['lat_red'] = df['latitude'].round(1)
        df['lon_red'] = df['longitude'].round(1)
        ubicaciones = df[['lat_red', 'lon_red']].drop_duplicates()
        datos_meteo = []

        for _, row in ubicaciones.iterrows():
            lat, lon = row['lat_red'], row['lon_red']
            meteo = self.obtener_datos_meteorologicos(lat, lon)
            riesgo = self.calcular_riesgo_fwi(meteo['viento_kmh'], meteo['humedad_relativa'], meteo['lluvia_7d_mm'], meteo['temperatura_c'])
            datos_meteo.append({
                'lat_red': lat, 'lon_red': lon, 'indice_riesgo': riesgo, 
                'nivel_riesgo': self.clasificar_riesgo(riesgo), **meteo
            })
        
        df_meteo = pd.DataFrame(datos_meteo)
        return pd.merge(df, df_meteo, on=['lat_red', 'lon_red'], how='left').drop(columns=['lat_red', 'lon_red'])

    def obtener_datos_rango_fechas(self, fecha_inicio, fecha_fin, fuente="VIIRS_SNPP_NRT"):
        todos_los_datos = []
        fecha_actual = fecha_inicio
        while fecha_actual <= fecha_fin:
            dias = min(5, (fecha_fin - fecha_actual).days + 1)
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{self.map_key}/{fuente}/{self.zona_bounds}/{dias}/{fecha_actual.strftime('%Y-%m-%d')}"
            try:
                res = requests.get(url, timeout=30)
                if res.status_code == 200 and "latitude" in res.text:
                    todos_los_datos.append(pd.read_csv(StringIO(res.text)))
            except Exception: pass
            fecha_actual += timedelta(days=dias)
        return pd.concat(todos_los_datos).drop_duplicates() if todos_los_datos else None

    def obtener_datos_actualizados(self):
        df = self.obtener_datos_rango_fechas(self.fecha_inicio_incendios, datetime.now())
        if df is not None:
            df = df[df['longitude'] > -72.2].copy()
            df['acq_date'] = pd.to_datetime(df['acq_date'])
        return df

    def filtrar_por_confianza(self, df, minima=70):
        df = df.copy()
        mapa_niveles = {'l': 30, 'low': 30, 'n': 60, 'nominal': 60, 'h': 90, 'high': 90}
        
        def sanitizar_confianza(valor):
            if isinstance(valor, (int, float, np.number)): return float(valor)
            val_str = str(valor).lower().strip()
            if val_str in mapa_niveles: return float(mapa_niveles[val_str])
            try: return float(val_str)
            except ValueError: return 0.0

        df['confidence'] = df['confidence'].apply(sanitizar_confianza).astype(float)
        return df[df['confidence'] >= minima].copy()

    def agregar_informacion_temporal(self, df):
        df['acq_date'] = pd.to_datetime(df['acq_date'])
        df['semana'] = df['acq_date'].dt.isocalendar().week
        df['mes'] = df['acq_date'].dt.month
        return df

    def crear_mapa_interactivo(self, df, nombre='mapa_incendios_historico.html'):
        mapa = folium.Map(location=[df['latitude'].mean(), df['longitude'].mean()], zoom_start=6)
        HeatMap(df[['latitude', 'longitude', 'frp']].values.tolist(), radius=15).add_to(mapa)
        cluster = MarkerCluster().add_to(mapa)
        colores = {"BAJO": "green", "MODERADO": "lightgreen", "ALTO": "orange", "MUY ALTO": "red", "EXTREMO": "purple"}
        for _, row in df.iterrows():
            folium.Marker(
                [row['latitude'], row['longitude']],
                icon=folium.Icon(color=colores.get(row['nivel_riesgo'], 'gray'), icon='fire', prefix='fa'),
                tooltip=f"Riesgo: {row['nivel_riesgo']}"
            ).add_to(cluster)
        mapa.save(nombre)

    def generar_reporte_web(self):
        df = self.obtener_datos_actualizados()
        if df is None or len(df) == 0: return None
        df = self.filtrar_por_confianza(df)
        df = self.agregar_informacion_temporal(df)
        df = self.agregar_datos_meteorologicos_rapido(df)
        self.crear_mapa_interactivo(df)
        return {
            'total_focos': len(df),
            'riesgo_promedio': round(df['indice_riesgo'].mean(), 1),
            'temp_promedio': round(df['temperatura_c'].mean(), 1),
            'humedad_promedio': round(df['humedad_relativa'].mean(), 1)
        }

# ==========================================
# APP FLASK
# ==========================================
app = Flask(__name__)
NASA_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
analizador = AnalizadorIncendiosHistorico(NASA_KEY)

@app.route('/')
def index():
    stats = analizador.generar_reporte_web()
    return render_template('index.html', stats=stats)

@app.route('/mapa')
def ver_mapa():
    return send_file('mapa_incendios_historico.html')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)