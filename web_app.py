import requests
import json
from flask import Flask, request, jsonify, Response
from datetime import datetime, timedelta, timezone
import os
import math

# --- 1. PYTHON BACKEND LOGIC (using Flask) ---

# The Flask application instance is named 'app', matching the gunicorn command: web_app:app
app = Flask(__name__)

# --- Configuration ---
# NOTE: Using a hardcoded key here for functional demonstration. 
# For true production, use environment variables (e.g., os.environ.get('OWM_API_KEY')).
OWM_API_KEY = "207cf060d7c9af525f46c1e0f15b5b60"
OWM_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OM_AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OM_FORECAST_URL = "https://api.open-meteo.com/v1/forecast" 

UNITS = "metric"

# --- Python Helper Functions ---
def deg_to_cardinal(deg):
    """Converts degrees to a cardinal wind direction."""
    if deg is None: return "N/A"
    val = int((deg / 22.5) + 0.5)
    arr = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return arr[(val % 16)]

def get_aqi_status_and_color(aqi_value):
    """Returns AQI status and a class name for styling (used by frontend)."""
    if aqi_value is None:
        return {"status": "N/A", "colorClasses": "aqi-na"}
    if aqi_value <= 50:
        return {"status": "Good", "colorClasses": "aqi-good"}
    elif aqi_value <= 100:
        return {"status": "Moderate", "colorClasses": "aqi-moderate"}
    elif aqi_value <= 150:
        return {"status": "Unhealthy for Sensitive Groups", "colorClasses": "aqi-sensitive"}
    elif aqi_value <= 200:
        return {"status": "Unhealthy", "colorClasses": "aqi-unhealthy"}
    elif aqi_value <= 300:
        return {"status": "Very Unhealthy", "colorClasses": "aqi-very-unhealthy"}
    else:
        return {"status": "Hazardous", "colorClasses": "aqi-hazardous"}

def get_uv_risk(uvi):
    """Returns UV risk level based on the index (used by frontend)."""
    if uvi is None or (isinstance(uvi, str) and uvi == 'N/A') or (isinstance(uvi, (float, int)) and math.isnan(uvi)): 
        return "N/A"
    uvi = float(uvi)
    if uvi < 3: return "Low Risk"
    if uvi < 6: return "Moderate Risk"
    if uvi < 8: return "High Risk"
    if uvi < 11: return "Very High Risk"
    return "Extreme Risk"

def map_wmo_to_lucide_icon(code, is_day=1):
    """Maps WMO weather codes (Open-Meteo) to Lucide icon names."""
    if code in [0]: return 'sun' if is_day else 'moon' 
    if code in [1, 2, 3]: return 'cloud-sun' if is_day else 'cloud-moon'
    if code in [45, 48]: return 'fog'
    if code in [51, 53, 55]: return 'cloud-drizzle'
    if code in [56, 57]: return 'snow-flake' if is_day else 'cloud-snow'
    if code in [61, 63, 65, 80, 81, 82]: return 'cloud-rain'
    if code in [66, 67]: return 'cloud-drizzle'
    if code in [71, 73, 75, 85, 86]: return 'snow-flake'
    if code in [77]: return 'cloud-hail'
    if code in [95, 96, 99]: return 'cloud-lightning'
    return 'cloud'

def format_hourly_forecast(hourly_data, timezone_offset):
    """Processes Open-Meteo hourly data into a simplified list for the frontend."""
    if not hourly_data or not hourly_data.get('time'):
        return []

    forecast_list = []
    for i in range(min(8, len(hourly_data['time']))):
        is_day = hourly_data.get('is_day', [1])[i]
        weather_code = hourly_data.get('weather_code', [800])[i]

        forecast_list.append({
            'time': hourly_data['time'][i],
            'temperature': f"{hourly_data.get('temperature_2m', [None])[i]:.0f}°",
            'iconName': map_wmo_to_lucide_icon(weather_code, is_day)
        })
    return forecast_list
    
