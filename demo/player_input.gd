extends Node
## Example adapter. No automatic playback or Space shortcut in normal play.

@export var motor: HumanoidMotor
@export var camera_rig: Node3D
var _focused: bool = true

func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_FOCUS_OUT:
		_focused = false
		if is_instance_valid(motor):
			motor.set_move_intent(Vector3.ZERO, 0)
	elif what == NOTIFICATION_APPLICATION_FOCUS_IN:
		_focused = true

func _physics_process(_delta: float) -> void:
	if not is_instance_valid(motor) or not is_instance_valid(camera_rig):
		return
	if not _focused:
		motor.set_move_intent(Vector3.ZERO, 0)
		return
	var x := float(Input.is_physical_key_pressed(KEY_D) or Input.is_physical_key_pressed(KEY_RIGHT)) - float(Input.is_physical_key_pressed(KEY_A) or Input.is_physical_key_pressed(KEY_LEFT))
	var y := float(Input.is_physical_key_pressed(KEY_W) or Input.is_physical_key_pressed(KEY_UP)) - float(Input.is_physical_key_pressed(KEY_S) or Input.is_physical_key_pressed(KEY_DOWN))
	var keyboard := Vector2(x, y).limit_length()
	var devices := Input.get_connected_joypads()
	var pad := Vector2.ZERO
	var jogging := Input.is_physical_key_pressed(KEY_SHIFT)
	if not devices.is_empty():
		var device: int = devices[0]
		pad = Vector2(Input.get_joy_axis(device, JOY_AXIS_LEFT_X), -Input.get_joy_axis(device, JOY_AXIS_LEFT_Y))
		if pad.length() > .18:
			pad = pad.normalized() * clampf((pad.length() - .18) / .82, 0, 1)
		else:
			pad = Vector2.ZERO
		jogging = jogging or Input.is_joy_button_pressed(device, JOY_BUTTON_LEFT_SHOULDER)
	var input_vector := keyboard if keyboard.length() >= pad.length() else pad
	# Yaw, rather than pitched camera basis, stays stable even at a low viewpoint.
	var yaw := camera_rig.rotation.y
	var forward := Vector3(-sin(yaw), 0, -cos(yaw))
	var right := Vector3(cos(yaw), 0, -sin(yaw))
	var direction := right * input_vector.x + forward * input_vector.y
	var speed := motor.config.jog_speed if jogging else motor.config.walk_speed
	if keyboard.is_zero_approx() and not pad.is_zero_approx():
		speed = motor.config.jog_speed * pad.length()
	else:
		speed *= input_vector.length()
	motor.set_move_intent(direction, speed)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_R:
			motor.reset_at(Vector3(0, .02, 4), camera_rig.rotation.y)
		elif event.keycode == KEY_F1 and get_parent().has_method("toggle_help"):
			get_parent().toggle_help()
