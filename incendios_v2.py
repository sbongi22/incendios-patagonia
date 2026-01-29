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
    """
    Analiza incendios desde el 1 de enero hasta hoy
    Se actualiza automáticamente cada vez que se ejecuta
    """
    
    def __init__(self, map_key):
        self.map_key = map_key
        
        # Zona ampliada: Patagonia Argentina
        self.zona_bounds = "-72.5,-47,-69,-42"
        
        self.fecha_inicio_incendios = datetime(2026, 1, 1)
        
        # API Open-Meteo (gratis, sin key)
        self.openmeteo_url = "https://api.open-meteo.com/v1/forecast"
    
    def obtener_datos_meteorologicos(self, lat, lon):
        """
        Obtiene datos meteorológicos actuales e históricos de Open-Meteo
        Retorna: viento (km/h), humedad (%), temperatura (°C), lluvia_7d (mm)
        """
        try:
            # Obtener datos actuales y de los últimos 7 días
            params = {
                'latitude': lat,
                'longitude': lon,
                'hourly': 'temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation',
                'past_days': 7,  # Últimos 7 días para lluvia acumulada
                'forecast_days': 0,  # Solo datos históricos/actuales
                'timezone': 'auto'
            }
            
            response = requests.get(self.openmeteo_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Extraer datos de la hora actual (última hora disponible)
            hourly = data['hourly']
            last_idx = len(hourly['time']) - 1
            
            viento_kmh = hourly['wind_speed_10m'][last_idx] * 3.6  # m/s a km/h
            humedad = hourly['relative_humidity_2m'][last_idx]
            temperatura = hourly['temperature_2m'][last_idx]
            
            # Calcular lluvia acumulada a 7 días (suma de precipitación)
            precipitacion_total = sum(hourly['precipitation'][:last_idx+1])
            
            return {
                'viento_kmh': round(viento_kmh, 1),
                'humedad_relativa': round(humedad, 1),
                'temperatura_c': round(temperatura, 1),
                'lluvia_7d_mm': round(precipitacion_total, 1)
            }
            
        except Exception as e:
            print(f"⚠️  Error obteniendo datos meteorológicos: {e}")
            # Datos por defecto en caso de error
            return {
                'viento_kmh': 10.0,
                'humedad_relativa': 50.0,
                'temperatura_c': 20.0,
                'lluvia_7d_mm': 0.0
            }
    
    def calcular_riesgo_fwi(self, viento, humedad, lluvia, temperatura):
        """
        Calcula índice de riesgo FWI simplificado
        Basado en: viento (40%), humedad (30%), lluvia (20%), temperatura (10%)
        """
        # Normalizar valores
        viento_norm = min(viento / 50, 1.0)  # Máx 50 km/h = 1.0
        humedad_norm = (100 - humedad) / 100  # Menor humedad = mayor riesgo
        lluvia_norm = max(0, 1 - (lluvia / 50))  # Más lluvia = menor riesgo
        temp_norm = min((temperatura - 10) / 30, 1.0)  # 10°C base, máx 40°C = 1.0
        
        # Calcular índice (0-100)
        indice = (
            viento_norm * 0.4 +
            humedad_norm * 0.3 +
            lluvia_norm * 0.2 +
            temp_norm * 0.1
        ) * 100
        
        indice = max(0, min(indice, 100))  # Asegurar entre 0-100
        return round(indice, 1)
    
    def clasificar_riesgo(self, indice):
        """
        Clasifica el índice en niveles de riesgo
        """
        if indice < 20:
            return "BAJO"
        elif indice < 40:
            return "MODERADO"
        elif indice < 60:
            return "ALTO"
        elif indice < 80:
            return "MUY ALTO"
        else:
            return "EXTREMO"
    
    def agregar_datos_meteorologicos_rapido(self, df):
        """
        Versión RÁPIDA: Agrupa ubicaciones similares para reducir llamadas API
        """
        print("\n🌤️  Obteniendo datos meteorológicos (modo rápido)...")
        
        # Crear caché para ubicaciones ya consultadas
        cache_meteo = {}
        
        # Agrupar ubicaciones similares (misma lat/lon redondeada)
        print("   Agrupando ubicaciones similares...")
        df['lat_redondeada'] = df['latitude'].round(1)  # Redondear a ~11km
        df['lon_redondeada'] = df['longitude'].round(1)
        
        # Obtener ubicaciones únicas
        ubicaciones_unicas = df[['lat_redondeada', 'lon_redondeada']].drop_duplicates()
        print(f"   {len(ubicaciones_unicas)} ubicaciones únicas de {len(df)} incendios")
        
        datos_meteo = []
        
        # Procesar ubicaciones únicas
        for i, (idx, row) in enumerate(ubicaciones_unicas.iterrows()):
            if i % 10 == 0:
                print(f"   Procesando ubicación {i+1}/{len(ubicaciones_unicas)}...")
            
            lat, lon = row['lat_redondeada'], row['lon_redondeada']
            
            # Verificar caché primero
            cache_key = f"{lat:.1f}_{lon:.1f}"
            if cache_key in cache_meteo:
                datos_meteo.append(cache_meteo[cache_key])
                continue
            
            try:
                # Obtener datos meteorológicos para esta ubicación
                meteo = self.obtener_datos_meteorologicos(lat, lon)
                
                # Calcular riesgo
                indice_riesgo = self.calcular_riesgo_fwi(
                    meteo['viento_kmh'],
                    meteo['humedad_relativa'],
                    meteo['lluvia_7d_mm'],
                    meteo['temperatura_c']
                )
                
                nivel_riesgo = self.clasificar_riesgo(indice_riesgo)
                
                # Datos para esta ubicación
                datos_ubicacion = {
                    'lat_redondeada': lat,
                    'lon_redondeada': lon,
                    'viento_kmh': meteo['viento_kmh'],
                    'humedad_relativa': meteo['humedad_relativa'],
                    'temperatura_c': meteo['temperatura_c'],
                    'lluvia_7d_mm': meteo['lluvia_7d_mm'],
                    'indice_riesgo': indice_riesgo,
                    'nivel_riesgo': nivel_riesgo
                }
                
                # Guardar en caché
                cache_meteo[cache_key] = datos_ubicacion
                datos_meteo.append(datos_ubicacion)
                
                # Pequeña pausa para no saturar API
                if i % 20 == 0 and i > 0:
                    time.sleep(0.1)
                    
            except Exception as e:
                print(f"⚠️  Error en ubicación {lat},{lon}: {e}")
                # Datos por defecto
                datos_default = {
                    'lat_redondeada': lat,
                    'lon_redondeada': lon,
                    'viento_kmh': 10.0,
                    'humedad_relativa': 50.0,
                    'temperatura_c': 20.0,
                    'lluvia_7d_mm': 0.0,
                    'indice_riesgo': 25.0,
                    'nivel_riesgo': "MODERADO"
                }
                cache_meteo[cache_key] = datos_default
                datos_meteo.append(datos_default)
        
        # Crear DataFrame de datos meteorológicos únicos
        df_meteo_unicos = pd.DataFrame(datos_meteo)
        
        # Unir con el DataFrame original
        df_completo = pd.merge(
            df,
            df_meteo_unicos,
            on=['lat_redondeada', 'lon_redondeada'],
            how='left'
        )
        
        # Eliminar columnas temporales
        df_completo = df_completo.drop(columns=['lat_redondeada', 'lon_redondeada'])
        
        print(f"✅ Datos meteorológicos agregados a {len(df)} incendios")
        print(f"   📊 Llamadas API reducidas: de {len(df)} a {len(ubicaciones_unicas)}")
        
        # Mostrar resumen de riesgos
        distribucion = df_completo['nivel_riesgo'].value_counts()
        print("\n📊 Distribución de riesgos:")
        for nivel, cantidad in distribucion.items():
            porcentaje = cantidad / len(df_completo) * 100
            print(f"   {nivel}: {cantidad} incendios ({porcentaje:.1f}%)")
        
        print(f"   📈 Índice de riesgo promedio: {df_completo['indice_riesgo'].mean():.1f}/100")
        
        return df_completo
    
    def obtener_datos_rango_fechas(self, fecha_inicio, fecha_fin, fuente="VIIRS_SNPP_NRT"):
        """
        Descarga datos dividiendo el rango en bloques de 5 días
        """
        todos_los_datos = []
        fecha_actual = fecha_inicio
        
        print(f"\n📅 Descargando datos desde {fecha_inicio.strftime('%Y-%m-%d')} hasta {fecha_fin.strftime('%Y-%m-%d')}")
        print(f"🗺️  Zona: Patagonia")
        print(f"📍 Coordenadas: {self.zona_bounds}")
        print(f"Total de días: {(fecha_fin - fecha_inicio).days + 1}")
        print("-" * 70)
        
        bloque_num = 1
        
        while fecha_actual <= fecha_fin:
            # Calcular el fin del bloque (máximo 5 días o hasta fecha_fin)
            dias_restantes = (fecha_fin - fecha_actual).days + 1
            dias_bloque = min(5, dias_restantes)
            fecha_fin_bloque = fecha_actual + timedelta(days=dias_bloque - 1)
            
            # Formatear fecha para la API (YYYY-MM-DD)
            fecha_str = fecha_actual.strftime('%Y-%m-%d')
            
            # URL con fecha específica
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{self.map_key}/{fuente}/{self.zona_bounds}/{dias_bloque}/{fecha_str}"
            
            print(f"Bloque {bloque_num}: {fecha_actual.strftime('%Y-%m-%d')} → {fecha_fin_bloque.strftime('%Y-%m-%d')} ({dias_bloque} días)")
            
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                
                respuesta_texto = response.text.strip()
                
                # Verificar si hay errores
                if "Invalid" in respuesta_texto or "Error" in respuesta_texto:
                    print(f"   ⚠️  Error de API: {respuesta_texto[:100]}")
                else:
                    # Leer CSV
                    df_bloque = pd.read_csv(StringIO(respuesta_texto))
                    
                    if len(df_bloque) > 0 and 'acq_date' in df_bloque.columns:
                        todos_los_datos.append(df_bloque)
                        print(f"   ✓ {len(df_bloque)} detecciones descargadas")
                    else:
                        print(f"   • Sin incendios en este período")
                
                # Pausa para no saturar la API
                time.sleep(0.5)
                
            except Exception as e:
                print(f"   ✗ Error: {e}")
            
            # Avanzar al siguiente bloque
            fecha_actual = fecha_fin_bloque + timedelta(days=1)
            bloque_num += 1
        
        print("-" * 70)
        
        # Combinar todos los DataFrames
        if len(todos_los_datos) > 0:
            df_completo = pd.concat(todos_los_datos, ignore_index=True)
            # Convertir fecha
            df_completo['acq_date'] = pd.to_datetime(df_completo['acq_date'])
            # Eliminar duplicados (por si hay overlap)
            df_completo = df_completo.drop_duplicates(subset=['latitude', 'longitude', 'acq_date', 'acq_time'])
            
            print(f"\n✅ TOTAL DESCARGADO: {len(df_completo)} detecciones únicas")
            return df_completo
        else:
            print(f"\n⚠️  No se encontraron datos")
            return None
    
    def obtener_datos_actualizados(self, fuente="VIIRS_SNPP_NRT"):
        """
        Descarga datos desde el 1 de enero hasta hoy
        Solo para la zona de la Patagonia (Argentina)
        """
        fecha_fin = datetime.now()
        
        print("\n" + "="*70)
        print("🔥 DESCARGA DE DATOS HISTÓRICOS DE INCENDIOS")
        print("="*70)
        print(f"Fecha de inicio: {self.fecha_inicio_incendios.strftime('%d/%m/%Y')}")
        print(f"Fecha de fin: {fecha_fin.strftime('%d/%m/%Y')} (hoy)")
        
        df = self.obtener_datos_rango_fechas(self.fecha_inicio_incendios, fecha_fin, fuente)
        
        # Filtrar solo Argentina de forma más precisa
        if df is not None and len(df) > 0:
            df_original = len(df)
            df = df[df['longitude'] > -72.2].copy()
            if len(df) < df_original:
                focos_excluidos = df_original - len(df)
                print(f"\n🇦🇷 Filtrado Chile: {len(df)} detecciones ({focos_excluidos} focos excluidos por estar en territorio chileno)")
            
            print(f"📍 Rango de longitudes: {df['longitude'].min():.2f}° a {df['longitude'].max():.2f}°")
            print(f"📍 Rango de latitudes: {df['latitude'].min():.2f}° a {df['latitude'].max():.2f}°")
        
        return df
    
    def filtrar_por_confianza(self, df, confianza_minima=70):
        """Filtra detecciones por nivel de confianza"""
        
        # Convertir confidence a numérico si viene como texto
        if df['confidence'].dtype == 'object':
            # Mapear valores textuales a numéricos
            confidence_map = {
                'low': 30,
                'nominal': 60,
                'high': 90,
                'l': 30,
                'n': 60,
                'h': 90
            }
            
            # Intentar convertir, si falla usar el mapeo
            def convertir_confidence(val):
                try:
                    return float(val)
                except:
                    return confidence_map.get(str(val).lower(), 50)
            
            df['confidence'] = df['confidence'].apply(convertir_confidence)
        
        df_filtrado = df[df['confidence'] >= confianza_minima].copy()
        print(f"\n📊 Filtrado por confianza >={confianza_minima}%: {len(df_filtrado)} de {len(df)} detecciones ({len(df_filtrado)/len(df)*100:.1f}%)")
        return df_filtrado
    
    def agregar_informacion_temporal(self, df):
        """Agrega columnas de tiempo"""
        df['semana'] = df['acq_date'].dt.isocalendar().week
        df['año'] = df['acq_date'].dt.year
        df['mes'] = df['acq_date'].dt.month
        df['dia_semana'] = df['acq_date'].dt.day_name()
        return df
    
    def analizar_evolucion_diaria(self, df):
        """Analiza evolución día por día"""
        evolucion = df.groupby('acq_date').agg({
            'latitude': 'count',
            'frp': ['sum', 'mean', 'max'],
            'confidence': 'mean'
        }).round(2)
        
        evolucion.columns = ['focos_nuevos', 'frp_total', 'frp_promedio', 'frp_maximo', 'confianza']
        evolucion = evolucion.reset_index()
        evolucion['focos_acumulados'] = evolucion['focos_nuevos'].cumsum()
        evolucion['superficie_estimada_ha'] = evolucion['focos_acumulados'] * 14
        
        return evolucion
    
    def crear_mapa_interactivo(self, df, nombre_archivo='mapa_incendios_historico.html'):
        """Crea mapa con todos los incendios desde el 1 de enero"""
        if len(df) == 0:
            print("⚠️  No hay datos para mapear")
            return
        
        centro_lat = df['latitude'].mean()
        centro_lon = df['longitude'].mean()
        
        mapa = folium.Map(
            location=[centro_lat, centro_lon],
            zoom_start=6,
            tiles='OpenStreetMap'
        )
        
        # Mapa de calor
        datos_calor = df[['latitude', 'longitude', 'frp']].values.tolist()
        HeatMap(datos_calor, radius=15, blur=20, max_zoom=13).add_to(mapa)
        
        # Marcadores agrupados por riesgo
        marker_cluster = MarkerCluster().add_to(mapa)
        
        # Colores según riesgo
        colores_riesgo = {
            "BAJO": "green",
            "MODERADO": "lightgreen",
            "ALTO": "orange",
            "MUY ALTO": "red",
            "EXTREMO": "purple"
        }
        
        for idx, row in df.iterrows():
            # Color según riesgo
            color = colores_riesgo.get(row['nivel_riesgo'], 'gray')
            
            popup_text = f"""
            <b>🔥 Incendio - Riesgo: {row['nivel_riesgo']}</b><br>
            📅 {row['acq_date'].strftime('%d/%m/%Y')}<br>
            🕐 {row['acq_time']}<br>
            ⚡ FRP: {row['frp']:.1f} MW<br>
            ✅ Confianza: {row['confidence']:.0f}%<br>
            📍 {row['latitude']:.4f}, {row['longitude']:.4f}<br>
            <hr>
            <b>🌤️ Datos Meteorológicos:</b><br>
            💨 Viento: {row['viento_kmh']} km/h<br>
            💧 Humedad: {row['humedad_relativa']}%<br>
            🌡️ Temperatura: {row['temperatura_c']}°C<br>
            🌧️ Lluvia 7d: {row['lluvia_7d_mm']} mm<br>
            ⚠️ Índice Riesgo: {row['indice_riesgo']}/100
            """
            
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=folium.Popup(popup_text, max_width=300),
                icon=folium.Icon(color=color, icon='fire', prefix='fa'),
                tooltip=f"Riesgo: {row['nivel_riesgo']} - FRP: {row['frp']:.1f} MW"
            ).add_to(marker_cluster)
        
        # Leyenda actualizada con riesgo
        leyenda_html = f'''
        <div style="position: fixed; 
                    bottom: 50px; right: 50px; width: 320px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 12px; border-radius: 5px;">
        <p style="margin:0; font-weight:bold; font-size:14px;">🔥 Incendios Patagonia Argentina</p>
        <p style="margin:5px 0; font-size:11px; color:#666;">Del 1/1/2026 al {datetime.now().strftime('%d/%m/%Y')}</p>
        
        <hr style="margin: 8px 0;">
        
        <p style="margin:3px 0; font-weight:bold;">📊 Niveles de Riesgo:</p>
        <p style="margin:2px 0;"><span style="color:green;">●</span> BAJO (0-20)</p>
        <p style="margin:2px 0;"><span style="color:lightgreen;">●</span> MODERADO (21-40)</p>
        <p style="margin:2px 0;"><span style="color:orange;">●</span> ALTO (41-60)</p>
        <p style="margin:2px 0;"><span style="color:red;">●</span> MUY ALTO (61-80)</p>
        <p style="margin:2px 0;"><span style="color:purple;">●</span> EXTREMO (81-100)</p>
        
        <hr style="margin: 8px 0;">
        
        <p style="margin:3px 0;"><span style="color:red;">●</span> Alta intensidad (&gt;100 MW)</p>
        <p style="margin:3px 0;"><span style="color:orange;">●</span> Media (50-100 MW)</p>
        <p style="margin:3px 0;"><span style="color:gold;">●</span> Baja (&lt;50 MW)</p>
        
        <p style="margin:8px 0 0 0; font-size:11px; color:gray;">
        Total: {len(df):,} detecciones<br>
        Riesgo promedio: {df['indice_riesgo'].mean():.1f}/100
        </p>
        </div>
        '''
        mapa.get_root().html.add_child(folium.Element(leyenda_html))
        
        mapa.save(nombre_archivo)
        print(f"✓ Mapa guardado: {nombre_archivo}")
        
        return mapa
    
    def crear_graficos_evolucion(self, evolucion, nombre_archivo='evolucion_historica.html'):
        """Crea gráficos de evolución temporal"""
        fig = make_subplots(
            rows=4, cols=1,
            subplot_titles=(
                '🔥 Focos detectados por día',
                '📈 Focos acumulados en el tiempo',
                '📏 Superficie estimada afectada (hectáreas)',
                '⚡ Intensidad promedio del fuego (FRP)'
            ),
            vertical_spacing=0.08,
            row_heights=[0.25, 0.25, 0.25, 0.25]
        )
        
        # Gráfico 1: Focos diarios
        fig.add_trace(
            go.Bar(
                x=evolucion['acq_date'],
                y=evolucion['focos_nuevos'],
                name='Focos por día',
                marker_color='orangered',
                hovertemplate='<b>%{x|%d/%m/%Y}</b><br>Focos: %{y}<extra></extra>'
            ),
            row=1, col=1
        )
        
        # Gráfico 2: Acumulados
        fig.add_trace(
            go.Scatter(
                x=evolucion['acq_date'],
                y=evolucion['focos_acumulados'],
                name='Focos acumulados',
                mode='lines',
                line=dict(color='crimson', width=3),
                fill='tozeroy',
                fillcolor='rgba(220, 20, 60, 0.2)',
                hovertemplate='<b>%{x|%d/%m/%Y}</b><br>Total: %{y:,}<extra></extra>'
            ),
            row=2, col=1
        )
        
        # Gráfico 3: Superficie
        fig.add_trace(
            go.Scatter(
                x=evolucion['acq_date'],
                y=evolucion['superficie_estimada_ha'],
                name='Superficie',
                mode='lines+markers',
                line=dict(color='darkred', width=3),
                marker=dict(size=6),
                hovertemplate='<b>%{x|%d/%m/%Y}</b><br>%{y:,.0f} ha<extra></extra>'
            ),
            row=3, col=1
        )
        
        # Gráfico 4: FRP
        fig.add_trace(
            go.Scatter(
                x=evolucion['acq_date'],
                y=evolucion['frp_promedio'],
                name='FRP promedio',
                mode='lines+markers',
                line=dict(color='orange', width=2),
                marker=dict(size=6),
                hovertemplate='<b>%{x|%d/%m/%Y}</b><br>%{y:.1f} MW<extra></extra>'
            ),
            row=4, col=1
        )
        
        # Layout
        fig.update_xaxes(title_text="Fecha", row=4, col=1)
        fig.update_yaxes(title_text="Cantidad", row=1, col=1)
        fig.update_yaxes(title_text="Focos totales", row=2, col=1)
        fig.update_yaxes(title_text="Hectáreas", row=3, col=1)
        fig.update_yaxes(title_text="MW", row=4, col=1)
        
        fig.update_layout(
            height=1200,
            title_text=f"<b>📊 Evolución de Incendios Patagonia Argentina - Del 1/01/2026 al {datetime.now().strftime('%d/%m/%Y')}</b>",
            title_font_size=18,
            showlegend=False,
            template="plotly_white",
            hovermode='x unified'
        )
        
        fig.write_html(nombre_archivo)
        print(f"✓ Gráficos guardados: {nombre_archivo}")
        
        return fig
    
    def exportar_excel_completo(self, df, evolucion, nombre_archivo=None):
        """Exporta TODO en un solo archivo Excel con múltiples pestañas"""
        print("\n📂 Generando archivo Excel completo...")
        
        if nombre_archivo is None:
            fecha_str = datetime.now().strftime("%Y%m%d_%H%M")
            nombre_archivo = f'analisis_incendios_completo_{fecha_str}.xlsx'
        
        try:
            # Crear archivo Excel
            with pd.ExcelWriter(nombre_archivo, engine='openpyxl') as writer:
                
                # PESTAÑA 1: Detalle completo CON DATOS METEOROLÓGICOS
                print("   📋 Generando pestaña 'Detalle' con datos meteorológicos...")
                df_export = df.copy()
                df_export['acq_date'] = df_export['acq_date'].dt.strftime('%Y-%m-%d')
                
                # Reordenar columnas para mejor visualización
                column_order = [
                    'acq_date', 'acq_time', 'latitude', 'longitude',
                    'frp', 'confidence', 
                    'viento_kmh', 'humedad_relativa', 'temperatura_c', 'lluvia_7d_mm',
                    'indice_riesgo', 'nivel_riesgo'
                ]
                
                # Mantener otras columnas si existen
                otras_columnas = [col for col in df_export.columns if col not in column_order]
                column_order.extend(otras_columnas)
                
                df_export = df_export[column_order]
                df_export.to_excel(writer, sheet_name='Detalle', index=False)
                
                # PESTAÑA 2: Evolución diaria
                print("   📊 Generando pestaña 'Evolución Diaria'...")
                evolucion_export = evolucion.copy()
                evolucion_export['acq_date'] = evolucion_export['acq_date'].dt.strftime('%Y-%m-%d')
                evolucion_export.to_excel(writer, sheet_name='Evolución Diaria', index=False)
                
                # PESTAÑA 3: Resumen semanal
                print("   📅 Generando pestaña 'Resumen Semanal'...")
                semanal = df.groupby(['año', 'semana']).agg({
                    'latitude': 'count',
                    'frp': ['mean', 'max', 'sum'],
                    'confidence': 'mean',
                    'acq_date': ['min', 'max']
                }).round(2)
                semanal.columns = ['focos', 'frp_promedio', 'frp_maximo', 'frp_total', 'confianza_promedio', 'fecha_inicio', 'fecha_fin']
                semanal = semanal.reset_index()
                semanal['superficie_estimada_ha'] = semanal['focos'] * 14
                semanal['fecha_inicio'] = pd.to_datetime(semanal['fecha_inicio']).dt.strftime('%Y-%m-%d')
                semanal['fecha_fin'] = pd.to_datetime(semanal['fecha_fin']).dt.strftime('%Y-%m-%d')
                semanal.to_excel(writer, sheet_name='Resumen Semanal', index=False)
                
                # PESTAÑA 4: Top 10 días más críticos
                print("   🔥 Generando pestaña 'Top 10 Días'...")
                top_dias = evolucion.nlargest(10, 'focos_nuevos').copy()
                top_dias['acq_date'] = pd.to_datetime(top_dias['acq_date']).dt.strftime('%Y-%m-%d')
                top_dias = top_dias[['acq_date', 'focos_nuevos', 'frp_maximo', 'frp_promedio', 'superficie_estimada_ha']]
                top_dias.columns = ['Fecha', 'Focos Detectados', 'FRP Máximo (MW)', 'FRP Promedio (MW)', 'Superficie Estimada (ha)']
                top_dias.to_excel(writer, sheet_name='Top 10 Días', index=False)
                
                # PESTAÑA 5: Resumen meteorológico y de riesgo
                print("   🌤️  Generando pestaña 'Resumen Meteorológico'...")
                
                # Estadísticas de riesgo
                riesgo_data = {
                    'Métrica': [
                        'Número total de incendios analizados',
                        'Índice de riesgo promedio',
                        'Nivel de riesgo predominante',
                        'Incendios con riesgo BAJO',
                        'Incendios con riesgo MODERADO',
                        'Incendios con riesgo ALTO',
                        'Incendios con riesgo MUY ALTO',
                        'Incendios con riesgo EXTREMO',
                        'Porcentaje con riesgo ALTO o superior',
                        'Viento promedio (km/h)',
                        'Humedad relativa promedio (%)',
                        'Temperatura promedio (°C)',
                        'Lluvia 7d promedio (mm)'
                    ],
                    'Valor': [
                        len(df),
                        f"{df['indice_riesgo'].mean():.1f}",
                        df['nivel_riesgo'].mode()[0] if len(df['nivel_riesgo'].mode()) > 0 else "N/A",
                        len(df[df['nivel_riesgo'] == 'BAJO']),
                        len(df[df['nivel_riesgo'] == 'MODERADO']),
                        len(df[df['nivel_riesgo'] == 'ALTO']),
                        len(df[df['nivel_riesgo'] == 'MUY ALTO']),
                        len(df[df['nivel_riesgo'] == 'EXTREMO']),
                        f"{len(df[df['indice_riesgo'] >= 40]) / len(df) * 100:.1f}%",
                        f"{df['viento_kmh'].mean():.1f}",
                        f"{df['humedad_relativa'].mean():.1f}",
                        f"{df['temperatura_c'].mean():.1f}",
                        f"{df['lluvia_7d_mm'].mean():.1f}"
                    ]
                }
                riesgo_df = pd.DataFrame(riesgo_data)
                riesgo_df.to_excel(writer, sheet_name='Resumen Meteorológico', index=False)
                
                # PESTAÑA 6: Resumen general
                print("   📈 Generando pestaña 'Resumen General'...")
                resumen_data = {
                    'Métrica': [
                        'Fecha inicio',
                        'Fecha fin',
                        'Días totales analizados',
                        'Total de detecciones',
                        'Total de detecciones alta confianza (>70%)',
                        'Superficie estimada total (hectáreas)',
                        'FRP promedio general (MW)',
                        'FRP máximo registrado (MW)',
                        'Confianza promedio (%)',
                        'Día con más focos',
                        'Cantidad máxima de focos en un día',
                        'Índice de riesgo promedio',
                        'Nivel de riesgo predominante',
                        'Última actualización'
                    ],
                    'Valor': [
                        df['acq_date'].min().strftime('%d/%m/%Y'),
                        df['acq_date'].max().strftime('%d/%m/%Y'),
                        (df['acq_date'].max() - df['acq_date'].min()).days + 1,
                        len(df),
                        len(df[df['confidence'] >= 70]),
                        f"{evolucion['superficie_estimada_ha'].iloc[-1]:,.0f}",
                        f"{df['frp'].mean():.1f}",
                        f"{df['frp'].max():.1f}",
                        f"{df['confidence'].mean():.1f}",
                        evolucion.loc[evolucion['focos_nuevos'].idxmax(), 'acq_date'].strftime('%d/%m/%Y'),
                        evolucion['focos_nuevos'].max(),
                        f"{df['indice_riesgo'].mean():.1f}/100",
                        df['nivel_riesgo'].mode()[0] if len(df['nivel_riesgo'].mode()) > 0 else "N/A",
                        datetime.now().strftime('%d/%m/%Y %H:%M')
                    ]
                }
                resumen_df = pd.DataFrame(resumen_data)
                resumen_df.to_excel(writer, sheet_name='Resumen General', index=False)
                
                # Ajustar anchos de columna
                for sheet_name in writer.sheets:
                    worksheet = writer.sheets[sheet_name]
                    for column in worksheet.columns:
                        max_length = 0
                        column_cells = [cell for cell in column]
                        for cell in column_cells:
                            try:
                                if len(str(cell.value)) > max_length:
                                    max_length = len(cell.value)
                            except:
                                pass
                        adjusted_width = min(max_length + 2, 50)
                        worksheet.column_dimensions[column_cells[0].column_letter].width = adjusted_width
            
            print(f"\n✅ Archivo Excel generado: {nombre_archivo}")
            print(f"   📑 6 pestañas creadas:")
            print(f"      1. Detalle - Con datos meteorológicos y riesgo")
            print(f"      2. Evolución Diaria - Día por día")
            print(f"      3. Resumen Semanal - Agrupado por semana")
            print(f"      4. Top 10 Días - Días más críticos")
            print(f"      5. Resumen Meteorológico - Estadísticas de clima y riesgo")
            print(f"      6. Resumen General - Estadísticas principales")
            
            return nombre_archivo
            
        except ImportError:
            print("\n⚠️  No se pudo generar Excel. Falta la librería 'openpyxl'")
            print("   Instala con: pip install openpyxl")
            print("\n   Generando CSVs alternativos...")
            
            # Fallback a CSVs individuales
            df.to_csv('incendios_detalle.csv', index=False, encoding='utf-8')
            evolucion.to_csv('incendios_evolucion_diaria.csv', index=False, encoding='utf-8')
            print("   ✓ CSVs generados como alternativa")
            return None
    
    def generar_reporte_completo(self, confianza_minima=70):
        """
        Genera el reporte completo desde el 1 de enero hasta hoy
        """
        print("\n" + "="*70)
        print("🔥 ANÁLISIS COMPLETO DE INCENDIOS - SUR DE ARGENTINA")
        print("="*70)
        
        # 1. Descargar datos
        df = self.obtener_datos_actualizados()
        
        if df is None or len(df) == 0:
            print("\n❌ No se encontraron datos de incendios")
            return None
        
        # 2. Filtrar por confianza
        df_filtrado = self.filtrar_por_confianza(df, confianza_minima)
        
        if len(df_filtrado) == 0:
            print(f"\n⚠️  No hay detecciones con confianza >={confianza_minima}%")
            return None
        
        # 3. Procesar datos temporales
        print("\n⚙️  Procesando datos temporales...")
        df_filtrado = self.agregar_informacion_temporal(df_filtrado)
        
        # 4. Agregar datos meteorológicos y calcular riesgo (MÉTODO RÁPIDO)
        df_filtrado = self.agregar_datos_meteorologicos_rapido(df_filtrado)
        
        # 5. Analizar evolución
        evolucion = self.analizar_evolucion_diaria(df_filtrado)
        
        # 6. Crear visualizaciones
        print("\n🎨 Generando visualizaciones...")
        #self.crear_mapa_interactivo(df_filtrado)
        #self.crear_graficos_evolucion(evolucion)
        
        # 7. Exportar Excel completo
        archivo_excel = None
        
        # 8. Resumen final
        print("\n" + "="*70)
        print("📋 RESUMEN FINAL")
        print("="*70)
        print(f"📅 Período: {df_filtrado['acq_date'].min().strftime('%d/%m/%Y')} → {df_filtrado['acq_date'].max().strftime('%d/%m/%Y')}")
        print(f"📆 Días totales: {(df_filtrado['acq_date'].max() - df_filtrado['acq_date'].min()).days + 1}")
        print(f"🔥 Total detecciones: {len(df_filtrado):,}")
        
        # Resumen de riesgo
        riesgo_promedio = df_filtrado['indice_riesgo'].mean()
        nivel_predominante = df_filtrado['nivel_riesgo'].mode()[0] if len(df_filtrado['nivel_riesgo'].mode()) > 0 else "N/A"
        focos_alto_riesgo = len(df_filtrado[df_filtrado['indice_riesgo'] >= 40])
        
        print(f"⚠️  Índice de riesgo promedio: {riesgo_promedio:.1f}/100 ({nivel_predominante})")
        print(f"🚨 Focos con riesgo ALTO o superior: {focos_alto_riesgo} ({focos_alto_riesgo/len(df_filtrado)*100:.1f}%)")
        
        # Condiciones meteorológicas promedio
        print(f"🌤️  Condiciones promedio:")
        print(f"   💨 Viento: {df_filtrado['viento_kmh'].mean():.1f} km/h")
        print(f"   💧 Humedad: {df_filtrado['humedad_relativa'].mean():.1f}%")
        print(f"   🌡️ Temperatura: {df_filtrado['temperatura_c'].mean():.1f}°C")
        print(f"   🌧️ Lluvia 7d: {df_filtrado['lluvia_7d_mm'].mean():.1f} mm")
        
        print(f"📊 Día con más focos: {evolucion.loc[evolucion['focos_nuevos'].idxmax(), 'acq_date'].strftime('%d/%m/%Y')} ({evolucion['focos_nuevos'].max()} focos)")
        print(f"📏 Superficie estimada total: {evolucion['superficie_estimada_ha'].iloc[-1]:,.0f} hectáreas")
        print(f"⚡ FRP máximo registrado: {df_filtrado['frp'].max():.1f} MW")
        print(f"📈 FRP promedio general: {df_filtrado['frp'].mean():.1f} MW")
        print(f"✅ Confianza promedio: {df_filtrado['confidence'].mean():.1f}%")
        
        print("\n📂 ARCHIVOS GENERADOS:")
        print("   🗺️  mapa_incendios_historico.html - Mapa interactivo con riesgo")
        print("   📊 evolucion_historica.html - Gráficos de evolución")
        if archivo_excel: 
            print(f"   📗 {archivo_excel} - Excel con 6 pestañas incluyendo:")
            print("      • Detalle - Con datos meteorológicos completos")
            print("      • Resumen Meteorológico - Estadísticas de clima")
            print("      • Evolución Diaria - Día por día")
            print("      • Resumen Semanal - Por semana")
            print("      • Top 10 Días - Días críticos")
            print("      • Resumen General - Estadísticas principales")
        
        print("\n💡 PRÓXIMOS PASOS:")
        print("   • Abre los .html en tu navegador para explorar")
        print("   • Ejecuta este script nuevamente mañana para actualizar con datos nuevos")
        print("   • Los datos se descargan siempre desde el 1/01/2026 hasta hoy")
        print("="*70 + "\n")
        
        return {
            'datos': df_filtrado,
            'evolucion': evolucion
        }


