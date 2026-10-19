extends Node3D
## Right-drag orbit remains available while walking. No automatic recentering.
@export var target: Node3D
@export var sensitivity: float = .003
var yaw: float = .48
var pitch: float = -.25
var distance: float = 4.4
var orbiting: bool = false
var _focused: bool = true
@onready var arm: SpringArm3D = $SpringArm3D
const MIN_PITCH := -80.0 * PI / 180.0
const MAX_PITCH := 35.0 * PI / 180.0

func _ready() -> void:
	if target is CollisionObject3D:
		arm.add_excluded_object(target.get_rid())
	rotation = Vector3(pitch, yaw, 0)
	arm.spring_length = distance
	if is_instance_valid(target):
		global_position = target.global_position + Vector3.UP * 1.05

func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_FOCUS_OUT:
		_focused = false
		_release_mouse()
	elif what == NOTIFICATION_APPLICATION_FOCUS_IN:
		_focused = true

func _release_mouse() -> void:
	orbiting = false
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_RIGHT:
			orbiting = event.pressed and _focused
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if orbiting else Input.MOUSE_MODE_VISIBLE
		if event.pressed and event.button_index == MOUSE_BUTTON_WHEEL_UP:
			distance = maxf(1.2, distance - .3)
		if event.pressed and event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			distance = minf(8.0, distance + .3)
	if event is InputEventMouseMotion and orbiting:
		yaw = wrapf(yaw - event.relative.x * sensitivity, -PI, PI)
		pitch = clampf(pitch - event.relative.y * sensitivity, MIN_PITCH, MAX_PITCH)
	if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		_release_mouse()

func _process(delta: float) -> void:
	if not is_instance_valid(target):
		return
	var devices := Input.get_connected_joypads()
	if _focused and not devices.is_empty():
		var device: int = devices[0]
		var stick := Vector2(Input.get_joy_axis(device, JOY_AXIS_RIGHT_X), Input.get_joy_axis(device, JOY_AXIS_RIGHT_Y))
		if stick.length() > .18:
			yaw = wrapf(yaw - stick.x * delta * 2.4, -PI, PI)
			pitch = clampf(pitch - stick.y * delta * 1.8, MIN_PITCH, MAX_PITCH)
	global_position = global_position.lerp(target.global_position + Vector3.UP * 1.05, 1 - exp(-12 * delta))
	rotation = Vector3(pitch, yaw, 0)
	arm.spring_length = lerpf(arm.spring_length, distance, 1 - exp(-12 * delta))
