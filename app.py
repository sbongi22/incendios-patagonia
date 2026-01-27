import os
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
from flask import Flask, render_template, send_file

# ==========================================
# LÓGICA DE PROCESAMIENTO (Tu clase original)
# ==========================================
class AnalizadorIncendiosHistorico:
    def __init__(self, map_key):
        self.map_key = map_key
        self.zona_bounds = "-72.5,-47,-69,-42"
        self.fecha_inicio_incendios = datetime(2026, 1, 1)
        self.openmeteo_url = "https://api.open-meteo.com/v1/forecast"

    # ... (Aquí van todos tus métodos: obtener_datos_meteorologicos, 
    # calcular_riesgo_fwi, clasificar_riesgo, agregar_datos_meteorologicos_rapido,
    # obtener_datos_rango_fechas, filtrar_por_confianza, etc.)
    # NOTA: Asegúrate de incluir todos los métodos de tu archivo incendios_v2.py

    def generar_reporte_web(self):
        df = self.obtener_datos_actualizados()
        if df is None or len(df) == 0: return None
        
        df_filtrado = self.filtrar_por_confianza(df, 70)
        df_filtrado = self.agregar_informacion_temporal(df_filtrado)
        df_filtrado = self.agregar_datos_meteorologicos_rapido(df_filtrado)
        
        # Generamos el mapa físicamente en el disco del servidor
        self.crear_mapa_interactivo(df_filtrado, 'mapa_incendios_historico.html')
        
        return {
            'total_focos': len(df_filtrado),
            'riesgo_promedio': round(df_filtrado['indice_riesgo'].mean(), 1),
            'temp_promedio': round(df_filtrado['temperatura_c'].mean(), 1),
            'humedad_promedio': round(df_filtrado['humedad_relativa'].mean(), 1)
        }

# ==========================================
# RUTAS DE FLASK
# ==========================================
app = Flask(__name__)

# Leemos la Key de Render (Environment Variable)
NASA_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
analizador = AnalizadorIncendiosHistorico(NASA_KEY)

@app.route('/')
def index():
    # Ejecutamos el análisis al cargar la página (Cuidado: puede tardar en Render Gratis)
    stats = analizador.generar_reporte_web()
    return render_template('index.html', stats=stats)

@app.route('/mapa')
def ver_mapa():
    # Esta ruta sirve el archivo HTML que genera tu clase
    return send_file('mapa_incendios_historico.html')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)