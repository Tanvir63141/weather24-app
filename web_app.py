import requests
import json
from flask import Flask, request, jsonify, Response
from datetime import datetime, timedelta, timezone
import os  # Import os to get the port from the environment
import math  # Import math for rounding/checking NaNs

# --- 1. PYTHON BACKEND LOGIC (using Flask) ---

app = Flask(__name__)

# --- Configuration ---
# NOTE: Replace the placeholder with your actual OpenWeatherMap API key.
OWM_API_KEY = "YOUR_OWM_API_KEY_HERE"
OWM_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OM_AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OM_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"  # Used for UV index

UNITS = "metric"


# --- Python Helper Functions ---
def deg_to_cardinal(deg):
    """
    Convert wind degree (0-360) into a human-friendly cardinal direction.
    Returns "N/A" if deg is None.
    """
    if deg is None:
        return "N/A"
    val = int((deg / 22.5) + 0.5)
    arr = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    ]
    return arr[(val % 16)]


def get_aqi_status_and_color(aqi_value):
    """
    Return a dict with 'status' and 'colorClasses' used by the frontend for styling.
    This only prepares UI metadata and does not change API behavior.
    """
    if aqi_value is None:
        return {"status": "N/A", "colorClasses": "aqi-na"}

    try:
        aqi_val = float(aqi_value)
    except (TypeError, ValueError):
        return {"status": "N/A", "colorClasses": "aqi-na"}

    if aqi_val <= 50:
        return {"status": "Good", "colorClasses": "aqi-good"}
    elif aqi_val <= 100:
        return {"status": "Moderate", "colorClasses": "aqi-moderate"}
    elif aqi_val <= 150:
        return {"status": "Unhealthy for Sensitive Groups", "colorClasses": "aqi-sensitive"}
    elif aqi_val <= 200:
        return {"status": "Unhealthy", "colorClasses": "aqi-unhealthy"}
    elif aqi_val <= 300:
        return {"status": "Very Unhealthy", "colorClasses": "aqi-very-unhealthy"}
    else:
        return {"status": "Hazardous", "colorClasses": "aqi-hazardous"}


def get_uv_risk(uvi):
    """
    Return a short UV risk description for a given UV index.
    """
    if uvi is None:
        return "N/A"
    try:
        u = float(uvi)
    except (TypeError, ValueError):
        return "N/A"
    if u < 3:
        return "Low Risk"
    if u < 6:
        return "Moderate Risk"
    if u < 8:
        return "High Risk"
    if u < 11:
        return "Very High Risk"
    return "Extreme Risk"


def map_weather_to_lucide_icon(weather_description):
    """
    Map a textual weather description to a lucide icon name.
    This is only for improved frontend visuals.
    """
    if not weather_description:
        return "cloud-sun-wind"
    desc = weather_description.lower()
    if "clear" in desc or "sun" in desc:
        return "sun"
    if "cloud" in desc or "overcast" in desc:
        return "cloud"
    if "rain" in desc or "shower" in desc or "drizzle" in desc:
        return "cloud-rain"
    if "thunder" in desc or "storm" in desc:
        return "cloud-lightning"
    if "snow" in desc or "sleet" in desc:
        return "cloud-snow"
    if "mist" in desc or "fog" in desc or "haze" in desc:
        return "fog"
    return "cloud-sun-wind"  # default


