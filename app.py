import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

# Environment‐based API key (set in Azure App Service → Configuration → Application settings)
API_KEY = os.getenv("DRONE_API_KEY")
if API_KEY is None:
    raise RuntimeError("DRONE_API_KEY environment variable not set")

# In‐memory store for missions
missions = {}

def verify_api_key():
    """
    Verifies that the incoming request has a valid X-API-Key header.
    Aborts with a 401 if missing or invalid.
    """
    incoming_key = request.headers.get("X-API-Key")
    if incoming_key != API_KEY:
        abort(401, description="Unauthorized: Invalid or missing API key.")

@app.route("/drone/submit_mission", methods=["POST"])
def submit_mission():
    """
    Submit a drone mission. Returns a mission_id and initial status.
    Requires a valid API key in the 'X-API-Key' header.
    Expected JSON body:
    {
      "waypoints": [
        { "lat": <float>, "lon": <float> },
        ...
      ],
      "altitude": <float>,
      "speed": <float>
    }
    """
    verify_api_key()

    payload = request.get_json(force=True)
    if not payload:
        abort(400, description="Missing JSON body.")

    # Basic validation
    waypoints = payload.get("waypoints")
    altitude = payload.get("altitude")
    speed = payload.get("speed")

    if (
        waypoints is None
        or not isinstance(waypoints, list)
        or altitude is None
        or speed is None
    ):
        abort(400, description="Invalid or missing fields: waypoints, altitude, speed.")

    # Validate each waypoint
    for wp in waypoints:
        if not isinstance(wp, dict) or "lat" not in wp or "lon" not in wp:
            abort(400, description="Each waypoint must be an object with 'lat' and 'lon'.")

    mission_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # Store mission in memory
    missions[mission_id] = {
        "flight_path": {
            "waypoints": waypoints,
            "altitude": altitude,
            "speed": speed
        },
        "status": "scheduled",
        "submitted_at": now,
        "images": []
    }

    response = {
        "mission_id": mission_id,
        "status": "scheduled",
        "submitted_at": now.isoformat() + "Z"
    }
    return jsonify(response), 200

@app.route("/drone/status/<mission_id>", methods=["GET"])
def get_status(mission_id):
    """
    Retrieve the status of a given mission_id.
    Requires a valid API key in the 'X-API-Key' header.
    """
    verify_api_key()

    mission = missions.get(mission_id)
    if mission is None:
        abort(404, description="Mission not found.")

    response = {
        "mission_id": mission_id,
        "status": mission["status"],
        "submitted_at": mission["submitted_at"].isoformat() + "Z"
    }
    return jsonify(response), 200

@app.route("/drone/complete_mission/<mission_id>", methods=["POST"])
def complete_mission(mission_id):
    """
    Mark a mission as completed and generate dummy image metadata.
    Requires a valid API key in the 'X-API-Key' header.
    Returns a list of ImageInfo dicts.
    """
    verify_api_key()

    mission = missions.get(mission_id)
    if mission is None:
        abort(404, description="Mission not found.")

    # If already completed, return existing images
    if mission["status"] == "completed":
        return jsonify(mission["images"]), 200

    # Simulate image captures at each waypoint
    images = []
    now = datetime.utcnow()
    for coord in mission["flight_path"]["waypoints"]:
        image_id = str(uuid.uuid4())
        url = f"https://example.com/drone_images/{mission_id}/{image_id}.jpg"
        image_info = {
            "image_id": image_id,
            "url": url,
            "timestamp": now.isoformat() + "Z",
            "coordinates": {
                "lat": coord["lat"],
                "lon": coord["lon"]
            }
        }
        images.append(image_info)

    mission["status"] = "completed"
    mission["images"] = images

    return jsonify(images), 200

@app.route("/drone/images/<mission_id>", methods=["GET"])
def get_images(mission_id):
    """
    Retrieve the list of images captured for a completed mission.
    Requires a valid API key in the 'X-API-Key' header.
    """
    verify_api_key()

    mission = missions.get(mission_id)
    if mission is None:
        abort(404, description="Mission not found.")
    if mission["status"] != "completed":
        abort(400, description="Mission not completed yet.")

    return jsonify(mission["images"]), 200

@app.route("/drone/update_waypoints/<mission_id>", methods=["PUT"])
def update_waypoints(mission_id):
    """
    Update the flight path of a mission before it has started.
    Requires a valid API key in the 'X-API-Key' header.
    Expected JSON body (same schema as submit_mission):
    {
      "waypoints": [
        { "lat": <float>, "lon": <float> },
        ...
      ],
      "altitude": <float>,
      "speed": <float>
    }
    """
    verify_api_key()

    mission = missions.get(mission_id)
    if mission is None:
        abort(404, description="Mission not found.")
    if mission["status"] != "scheduled":
        abort(400, description="Cannot update waypoints after mission has started or completed.")

    payload = request.get_json(force=True)
    if not payload:
        abort(400, description="Missing JSON body.")

    waypoints = payload.get("waypoints")
    altitude = payload.get("altitude")
    speed = payload.get("speed")

    if (
        waypoints is None
        or not isinstance(waypoints, list)
        or altitude is None
        or speed is None
    ):
        abort(400, description="Invalid or missing fields: waypoints, altitude, speed.")

    for wp in waypoints:
        if not isinstance(wp, dict) or "lat" not in wp or "lon" not in wp:
            abort(400, description="Each waypoint must be an object with 'lat' and 'lon'.")

    mission["flight_path"] = {
        "waypoints": waypoints,
        "altitude": altitude,
        "speed": speed
    }

    response = {
        "mission_id": mission_id,
        "status": mission["status"],
        "submitted_at": mission["submitted_at"].isoformat() + "Z"
    }
    return jsonify(response), 200

@app.route("/drone/cancel_mission/<mission_id>", methods=["DELETE"])
def cancel_mission(mission_id):
    """
    Cancel a scheduled mission.
    Requires a valid API key in the 'X-API-Key' header.
    """
    verify_api_key()

    mission = missions.get(mission_id)
    if mission is None:
        abort(404, description="Mission not found.")
    if mission["status"] != "scheduled":
        abort(400, description="Cannot cancel a mission that is in progress or completed.")

    mission["status"] = "canceled"
    response = {
        "mission_id": mission_id,
        "status": "canceled",
        "submitted_at": mission["submitted_at"].isoformat() + "Z"
    }
    return jsonify(response), 200

@app.route("/", methods=["GET"])
def root():
    """
    API Health Check
    Requires a valid API key in the 'X-API-Key' header.
    """
    verify_api_key()
    return jsonify({"message": "Mock Drone API is up and running."}), 200

if __name__ == '__main__':
   app.run()