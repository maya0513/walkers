extends SceneTree
## Explicit visual QA only. Run with --fixed-fps 60 and -- --feet or --stairs.
## Captures actual OpenGL frames; never instantiated by the normal demo.
var stage: Node3D
var actor: HumanoidMotor
var camera: Camera3D
var tick := 0
var last_render_tick := -1
var captured := {"Walk":0,"Jog":0}
var records: Array[Dictionary] = []
var output := "res://reports/captures/contact_feet"
var initialized := false
var terrain := false

func _initialize() -> void:
	_start.call_deferred()

func _start() -> void:
	terrain = "--stairs" in OS.get_cmdline_user_args()
	if not terrain and not "--feet" in OS.get_cmdline_user_args():
		push_error("Choose explicit --feet or --stairs capture mode")
		quit(1)
		return
	if terrain:
		output = "res://reports/captures/contact_stairs"
		captured = {"Stairs":0}
	Engine.physics_ticks_per_second = 60
	Engine.max_fps = 60
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	root.size = Vector2i(960,600)
	stage = load("res://demo/main.tscn").instantiate()
	root.add_child(stage)
	stage.adapter.set_physics_process(false)
	stage.camera_rig.set_process(false)
	actor = stage.player
	actor.reset_at(Vector3(6.25,.005,-.3) if terrain else Vector3(12,.005,5), PI*.25 if terrain else 0)
	camera = Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 1.15 if terrain else .85
	camera.current = true
	root.add_child(camera)
	DirAccess.make_dir_recursive_absolute(output)
	initialized = true

func _physics_process(_delta: float) -> bool:
	if initialized:
		tick += 1
		if terrain:
			actor.set_move_intent(Vector3(-1,0,-1).normalized() if tick <= 180 else Vector3(1,0,1).normalized(), 0.0 if tick > 180 and tick <= 220 else 1.4)
		else:
			actor.set_move_intent(Vector3.FORWARD, 1.4 if tick <= 216 else 2.8)
	return false

func _process(_delta: float) -> bool:
	if not initialized:
		return false
	var target := actor.get_display_position() + Vector3.UP * (.5 if terrain else .35)
	camera.global_position = target + (Vector3(3,.15,.7) if terrain else Vector3(3,0,.025))
	camera.look_at(target,Vector3.UP)
	var gait := "Stairs" if terrain and tick > 0 else "Walk" if tick >= 91 and tick <= 216 else "Jog" if tick >= 277 and tick <= 360 else ""
	if not gait.is_empty() and tick != last_render_tick:
		last_render_tick = tick
		captured[gait] += 1
		var path := output + "/%s_%04d.png" % [gait,captured[gait]]
		var row := {"gait":gait,"time_seconds":tick/60.0,"phase":actor.pose_recorder.final_phase,"file":path,
			"state":String(actor.pose_recorder.final_state)}
		records.append(row)
		var finish := tick >= (300 if terrain else 360)
		_capture.call_deferred(path, row, finish)
		if finish:
			initialized = false
	return false

func _capture(path: String, row: Dictionary, finish: bool) -> void:
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(path)
	row["sha256"] = FileAccess.get_sha256(path)
	if not finish:
		return
	var hashes := {}
	for source: String in ["source/character.blend", "addons/walkers/assets/humanoid.glb", "addons/walkers/assets/motions.json",
		"addons/walkers/grounding.gd", "addons/walkers/animation_driver.gd", "addons/walkers/motor.gd",
		"addons/walkers/presentation.gd", "tests/contact_viewport_capture.gd"]:
		hashes[source] = FileAccess.get_sha256("res://" + source)
	var report := {"source":"Actual Godot OpenGL viewport", "godot":Engine.get_version_info().string,
		"fps":60,"physics_hz":60,"size":[960,600], "mode":"stairs_side_release_reverse" if terrain else "steady_gait_feet",
		"camera":{"projection":"orthographic", "size":camera.size,"target_height_m":.5 if terrain else .35,
			"world_offset_m":[3,.15,.7] if terrain else [3,0,.025]},
		"sequence":"Diagonal right-side stair rub: 0–3s; release: 3–3.667s; reverse and depart: 3.667–5s." if terrain else "Walk: settle 1.5s then 2 cycles; Jog: settle 1s then 2 cycles.",
		"sha256":hashes,"captured":captured,"frames":records}
	var destination := "res://reports/runtime_stairs_capture.json" if terrain else "res://reports/runtime_feet_capture.json"
	var file := FileAccess.open(destination,FileAccess.WRITE)
	file.store_string(JSON.stringify(report,"\t"))
	print("CONTACT_VIEWPORT_CAPTURED ",captured)
	quit()
