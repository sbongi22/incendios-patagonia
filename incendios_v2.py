import requests
import pandas as pd
import folium
from folium.plugins import HeatMap, MarkerCluster
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import numpy as np
from io import StringIO
import time
import os

class AnalizadorIncendiosHistorico:
    def __init__(self, map_key):
        self.map_key = map_key
        self.zona_bounds = "-72.5,-47,-69,-42"
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
            viento_kmh = hourly['wind_speed_10m'][last_idx] * 3.6
            humedad = hourly['relative_humidity_2m'][last_idx]
            temperatura = hourly['temperature_2m'][last_idx]
            precipitacion_total = sum(hourly['precipitation'][:last_idx+1])
            return {
                'viento_kmh': round(viento_kmh, 1),
                'humedad_relativa': round(humedad, 1),
                'temperatura_c': round(temperatura, 1),
                'lluvia_7d_mm': round(precipitacion_total, 1)
            }
        except Exception:
            return {'viento_kmh': 10.0, 'humedad_relativa': 50.0, 'temperatura_c': 20.0, 'lluvia_7d_mm': 0.0}

    def calcular_riesgo_fwi(self, viento, humedad, lluvia, temperatura):
        # REGLA 30-30-30
        if temperatura >= 30 and humedad <= 30 and viento >= 30:
            return 100.0
        viento_norm = min(viento / 50, 1.0)
        humedad_norm = (100 - humedad) / 100
        lluvia_norm = max(0, 1 - (lluvia / 50))
        temp_norm = min((temperatura - 10) / 30, 1.0)
        indice = (viento_norm * 0.4 + humedad_norm * 0.3 + lluvia_norm * 0.2 + temp_norm * 0.1) * 100
        return round(max(0, min(indice, 100)), 1)

    def clasificar_riesgo(self, indice):
        if indice >= 100: return "EXTREMO (30-30-30)"
        if indice < 20: return "BAJO"
        elif indice < 40: return "MODERADO"
        elif indice < 60: return "ALTO"
        elif indice < 80: return "MUY ALTO"
        else: return "EXTREMO"

    def agregar_datos_meteorologicos_rapido(self, df):
        cache_meteo = {}
        df['lat_redondeada'] = df['latitude'].round(1)
        df['lon_redondeada'] = df['longitude'].round(1)
        ubicaciones_unicas = df[['lat_redondeada', 'lon_redondeada']].drop_duplicates()
        datos_meteo = []
        for i, (idx, row) in enumerate(ubicaciones_unicas.iterrows()):
            lat, lon = row['lat_redondeada'], row['lon_redondeada']
            cache_key = f"{lat:.1f}_{lon:.1f}"
            if cache_key in cache_meteo:
                datos_meteo.append(cache_meteo[cache_key])
                continue
            meteo = self.obtener_datos_meteorologicos(lat, lon)
            indice = self.calcular_riesgo_fwi(meteo['viento_kmh'], meteo['humedad_relativa'], meteo['lluvia_7d_mm'], meteo['temperatura_c'])
            datos_ubicacion = {
                'lat_redondeada': lat, 'lon_redondeada': lon,
                'viento_kmh': meteo['viento_kmh'], 'humedad_relativa': meteo['humedad_relativa'],
                'temperatura_c': meteo['temperatura_c'], 'lluvia_7d_mm': meteo['lluvia_7d_mm'],
                'indice_riesgo': indice, 'nivel_riesgo': self.clasificar_riesgo(indice)
            }
            cache_meteo[cache_key] = datos_ubicacion
            datos_meteo.append(datos_ubicacion)
        df_meteo = pd.DataFrame(datos_meteo)
        df_completo = pd.merge(df, df_meteo, on=['lat_redondeada', 'lon_redondeada'], how='left')
        return df_completo.drop(columns=['lat_redondeada', 'lon_redondeada'])

    def obtener_datos_rango_fechas(self, fecha_inicio, fecha_fin, fuente="VIIRS_SNPP_NRT"):
        todos_los_datos = []
        fecha_actual = fecha_inicio
        while fecha_actual <= fecha_fin:
            dias_bloque = min(5, (fecha_fin - fecha_actual).days + 1)
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{self.map_key}/{fuente}/{self.zona_bounds}/{dias_bloque}/{fecha_actual.strftime('%Y-%m-%d')}"
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200 and "latitude" in r.text:
                    todos_los_datos.append(pd.read_csv(StringIO(r.text)))
            except Exception: pass
            fecha_actual += timedelta(days=dias_bloque)
        return pd.concat(todos_los_datos).drop_duplicates(subset=['latitude', 'longitude', 'acq_date', 'acq_time']) if todos_los_datos else None

    def obtener_datos_actualizados(self, fuente="VIIRS_SNPP_NRT"):
        df = self.obtener_datos_rango_fechas(self.fecha_inicio_incendios, datetime.now(), fuente)
        if df is not None:
            df = df[df['longitude'] > -72.2].copy()
            df['acq_date'] = pd.to_datetime(df['acq_date'])
        return df

    def filtrar_por_confianza(self, df, conf=70):
        confidence_map = {'low': 30, 'nominal': 75, 'high': 95, 'l': 30, 'n': 75, 'h': 95}
        df['confidence'] = df['confidence'].apply(lambda x: float(x) if str(x).isdigit() else confidence_map.get(str(x).lower(), 50))
        return df[df['confidence'] >= conf].copy()

    def analizar_evolucion_diaria(self, df):
        evo = df.groupby('acq_date').agg({'latitude': 'count', 'frp': ['sum', 'mean', 'max']}).round(2)
        evo.columns = ['focos_nuevos', 'frp_total', 'frp_promedio', 'frp_maximo']
        evo = evo.reset_index()
        evo['focos_acumulados'] = evo['focos_nuevos'].cumsum()
        evo['superficie_estimada_ha'] = evo['focos_acumulados'] * 14
        return evo

    def crear_mapa_interactivo(self, df, nombre_archivo='static/mapa_generado.html'):
        mapa = folium.Map(location=[df['latitude'].mean(), df['longitude'].mean()], zoom_start=6)
        HeatMap(df[['latitude', 'longitude', 'frp']].values.tolist(), radius=15).add_to(mapa)
        mc = MarkerCluster().add_to(mapa)
        colores = {"BAJO": "green", "MODERADO": "lightgreen", "ALTO": "orange", "MUY ALTO": "red", "EXTREMO": "purple", "EXTREMO (30-30-30)": "black"}
        for _, r in df.iterrows():
            folium.Marker([r['latitude'], r['longitude']], icon=folium.Icon(color=colores.get(r['nivel_riesgo'], 'gray'), icon='fire', prefix='fa')).add_to(mc)
        
        leyenda = f'''<div style="position: fixed; bottom: 50px; right: 50px; width: 280px; background: white; border:2px solid grey; z-index:9999; padding: 10px; border-radius: 5px;">
        <b>🔥 Riesgo Incendios</b><br>
        <span style="color:black;">●</span> 🚨 CRÍTICO (30-30-30)<br>
        <span style="color:purple;">●</span> EXTREMO<br>
        <span style="color:red;">●</span> MUY ALTO<br>
        <span style="color:orange;">●</span> ALTO<br>
        <span style="color:green;">●</span> BAJO
        </div>'''
        mapa.get_root().html.add_child(folium.Element(leyenda))
        mapa.save(nombre_archivo)

    def crear_graficos_evolucion(self, evo, nombre_archivo='static/evolucion_historica.html'):
        fig = make_subplots(rows=3, cols=1, subplot_titles=('Focos por día', 'Focos acumulados', 'Hectáreas estimadas'))
        fig.add_trace(go.Bar(x=evo['acq_date'], y=evo['focos_nuevos'], marker_color='orangered'), row=1, col=1)
        fig.add_trace(go.Scatter(x=evo['acq_date'], y=evo['focos_acumulados'], fill='tozeroy'), row=2, col=1)
        fig.add_trace(go.Scatter(x=evo['acq_date'], y=evo['superficie_estimada_ha'], line=dict(color='darkred')), row=3, col=1)
        fig.update_layout(height=900, template="plotly_white", showlegend=False)
        fig.write_html(nombre_archivo)

    def exportar_excel_completo(self, df, evo, nombre_archivo):
        with pd.ExcelWriter(nombre_archivo) as writer:
            df.to_excel(writer, sheet_name='Detalle', index=False)
            evo.to_excel(writer, sheet_name='Evolucion', index=False)

    def generar_reporte_completo(self):
        df = self.obtener_datos_actualizados()
        if df is None: return None
        df = self.filtrar_por_confianza(df)
        df['año'] = df['acq_date'].dt.year
        df['semana'] = df['acq_date'].dt.isocalendar().week
        df = self.agregar_datos_meteorologicos_rapido(df)
        evo = self.analizar_evolucion_diaria(df)
        return {'datos': df, 'evolucion': evo}

