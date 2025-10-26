import requests
import json
from flask import Flask, request, jsonify, Response
from datetime import datetime, timedelta, timezone
import os # Import os to get the port from the environment

# --- 1. PYTHON BACKEND LOGIC (using Flask) ---

app = Flask(__name__)

# --- Configuration ---
OWM_API_KEY = "207cf060d7c9af525f46c1e0f15b5b60"
OWM_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
OM_AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OM_UV_URL = "https://api.open-meteo.com/v1/forecast"
UNITS = "metric"

# --- Python Helper Functions ---
def deg_to_cardinal(deg):
    val = int((deg / 22.5) + 0.5)
    arr = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return arr[(val % 16)]

# --- API Endpoint 1: The Data (Handles API calls) ---
@app.route('/api/weather')
def get_weather_data():
    city_name = request.args.get('city')
    if not city_name:
        return jsonify({"error": "A 'city' query parameter is required."}), 400

    # 1. Fetch Core Weather (OWM)
    owm_params = {'q': city_name, 'units': UNITS, 'appid': OWM_API_KEY}
    try:
        weather_response = requests.get(OWM_WEATHER_URL, params=owm_params)
        weather_response.raise_for_status()
        weather_data = weather_response.json()
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == 404:
            return jsonify({"error": f"City '{city_name}' not found."}), 404
        return jsonify({"error": f"Weather service error: {err}"}), 500
    except requests.exceptions.RequestException as err:
        return jsonify({"error": f"Network error: {err}"}), 500

    lat, lon = weather_data['coord']['lat'], weather_data['coord']['lon']
    
    # 2. Fetch AQI and UV Index (Open-Meteo)
    aqi_data, uvi_value = {}, None
    try:
        aqi_params = {'latitude': lat, 'longitude': lon, 'hourly': 'us_aqi,pm2_5'}
        aqi_response = requests.get(OM_AQI_URL, params=aqi_params)
        aqi_data = aqi_response.json()

        uv_params = {'latitude': lat, 'longitude': lon, 'current': 'uv_index', 'forecast_days': 1}
        uv_response = requests.get(OM_UV_URL, params=uv_params)
        uvi_value = uv_response.json().get('current', {}).get('uv_index')
    except Exception as e:
        print(f"Warning: Could not fetch secondary data. Error: {e}")

    # 3. Consolidate Data
    rain = weather_data.get('rain', {}).get('1h', 0)
    snow = weather_data.get('snow', {}).get('1h', 0)
    current_aqi = aqi_data.get('hourly', {}).get('us_aqi', [None])[0]
    current_pm25 = aqi_data.get('hourly', {}).get('pm2_5', [None])[0]

    final_data = {
        "locationName": f"{weather_data['name']}, {weather_data['sys']['country']}",
        "description": weather_data['weather'][0]['description'].title(),
        "temperature": f"{weather_data['main']['temp']:.0f}°C",
        "feelsLike": f"{weather_data['main']['feels_like']:.0f}°C",
        "aqiValue": current_aqi,
        "pm25": f"{current_pm25:.1f} µg/m³" if current_pm25 is not None else "N/A",
        "uvIndex": f"{uvi_value:.1f}" if uvi_value is not None else "N/A",
        "humidity": f"{weather_data['main']['humidity']}%",
        "windSpeed": f"{weather_data['wind']['speed']:.1f} m/s",
        "windDirection": f"from {deg_to_cardinal(weather_data['wind'].get('deg', 0))}",
        "precipitation": f"{(rain + snow):.1f} mm",
        "sunrise": weather_data['sys']['sunrise'],
        "sunset": weather_data['sys']['sunset'],
        "timezone": weather_data.get('timezone', 0)
    }
    
    return jsonify(final_data)


