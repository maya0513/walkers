extends SceneTree
## Exercise the shipped scene and input adapter, not a second controller.

var stage: Node3D
var actor: HumanoidMotor
var camera_rig: Node3D
var adapter: Node
var failures: Array[String] = []
var measured: Dictionary = {}

func _initialize() -> void:
	_run.call_deferred()

func _ticks(count: int) -> void:
	for i in range(count):
		await physics_frame
		await process_frame

func _check(condition: bool, label: String) -> void:
	if not condition:
		failures.append(label)

func _key(code: Key, pressed: bool) -> void:
	var event := InputEventKey.new()
	event.keycode = code
	event.physical_keycode = code
	event.pressed = pressed
	Input.parse_input_event(event)

func _mouse_button(button: MouseButton, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = button
	event.pressed = pressed
	camera_rig._unhandled_input(event)

func _drag(relative: Vector2) -> void:
	var event := InputEventMouseMotion.new()
	event.relative = relative
	camera_rig._unhandled_input(event)

func _run() -> void:
	Engine.physics_ticks_per_second = 60
	stage = load("res://demo/main.tscn").instantiate()
	root.add_child(stage)
	actor = stage.player
	camera_rig = stage.camera_rig
	adapter = stage.adapter
	await _ticks(4)
	var initial := actor.global_position
	var initial_yaw: float = actor.facing_yaw
	_check(absf(wrapf(initial_yaw-camera_rig.yaw,-PI,PI)) < .001, "initial heading differs from camera")
	_check(not stage.help.visible, "help visible at startup")
	# Longer than the former 20-second automatic-demo cycle.
	await _ticks(1320)
	var displacement := Vector2(actor.global_position.x-initial.x, actor.global_position.z-initial.z).length()
	measured.no_input_seconds = 22
	measured.idle_horizontal_displacement_m = displacement
	_check(displacement < .001 and actor.requested_speed == 0, "uncommanded movement or reset")
	_check(actor.animator.state == &"Idle", "idle state did not persist")
	_key(KEY_SPACE, true)
	await _ticks(4)
	_key(KEY_SPACE, false)
	await _ticks(8)
	_check(actor.global_position.distance_to(initial) < .01 and actor.requested_speed == 0, "Space changes movement or resets")
	_key(KEY_W, true)
	await _ticks(50)
	_check(actor.actual_velocity.length() > 1.2, "keyboard movement failed")
	var moving_from := actor.global_position
	var old_yaw: float = camera_rig.yaw
	_mouse_button(MOUSE_BUTTON_RIGHT, true)
	_drag(Vector2(200, 20))
	await _ticks(15)
	_check(camera_rig.orbiting and absf(wrapf(camera_rig.yaw-old_yaw,-PI,PI)) > .5, "right-drag failed while moving")
	_check(actor.global_position.distance_to(moving_from) > .2 and actor.requested_speed > 1, "orbit interrupts movement")
	_mouse_button(MOUSE_BUTTON_RIGHT, false)
	_key(KEY_W, false)
	await _ticks(60)
	var retained_yaw: float = camera_rig.yaw
	await _ticks(30)
	_check(absf(wrapf(camera_rig.yaw-retained_yaw,-PI,PI)) < .0001, "camera recenters automatically")
	_mouse_button(MOUSE_BUTTON_RIGHT, true)
	_drag(Vector2(30000,-30000))
	_check(is_equal_approx(camera_rig.pitch,camera_rig.MAX_PITCH), "upper pitch limit")
	_drag(Vector2(-30000,30000))
	_check(is_equal_approx(camera_rig.pitch,camera_rig.MIN_PITCH), "lower pitch limit")
	_check(camera_rig.yaw >= -PI and camera_rig.yaw <= PI, "camera yaw not wrapped")
	for i in range(60):
		_mouse_button(MOUSE_BUTTON_WHEEL_UP,true)
	_check(is_equal_approx(camera_rig.distance,1.2), "minimum camera distance")
	for i in range(60):
		_mouse_button(MOUSE_BUTTON_WHEEL_DOWN,true)
	_check(is_equal_approx(camera_rig.distance,8.0), "maximum camera distance")
	camera_rig._notification(Node.NOTIFICATION_APPLICATION_FOCUS_OUT)
	_check(not camera_rig.orbiting and Input.mouse_mode == Input.MOUSE_MODE_VISIBLE, "focus loss leaves mouse captured")
	camera_rig._notification(Node.NOTIFICATION_APPLICATION_FOCUS_IN)
	# Motor response is measured without the adapter overwriting the public API.
	adapter.set_physics_process(false)
	var turns: Dictionary = {}
	for degrees: int in [90,180]:
		actor.reset_at(Vector3(0,.005,4),0)
		await _ticks(2)
		var target := deg_to_rad(degrees)
		actor.set_move_intent(Vector3(-sin(target),0,-cos(target)),1.4)
		var elapsed := 0.0
		while absf(wrapf(target-actor.facing_yaw,-PI,PI)) > deg_to_rad(1) and elapsed < .8:
			await _ticks(1)
			elapsed += 1.0/60.0
		turns[str(degrees)] = elapsed
		_check(elapsed <= (.25 if degrees == 90 else .4), "%d degree steering too slow" % degrees)
		_check(actor.actual_velocity.length() > .05, "%d degree steering blocks movement" % degrees)
		# Change direction before a nominal source turn animation would finish.
		actor.set_move_intent(Vector3.FORWARD,1.4)
		await _ticks(25)
		_check(absf(wrapf(actor.facing_yaw,-PI,PI)) < deg_to_rad(1), "steering input cannot interrupt")
	measured.turn_response_seconds = turns
	actor.set_move_intent(Vector3.ZERO,0)
	actor.reset_at(Vector3(0,.005,-10.7),0)
	camera_rig.yaw = 0
	camera_rig.pitch = 0
	camera_rig.distance = 4.4
	camera_rig.global_position = actor.global_position + Vector3.UP*1.05
	await _ticks(20)
	var hit_length: float = camera_rig.arm.get_hit_length()
	measured.camera_obstruction_length_m = hit_length
	_check(hit_length < 1.5 and hit_length > .1, "camera obstruction not avoided")
	var file := FileAccess.open("res://reports/controls.json",FileAccess.WRITE)
	file.store_string(JSON.stringify({"failures":failures,"measured":measured},"\t"))
	file.close()
	print("CONTROLS_COMPLETE failures=",failures," measured=",measured)
	quit(0 if failures.is_empty() else 1)
