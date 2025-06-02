import os
import json
import requests
from flask import Flask, render_template, request, jsonify
from semantic_kernel import Kernel, OpenApiSkill
from semantic_kernel.connectors.ai.openai import OpenAIClient
from semantic_kernel.core_skills import HttpSkill
from dotenv import load_dotenv

# ==============================================================================
# CONFIGURATION
# ==============================================================================
load_dotenv()

OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY")
OWM_API_KEY           = os.getenv("OPENWEATHERMAP_API_KEY")
SENTINEL_CLIENT_ID    = os.getenv("SENTINEL_CLIENT_ID")
SENTINEL_CLIENT_SECRET= os.getenv("SENTINEL_CLIENT_SECRET")
DRONE_API_KEY         = os.getenv("DRONE_API_KEY")
SEARCH_API_KEY        = os.getenv("SEARCH_API_KEY")
SEARCH_CX_ID          = os.getenv("SEARCH_CX_ID")

# ==============================================================================
# FLASK APP
# ==============================================================================
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "change-me")

# ==============================================================================
# SEMANTIC KERNEL SETUP
# ==============================================================================
# 1) Create an AI client (using OpenAI for language planning)
ai_client = OpenAIClient(api_key=OPENAI_API_KEY)
kernel    = Kernel(ai_client)

# 2) Register core skills (e.g., HTTP)
kernel.import_skill(HttpSkill(kernel), "http")

# 3a) OpenWeatherMap “get_current_weather” skill
with open("openapi/openapi-openweathermap.json", "r") as f:
    openweather_openapi = json.load(f)

kernel.import_skill(
    OpenApiSkill(
        kernel,
        openweather_openapi,
        default_operation_id="getOneCallCurrent",
        # Inject the API key as query parameter “appid”
        auth_setting={"appid": OWM_API_KEY}
    ),
    skill_name="OpenWeather"
)

# 3b) Drone Dispatch “send_drone_mission” skill
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

# 3c) Web search “search_web” skill
def search_web_func(input_text: str) -> str:
    """
    Hand-rolled “search_web” skill using Google Custom Search.
    Replace with your preferred search engine as needed.
    """
    if not SEARCH_API_KEY or not SEARCH_CX_ID:
        return "Error: SEARCH_API_KEY or SEARCH_CX_ID is not set in environment."

    params = {
        "key": SEARCH_API_KEY,
        "cx": SEARCH_CX_ID,
        "q": input_text
    }
    resp = requests.get("https://www.googleapis.com/customsearch/v1", params=params)
    if resp.status_code != 200:
        return f"Search error (status {resp.status_code}): {resp.text}"

    data = resp.json()
    items = data.get("items", [])
    results = []
    for it in items:
        title = it.get("title", "<no title>")
        snippet = it.get("snippet", "")
        results.append(f"• {title} → {snippet}")
    return "\n".join(results)

kernel.register_semantic_function(
    name="search_web",
    function=lambda ctx: search_web_func(ctx.get_input()),
    skill_name="WebSearch"
)

# ==============================================================================
# Sentinel Hub: OAuth2 token + OpenAPI skill registration
# ==============================================================================
def get_sentinel_token() -> str:
    """
    Perform client_credentials OAuth call to Sentinel Hub and return the access token.
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
    Fetch a fresh OAuth2 token and register (or re-register) the Sentinel skill
    with that token in the Authorization header.
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

# Register Sentinel at startup
import_sentinel_skill()

# ==============================================================================
# AGENT “PROMPT” / PLAN (loaded from external file)
# ==============================================================================
plan_path = os.path.join(os.path.dirname(__file__), "fire_risk_plan.txt")
try:
    with open(plan_path, "r", encoding="utf-8") as plan_file:
        fire_risk_plan = plan_file.read()
except FileNotFoundError:
    fire_risk_plan = ""

fire_risk_function = kernel.create_semantic_function(
    fire_risk_plan,
    name="CheckFireRisk",
    description=(
        "Multi-step agent that fetches weather, calculates fire risk, "
        "checks news, checks satellite, and dispatches a drone."
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
    Returns JSON: { "answer": "<agent's full bullet-list response>" }
    """
    payload = request.json or {}
    question = payload.get("question", "").strip()
    if not question:
        return jsonify({"error": "No question provided."}), 400

    # Before invoking the agent, refresh the Sentinel skill token
    import_sentinel_skill()

    # Invoke the Kernel function “CheckFireRisk” with the user's question
    result = fire_risk_function.invoke(question)
    answer_text = result  # This will be the agent’s final answer (string)

    return jsonify({"answer": answer_text})


# ==============================================================================
# APP ENTRYPOINT
# ==============================================================================
if __name__ == '__main__':
   app.run()