# --- API Endpoint 2: The Website (Serves the HTML/CSS/JS) ---
@app.route('/')
def home():
    # This triple-quoted string is the entire HTML/CSS/JS front-end
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Weather24 | Global Weather & AQI</title>
        <!-- Load Tailwind CSS (Our CSS) -->
        <script src="https://cdn.tailwindcss.com"></script>
        <!-- Load Lucide Icons -->
        <script src="https://unpkg.com/lucide@latest"></script>
        <!-- Google Font -->
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
        <style>
            :root { font-family: 'Inter', sans-serif; }
        </style>
    </head>
    <body class="bg-gray-100 min-h-screen flex items-center justify-center p-4">

        <!-- This is our HTML structure -->
        <div class="w-full max-w-2xl bg-white rounded-2xl shadow-2xl p-6 md:p-10 space-y-8">

            <h1 class="text-3xl font-extrabold text-gray-800 text-center flex items-center justify-center gap-2">
                <i data-lucide="cloud-sun-wind" class="w-7 h-7 text-indigo-600"></i>
                Weather24
            </h1>

            <!-- Search Input -->
            <div class="flex flex-col sm:flex-row gap-3">
                <input type="text" id="cityInput" placeholder="Enter city name (e.g., Paris, Sydney)"
                       class="flex-grow p-3 border-2 border-gray-300 rounded-lg focus:border-indigo-600 focus:ring-2 focus:ring-indigo-600 transition duration-150 shadow-sm text-gray-700"
                       onkeydown="if(event.key === 'Enter') document.getElementById('searchButton').click()">
                <button id="searchButton"
                        class="w-full sm:w-auto px-6 py-3 bg-indigo-600 text-white font-semibold rounded-lg hover:bg-indigo-700 transition duration-200 shadow-lg shadow-indigo-300 active:bg-indigo-800 flex items-center justify-center gap-2">
                    <i data-lucide="search" class="w-5 h-5"></i>
                    Search
                </button>
            </div>

            <!-- Loading Spinner -->
            <div id="loadingIndicator" class="text-center text-indigo-600 hidden">
                <svg class="animate-spin h-8 w-8 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-2 text-sm">Fetching weather data...</p>
            </div>

            <!-- Weather Results Area -->
            <div id="weatherResult" class="hidden space-y-8">
                <!-- ... (HTML structure for results) ... -->
                <div class="text-center bg-indigo-50 p-4 rounded-xl shadow-inner">
                    <h2 id="locationName" class="text-4xl font-extrabold text-gray-900">Welcome!</h2>
                    <p id="weatherDescription" class="text-xl text-gray-600 mt-1">Search a city to begin.</p>
                </div>
                <div class="grid grid-cols-3 gap-4">
                    <div class="bg-white p-5 rounded-xl border border-indigo-200 shadow-lg text-center">
                        <p class="text-xs font-medium text-gray-500">Temperature</p>
                        <p class="text-5xl font-extrabold text-indigo-700 mt-1" id="temperature">--</p>
                        <p class="text-xs font-medium text-gray-500 mt-2">Feels Like: <span id="feelsLike" class="font-semibold text-gray-700">--</span></p>
                    </div>
                    <div id="aqiCard" class="bg-white p-5 rounded-xl shadow-lg border-2 text-center transition duration-300 col-span-2 md:col-span-1">
                        <p class="text-xs font-medium text-gray-500">US AQI (Air Quality)</p>
                        <p class="text-5xl font-extrabold mt-1" id="aqiValue">--</p>
                        <p class="text-sm font-semibold mt-1" id="aqiStatus">--</p>
                    </div>
                    <div class="bg-white p-5 rounded-xl shadow-lg border-2 border-orange-200 text-center">
                        <p class="text-xs font-medium text-gray-500">UV Index</p>
                        <p class="text-5xl font-extrabold text-orange-600 mt-1" id="uvIndex">--</p>
                        <p class="text-sm font-medium text-gray-500 mt-2" id="uvRisk">--</p>
                    </div>
                </div>
                <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    <div class="bg-gray-50 p-4 rounded-xl shadow-md flex flex-col items-center justify-center gap-1">
                        <i data-lucide="wind" class="w-6 h-6 text-cyan-600"></i>
                        <p class="text-sm text-gray-500">Wind</p>
                        <p id="windSpeed" class="text-lg font-semibold text-gray-800">--</p>
                        <p id="windDirection" class="text-xs text-gray-500">--</p>
                    </div>
                    <div class="bg-gray-50 p-4 rounded-xl shadow-md flex flex-col items-center justify-center gap-1">
                        <i data-lucide="droplet" class="w-6 h-6 text-blue-600"></i>
                        <p class="text-sm text-gray-500">Humidity</p>
                        <p id="humidity" class="text-lg font-semibold text-gray-800">--</p>
                    </div>
                    <div class="bg-gray-50 p-4 rounded-xl shadow-md flex flex-col items-center justify-center gap-1">
                        <i data-lucide="cloud-rain" class="w-6 h-6 text-indigo-600"></i>
                        <p class="text-sm text-gray-500">Precipitation (1h)</p>
                        <p id="precipitation" class="text-lg font-semibold text-gray-800">--</p>
                    </div>
                    <div class="bg-gray-50 p-4 rounded-xl shadow-md flex flex-col items-center justify-center gap-1">
                        <i data-lucide="microscope" class="w-6 h-6 text-green-600"></i>
                        <p class="text-sm text-gray-500">PM2.5</p>
                        <p id="pm25" class="text-lg font-semibold text-gray-800">--</p>
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-4 border-t pt-4 border-gray-200">
                    <div class="flex items-center justify-center gap-3 bg-gray-50 p-3 rounded-lg border border-gray-200">
                        <i data-lucide="sunrise" class="w-6 h-6 text-orange-500"></i>
                        <div>
                            <p class="text-sm text-gray-500">Sunrise</p>
                            <p id="sunriseTime" class="text-lg font-semibold text-gray-800">--:--</p>
                        </div>
                    </div>
                    <div class="flex items-center justify-center gap-3 bg-gray-50 p-3 rounded-lg border border-gray-200">
                        <i data-lucide="sunset" class="w-6 h-6 text-red-500"></i>
                        <div>
                            <p class="text-sm text-gray-500">Sunset</p>
                            <p id="sunsetTime" class="text-lg font-semibold text-gray-800">--:--</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Error Message Box -->
            <div id="errorMessage" class="hidden bg-red-100 border-l-4 border-red-500 text-red-700 p-4 rounded-md" role="alert">
                <p class="font-bold">Error fetching data</p>
                <p id="errorText"></p>
            </div>
        </div>

        <!-- This JavaScript runs in the user's browser -->
        <script>
            // Initialize Lucide Icons
            lucide.createIcons();

            // --- JAVASCRIPT FRONTEND LOGIC ---
            const PYTHON_BACKEND_URL = "/api/weather"; // Talks to our Python app
            const cityInput = document.getElementById('cityInput');
            const searchButton = document.getElementById('searchButton');
            const loadingIndicator = document.getElementById('loadingIndicator');
            const weatherResult = document.getElementById('weatherResult');
            const errorMessage = document.getElementById('errorMessage');
            const errorText = document.getElementById('errorText');
            const aqiCard = document.getElementById('aqiCard');

            // --- JS Helper Functions (for display) ---
            function getAqiStatus(aqi) {
                let status, colorClasses;
                if (aqi === null || aqi === undefined) { 
                    return { status: "N/A", colorClasses: "bg-gray-100 border-gray-300" };
                }
                if (aqi <= 50) { status = "Good"; colorClasses = "bg-green-100 border-green-400 text-green-700"; }
                else if (aqi <= 100) { status = "Moderate"; colorClasses = "bg-yellow-100 border-yellow-400 text-yellow-700"; }
                else if (aqi <= 150) { status = "Unhealthy (Sensitive)"; colorClasses = "bg-orange-100 border-orange-400 text-orange-700"; }
                else if (aqi <= 200) { status = "Unhealthy"; colorClasses = "bg-red-100 border-red-400 text-red-700"; }
                else if (aqi <= 300) { status = "Very Unhealthy"; colorClasses = "bg-purple-100 border-purple-400 text-purple-700"; }
                else { status = "Hazardous"; colorClasses = "bg-red-800 border-red-900 text-white"; }
                return { status, colorClasses };
            }
            
            function getUVRisk(uvi) {
                const uviNum = parseFloat(uvi);
                if (isNaN(uviNum)) return "N/A";
                if (uviNum < 3) return "Low Risk";
                if (uviNum < 6) return "Moderate Risk";
                if (uviNum < 8) return "High Risk";
                if (uviNum < 11) return "Very High Risk";
                return "Extreme Risk";
            }

            function formatTime(timestamp, timezoneOffset) {
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
                weatherResult.classList.add('hidden');
            }
            
            function updateWeatherDisplay(data) {
                setLoadingState(false);
                document.getElementById('locationName').textContent = data.locationName;
                document.getElementById('weatherDescription').textContent = data.description;
                document.getElementById('temperature').textContent = data.temperature;
                document.getElementById('feelsLike').textContent = data.feelsLike;
                document.getElementById('humidity').textContent = data.humidity;
                document.getElementById('windSpeed').textContent = data.windSpeed;
                document.getElementById('windDirection').textContent = data.windDirection;
                document.getElementById('precipitation').textContent = data.precipitation;
                const { status, colorClasses } = getAqiStatus(data.aqiValue);
                document.getElementById('aqiValue').textContent = data.aqiValue ?? "N/A";
                document.getElementById('aqiStatus').textContent = status;
                document.getElementById('pm25').textContent = data.pm25;
                aqiCard.className = `p-5 rounded-xl shadow-lg border-2 text-center transition duration-300 ${colorClasses}`;
                document.getElementById('aqiValue').style.color = status === "Hazardous" ? 'white' : ''; 
                document.getElementById('aqiStatus').style.color = status === "Hazardous" ? 'white' : ''; 
                document.getElementById('uvIndex').textContent = data.uvIndex;
                document.getElementById('uvRisk').textContent = getUVRisk(data.uvIndex);
                document.getElementById('sunriseTime').textContent = formatTime(data.sunrise, data.timezone);
                document.getElementById('sunsetTime').textContent = formatTime(data.sunset, data.timezone);
                weatherResult.classList.remove('hidden');
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
                    displayError("Could not connect to the Python server. Is it running?");
                }
            }

            searchButton.addEventListener('click', fetchAllDataFromServer);
            document.addEventListener('DOMContentLoaded', () => {
                 weatherResult.classList.remove('hidden');
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