if __name__ == "__main__":
    from supabase import create_client
    MAP_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
    SB_URL = os.environ.get("SUPABASE_URL", "https://sglrflawktvymwujppqt.supabase.co")
    SB_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnbHJmbGF3a3R2eW13dWpwcHF0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk2NDIxNzksImV4cCI6MjA4NTIxODE3OX0.tDVdjdmV1FDe-SjpusA_KdWM4BLEIHE6FbfePMjz7qY")
    
    analizador = AnalizadorIncendiosHistorico(MAP_KEY)
    res = analizador.generar_reporte_completo()
    if res:
        df, evo = res['datos'], res['evolucion']
        analizador.crear_mapa_interactivo(df)
        analizador.crear_graficos_evolucion(evo)
        analizador.exportar_excel_completo(df, evo, 'static/detalle_incendios.xlsx')
        
        # Lógica de Supabase profesional
        supa = create_client(SB_URL, SB_KEY)
        supa.table("stats").upsert({
            "id": 1,
            "total_focos": str(len(df)),
            "riesgo_avg": df['nivel_riesgo'].mode()[0],
            "intensidad_max": f"{df['frp'].mean():.1f} MW",
            "area_critica": f"{evo['superficie_estimada_ha'].iloc[-1]:,.0f} ha",
            "ultima_actualizacion": (datetime.now() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
        }).execute()
