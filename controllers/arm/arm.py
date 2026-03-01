from controller import Supervisor # Note: Changed from Robot to Supervisor

# Initialize the Supervisor
robot = Supervisor()
timestep = int(robot.getBasicTimeStep())

# Initialize Devices

camera = robot.getDevice('color_sensor')
camera.enable(timestep)

pusher = robot.getDevice('pusher_motor')
pusher.setPosition(0.0)


target_box = robot.getFromDef('TARGET_BOX')
skip_box1 = robot.getFromDef('SKIP_BOX')

translation_field = target_box.getField('translation')
translation_field1 = skip_box1.getField('translation')

# The exact coordinates [X, Y, Z] where you want the box to spawn on the belt.
# You will need to change these values to match your conveyor belt's location.
spawn_coords_bad = [-2.0, 0.0, -0.2] 
spawn_coords_good = [-1.0, 0.0, -0.2] 

# Set up the 10-second timer
spawn_interval = 20.0 
steps_to_wait = int(spawn_interval / (timestep / 1000.0))
spawn_counter = 0

# State machine variables
pushing = False
push_timer = 0

while robot.step(timestep) != -1:
    
    # --- Teleportation Logic ---
    spawn_counter += 1
    if spawn_counter >= steps_to_wait:
        target_box.resetPhysics()
        translation_field.setSFVec3f(spawn_coords_bad)
        
        skip_box1.resetPhysics()
        translation_field1.setSFVec3f(spawn_coords_good)
        spawn_counter = 0

    # --- Existing Pusher Logic ---
    if pushing:
        push_timer -= 1
        if push_timer <= 0:
            pusher.setPosition(0.0) # Retract
            pushing = False
        continue

    # Discriminate based on color
    image = camera.getImage()
    
    r = camera.imageGetRed(image, 1, 0, 0)
    g = camera.imageGetGreen(image, 1, 0, 0)
    b = camera.imageGetBlue(image, 1, 0, 0)

    if r > g + 50 and r > b + 50:
        pusher.setPosition(-1) 
        pushing = True
        
        push_timer = int(1.0 / (timestep / 1000.0))