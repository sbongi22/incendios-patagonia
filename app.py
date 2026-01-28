import os, json, requests
import pandas as pd
from flask import Flask, render_template, send_file
from datetime import datetime
from io import StringIO

app = Flask(__name__)

# Configuramos las rutas absolutas para evitar el "Internal Server Error"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
STATS_FILE = os.path.join(STATIC_DIR, 'stats.json')
EXCEL_FILE = os.path.join(STATIC_DIR, 'detalle_incendios.xlsx')
MAP_FILE = os.path.join(STATIC_DIR, 'mapa_generado.html')

# Aseguramos que la carpeta static existe
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

@app.route('/')
def index():
    # Intentamos leer los datos generados a las 6 AM
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                stats = json.load(f)
        except:
            stats = None
    else:
        stats = None

    # Si no hay datos (o el archivo no existe), pasamos valores por defecto
    if not stats:
        stats = {
            "total_focos": "Pendiente",
            "riesgo_avg": "Procesando",
            "intensidad_max": "---",
            "area_critica": "Patagonia",
            "ultima_actualizacion": "A las 06:00 AM"
        }
    
    return render_template('index.html', stats=stats)

@app.route('/mapa_embed')
def mapa_embed():
    # Esta es la ruta que llama tu iframe en index.html
    if os.path.exists(MAP_FILE):
        return send_file(MAP_FILE)
    return "<h3>El mapa se está procesando. Estará disponible tras la actualización de las 06:00 AM.</h3>"

@app.route('/descargar')
def descargar():
    if os.path.exists(EXCEL_FILE):
        return send_file(EXCEL_FILE, as_attachment=True)
    return "El archivo Excel se está generando.", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)