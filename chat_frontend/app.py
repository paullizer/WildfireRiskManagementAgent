import os
import json
import requests
from flask import Flask, render_template, request, jsonify

# === SEMANTIC KERNEL IMPORTS ===
from semantic_kernel import Kernel
from semantic_kernel.skill_definition import OpenApiSkill
from semantic_kernel.connectors.ai.azure_openai import AzureOpenAIClient
from semantic_kernel.core_skills import HttpSkill

from dotenv import load_dotenv

# ==============================================================================
# CONFIGURATION
# ==============================================================================
load_dotenv()

# --- Azure OpenAI settings ---
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# --- Other API keys & IDs ---
OWM_API_KEY            = os.getenv("OPENWEATHERMAP_API_KEY")
SENTINEL_CLIENT_ID     = os.getenv("SENTINEL_CLIENT_ID")
SENTINEL_CLIENT_SECRET = os.getenv("SENTINEL_CLIENT_SECRET")
DRONE_API_KEY          = os.getenv("DRONE_API_KEY")

# --- Azure AI Foundry search‐agent settings ---
FOUNDRY_ENDPOINT         = os.getenv("FOUNDRY_ENDPOINT")
FOUNDRY_PROJECT_ID       = os.getenv("FOUNDRY_PROJECT_ID")
FOUNDRY_SEARCH_AGENT_ID  = os.getenv("FOUNDRY_SEARCH_AGENT_ID")
FOUNDRY_API_KEY          = os.getenv("FOUNDRY_API_KEY")

# ==============================================================================
# FLASK APP
# ==============================================================================
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "change‐me")

# ==============================================================================
# SEMANTIC KERNEL SETUP (using Azure OpenAI)
# ==============================================================================
# 1) Create and configure an AzureOpenAIClient
if not (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT):
    raise RuntimeError(
        "Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT."
    )

ai_client = AzureOpenAIClient(
    endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    deployment_name=AZURE_OPENAI_DEPLOYMENT
)
kernel = Kernel(ai_client)

# 2) Register HttpSkill (for any low‐level HTTP calls, e.g., Sentinel token)
kernel.import_skill(HttpSkill(kernel), "http")

# ==============================================================================
# 1) OPENWEATHER: “get_current_weather” skill registration
# ==============================================================================
with open("openapi/openapi-openweathermap.json", "r") as f:
    openweather_openapi = json.load(f)

kernel.import_skill(
    OpenApiSkill(
        kernel,
        openweather_openapi,
        default_operation_id="getOneCallCurrent",
        # This tells the SDK to append "?appid=<OWM_API_KEY>" to every call
        auth_setting={"appid": OWM_API_KEY}
    ),
    skill_name="OpenWeather"
)

# ==============================================================================
# 2) DRONE: “send_drone_mission” skill registration
# ==============================================================================
with open("openapi/openapi-drone.json", "r") as f:
    drone_openapi = json.load(f)

kernel.import_skill(
    OpenApiSkill(
        kernel,
        drone_openapi,
        default_operation_id="sendDroneMission",
        auth_setting={"Authorization": f"Bearer {DRONE_API_KEY}"}
    ),
    skill_name="Drone"
)

