from controller import Supervisor
import time

# Simulation time step
TIME_STEP = 32

def main():
    robot = Supervisor()
    
    # Link to the box using the DEF name we set earlier
    target_box = robot.getFromDef('TARGET_BOX')
    
    # Access the 'translation' field of the box
    # This is the specific field that controls its 3D position
    if target_box:
        trans_field = target_box.getField('translation')
    else:
        print("Error: Could not find TARGET_BOX")
        return

    # Track time for the teleportation interval
    last_teleport_time = robot.getTime()
    teleport_interval = 5.0 # Seconds

    while robot.step(TIME_STEP) != -1:
        current_time = robot.getTime()
        
        # Check if 5 seconds have passed
        if current_time - last_teleport_time > teleport_interval:
            print(f"Teleporting box at {current_time:.2f}s")
            
            # Set the new coordinates [X, Y, Z]
            # Example: 0.5m in front of robot, 0.05m high (on the belt)
            new_position = [0.0, -0.0196559, 0.444809]
            
            # This 'setSFVec3f' command is what actually moves the object
            trans_field.setSFVec3f(new_position)
            
            # Reset the physics so it doesn't carry over old momentum
            target_box.resetPhysics()
            
            last_teleport_time = current_time

if __name__ == '__main__':
    main()