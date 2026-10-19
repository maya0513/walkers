extends Node
## Explicit offline capture adapter. It is never instantiated during normal play.
@export var motor: HumanoidMotor
var time: float = 0.0

func _physics_process(delta: float) -> void:
	time += delta
	var direction := Vector3.ZERO
	var speed := 0.0
	if time > 1 and time < 4:
		direction = Vector3.FORWARD
		speed = motor.config.walk_speed
	elif time >= 4 and time < 6:
		direction = Vector3.FORWARD
		speed = motor.config.jog_speed
	elif time > 7 and time < 10:
		direction = Vector3.BACK
		speed = motor.config.walk_speed
	elif time >= 10 and time < 12:
		direction = Vector3.BACK
		speed = motor.config.jog_speed
	elif time > 13 and time < 15:
		direction = Vector3.LEFT
		speed = motor.config.walk_speed
	elif time > 16 and time < 18:
		direction = Vector3.RIGHT
		speed = motor.config.walk_speed
	motor.set_move_intent(direction, speed)