# --- API Endpoint 1: The Data (Handles API calls) ---
@app.route('/api/weather')
def get_weather_data():
    """
    Primary API endpoint that:
    1) Fetches core weather from OpenWeatherMap.
    2) Fetches AQI and UV from Open-Meteo (when available).
    3) Consolidates and returns a JSON payload for the frontend.
    """
    city_name = request.args.get('city')
    if not city_name:
        return jsonify({"error": "A 'city' query parameter is required."}), 400

    # 1. Fetch Core Weather (OWM)
    owm_params = {'q': city_name, 'units': UNITS, 'appid': OWM_API_KEY}
    try:
        weather_response = requests.get(OWM_WEATHER_URL, params=owm_params, timeout=8)
        weather_response.raise_for_status()
        weather_data = weather_response.json()
    except requests.exceptions.HTTPError as err:
        if err.response is not None and err.response.status_code == 404:
            return jsonify({"error": f"City '{city_name}' not found."}), 404
        return jsonify({"error": f"Weather service error: {err}"}), 500
    except requests.exceptions.RequestException as err:
        return jsonify({"error": f"Network error: {err}"}), 500

    lat = weather_data['coord']['lat']
    lon = weather_data['coord']['lon']

    # 2. Fetch AQI and UV Index (Open-Meteo) - attempt but don't fail the whole request if unavailable
    aqi_data = {}
    uv_data = {}

    # Fetch AQI (Open-Meteo air-quality)
    try:
        aqi_params = {'latitude': lat, 'longitude': lon, 'hourly': 'us_aqi,pm2_5', 'timezone': 'auto'}
        aqi_response = requests.get(OM_AQI_URL, params=aqi_params, timeout=5)
        aqi_response.raise_for_status()
        aqi_data = aqi_response.json()
    except Exception as e:
        # Non-fatal: warn on server logs and continue returning weather-only data
        print(f"Warning: Could not fetch AQI data. Error: {e}")

    # Fetch UV Index (Open-Meteo forecast endpoint)
    try:
        uv_params = {'latitude': lat, 'longitude': lon, 'current': 'uv_index', 'forecast_days': 1, 'timezone': 'auto'}
        uv_response = requests.get(OM_FORECAST_URL, params=uv_params, timeout=5)
        uv_response.raise_for_status()
        uv_data = uv_response.json()
    except Exception as e:
        print(f"Warning: Could not fetch UV data. Error: {e}")

    # 3. Consolidate Data
    rain = weather_data.get('rain', {}).get('1h', 0)
    snow = weather_data.get('snow', {}).get('1h', 0)
    precipitation_total = rain + snow

    # Pull first hourly entries from Open-Meteo responses where available
    current_aqi_arr = aqi_data.get('hourly', {}).get('us_aqi', [None])
    current_pm25_arr = aqi_data.get('hourly', {}).get('pm2_5', [None])

    aqi_value = current_aqi_arr[0] if current_aqi_arr and current_aqi_arr[0] is not None else None
    pm25_value = current_pm25_arr[0] if current_pm25_arr and current_pm25_arr[0] is not None else None

    # UV data (current)
    uvi_value = uv_data.get('current', {}).get('uv_index')

    # Format PM2.5 and UV values safely
    formatted_pm25 = f"{pm25_value:.1f} µg/m³" if (pm25_value is not None and not math.isnan(pm25_value)) else "N/A"
    formatted_uvi = f"{uvi_value:.1f}" if (uvi_value is not None and not (isinstance(uvi_value, float) and math.isnan(uvi_value))) else "N/A"

    # Prepare AQI UI metadata
    aqi_ui = get_aqi_status_and_color(aqi_value)

    final_data = {
        "locationName": f"{weather_data['name']}, {weather_data['sys']['country']}",
        "description": weather_data['weather'][0]['description'].title(),
        "iconName": map_weather_to_lucide_icon(weather_data['weather'][0]['description']),  # for nicer UI
        "temperature": f"{weather_data['main']['temp']:.0f}°C",
        "feelsLike": f"{weather_data['main']['feels_like']:.0f}°C",
        "aqiValue": aqi_value,
        "aqiStatus": aqi_ui['status'],
        "aqiColorClasses": aqi_ui['colorClasses'],
        "pm25": formatted_pm25,
        "uvIndex": formatted_uvi,
        "uvRisk": get_uv_risk(uvi_value),
        "humidity": f"{weather_data['main']['humidity']}%",
        "windSpeed": f"{weather_data['wind']['speed']:.1f} m/s",
        "windDirection": f"from {deg_to_cardinal(weather_data['wind'].get('deg'))}",
        "precipitation": f"{precipitation_total:.1f} mm",
        "sunrise": weather_data['sys']['sunrise'],
        "sunset": weather_data['sys']['sunset'],
        "timezone": weather_data.get('timezone', 0)
    }

    return jsonify(final_data)


