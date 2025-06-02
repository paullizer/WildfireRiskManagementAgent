
**Explanation & Annotations:**

1. **Semantic Kernel Setup**  
   - We create an `OpenAIClient` (backed by `OPENAI_API_KEY`) to handle the LLM logic.  
   - We import an `HttpSkill` (for generic HTTP calls, if needed).  
   - We import three OpenAPI-based skills via `kernel.import_skill(OpenApiSkill(...))` using the JSON definitions in `openapi/openapi-*.json`:  
     - **OpenWeather** skill (operation `getOneCallCurrent`) to fetch `temp`, `humidity`, `wind_speed`.  
     - **Sentinel** skill (operation `process`) for on-the-fly NDVI/thermal retrieval.  
     - **Drone** skill (operation `sendDroneMission`) to dispatch a drone.  
   - We register a custom, hand-rolled `search_web` function (using a real search engine like Google Custom Search or SerpAPI) under the name `"search_web"`.  

2. **Agent Prompt**  
   - We place the entire multi-step logic—exactly as the user described it—inside a Semantic Kernel “system-style” prompt.  
   - We wrap that into a single `kernel.create_semantic_function(...)` call, naming it `"CheckFireRisk"`.  
   - At runtime, when the user asks “What is the fire risk in Alexandria, VA?”, Kernel will:  
     1. Extract “Alexandria, VA”  
     2. Call `get_current_weather` with its coordinates  
     3. Compute `weather_fire_risk` locally (weather > humidity > wind thresholds)  
     4. Call `search_web` → parse results → possibly elevate risk  
     5. Call `get_satellite_image` → look for hotspots → possibly elevate risk  
     6. If final ≥ High → call `send_drone_mission`  
     7. Assemble a neatly bulleted summary.  

3. **Flask Endpoints**  
   - **`/`** → serves **`templates/index.html`** (our “landing page”).  
   - **`/chat`** → serves **`templates/chat.html`**, where the user can type a question and see the streaming response.  
   - **`/api/ask`** → AJAX endpoint. Receives a JSON object like `{"question": "What is the fire risk in Alexandria, VA?"}` and returns `{"answer": "<full agent response>"}`.  

4. **Templates**  

   ### templates/base.html (:contentReference[oaicite:4]{index=4})  
   This is the “wrapper” layout (navbar, container, footer). You already have it. It includes Bootstrap via CDN and also references a local copy of `static/bootstrap/css/bootstrap.css`.  

   ### templates/index.html (:contentReference[oaicite:5]{index=5})  
   Your current **`index.html`** shows a “select features” UI. You might repurpose it or simply add a “Go to Chat” button. For example:
   ```html
   {% extends 'base.html' %}
   {% block title %}Fire Risk Chatbot{% endblock %}

   {% block content %}
   <div class="container text-center my-5">
       <h1 class="display-4">Fire Risk Chatbot</h1>
       <p class="lead">Ask about the current fire risk anywhere in the U.S. (or global)!</p>
       <a href="{{ url_for('chat_page') }}" class="btn btn-primary btn-lg mt-4">Start Chat →</a>
   </div>
   {% endblock %}
