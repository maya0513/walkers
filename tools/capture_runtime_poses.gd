extends SceneTree
## Record the shipped motor + explicit capture adapter without a display server.
## This is measured post-IK pose data, not a Godot viewport capture.
var stage: Node3D
var actor: HumanoidMotor
var recorder: Node3D
var clock := 0.0
var duration := 20.0
var sample_rate := 25
var output := "res://reports/runtime_poses.json"
var frames: Array[Dictionary] = []
var bone_names: Array[String] = []
var parents: Array[int] = []
var rest: Array = []
var previous_phase := 0.0
var previous_state := "Idle"
var terrain: Array[Dictionary] = []

func _initialize() -> void:
	_start.call_deferred()

func _matrix(value: Transform3D) -> Array:
	return [[value.basis.x.x,value.basis.y.x,value.basis.z.x,value.origin.x],
		[value.basis.x.y,value.basis.y.y,value.basis.z.y,value.origin.y],
		[value.basis.x.z,value.basis.y.z,value.basis.z.z,value.origin.z], [0,0,0,1]]

func _start() -> void:
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--output="):
			output = arg.trim_prefix("--output=")
		elif arg.begins_with("--duration="):
			duration = clampf(float(arg.trim_prefix("--duration=")), 1, 120)
		elif arg.begins_with("--sample-rate="):
			sample_rate = clampi(int(arg.trim_prefix("--sample-rate=")), 1, 120)
	Engine.physics_ticks_per_second = 60
	stage = load("res://demo/main.tscn").instantiate()
	root.add_child(stage)
	actor = stage.player
	# --capture itself would also ask stage.gd for real viewport PNGs. Use the
	# same input adapter explicitly, leaving screenshot mode disabled.
	stage.adapter.set_script(load("res://demo/capture_sequence.gd"))
	stage.adapter.motor = actor
	stage.adapter.set_physics_process(true)
	actor.reset_at(Vector3(0,.02,4), 0)
	for i in range(actor.skeleton.get_bone_count()):
		bone_names.append(actor.skeleton.get_bone_name(i))
		parents.append(actor.skeleton.get_bone_parent(i))
		rest.append(_matrix(actor.skeleton.get_bone_global_rest(i)))
	for child: Node in stage.get_children():
		if child is StaticBody3D:
			for mesh: Node in child.get_children():
				if mesh is MeshInstance3D and mesh.mesh is BoxMesh:
					var size: Vector3 = mesh.mesh.size
					var color: Color = mesh.material_override.albedo_color
					terrain.append({"name":String(child.name),"world":_matrix(mesh.global_transform),"size":[size.x,size.y,size.z],"color":[color.r,color.g,color.b]})
	_append_frame(0.0, 1.0)
	# Node callback is ordered after the shipped motor and capture input adapter.
	recorder = Node3D.new()
	recorder.set_script(load("res://tools/runtime_pose_sampler.gd"))
	recorder.set("owner_recorder", self)
	recorder.process_physics_priority = 200
	root.add_child(recorder)

func _global_pose(index: int, local: Array[Transform3D], cache: Dictionary) -> Transform3D:
	if cache.has(index):
		return cache[index]
	var value: Transform3D = local[index]
	if parents[index] >= 0:
		value = _global_pose(parents[index], local, cache) * value
	cache[index] = value
	return value

func _append_frame(time: float, alpha: float) -> void:
	var display: Node = actor.presentation
	var local: Array[Transform3D] = []
	for i in range(bone_names.size()):
		local.append(display.previous_pose[i].interpolate_with(display.current_pose[i], alpha))
	var globals: Array = []
	var cache: Dictionary = {}
	for i in range(bone_names.size()):
		globals.append(_matrix(_global_pose(i, local, cache)))
	var phase: float = actor.pose_recorder.final_phase
	var phase_delta := wrapf(phase-previous_phase, -.5,.5)
	frames.append({"time":time,"world":_matrix(display.previous_transform.interpolate_with(display.current_transform, alpha)),
		"global_poses":globals,"state":String(actor.pose_recorder.final_state) if alpha >= .5 else previous_state,
		"phase":fposmod(previous_phase + phase_delta*alpha,1),"contacts":[actor.animator.contacts.x,actor.animator.contacts.y]})

func tick(delta: float) -> void:
	clock += delta
	var limit := int(round(duration * sample_rate))
	while frames.size() < limit and float(frames.size())/sample_rate <= clock + .0000001:
		var sample_time := float(frames.size())/sample_rate
		var alpha := clampf((sample_time-(clock-delta))/delta, 0, 1)
		_append_frame(sample_time, alpha)
	previous_phase = actor.pose_recorder.final_phase
	previous_state = String(actor.pose_recorder.final_state)
	if clock >= duration - .0000001:
		var document := {"source_label":"Headless Godot post-IK poses for Blender re-rendering; not a Godot viewport capture.",
			"godot":Engine.get_version_info().string,"physics_hz":60,"sample_fps":sample_rate,"duration_seconds":duration,
			"sample_method":"Exact sample times; interpolate final post-IK local bone transforms and visual world transform between adjacent physics ticks.",
			"matrix_format":"Row-major 4x4; Godot coordinates (X right, Y up). global_poses are skeleton-space; world maps skeleton-space to world.",
			"model_sha256":FileAccess.get_sha256("res://addons/walkers/assets/humanoid.glb"),
			"motion_metadata_sha256":FileAccess.get_sha256(actor.config.motion_metadata),
			"bone_names":bone_names,"parents":parents,"rest_global_poses":rest,"terrain":terrain,"frames":frames}
		var file := FileAccess.open(output,FileAccess.WRITE)
		if file == null:
			push_error("Cannot write measured poses: " + output)
			quit(1)
			return
		file.store_string(JSON.stringify(document))
		file.close()
		print("RUNTIME_POSES_SAVED frames=",frames.size()," path=",output)
		quit(0)