# --- API Endpoint 2: The Website (Serves the HTML/CSS/JS) ---
@app.route('/')
def home():
    """
    Serves the full single-file frontend (HTML/CSS/JS).
    The frontend expects the /api/weather endpoint and the JSON structure returned above.
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Weather24 Pro | Global Weather & AQI</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://unpkg.com/lucide@latest"></script>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet" />
        <style>
            :root { font-family: 'Inter', sans-serif; }
            /* --- Custom AQI Styles for Professional Visuals --- */
            .aqi-good { border-color: #10B981; background-color: #ECFDF5; color: #065F46; } /* Green */
            .aqi-moderate { border-color: #FBBF24; background-color: #FFFBEB; color: #B45309; } /* Yellow */
            .aqi-sensitive { border-color: #F97316; background-color: #FFF7ED; color: #C2410C; } /* Orange */
            .aqi-unhealthy { border-color: #EF4444; background-color: #FEF2F2; color: #991B1B; } /* Red */
            .aqi-very-unhealthy { border-color: #8B5CF6; background-color: #F5F3FF; color: #6D28D9; } /* Purple */
            .aqi-hazardous { border-color: #7F1D1D; background-color: #7F1D1D; color: #FFFFFF; } /* Dark Red/Maroon, White Text */
            .aqi-na { border-color: #D1D5DB; background-color: #F9FAFB; color: #6B7280; } /* Gray */

            .aqi-hazardous .aqi-value-text, .aqi-hazardous .aqi-status-text { color: white !important; }
        </style>
    </head>
    <body class="bg-gray-100 min-h-screen flex items-start justify-center p-4">
        <div class="w-full max-w-4xl bg-white rounded-2xl shadow-2xl p-4 sm:p-6 md:p-8 space-y-6 sm:space-y-8">
            <h1 class="text-3xl font-extrabold text-gray-800 text-center flex items-center justify-center gap-3">
                <i data-lucide="cloud-sun-wind" class="w-8 h-8 text-indigo-600"></i>
                Weather24 <span class="text-sm font-semibold text-indigo-400">PRO</span>
            </h1>

            <div class="flex flex-col sm:flex-row gap-3">
                <input type="text" id="cityInput" placeholder="Enter city name (e.g., Paris, Sydney)"
                       class="flex-grow p-4 border-2 border-gray-300 rounded-xl focus:border-indigo-600 focus:ring-4 focus:ring-indigo-200 transition duration-300 shadow-md text-gray-700 placeholder-gray-400"
                       onkeydown="if(event.key === 'Enter') document.getElementById('searchButton').click()">
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
                <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center bg-indigo-50 p-6 rounded-2xl shadow-inner">
                    <div class="text-center sm:text-left">
                        <h2 id="locationName" class="text-4xl sm:text-5xl font-extrabold text-gray-900">City, Country</h2>
                        <p id="weatherDescription" class="text-xl text-gray-600 mt-2 font-medium">Clear Sky</p>
                    </div>
                    <div class="mt-4 sm:mt-0 flex justify-center items-center gap-4">
                        <i data-lucide="cloud-sun-wind" id="weatherIcon" class="w-12 h-12 sm:w-16 sm:h-16 text-indigo-600"></i>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="bg-white p-6 rounded-2xl border-4 border-indigo-100 shadow-2xl text-center flex flex-col justify-between">
                        <div>
                            <p class="text-lg font-semibold text-gray-500">Temperature</p>
                            <p class="text-7xl font-extrabold text-indigo-800 mt-2" id="temperature">--</p>
                        </div>
                        <p class="text-base font-medium text-gray-500 mt-4">Feels Like: <span id="feelsLike" class="font-bold text-gray-700">--</span></p>
                    </div>

                    <div id="aqiCard" class="p-6 rounded-2xl shadow-2xl border-4 text-center transition duration-500 flex flex-col justify-between">
                        <div>
                            <p class="text-lg font-semibold text-gray-600">US AQI (Air Quality)</p>
                            <p class="text-7xl font-extrabold mt-2 aqi-value-text" id="aqiValue">--</p>
                        </div>
                        <p class="text-xl font-bold mt-4 aqi-status-text" id="aqiStatus">--</p>
                    </div>

                    <div class="bg-white p-6 rounded-2xl shadow-2xl border-4 border-orange-100 text-center flex flex-col justify-between">
                        <div>
                            <p class="text-lg font-semibold text-gray-500">UV Index</p>
                            <p class="text-7xl font-extrabold text-orange-600 mt-2" id="uvIndex">--</p>
                        </div>
                        <p class="text-xl font-bold text-orange-700 mt-4" id="uvRisk">--</p>
                    </div>
                </div>

                <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 md:gap-6">
                    <div class="bg-gray-50 p-5 rounded-xl shadow-lg flex flex-col items-center justify-center gap-1 border border-gray-200">
                        <i data-lucide="wind" class="w-8 h-8 text-cyan-600"></i>
                        <p class="text-base text-gray-500 font-medium">Wind</p>
                        <p id="windSpeed" class="text-xl font-bold text-gray-800">--</p>
                        <p id="windDirection" class="text-sm text-gray-500">--</p>
                    </div>
                    <div class="bg-gray-50 p-5 rounded-xl shadow-lg flex flex-col items-center justify-center gap-1 border border-gray-200">
                        <i data-lucide="droplet" class="w-8 h-8 text-blue-600"></i>
                        <p class="text-base text-gray-500 font-medium">Humidity</p>
                        <p id="humidity" class="text-xl font-bold text-gray-800">--</p>
                    </div>
                    <div class="bg-gray-50 p-5 rounded-xl shadow-lg flex flex-col items-center justify-center gap-1 border border-gray-200">
                        <i data-lucide="cloud-rain" class="w-8 h-8 text-indigo-600"></i>
                        <p class="text-base text-gray-500 font-medium">Precip (1h)</p>
                        <p id="precipitation" class="text-xl font-bold text-gray-800">--</p>
                    </div>
                    <div class="bg-gray-50 p-5 rounded-xl shadow-lg flex flex-col items-center justify-center gap-1 border border-gray-200">
                        <i data-lucide="microscope" class="w-8 h-8 text-green-600"></i>
                        <p class="text-base text-gray-500 font-medium">PM2.5</p>
                        <p id="pm25" class="text-xl font-bold text-gray-800">--</p>
                    </div>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 border-t pt-6 border-gray-200">
                    <div class="flex items-center justify-center gap-4 bg-gray-50 p-5 rounded-lg border border-gray-200 shadow-md">
                        <i data-lucide="sunrise" class="w-8 h-8 text-orange-500"></i>
                        <div class="text-center sm:text-left">
                            <p class="text-base text-gray-500 font-medium">Sunrise</p>
                            <p id="sunriseTime" class="text-2xl font-bold text-gray-800">--:--</p>
                        </div>
                    </div>
                    <div class="flex items-center justify-center gap-4 bg-gray-50 p-5 rounded-lg border border-gray-200 shadow-md">
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
            const errorText = document.getElementById('errorText');
            const aqiCard = document.getElementById('aqiCard');
            const weatherIcon = document.getElementById('weatherIcon');

            function formatTime(timestamp, timezoneOffset) {
                // Timezone offset is in seconds from UTC.
                // We add the offset to the timestamp (already in seconds) and format it as UTC time.
                const date = new Date((timestamp + timezoneOffset) * 1000);
                return date.toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: true,
                    timeZone: 'UTC'
                });
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
                errorText.textContent = message;
                errorMessage.classList.remove('hidden');
            }

            function updateWeatherDisplay(data) {
                setLoadingState(false);

                // Update Main Info
                document.getElementById('locationName').textContent = data.locationName;
                document.getElementById('weatherDescription').textContent = data.description;
                document.getElementById('temperature').textContent = data.temperature;
                document.getElementById('feelsLike').textContent = data.feelsLike;

                // Update Dynamic Weather Icon
                if (data.iconName) {
                    weatherIcon.setAttribute('data-lucide', data.iconName);
                }

                // Update AQI Card
                document.getElementById('aqiValue').textContent = data.aqiValue ?? "N/A";
                document.getElementById('aqiStatus').textContent = data.aqiStatus ?? "--";
                aqiCard.className = `p-6 rounded-2xl shadow-2xl border-4 text-center transition duration-500 flex flex-col justify-between ${data.aqiColorClasses ?? ''}`;

                // Update UV Card
                document.getElementById('uvIndex').textContent = data.uvIndex;
                document.getElementById('uvRisk').textContent = data.uvRisk;

                // Update Secondary Metrics
                document.getElementById('humidity').textContent = data.humidity;
                document.getElementById('windSpeed').textContent = data.windSpeed;
                document.getElementById('windDirection').textContent = data.windDirection;
                document.getElementById('precipitation').textContent = data.precipitation;
                document.getElementById('pm25').textContent = data.pm25;

                // Update Sun Times
                document.getElementById('sunriseTime').textContent = formatTime(data.sunrise, data.timezone);
                document.getElementById('sunsetTime').textContent = formatTime(data.sunset, data.timezone);

                weatherResult.classList.remove('hidden');

                // Re-render all lucide icons
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
                        displayError(data.error || `An unknown error occurred (HTTP ${response.status})`);
                    } else {
                        updateWeatherDisplay(data);
                    }
                } catch (error) {
                    console.error("Error fetching from Python backend:", error);
                    displayError("Could not connect to the Python server. Please check the console for details.");
                }
            }

            searchButton.addEventListener('click', fetchAllDataFromServer);

            // Initial call to populate with Chandigarh data on load (like the screenshot)
            // You can comment this out if you prefer a blank initial state.
            document.addEventListener('DOMContentLoaded', () => {
                cityInput.value = "Chandigarh";
                fetchAllDataFromServer();
            });
        </script>
    </body>
    </html>
    """
    return Response(html_content, mimetype='text/html')


# --- 3. RUN THE PYTHON SERVER ---
if __name__ == '__main__':
    # Get port from environment variable for hosting, default to 5000 for local
    port = int(os.environ.get('PORT', 5000))
    # Run on '0.0.0.0' to be accessible for hosting
    app.run(host='0.0.0.0', port=port, debug=False)
