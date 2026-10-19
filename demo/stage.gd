extends Node3D

const CHARACTER = preload("res://addons/walkers/character.tscn")
var player: HumanoidMotor
var camera_rig: Node3D
var adapter: Node
var help: Label

var _capture: bool = false
var _frame: int = 0
var _capture_limit: int = 500
var _capture_dir: String = "res://reports/captures/runtime"

func _ready() -> void:
	_make_world()
	player = CHARACTER.instantiate()
	player.name = "Player"
	add_child(player)
	player.reset_at(Vector3(0, .02, 4), .48)
	camera_rig = Node3D.new()
	camera_rig.name = "OrbitCamera"
	camera_rig.set_script(load("res://demo/orbit_camera.gd"))
	camera_rig.set("target", player)
	var arm := SpringArm3D.new()
	arm.name = "SpringArm3D"
	arm.collision_mask = 1
	arm.margin = .15
	var camera := Camera3D.new()
	camera.name = "Camera3D"
	camera.fov = 46
	camera.current = true
	arm.add_child(camera)
	camera_rig.add_child(arm)
	add_child(camera_rig)
	_capture = "--capture" in OS.get_cmdline_user_args()
	adapter = Node.new()
	adapter.name = "PlayerInput"
	adapter.set_script(load("res://demo/capture_sequence.gd" if _capture else "res://demo/player_input.gd"))
	adapter.set("motor", player)
	if not _capture:
		adapter.set("camera_rig", camera_rig)
	add_child(adapter)
	_make_interface()
	_capture = "--capture" in OS.get_cmdline_user_args()
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--capture-frames="):
			_capture_limit = int(arg.get_slice("=", 1))
		if arg.begins_with("--capture-dir="):
			_capture_dir = "res://reports/captures/" + arg.get_slice("=", 1).validate_filename()
	if _capture:
		player.reset_at(Vector3(0, .02, 4), 0)
		help.visible = false
		DirAccess.make_dir_recursive_absolute(_capture_dir)
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
		get_viewport().size = Vector2i(960, 600)
		Engine.max_fps = 25

func _make_world() -> void:
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color("bcbcbc")
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color("ffffff")
	environment.ambient_light_energy = 0.30
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	var world := WorldEnvironment.new()
	world.environment = environment
	add_child(world)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-48, -30, 0)
	sun.light_color = Color("ffffff")
	sun.light_energy = 0.65
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 45
	add_child(sun)
	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-30, 150, 0)
	fill.light_color = Color("ffffff")
	fill.light_energy = .15
	add_child(fill)
	_box("Ground", Vector3(0, -.16, 0), Vector3(50, .32, 50), _material(Color("a5a5a5")))
	# Ramp rises toward -Z, 20 degrees; a platform and a matching return ramp.
	var ramp := _box("Slope20", Vector3(-5, .48, -2), Vector3(3, .20, 3.5), _material(Color("b5bdb2")))
	ramp.rotation.x = deg_to_rad(20)
	_box("SlopeLanding", Vector3(-5, .585, -4.3), Vector3(3, 1.17, 1.5), _material(Color("b5bdb2")))
	for i in range(5):
		var height := (i+1)*.15
		_box("Step15_%d" % i, Vector3(4.5, height*.5, 1.4-i*.65), Vector3(2.7, height, .65), _material(Color("b8aa91")))
	_box("StepLanding", Vector3(4.5, .375, -2.1), Vector3(2.7, .75, 1.2), _material(Color("b8aa91")))
	_box("Wall", Vector3(0, .8, -10), Vector3(4, 1.6, .25), _material(Color("778a91")))
	_box("OverLimitStep", Vector3(8, .2, 2), Vector3(2, .4, 1.5), _material(Color("aa8e82")))

func _material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = .84
	return material

func _box(node_name: String, position_value: Vector3, size: Vector3, material: Material) -> StaticBody3D:
	var body := StaticBody3D.new()
	body.name = node_name
	body.position = position_value
	body.collision_layer = 1
	body.collision_mask = 2
	var mesh := MeshInstance3D.new()
	var cube := BoxMesh.new()
	cube.size = size
	mesh.mesh = cube
	mesh.material_override = material
	body.add_child(mesh)
	var collision := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = size
	collision.shape = shape
	body.add_child(collision)
	add_child(body)
	return body

func _make_interface() -> void:
	var layer := CanvasLayer.new()
	layer.name = "Interface"
	add_child(layer)
	help = Label.new()
	help.name = "Help"
	help.text = "WASD / Left stick: move   Shift / LB: jog\nRight drag / Right stick: orbit   Wheel: zoom\nR: reset position   Esc: release mouse   F1: help"
	help.position = Vector2(16, 16)
	help.mouse_filter = Control.MOUSE_FILTER_IGNORE
	help.add_theme_font_size_override("font_size", 14)
	help.add_theme_color_override("font_color", Color("262626"))
	help.visible = false
	layer.add_child(help)

func toggle_help() -> void:
	help.visible = not help.visible

func _process(_delta: float) -> void:
	if _capture and _frame < _capture_limit:
		_frame += 1
		var capture_frame := _frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(_capture_dir + "/%04d.png" % capture_frame)
		if capture_frame >= _capture_limit:
			_capture = false
			get_tree().quit()

