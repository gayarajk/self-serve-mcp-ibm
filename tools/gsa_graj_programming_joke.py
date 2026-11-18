import requests
from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool()
def gsa_graj_programming_joke() -> str:
    """Fetch a random programming joke from a public API.

    Calls the JokeAPI to retrieve a single-part programming joke,
    demonstrating outbound internet access to a second distinct public endpoint.

    Returns:
        str: A programming joke.
    """
    url = "https://v2.jokeapi.dev/joke/Programming?type=single"
    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()

    if data.get("error"):
        return "Sorry, no joke could be fetched right now."

    return data["joke"]
