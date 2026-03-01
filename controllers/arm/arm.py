import threading  # Added for background tasks
import time

import requests
from controller import Supervisor

# Initialize the Supervisor
robot = Supervisor()
timestep = int(robot.getBasicTimeStep())

# API Configuration
ENDPOINT_URL = "https://28e1-77-59-244-130.ngrok-free.app/factory/failure"


def upload_image(filename, description):
    """Function to be run in a background thread."""
    try:
        with open(filename, "rb") as f:
            files = {"image": (filename, f, "image/jpeg")}
            data = {"description": description}
            response = requests.post(ENDPOINT_URL, files=files, data=data, timeout=10)

        if response.status_code == 200:
            print(f"Async alert sent: {response.json().get('status')}")
        else:
            print(f"Async upload failed: {response.status_code}")
    except Exception as e:
        print(f"Background network error: {e}")


# Initialize Devices
camera = robot.getDevice("color_sensor")
camera.enable(timestep)

pusher = robot.getDevice("pusher_motor")
pusher.setPosition(0.0)

# ... [Existing box/translation setup code] ...
target_box = robot.getFromDef("TARGET_BOX")
skip_box2 = robot.getFromDef("SKIP_BOX2")
skip_box3 = robot.getFromDef("SKIP_BOX3")
skip_box4 = robot.getFromDef("SKIP_BOX4")

translation_field = target_box.getField("translation")
translation_field2 = skip_box2.getField("translation")
translation_field3 = skip_box3.getField("translation")
translation_field4 = skip_box4.getField("translation")

spawn_coords_bad = [-3.0, 0.0, -0.2]
spawn_coords_good2 = [-1.0, 0.0, -0.2]
spawn_coords_good3 = [-2.0, 0.0, -0.2]
spawn_coords_good4 = [-4.0, 0.0, -0.2]

spawn_interval = 20.0
steps_to_wait = int(spawn_interval / (timestep / 1000.0))
spawn_counter = 0

pushing = False
push_timer = 0
is_error = False

while robot.step(timestep) != -1:
    spawn_counter += 1
    # --- Teleportation Logic ---
    if spawn_counter >= steps_to_wait:
        target_box.resetPhysics()
        translation_field.setSFVec3f(spawn_coords_bad)
        skip_box2.resetPhysics()
        translation_field2.setSFVec3f(spawn_coords_good2)
        skip_box3.resetPhysics()
        translation_field3.setSFVec3f(spawn_coords_good3)
        skip_box4.resetPhysics()
        translation_field4.setSFVec3f(spawn_coords_good4)
        spawn_counter = 0

    if pushing:
        push_timer -= 1
        if push_timer <= 0:
            pusher.setPosition(0.0)
            pushing = False
        continue

    # --- Non-blocking Image Upload ---
    if is_error:
        filename = f"error_scene_{int(time.time())}.jpg"
        robot.exportImage(filename, 100)

        # Launch the upload in a separate thread
        desc = "Red box detected: Sorting failure event."
        thread = threading.Thread(target=upload_image, args=(filename, desc))
        thread.start()

        is_error = False

    # Discriminate based on color
    image = camera.getImage()
    r = camera.imageGetRed(image, 1, 0, 0)
    g = camera.imageGetGreen(image, 1, 0, 0)
    b = camera.imageGetBlue(image, 1, 0, 0)

    if r > g + 50 and r > b + 50:
        pusher.setPosition(-1)
        pushing = True
        print("Found error! Dispatching notification...")
        is_error = True
        push_timer = int(1.0 / (timestep / 1000.0))