def format_daily_forecast(daily_data):
    """Processes Open-Meteo daily data for 7-day view."""
    if not daily_data or not daily_data.get('time'):
        return []

    forecast_list = []
    for i in range(min(7, len(daily_data['time']))):
        date_str = daily_data['time'][i]
        weather_code = daily_data.get('weather_code', [800])[i]
        temp_max = daily_data.get('temperature_2m_max', [None])[i]
        temp_min = daily_data.get('temperature_2m_min', [None])[i]
        
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = "Today" if i == 0 else date_obj.strftime("%a")

        forecast_list.append({
            'day': day_name,
            'iconName': map_wmo_to_lucide_icon(weather_code, is_day=1),
            'tempMax': f"{temp_max:.0f}°" if temp_max is not None else '--',
            'tempMin': f"{temp_min:.0f}°" if temp_min is not None else '--',
        })
    return forecast_list

def get_background_gradient(description):
    """Maps weather description to a professional Tailwind gradient class."""
    desc = description.lower()
    if 'clear' in desc or 'sun' in desc:
        return "bg-gradient-to-br from-blue-200 to-yellow-100 text-gray-900"
    if 'cloud' in desc or 'overcast' in desc:
        return "bg-gradient-to-br from-gray-200 to-blue-100 text-gray-900"
    if 'rain' in desc or 'shower' in desc or 'drizzle' in desc:
        return "bg-gradient-to-br from-slate-400 to-blue-500 text-white"
    if 'thunder' in desc:
        return "bg-gradient-to-br from-slate-800 to-purple-800 text-white"
    if 'snow' in desc or 'sleet' in desc:
        return "bg-gradient-to-br from-white to-sky-200 text-gray-900"
    if 'mist' in desc or 'fog' in desc or 'haze' in desc:
        return "bg-gradient-to-br from-gray-300 to-gray-100 text-gray-900"
    return "bg-gradient-to-br from-indigo-100 to-white text-gray-900"

