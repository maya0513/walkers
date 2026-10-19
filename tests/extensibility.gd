extends SceneTree
## A synthetic extra gait checks the extension API without shipping a dash clip.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene := Node3D.new()
	root.add_child(scene)
	var floor_body := StaticBody3D.new()
	var collider := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(40,.2,40)
	collider.shape = shape
	floor_body.add_child(collider)
	floor_body.position.y = -.1
	scene.add_child(floor_body)
	var actor: HumanoidMotor = load("res://addons/walkers/character.tscn").instantiate()
	var player: AnimationPlayer = actor._find_type(actor.get_node("Visual"), "AnimationPlayer")
	var jog: Animation
	for name: StringName in player.get_animation_list():
		if String(name) == "Jog" or String(name).ends_with("/Jog"):
			jog = player.get_animation(name)
	assert(jog != null)
	player.get_animation_library(&"").add_animation(&"SprintProbe",jog.duplicate(true))
	var metadata: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://addons/walkers/assets/motions.json"))
	metadata.clips.SprintProbe = metadata.clips.Jog.duplicate(true)
	var file := FileAccess.open("user://probe_motions.json",FileAccess.WRITE)
	file.store_string(JSON.stringify(metadata))
	file.close()
	var settings: LocomotionConfig = actor.config.duplicate()
	settings.motion_metadata = "user://probe_motions.json"
	var extra := LocomotionGait.new()
	extra.animation = &"SprintProbe"
	extra.speed = 4.2
	extra.stride_length = 2.24
	settings.extra_gaits = [extra]
	actor.config = settings
	scene.add_child(actor)
	actor.reset_at(Vector3(0,.01,8))
	var footfalls := [0]
	actor.footstep.connect(func(_s: StringName,_p: Vector3,_n: Vector3) -> void: footfalls[0] += 1)
	for i in range(240):
		actor.set_move_intent(Vector3.FORWARD,4.2)
		await physics_frame
	var speed := Vector2(actor.actual_velocity.x,actor.actual_velocity.z).length()
	var failures: Array[String] = []
	if absf(speed-4.2) > .1:
		failures.append("extra gait speed")
	if footfalls[0] < 2:
		failures.append("footstep events")
	var before_unlocked: int = footfalls[0]
	actor.config.foot_lock = false
	for i in range(90):
		actor.set_move_intent(Vector3.FORWARD,2.8)
		await physics_frame
	var unlocked_footfalls: int = footfalls[0]-before_unlocked
	if unlocked_footfalls < 2 or actor.grounding.locked[0] or actor.grounding.locked[1]:
		failures.append("footstep events without foot lock")
	actor.set_move_intent(Vector3(INF,0,0),4.2)
	if actor.requested_speed != 0:
		failures.append("invalid intent")
	actor.set_move_intent(Vector3.FORWARD,-1)
	if actor.requested_speed != 0:
		failures.append("negative speed")
	var legacy_results: Array[Dictionary] = []
	for schema in [1, 2, 3]:
		var legacy := metadata.duplicate(true)
		legacy.schema_version = schema
		legacy.erase("support_material_space")
		for clip: String in legacy.clips:
			legacy.clips[clip].erase("support_materials")
			if schema < 3:
				legacy.clips[clip].erase("support_offsets")
			if schema < 2:
				legacy.clips[clip].erase("support_regions")
		actor.animator.metadata = legacy
		actor.config.foot_lock = true
		actor.reset_at(Vector3(-3, .01, 8))
		var legacy_events_before: int = footfalls[0]
		for i in range(120):
			actor.set_move_intent(Vector3.FORWARD, 1.4)
			await physics_frame
		var legacy_speed := Vector2(actor.actual_velocity.x, actor.actual_velocity.z).length()
		var legacy_events: int = footfalls[0] - legacy_events_before
		if absf(legacy_speed - 1.4) > .05 or legacy_events < 2 or not actor.animator.support_materials.is_empty():
			failures.append("legacy schema %d metadata compatibility" % schema)
		legacy_results.append({"schema":schema, "speed_mps":legacy_speed, "footsteps":legacy_events,
			"continuous_offsets":actor.animator.support_offsets.size() == 2, "deforming_materials":actor.animator.support_materials.size()})
	var report := {"extra_gait_speed":speed,"footfalls":footfalls[0],"unlocked_footfalls":unlocked_footfalls,
		"legacy_metadata":legacy_results,"failures":failures}
	file = FileAccess.open("res://reports/extensibility.json",FileAccess.WRITE)
	file.store_string(JSON.stringify(report,"\t"))
	file.close()
	print("EXTENSIBILITY ",report)
	scene.queue_free()
	await process_frame
	quit(0 if failures.is_empty() else 1)

