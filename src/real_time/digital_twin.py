"""
Webots Controller: Robotic Arm Pick and Place
Standard structure for a basic waypoint-based movement sequence.
"""
from controller import Robot

# Simulation time step (usually 32ms in Webots)
TIME_STEP = 32

def initialize_motors(robot, motor_names):
    """Retrieves motor devices and sets initial parameters."""
    motors = {}
    for name in motor_names:
        motor = robot.getDevice(name)
        if motor:
            # Set to position control mode (default)
            motor.setPosition(0.0) 
            motors[name] = motor
        else:
            print(f"Warning: Motor '{name}' not found on the robot node.")
    return motors

def main():
    # Initialize the Webots Robot instance
    robot = Robot()
    
    # These names must exactly match the joint names in your Webots Scene Tree.
    # The following are standard for UR-series robots.
    joint_names = [
        'shoulder_pan_joint', 'shoulder_lift_joint', 'elbow_joint',
        'wrist_1_joint', 'wrist_2_joint', 'wrist_3_joint'
    ]
    
    motors = initialize_motors(robot, joint_names)
    
    # Define waypoints (joint angles in radians) for the sequence
    # Note: You will need to physically jog the robot in Webots to find 
    # the exact radian values for your specific table and items.
    waypoints = {
        'home':  [0.0, -1.57, 0.0, -1.57, 0.0, 0.0],
        'hover': [1.57, -1.57, 1.57, -1.57, -1.57, 0.0],
        'pick':  [1.57, -1.0,  2.0,  -2.57, -1.57, 0.0]
    }
    
    current_state = 'home'
    timer = 0
    state_duration = 50 # Number of ticks to wait before changing state

    # Main simulation loop
    while robot.step(TIME_STEP) != -1:
        # State Machine Logic
        if timer == 0:
            if current_state == 'home':
                # Move to hover above the table
                target = waypoints['hover']
                current_state = 'hover'
                
            elif current_state == 'hover':
                # Move down to pick the item
                target = waypoints['pick']
                current_state = 'pick'
                
            elif current_state == 'pick':
                # Move back up to home
                target = waypoints['home']
                current_state = 'home'
            
            # Apply target positions to motors
            if len(motors) == len(target):
                for i, name in enumerate(joint_names):
                    motors[name].setPosition(target[i])
            
            # Reset timer to hold the pose
            timer = state_duration
            
        else:
            # Countdown while the robot physically moves to the target
            timer -= 1

if __name__ == '__main__':
    main()