# --- API Endpoint 1: The Data (Handles API calls) ---
@app.route('/api/weather')
def get_weather_data():
    city_name = request.args.get('city')
    if not city_name:
        return jsonify({"error": "A 'city' query parameter is required."}), 400

    # 1. Fetch Core Weather (OWM)
    owm_params = {'q': city_name, 'units': UNITS, 'appid': OWM_API_KEY}
    try:
        weather_response = requests.get(OWM_WEATHER_URL, params=owm_params, timeout=5)
        weather_response.raise_for_status()
        weather_data = weather_response.json()
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == 404:
            return jsonify({"error": f"City '{city_name}' not found."}), 404
        # Return generic error for other HTTP codes (API key invalid, 5xx errors, etc.)
        return jsonify({"error": f"Weather service error (HTTP {err.response.status_code})."}), 500 
    except requests.exceptions.RequestException as err:
        return jsonify({"error": f"Network error connecting to OWM: {err}"}), 500

    lat, lon = weather_data['coord']['lat'], weather_data['coord']['lon']
    
    # 2. Fetch AQI
    aqi_data = {}
    try:
        aqi_params = {'latitude': lat, 'longitude': lon, 'hourly': 'us_aqi,pm2_5', 'timezone': 'auto'}
        aqi_response = requests.get(OM_AQI_URL, params=aqi_params, timeout=5)
        aqi_response.raise_for_status()
        aqi_data = aqi_response.json()
    except Exception as e:
        print(f"Warning: Could not fetch AQI data. Error: {e}")

    # 3. Fetch UV, Hourly, and Daily Forecast (Open-Meteo)
    forecast_data = {}
    try:
        uv_hourly_daily_params = {
            'latitude': lat, 
            'longitude': lon, 
            'current': 'uv_index,is_day', 
            'hourly': 'temperature_2m,weather_code,is_day',
            'daily': 'weather_code,temperature_2m_max,temperature_2m_min',
            'forecast_days': 7, 
            'timezone': 'auto'
        }
        forecast_response = requests.get(OM_FORECAST_URL, params=uv_hourly_daily_params, timeout=5)
        forecast_response.raise_for_status() 
        forecast_data = forecast_response.json()
    except Exception as e:
        print(f"Warning: Could not fetch UV/Hourly/Daily data. Error: {e}")

    # 4. Consolidate Data and Format
    rain_1h = weather_data.get('rain', {}).get('1h', 0)
    snow_1h = weather_data.get('snow', {}).get('1h', 0)
    precipitation_total = rain_1h + snow_1h
    
    current_aqi = aqi_data.get('hourly', {}).get('us_aqi', [None])
    current_pm25 = aqi_data.get('hourly', {}).get('pm2_5', [None])
    aqi_value = current_aqi[0] if current_aqi and current_aqi[0] is not None else None
    pm25_value = current_pm25[0] if current_pm25 and current_pm25[0] is not None else None

    uvi_value = forecast_data.get('current', {}).get('uv_index')
    is_day = forecast_data.get('current', {}).get('is_day', 1) 
    
    weather_desc = weather_data['weather'][0]['description']
    # OWM ID is used as an approximate WMO code for icon mapping
    wmo_code = weather_data['weather'][0]['id'] 

    # Format strings
    formatted_pm25 = f"{pm25_value:.1f} µg/m³" if pm25_value is not None and not math.isnan(pm25_value) else "N/A"
    formatted_uvi = f"{uvi_value:.1f}" if uvi_value is not None and not math.isnan(uvi_value) else "N/A"

    aqi_info = get_aqi_status_and_color(aqi_value)

    final_data = {
        "locationName": f"{weather_data['name']}, {weather_data['sys']['country']}",
        "description": weather_desc.title(),
        "iconName": map_wmo_to_lucide_icon(wmo_code, is_day), 
        "gradientClass": get_background_gradient(weather_desc), 
        "temperature": f"{weather_data['main']['temp']:.0f}°C",
        "feelsLike": f"{weather_data['main']['feels_like']:.0f}°C",
        
        "aqiValue": aqi_value,
        "aqiStatus": aqi_info['status'], 
        "aqiColorClasses": aqi_info['colorClasses'],
        "pm25": formatted_pm25,
        
        "uvIndex": formatted_uvi,
        "uvRisk": get_uv_risk(uvi_value), 
        
        "humidity": f"{weather_data['main']['humidity']}%",
        "windSpeed": f"{weather_data['wind']['speed']:.1f} m/s",
        "windDirection": f"{deg_to_cardinal(weather_data['wind'].get('deg'))}",
        "precipitation": f"{precipitation_total:.1f} mm",
        "sunrise": weather_data['sys']['sunrise'],
        "sunset": weather_data['sys']['sunset'],
        "timezone": weather_data.get('timezone', 0),
        
        "hourlyForecast": format_hourly_forecast(forecast_data.get('hourly', {}), weather_data.get('timezone', 0)),
        "dailyForecast": format_daily_forecast(forecast_data.get('daily', {}))
    }
    
    return jsonify(final_data)


