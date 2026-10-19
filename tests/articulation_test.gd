extends SceneTree
## Verify that terrain IK and display snapshots preserve authored toe/torso locals.
var failures: Array[String] = []
var results: Array[Dictionary] = []
var actor: HumanoidMotor
var events: Array[String] = []
var steady_events: Array[String] = []

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	Engine.physics_ticks_per_second = 60
	var stage: Node3D = load("res://demo/main.tscn").instantiate()
	root.add_child(stage)
	stage.adapter.set_physics_process(false)
	actor = stage.player
	actor.presentation.set_process(false)
	actor.footstep.connect(func(side: StringName, _position: Vector3, _normal: Vector3) -> void:
		events.append(String(side))
		if actor.animator.state == &"Move" and actor.animator.state_time > 1.0:
			steady_events.append(String(side)))
	for gait: String in ["Walk", "Jog"]:
		actor.reset_at(Vector3(0, .005, 5), 0)
		events.clear()
		steady_events.clear()
		var max_rotation_error := 0.0
		var max_position_error := 0.0
		var max_material_offset_error := 0.0
		var max_material_weight_error := 0.0
		var initial_toes: Dictionary = {}
		var toe_motion := {"Left":0.0, "Right":0.0}
		var frames := 0
		for frame in range(270):
			actor.set_move_intent(Vector3.FORWARD, 1.4 if gait == "Walk" else 2.8)
			await physics_frame
			await process_frame
			if frame < 90 or actor.pose_recorder.final_state != &"Move":
				continue
			frames += 1
			if actor.animator.support_materials.size() != 2:
				failures.append(gait + ": missing deforming support bindings")
				break
			for side in range(2):
				var material: Array = actor.animator.support_materials[side]
				var total_weight := 0.0
				for entry: Dictionary in material:
					total_weight += float(entry.weight)
				max_material_weight_error = maxf(max_material_weight_error, absf(total_weight - 1.0))
				var material_position: Vector3 = actor.grounding._material_local(side, material)
				var support_position: Vector3 = actor.grounding._support_offset(side, actor.animator.support_regions[side])
				max_material_offset_error = maxf(max_material_offset_error, material_position.distance_to(support_position))
			var final: Array = actor.pose_recorder.final_pose
			for name: String in ["LeftToes", "RightToes", "Spine", "Chest", "UpperChest", "Neck", "Head"]:
				var bone := actor.skeleton.find_bone(name)
				var parent := actor.skeleton.get_bone_parent(bone)
				var local: Transform3D = (final[parent] as Transform3D).affine_inverse() * final[bone]
				var authored: Transform3D = actor.presentation.physics_pose[bone]
				max_rotation_error = maxf(max_rotation_error, rad_to_deg(local.basis.get_rotation_quaternion().angle_to(authored.basis.get_rotation_quaternion())))
				max_position_error = maxf(max_position_error, local.origin.distance_to(authored.origin))
				if name.ends_with("Toes"):
					var side := name.trim_suffix("Toes")
					if not initial_toes.has(side):
						initial_toes[side] = local.basis.get_rotation_quaternion()
					toe_motion[side] = maxf(toe_motion[side], rad_to_deg((initial_toes[side] as Quaternion).angle_to(local.basis.get_rotation_quaternion())))
		if frames < 60:
			failures.append(gait + ": insufficient post-IK samples")
		if max_rotation_error > .1 or max_position_error > .00001:
			failures.append(gait + ": IK changed authored toe/torso local pose")
		if max_material_weight_error > .00001:
			failures.append(gait + ": deforming support skin weights do not sum to one")
		if max_material_offset_error > .004:
			failures.append(gait + ": skin binding support differs from virtual sole by > 4mm")
		for side: String in ["Left", "Right"]:
			if toe_motion[side] < 8.0:
				failures.append(gait + ": " + side + " toe articulation < 8 degrees")
		for i in range(1, steady_events.size()):
			if steady_events[i] == steady_events[i-1]:
				failures.append(gait + ": repeated steady-cycle footstep event from same foot")
		if events.size() < 6:
			failures.append(gait + ": missing contact events")
		results.append({"gait":gait, "post_ik_frames":frames, "maximum_local_rotation_error_degrees":max_rotation_error,
			"maximum_local_position_error_m":max_position_error, "toe_excursion_from_reference_degrees":toe_motion,
			"maximum_support_material_offset_m":max_material_offset_error, "maximum_support_weight_error":max_material_weight_error,
			"footsteps":events.duplicate(), "steady_cycle_footsteps":steady_events.duplicate()})
	actor.set_physics_process(false)
	actor.reset_at(Vector3(0, .005, 5), 0)
	actor.animator.state = &"Move"
	actor.grounding._was_contact = [false, false]
	events.clear()
	for weight: float in [0.0, .8, .6, .8, .4, .8, 0.0, .8]:
		actor.animator.contacts = Vector2(weight, 0)
		actor.grounding._process_modification_with_delta(1.0 / 60.0)
	if events != ["Left", "Left"]:
		failures.append("contact-weight oscillation emitted repeated onset or missed recontact")
	var file := FileAccess.open("res://reports/articulation.json", FileAccess.WRITE)
	file.store_string(JSON.stringify({"physics_hz":60, "results":results,
		"contact_hysteresis":{"weights":[0,.8,.6,.8,.4,.8,0,.8], "onsets":events.duplicate()}, "failures":failures}, "\t"))
	print("ARTICULATION_PASS" if failures.is_empty() else JSON.stringify(failures))
	quit(0 if failures.is_empty() else 1)
