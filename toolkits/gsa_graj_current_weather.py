import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool()
def gsa_graj_current_weather(city: str) -> str:
    """Return current weather for a city.

    Calls the wttr.in public API to retrieve live weather data,
    proving outbound internet access from the tool container.

    Args:
        city (str): The city to look up, e.g. 'London' or 'New York'.

    Returns:
        str: A short weather summary including temperature, condition, and humidity.
    """
    url = f"https://wttr.in/{requests.utils.quote(city)}?format=j1"
    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()
    current = data["current_condition"][0]

    temp_c = current["temp_C"]
    temp_f = current["temp_F"]
    description = current["weatherDesc"][0]["value"]
    humidity = current["humidity"]
    feels_like_c = current["FeelsLikeC"]

    return (
        f"Weather in {city}: {description}. "
        f"Temperature: {temp_c}°C ({temp_f}°F), feels like {feels_like_c}°C. "
        f"Humidity: {humidity}%."
    )