# --- API Endpoint 2: The Website (Serves the HTML/CSS/JS) ---
@app.route('/')
def home():
    # The entire production-ready HTML/CSS/JS frontend
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Weather24 Pro | Global Weather & AQI</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://unpkg.com/lucide@latest"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
        <style>
            :root { font-family: 'Inter', sans-serif; }
            .content-wrapper {
                transition: background-color 0.5s ease, background-image 0.5s ease;
            }
            /* AQI Styles */
            .aqi-good { border-color: #10B981; background-color: #ECFDF5; color: #065F46; }
            .aqi-moderate { border-color: #FBBF24; background-color: #FFFBEB; color: #B45309; }
            .aqi-sensitive { border-color: #F97316; background-color: #FFF7ED; color: #C2410C; }
            .aqi-unhealthy { border-color: #EF4444; background-color: #FEF2F2; color: #991B1B; }
            .aqi-very-unhealthy { border-color: #8B5CF6; background-color: #F5F3FF; color: #6D28D9; }
            .aqi-hazardous { border-color: #7F1D1D; background-color: #7F1D1D; color: #FFFFFF; }
            .aqi-na { border-color: #D1D5DB; background-color: #F9FAFB; color: #6B7280; }
            .aqi-hazardous .aqi-value-text, .aqi-hazardous .aqi-status-text { color: white !important; }

            /* Custom scrollbar for hourly section */
            #hourlyForecastContainer::-webkit-scrollbar {
                height: 6px;
            }
            #hourlyForecastContainer::-webkit-scrollbar-thumb {
                background: rgba(100, 116, 139, 0.5); /* slate-500 with opacity */
                border-radius: 3px;
            }
            #hourlyForecastContainer::-webkit-scrollbar-track {
                background: transparent;
            }
        </style>
    </head>
    <body class="min-h-screen flex items-start justify-center p-4 content-wrapper">

        <div class="w-full max-w-5xl bg-white/95 backdrop-blur-sm rounded-3xl shadow-3xl p-4 sm:p-8 md:p-10 space-y-8">

            <h1 class="text-3xl font-extrabold text-gray-800 text-center flex items-center justify-center gap-3">
                <i data-lucide="cloud-sun-wind" class="w-8 h-8 text-indigo-600"></i>
                Weather24 <span class="text-sm font-semibold text-indigo-400">PRO</span>
            </h1>

            <div class="flex flex-col sm:flex-row gap-4">
                <input type="text" id="cityInput" placeholder="Enter city name (e.g., London, Tokyo)"
                        class="flex-grow p-4 border-2 border-gray-300 rounded-xl focus:border-indigo-600 focus:ring-4 focus:ring-indigo-200 transition duration-300 shadow-md text-lg">
                <button id="searchButton"
                         class="w-full sm:w-auto px-8 py-4 bg-indigo-600 text-white font-bold rounded-xl hover:bg-indigo-700 transition duration-300 shadow-xl shadow-indigo-300 active:bg-indigo-800 flex items-center justify-center gap-2 text-lg">
                    <i data-lucide="search" class="w-5 h-5"></i>
                    Search
                </button>
            </div>

            <div id="loadingIndicator" class="text-center text-indigo-600 hidden py-10">
                <svg class="animate-spin h-10 w-10 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-4 text-md font-medium">Fetching the latest weather data...</p>
            </div>

            <div id="weatherResult" class="hidden space-y-8">
                <div id="mainSummary" class="flex flex-col sm:flex-row sm:justify-between sm:items-center bg-indigo-50/70 p-6 rounded-2xl shadow-xl border border-indigo-200">
                    <div class="text-center sm:text-left">
                        <h2 id="locationName" class="text-4xl sm:text-5xl font-extrabold text-gray-900">City, Country</h2>
                        <p id="weatherDescription" class="text-xl text-gray-700 mt-2 font-medium">Clear Sky</p>
                    </div>
                    <div class="mt-4 sm:mt-0 flex justify-center items-center gap-4">
                        <i data-lucide="sun" id="weatherIcon" class="w-16 h-16 sm:w-20 sm:h-20 text-indigo-700"></i>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-3 gap-6"> 
                    <div class="bg-white p-6 rounded-2xl border-4 border-indigo-100 shadow-2xl text-center flex flex-col justify-between hover:scale-[1.02] transition duration-300">
                        <div>
                            <p class="text-lg font-semibold text-gray-500">Temperature</p>
                            <p class="text-7xl font-extrabold text-indigo-800 mt-2" id="temperature">--</p>
                        </div>
                        <p class="text-base font-medium text-gray-500 mt-4">Feels Like: <span id="feelsLike" class="font-bold text-gray-700">--</span></p>
                    </div>

                    <div id="aqiCard" class="p-6 rounded-2xl shadow-2xl border-4 text-center flex flex-col justify-between hover:scale-[1.02] transition duration-300">
                        <div>
                            <p class="text-lg font-semibold text-gray-600">US AQI (Air Quality)</p>
                            <p class="text-7xl font-extrabold mt-2 aqi-value-text" id="aqiValue">--</p>
                        </div>
                        <p class="text-xl font-bold mt-4 aqi-status-text" id="aqiStatus">--</p>
                    </div>
                    
                    <div class="bg-white p-6 rounded-2xl shadow-2xl border-4 border-orange-100 text-center flex flex-col justify-between hover:scale-[1.02] transition duration-300">
                        <div>
                            <p class="text-lg font-semibold text-gray-500">UV Index</p>
                            <p class="text-7xl font-extrabold text-orange-600 mt-2" id="uvIndex">--</p>
                        </div>
                        <p class="text-xl font-bold text-orange-700 mt-4" id="uvRisk">--</p>
                    </div>
                </div>

                <div class="space-y-4">
                    <div class="flex border-b border-gray-300 overflow-x-auto whitespace-nowrap">
                        <button id="tabHourly" class="px-4 py-2 text-lg font-semibold border-b-2 border-indigo-600 text-indigo-600 transition duration-300 flex-shrink-0">Hourly Forecast</button>
                        <button id="tabDaily" class="px-4 py-2 text-lg font-semibold border-b-2 border-transparent text-gray-500 hover:text-indigo-600 transition duration-300 flex-shrink-0">7-Day Forecast</button>
                        <button id="tabMonthly" class="px-4 py-2 text-lg font-semibold border-b-2 border-transparent text-gray-500 hover:text-indigo-600 transition duration-300 flex-shrink-0">Monthly View (Concept)</button>
                    </div>

                    <div id="contentHourly" class="tab-content">
                        <div id="hourlyForecastContainer" class="flex overflow-x-auto gap-4 p-4 -m-4 pb-6">
                            </div>
                    </div>

                    <div id="contentDaily" class="tab-content hidden">
                        <div id="dailyForecastContainer" class="space-y-3">
                            </div>
                    </div>
                    
                    <div id="contentMonthly" class="tab-content hidden p-6 bg-gray-50 rounded-xl border border-gray-200 text-center">
                        <h4 class="text-xl font-bold text-gray-700 mb-2">Monthly Outlook</h4>
                        <p class="text-gray-500">True monthly weather forecasts are typically statistical and not available via these APIs.</p>
                        <p class="text-gray-500 mt-1">For a professional version, this would show monthly temperature averages and precipitation norms.</p>
                    </div>
                </div>

                <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 md:gap-6 border-t pt-6 border-gray-200">
                    <div class="bg-gray-50/70 p-5 rounded-xl shadow-lg flex flex-col items-center justify-center gap-1 border border-gray-200">
                        <i data-lucide="wind" class="w-8 h-8 text-cyan-600"></i>
                        <p class="text-base text-gray-500 font-medium">Wind</p>
                        <p id="windSpeed" class="text-xl font-bold text-gray-800">--</p>
                        <p id="windDirection" class="text-sm text-gray-500 text-center">--</p>
                    </div>
                    <div class="bg-gray-50/70 p-5 rounded-xl shadow-lg flex flex-col items-center justify-center gap-1 border border-gray-200">
                        <i data-lucide="droplet" class="w-8 h-8 text-blue-600"></i>
                        <p class="text-base text-gray-500 font-medium">Humidity</p>
                        <p id="humidity" class="text-xl font-bold text-gray-800">--</p>
                    </div>
                    <div class="bg-gray-50/70 p-5 rounded-xl shadow-lg flex flex-col items-center justify-center gap-1 border border-gray-200">
                        <i data-lucide="cloud-rain" class="w-8 h-8 text-indigo-600"></i>
                        <p class="text-base text-gray-500 font-medium">Precipitation (1h)</p>
                        <p id="precipitation" class="text-xl font-bold text-gray-800">--</p>
                    </div>
                    <div class="bg-gray-50/70 p-5 rounded-xl shadow-lg flex flex-col items-center justify-center gap-1 border border-gray-200">
                        <i data-lucide="microscope" class="w-8 h-8 text-green-600"></i>
                        <p class="text-base text-gray-500 font-medium">PM2.5</p>
                        <p id="pm25" class="text-xl font-bold text-gray-800">--</p>
                    </div>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 border-t pt-6 border-gray-200">
                    <div class="flex items-center justify-center gap-4 bg-gray-50/70 p-5 rounded-lg border border-gray-200 shadow-md">
                        <i data-lucide="sunrise" class="w-8 h-8 text-orange-500"></i>
                        <div class="text-center sm:text-left"> 
                            <p class="text-base text-gray-500 font-medium">Sunrise</p>
                            <p id="sunriseTime" class="text-2xl font-bold text-gray-800">--:--</p>
                        </div>
                    </div>
                    <div class="flex items-center justify-center gap-4 bg-gray-50/70 p-5 rounded-lg border border-gray-200 shadow-md">
                        <i data-lucide="sunset" class="w-8 h-8 text-red-500"></i>
                        <div class="text-center sm:text-left">
                            <p class="text-base text-gray-500 font-medium">Sunset</p>
                            <p id="sunsetTime" class="text-2xl font-bold text-gray-800">--:--</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <div id="errorMessage" class="hidden bg-red-100 border-l-4 border-red-500 text-red-700 p-4 rounded-md font-medium" role="alert">
                <p class="font-bold">Error fetching data</p>
                <p id="errorText"></p>
            </div>
            
            <footer class="text-center text-sm text-gray-400 pt-4 border-t border-gray-100">
                Data powered by OpenWeatherMap and Open-Meteo.
            </footer>
        </div>

        <script>
            // Initialize Lucide Icons
            lucide.createIcons();

            // --- JAVASCRIPT FRONTEND LOGIC ---
            const PYTHON_BACKEND_URL = "/api/weather"; 
            const cityInput = document.getElementById('cityInput');
            const searchButton = document.getElementById('searchButton');
            const loadingIndicator = document.getElementById('loadingIndicator');
            const weatherResult = document.getElementById('weatherResult');
            const errorMessage = document.getElementById('errorMessage');
            const aqiCard = document.getElementById('aqiCard');
            const weatherIcon = document.getElementById('weatherIcon');
            const hourlyContainer = document.getElementById('hourlyForecastContainer');
            const dailyContainer = document.getElementById('dailyForecastContainer');
            const body = document.body;

            // Tab elements
            const tabHourly = document.getElementById('tabHourly');
            const tabDaily = document.getElementById('tabDaily');
            const tabMonthly = document.getElementById('tabMonthly');
            const contentHourly = document.getElementById('contentHourly');
            const contentDaily = document.getElementById('contentDaily');
            const contentMonthly = document.getElementById('contentMonthly');

            function switchTab(activeTab) {
                // Deactivate all
                [tabHourly, tabDaily, tabMonthly].forEach(tab => {
                    tab.classList.remove('border-indigo-600', 'text-indigo-600');
                    tab.classList.add('border-transparent', 'text-gray-500');
                });
                [contentHourly, contentDaily, contentMonthly].forEach(content => {
                    content.classList.add('hidden');
                });

                // Activate selected tab and content
                activeTab.classList.remove('border-transparent', 'text-gray-500');
                activeTab.classList.add('border-indigo-600', 'text-indigo-600');
                
                if (activeTab === tabHourly) contentHourly.classList.remove('hidden');
                if (activeTab === tabDaily) contentDaily.classList.remove('hidden');
                if (activeTab === tabMonthly) contentMonthly.classList.remove('hidden');
            }

            // Tab listeners
            tabHourly.addEventListener('click', () => switchTab(tabHourly));
            tabDaily.addEventListener('click', () => switchTab(tabDaily));
            tabMonthly.addEventListener('click', () => switchTab(tabMonthly));

            function formatTime(timestamp, timezoneOffset, isHourly = false) {
                // Adjust timestamp by adding the timezone offset (in seconds)
                const date = new Date((timestamp + timezoneOffset) * 1000);
                
                if (isHourly) {
                    const now = new Date();
                    const nowUTC = Math.floor(now.getTime() / 1000) + (now.getTimezoneOffset() * 60);
                    // Check if the timestamp is within the current hour (within 3600 seconds)
                    const isCurrentHour = Math.floor(timestamp / 3600) === Math.floor(nowUTC / 3600);
                    
                    if (isCurrentHour) return "Now";
                    
                    // Display hour (e.g., 3 PM)
                    return date.toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        hour12: true,
                        timeZone: 'UTC' 
                    });
                }
                
                // Display 2-digit hour/minute (e.g., 06:33 AM)
                return date.toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: true,
                    timeZone: 'UTC'  
                });
            }

            function renderHourlyForecast(forecastArray, timezoneOffset) {
                hourlyContainer.innerHTML = '';
                if (forecastArray.length === 0) {
                    hourlyContainer.innerHTML = '<p class="text-gray-500 p-4">Hourly forecast data not available.</p>';
                    return;
                }

                forecastArray.forEach((item) => {
                    const utcTimestamp = new Date(item.time).getTime() / 1000;
                    const timeLabel = formatTime(utcTimestamp, timezoneOffset, true);
                    
                    const card = document.createElement('div');
                    card.className = 'flex flex-col items-center justify-between p-3 sm:p-4 rounded-xl shadow-md bg-white border border-gray-200 min-w-[75px] sm:min-w-[100px] flex-shrink-0';
                    card.innerHTML = `
                        <p class="text-sm font-semibold ${timeLabel === 'Now' ? 'text-indigo-600' : 'text-gray-600'}">${timeLabel}</p>
                        <i data-lucide="${item.iconName}" class="w-6 h-6 sm:w-8 sm:h-8 text-gray-700 my-2"></i>
                        <p class="text-xl font-bold text-gray-800">${item.temperature}</p>
                    `;
                    hourlyContainer.appendChild(card);
                });
                lucide.createIcons();
            }

            function renderDailyForecast(forecastArray) {
                dailyContainer.innerHTML = '';
                if (forecastArray.length === 0) {
                    dailyContainer.innerHTML = '<p class="text-gray-500 p-4">Daily forecast data not available.</p>';
                    return;
                }

                forecastArray.forEach((item) => {
                    const row = document.createElement('div');
                    row.className = 'flex items-center justify-between p-4 bg-white rounded-xl shadow-sm border border-gray-100';
                    row.innerHTML = `
                        <p class="text-lg font-semibold w-1/4 ${item.day === 'Today' ? 'text-indigo-600' : 'text-gray-800'}">${item.day}</p>
                        <div class="flex items-center w-1/4 justify-center">
                           <i data-lucide="${item.iconName}" class="w-7 h-7 text-indigo-500"></i>
                        </div>
                        <p class="text-lg font-bold text-gray-800 w-1/4 text-right">${item.tempMax}</p>
                        <p class="text-lg text-gray-500 w-1/4 text-right">${item.tempMin}</p>
                    `;
                    dailyContainer.appendChild(row);
                });
                lucide.createIcons();
            }
            
            function setLoadingState(isLoading) {
                loadingIndicator.classList.toggle('hidden', !isLoading);
                weatherResult.classList.add('hidden');
                errorMessage.classList.add('hidden');
                searchButton.disabled = isLoading;
                cityInput.disabled = isLoading;
            }

            function displayError(message) {
                setLoadingState(false);
                document.getElementById('errorText').textContent = message;
                errorMessage.classList.remove('hidden');
            }
            
            async function updateWeatherDisplay(data) {
                setLoadingState(false);
                
                // 1. Dynamic Background & Text Color
                body.className = body.className.split(' ').filter(cls => !cls.startsWith('bg-gradient-') && !cls.startsWith('text-')).join(' ');
                body.classList.add(data.gradientClass);
                body.classList.add('min-h-screen', 'flex', 'items-start', 'justify-center', 'p-4', 'content-wrapper');

                // 2. Main Info
                document.getElementById('locationName').textContent = data.locationName;
                document.getElementById('weatherDescription').textContent = data.description;
                document.getElementById('temperature').textContent = data.temperature;
                document.getElementById('feelsLike').textContent = data.feelsLike;
                
                // 3. Dynamic Icon
                weatherIcon.setAttribute('data-lucide', data.iconName);
                
                // 4. AQI Card
                document.getElementById('aqiValue').textContent = data.aqiValue ?? "N/A";
                document.getElementById('aqiStatus').textContent = data.aqiStatus;
                aqiCard.className = `p-6 rounded-2xl shadow-2xl border-4 text-center flex flex-col justify-between hover:scale-[1.02] transition duration-300 ${data.aqiColorClasses}`; 

                // 5. UV Card
                document.getElementById('uvIndex').textContent = data.uvIndex;
                document.getElementById('uvRisk').textContent = data.uvRisk;

                // 6. Secondary Metrics
                document.getElementById('humidity').textContent = data.humidity;
                document.getElementById('windSpeed').textContent = data.windSpeed;
                document.getElementById('windDirection').textContent = data.windDirection;
                document.getElementById('precipitation').textContent = data.precipitation;
                document.getElementById('pm25').textContent = data.pm25;
                
                // 7. Sun Times
                document.getElementById('sunriseTime').textContent = formatTime(data.sunrise, data.timezone);
                document.getElementById('sunsetTime').textContent = formatTime(data.sunset, data.timezone);
                
                // 8. Forecasts (New Features)
                renderHourlyForecast(data.hourlyForecast, data.timezone);
                renderDailyForecast(data.dailyForecast);

                weatherResult.classList.remove('hidden');
                // Ensure default tab is selected on fresh load
                switchTab(tabHourly);
                lucide.createIcons();
            }

            async function fetchAllDataFromServer() {
                const city = cityInput.value.trim();
                if (!city) {
                    displayError("Please enter a city name.");
                    return;
                }
                setLoadingState(true);
                const fullBackendUrl = `${PYTHON_BACKEND_URL}?city=${encodeURIComponent(city)}`;
                
                try {
                    const response = await fetch(fullBackendUrl);
                    const data = await response.json();
                    if (!response.ok) {
                        displayError(data.error || `City not found or data error (HTTP ${response.status})`);
                    } else {
                        updateWeatherDisplay(data);
                    }
                } catch (error) {
                    console.error("Error fetching from Python backend:", error);
                    displayError("Could not connect to the Python server. Please check the console for details.");
                }
            }

            searchButton.addEventListener('click', fetchAllDataFromServer);
            
            // Initial call to populate with default city on load
            document.addEventListener('DOMContentLoaded', () => {
                cityInput.value = "Chandigarh"; 
                fetchAllDataFromServer(); 
            });
        </script>
    </body>
    </html>
    """
    return Response(html_content, mimetype='text/html')


# --- 3. RUN THE PYTHON SERVER (Used for local testing) ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # This block is ignored by Gunicorn but is useful for local development
    app.run(host='0.0.0.0', port=port, debug=True)