# ==============================================================================
# 3) SENTINEL: OAuth2 + dynamic “process” skill registration
# ==============================================================================
def get_sentinel_token() -> str:
    """
    Perform the client_credentials OAuth call to Sentinel Hub and return the access token.
    """
    token_url = (
        "https://services.sentinel-hub.com/"
        "auth/realms/main/protocol/openid-connect/token"
    )
    data = {
        "grant_type":    "client_credentials",
        "client_id":     SENTINEL_CLIENT_ID,
        "client_secret": SENTINEL_CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(token_url, data=data, headers=headers)
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Failed to obtain Sentinel Hub access_token")
    return token

with open("openapi/openapi-sentinel.json", "r") as f:
    sentinel_openapi = json.load(f)

def import_sentinel_skill():
    """
    Fetch a fresh OAuth2 token and (re)register the Sentinel “process” skill
    with that Authorization: Bearer <token> header.
    """
    token = get_sentinel_token()
    kernel.import_skill(
        OpenApiSkill(
            kernel,
            sentinel_openapi,
            default_operation_id="process",
            auth_setting={"Authorization": f"Bearer {token}"}
        ),
        skill_name="Sentinel"
    )

# Register Sentinel skill at startup
import_sentinel_skill()

# ==============================================================================
# 4) AZURE AI FOUNDRY: “Internet Fire Search Agent” registration
# ==============================================================================
def search_foundry_agent(query_text: str) -> str:
    """
    Invoke the Azure AI Foundry “Internet Fire Search Agent” via REST:
      POST {FOUNDRY_ENDPOINT}/projects/{FOUNDRY_PROJECT_ID}/agents/{FOUNDRY_SEARCH_AGENT_ID}/invoke
    Payload: { "question": "<query_text>" }
    Returns the “answer” string from Foundry.
    """
    if not (FOUNDRY_ENDPOINT and FOUNDRY_PROJECT_ID and FOUNDRY_SEARCH_AGENT_ID and FOUNDRY_API_KEY):
        return "Error: Foundry endpoint, project ID, agent ID or API key not set."

    invoke_url = (
        f"{FOUNDRY_ENDPOINT}/projects/{FOUNDRY_PROJECT_ID}"
        f"/agents/{FOUNDRY_SEARCH_AGENT_ID}/invoke"
    )
    payload = {"question": query_text}
    headers = {
        "Content-Type": "application/json",
        "api-key":       FOUNDRY_API_KEY
    }

    resp = requests.post(invoke_url, json=payload, headers=headers)
    if resp.status_code != 200:
        return f"Foundry Search Agent error ({resp.status_code}): {resp.text}"

    data = resp.json()
    # Foundry returns {"answer": "<agent’s reply>", …}
    return data.get("answer", "<no answer returned>")

# Register it as a semantic function under the name “search_web”
kernel.register_semantic_function(
    name="search_web",
    function=lambda ctx: search_foundry_agent(ctx.get_input()),
    skill_name="WebSearch"
)

# ==============================================================================
# AGENT PROMPTS (each in its own Markdown file)
# ==============================================================================
base_dir = os.path.dirname(__file__)

# 1) Weather Analysis Agent
weather_path = os.path.join(base_dir, "prompts/Weather Analysis Agent.md")
with open(weather_path, "r", encoding="utf-8") as f:
    weather_plan = f.read()

weather_function = kernel.create_semantic_function(
    weather_plan,
    name="WeatherAgent",
    description="Retrieves current weather and computes a weather-based fire risk."
)

# 2) Internet Search Agent (orchestrated by Foundry)
search_path = os.path.join(base_dir, "prompts/Internet Search Agent.md")
with open(search_path, "r", encoding="utf-8") as f:
    search_plan = f.read()

search_function = kernel.create_semantic_function(
    search_plan,
    name="SearchAgent",
    description="Queries the Azure AI Foundry Internet Fire Search Agent."
)

# 3) Drone Dispatch Agent
drone_path = os.path.join(base_dir, "prompts/Drone Dispatch Agent.md")
with open(drone_path, "r", encoding="utf-8") as f:
    drone_plan = f.read()

drone_function = kernel.create_semantic_function(
    drone_plan,
    name="DroneAgent",
    description="Dispatches a drone when fire risk is high."
)

# 4) Wildfire Management Agent (orchestrator)
wildfire_path = os.path.join(base_dir, "prompts/Wildfire Management Agent.md")
with open(wildfire_path, "r", encoding="utf-8") as f:
    wildfire_plan = f.read()

wildfire_function = kernel.create_semantic_function(
    wildfire_plan,
    name="WildfireAgent",
    description=(
        "Orchestrates WeatherAgent, SearchAgent, and DroneAgent to produce "
        "a complete wildfire risk report."
    )
)

# ==============================================================================
# FLASK ROUTES
# ==============================================================================
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/chat", methods=["GET"])
def chat_page():
    return render_template("chat.html")


@app.route("/api/ask", methods=["POST"])
def ask_agent():
    """
    Called by the chat UI via AJAX. Expects JSON:
       { "question": "What is the fire risk in Alexandria, VA?" }
    Returns JSON: { "answer": "<Wildfire risk report>" }
    """
    payload = request.json or {}
    question = payload.get("question", "").strip()
    if not question:
        return jsonify({"error": "No question provided."}), 400

    # Refresh the Sentinel token so any downstream calls to Sentinel use a valid Bearer token
    import_sentinel_skill()

    # Invoke the Wildfire Management Agent (which itself will call WeatherAgent, SearchAgent, DroneAgent)
    result = wildfire_function.invoke(question)
    report = result  # The orchestrator’s final report (string)

    return jsonify({"answer": report})


# ==============================================================================
# APP ENTRYPOINT
# ==============================================================================
if __name__ == '__main__':
   app.run()