# ============================================================
# EJECUTAR ANÁLISIS
# ============================================================
if __name__ == "__main__":
    import os
    from supabase import create_client
    
    MAP_KEY = os.environ.get("MAP_KEY", "a66ff23e6b0f370791cb4bd2dd3123d0")
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://sglrflawktvymwujppqt.supabase.co")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNnbHJmbGF3a3R2eW13dWpwcHF0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk2NDIxNzksImV4cCI6MjA4NTIxODE3OX0.tDVdjdmV1FDe-SjpusA_KdWM4BLEIHE6FbfePMjz7qY")

    analizador = AnalizadorIncendiosHistorico(MAP_KEY)
    
    # 1. Generar reporte
    resultados = analizador.generar_reporte_completo()
    df = resultados['datos']
    evolucion = resultados['evolucion']
    
    # 2. GUARDAR EN STATIC (Nombres fijos para que app.py los encuentre)
    print("Generando archivos en carpeta static...")
    analizador.crear_mapa_interactivo(df, nombre_archivo='static/mapa_generado.html')
    analizador.crear_graficos_evolucion(evolucion, nombre_archivo='static/evolucion_historica.html')
    
    # Forzamos el nombre exacto que espera app.py
    analizador.exportar_excel_completo(df, evolucion, nombre_archivo='static/detalle_incendios.xlsx')
    
    # 3. ACTUALIZAR SUPABASE
    try:
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
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
        sb.table("stats").upsert(nuevos_stats).execute()
        print("\n🚀 ¡ÉXITO! Todo en /static y Supabase actualizado.")
    except Exception as e:
        print(f"❌ Error Supabase: {e}")