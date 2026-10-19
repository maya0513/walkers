extends Node3D
## Behaviour tests use the public API and capture the actual post-IK skeleton.

const CHARACTER = preload("res://addons/walkers/character.tscn")
var actor: HumanoidMotor
var case_index: int = -1
var clock: float = 0
var results: Array[Dictionary] = []
var samples: Array[Dictionary] = []
var anchors: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var previous_locked: Array[bool] = [false, false]
var previous_regions: Array[String] = ["", ""]
var eligible_support_samples: Array[int] = [0, 0]
var previous_lock_anchors: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var previous_foot_transforms: Array[Transform3D] = [Transform3D.IDENTITY, Transform3D.IDENTITY]
var previous_support_local: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var cumulative_material_slip: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var sole_samples: Dictionary
var bindings: Dictionary = {}
var physics_rate: int = 60
var render_rate: int = 60
var case_filter: String = ""
var report_path: String
var worst: Dictionary = {}
var full_mesh: RefCounted
var full_mesh_max: float = 0.0
var frame_number: int = 0
var full_mesh_worst: Dictionary = {}
var mesh_oracle: Dictionary = {}
var cases: Array[Dictionary] = [
	{"name":"idle", "duration":.7, "start":Vector3(0,.005,5), "direction":Vector3.ZERO, "speed":0.0},
	{"name":"walk", "duration":4.0, "start":Vector3(0,.005,5), "direction":Vector3.FORWARD, "speed":1.4},
	{"name":"jog", "duration":3.5, "start":Vector3(0,.005,5), "direction":Vector3.FORWARD, "speed":2.8},
	{"name":"walk_jog_stop", "duration":6.0, "start":Vector3(0,.005,5), "direction":Vector3.FORWARD, "speed":1.4},
	{"name":"reverse180", "duration":5.0, "start":Vector3(0,.005,5), "direction":Vector3.FORWARD, "speed":1.4},
	{"name":"turn90", "duration":3.0, "start":Vector3(0,.005,5), "direction":Vector3.RIGHT, "speed":1.4},
	{"name":"interrupt_start", "duration":2.5, "start":Vector3(0,.005,5), "direction":Vector3.FORWARD, "speed":1.4},
	{"name":"wall", "duration":3.5, "start":Vector3(0,.005,-4.2), "direction":Vector3.FORWARD, "speed":2.8},
	{"name":"slope_up", "duration":3.0, "start":Vector3(-5,.005,0), "direction":Vector3.FORWARD, "speed":1.4},
	{"name":"slope_down", "duration":3.0, "start":Vector3(-5,1.03,-3.0), "direction":Vector3.BACK, "speed":1.4, "yaw":PI},
	{"name":"steps_up", "duration":3.7, "start":Vector3(5,.005,2.0), "direction":Vector3.FORWARD, "speed":1.4},
	{"name":"steps_down", "duration":3.7, "start":Vector3(5,.76,-1.8), "direction":Vector3.BACK, "speed":1.4, "yaw":PI},
	{"name":"over_limit_step", "duration":2.2, "start":Vector3(9,.005,2.0), "direction":Vector3.FORWARD, "speed":1.4},
	{"name":"stairs_side_left", "duration":2.6, "start":Vector3(3.35,.005,-.35), "direction":Vector3(1,0,-1).normalized(), "speed":1.4},
	{"name":"stairs_side_right", "duration":2.6, "start":Vector3(6.65,.005,-.35), "direction":Vector3(-1,0,-1).normalized(), "speed":1.4},
	{"name":"stairs_corner_exit", "duration":3.2, "start":Vector3(3.35,.005,-.35), "direction":Vector3(1,0,-1).normalized(), "speed":1.4},
	{"name":"stairs_side_release", "duration":2.8, "start":Vector3(6.65,.005,-.35), "direction":Vector3(-1,0,-1).normalized(), "speed":1.4},
	{"name":"stairs_side_reverse", "duration":3.4, "start":Vector3(3.35,.005,-.35), "direction":Vector3(1,0,-1).normalized(), "speed":1.4},
]

func _ready() -> void:
	process_physics_priority = 100
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--case="):
			case_filter = arg.get_slice("=", 1)
		if arg.begins_with("--rate="):
			physics_rate = int(arg.get_slice("=", 1))
		if arg.begins_with("--render-rate="):
			render_rate = int(arg.get_slice("=", 1))
	if not case_filter.is_empty():
		cases = cases.filter(func(test: Dictionary) -> bool: return test.name == case_filter)
		assert(not cases.is_empty(), "Unknown scenario: " + case_filter)
	Engine.physics_ticks_per_second = physics_rate
	report_path = "res://reports/runtime_p%d_r%d.json" % [physics_rate, render_rate]
	if not case_filter.is_empty():
		report_path = "res://reports/probe_" + case_filter.validate_filename() + ".json"
	_box(Vector3(0,-.1,0), Vector3(40,.2,40))
	_box(Vector3(0,1,-6), Vector3(5,2,.25))
	var ramp := _box(Vector3(-5,.47,-1.8), Vector3(2.5,.12,3))
	ramp.rotation.x = deg_to_rad(25)
	_box(Vector3(-5,.579,-3.8), Vector3(2.5,1.158,1.3))
	for i in range(5):
		var h: float = (i+1)*.15
		_box(Vector3(5,h*.5,1.15-i*.65), Vector3(2.5,h,.65))
	_box(Vector3(5,.375,-2.2), Vector3(2.5,.75,1.1))
	_box(Vector3(9,.2,.8), Vector3(2,.4,1.2))
	actor = CHARACTER.instantiate()
	add_child(actor)
	sole_samples = JSON.parse_string(FileAccess.get_file_as_string("res://addons/walkers/assets/sole_samples.json"))
	for i in range(actor.skeleton.get_bone_count()):
		bindings[actor.skeleton.get_bone_name(i)] = {"index":i, "inverse":actor.skeleton.get_bone_global_rest(i).affine_inverse()}
	full_mesh = load("res://tests/full_mesh_clearance.gd").new()
	full_mesh.setup(actor._find_type(actor.visual,"MeshInstance3D"),actor.skeleton)
	print("Independent sole surface vertices: ",full_mesh.points.size())
	# Validate the independent wall oracle with a known intrusive foot and a
	# known point above the ramp beyond its end face before testing motion.
	var rest_poses: Array[Transform3D] = []
	for i in range(actor.skeleton.get_bone_count()):
		rest_poses.append(actor.skeleton.get_bone_global_rest(i))
	var intrusive_world := Transform3D(Basis(Vector3.UP, PI), Vector3(0,.002,-5.78))
	var known_intrusion: float = full_mesh.penetration(rest_poses, intrusive_world, actor.grounding)
	mesh_oracle = {"known_wall_intrusion_depth_m":known_intrusion}
	_next_case()

func _box(position_value: Vector3, size: Vector3) -> StaticBody3D:
	var body := StaticBody3D.new()
	body.position = position_value
	var shape := BoxShape3D.new()
	shape.size = size
	var collider := CollisionShape3D.new()
	collider.shape = shape
	body.add_child(collider)
	add_child(body)
	return body

func _next_case() -> void:
	if case_index >= 0:
		var speeds: Array[float] = []
		var max_drift := 0.0
		var max_penetration := 0.0
		var max_constraint_residual := 0.0
		var states: Array[String] = []
		var max_y := -100.0
		var samples_grounded := 0
		var head_min := INF
		var head_max := -INF
		var head_speed_max := 0.0
		var head_sample_count := 0
		var body_floor_min := INF
		var body_floor_max := -INF
		var body_floor_samples := 0
		var midstance_knees: Dictionary = {
			"Left":{"max_flex_degrees":0.0,"sample_count":0},
			"Right":{"max_flex_degrees":0.0,"sample_count":0}}
		for sample: Dictionary in samples:
			if sample.time > 1.4:
				speeds.append(sample.speed)
			# Flat steady locomotion: measure the delivered post-IK Head bone,
			# using the world transform captured in the same skeleton evaluation.
			var head_window: bool = (sample.time > 1.4 and sample.pose_state == "Move") or (cases[case_index].name == "idle" and sample.time > .25)
			if head_window:
				body_floor_min = minf(body_floor_min, sample.position[1])
				body_floor_max = maxf(body_floor_max, sample.position[1])
				body_floor_samples += 1
			if sample.head_valid and head_window:
				head_min = minf(head_min, sample.head_y)
				head_max = maxf(head_max, sample.head_y)
				head_speed_max = maxf(head_speed_max, sample.head_vertical_speed_mps)
				head_sample_count += 1
			if cases[case_index].name == "walk" and sample.head_valid and sample.time > 1.4 and sample.pose_state == "Move":
				for side: String in ["Left", "Right"]:
					var low := .2 if side == "Left" else .7
					if sample.pose_phase >= low and sample.pose_phase <= low + .1:
						midstance_knees[side].sample_count += 1
						midstance_knees[side].max_flex_degrees = maxf(midstance_knees[side].max_flex_degrees, sample["knee_flex_" + side.to_lower() + "_degrees"])
			max_drift = maxf(max_drift, sample.drift)
			max_constraint_residual = maxf(max_constraint_residual, sample.constraint_residual)
			max_penetration = maxf(max_penetration, sample.penetration)
			max_y = maxf(max_y, sample.position[1])
			if sample.grounded:
				samples_grounded += 1
			if not sample.state in states:
				states.append(sample.state)
		var mean_speed := 0.0
		for speed: float in speeds:
			mean_speed += speed / maxf(speeds.size(), 1)
		results.append({"name":cases[case_index].name,"mean_speed_after_settle":mean_speed,
			"support_drift_max_m":max_drift,"support_drift_method":"material_point_integration" if int(actor.animator.metadata.get("schema_version",1)) >= 3 else "fixed_region_point",
			"support_constraint_residual_max_m":max_constraint_residual,"eligible_support_samples":{"Left":eligible_support_samples[0],"Right":eligible_support_samples[1]},"sole_penetration_max_m":max_penetration,
			"head_height":{"min_m":head_min if head_sample_count else 0.0,"max_m":head_max if head_sample_count else 0.0,
				"peak_to_peak_m":head_max-head_min if head_sample_count else 0.0,"vertical_speed_max_mps":head_speed_max,"sample_count":head_sample_count},
			"midstance_knees":midstance_knees,
			"body_height_after_settle":{"min_m":body_floor_min if body_floor_samples else 0.0,"max_m":body_floor_max if body_floor_samples else 0.0,
				"range_m":body_floor_max-body_floor_min if body_floor_samples else 0.0,"sample_count":body_floor_samples},
			"max_body_height_m":max_y,"grounded_ratio":float(samples_grounded)/maxf(samples.size(),1),
			"states":states,"end_position":[actor.position.x,actor.position.y,actor.position.z],"worst":worst,
			"full_mesh_penetration_m":full_mesh_max,"full_mesh_worst":full_mesh_worst,"samples":samples})
		print("CASE ", cases[case_index].name, " speed=", mean_speed, " drift=", max_drift, " penetration=", max_penetration, " height=", max_y)
	case_index += 1
	if case_index >= cases.size():
		_finish()
		return
	clock = 0
	samples = []
	worst = {}
	full_mesh_max = 0.0
	full_mesh_worst = {}
	eligible_support_samples = [0, 0]
	previous_locked = [false,false]
	previous_regions = ["", ""]
	cumulative_material_slip = [Vector3.ZERO, Vector3.ZERO]
	actor.reset_at(cases[case_index].start, cases[case_index].get("yaw",0))

func _physics_process(delta: float) -> void:
	if case_index >= cases.size():
		return
	clock += delta
	frame_number += 1
	var test := cases[case_index]
	var direction: Vector3 = test.direction
	var speed: float = test.speed
	if test.name == "walk_jog_stop":
		speed = 1.4 if clock < 2 else 2.8 if clock < 4 else 0.0
	if test.name == "reverse180" and clock > 1.5:
		direction = Vector3.BACK
	if test.name == "interrupt_start":
		speed = 1.4 if (clock < .12 or (.3 < clock and clock < .45) or (1.0 < clock and clock < 1.5)) else 0.0
	if test.name == "stairs_corner_exit" and clock > 1.3:
		direction = Vector3.LEFT
	if test.name == "stairs_side_release" and clock > 1.3:
		speed = 0.0
	if test.name == "stairs_side_reverse" and clock > 1.3:
		direction = Vector3(-1,0,1).normalized()
	actor.set_move_intent(direction, speed)
	var drift := 0.0
	var constraint_residual := 0.0
	var penetration := 0.0
	var head_y := 0.0
	var head_valid := false
	var head_vertical_speed := 0.0
	var knee_flex := Vector2.ZERO
	var final: Array = actor.pose_recorder.get("final_pose")
	var pose_world: Transform3D = actor.pose_recorder.get("final_world_transform")
	if final.size() == actor.skeleton.get_bone_count():
		head_y = (pose_world * (final[bindings["Head"].index] as Transform3D).origin).y
		head_valid = true
		for i in range(2):
			var side := "Left" if i == 0 else "Right"
			var hip: Vector3 = pose_world * (final[bindings[side + "UpperLeg"].index] as Transform3D).origin
			var knee: Vector3 = pose_world * (final[bindings[side + "LowerLeg"].index] as Transform3D).origin
			var ankle: Vector3 = pose_world * (final[bindings[side + "Foot"].index] as Transform3D).origin
			knee_flex[i] = rad_to_deg((knee - hip).angle_to(ankle - knee))
		if not samples.is_empty() and samples[-1].head_valid:
			head_vertical_speed = absf(head_y - float(samples[-1].head_y)) / delta
		if frame_number % 8 == 0 and clock > .3:
			var full_depth: float = full_mesh.penetration(final,pose_world,actor.grounding)
			if full_depth > full_mesh_max:
				full_mesh_max = full_depth
				full_mesh_worst = full_mesh.worst.duplicate(true)
				full_mesh_worst["time"] = clock
				full_mesh_worst["state"] = String(actor.animator.state)
		for i in range(2):
			var supported: bool = actor.grounding.locked[i] and actor.animator.contacts[i] > .995 and actor.is_on_floor() and clock > 1.2 and actor.animator.state == &"Move"
			var foot := actor.grounding.actual_support_points[i]
			var region: String = actor.grounding.support_regions[i]
			if supported:
				eligible_support_samples[i] += 1
				var foot_world: Transform3D = pose_world * final[bindings[("Left" if i == 0 else "Right") + "Foot"].index]
				if int(actor.animator.metadata.get("schema_version",1)) >= 3:
					if previous_locked[i]:
						# Track the SAME material point on the foot across the step.
						# R*delta_support is a legitimate rolling-contact migration,
						# so it must not be measured as slip or reset this integral.
						var previous_point := previous_support_local[i]
						var displacement := foot_world * previous_point - previous_foot_transforms[i] * previous_point
						cumulative_material_slip[i] += Vector3(displacement.x, 0, displacement.z)
					else:
						cumulative_material_slip[i] = Vector3.ZERO
					drift = maxf(drift, cumulative_material_slip[i].length())
				else:
					if not previous_locked[i] or previous_regions[i] != region or previous_lock_anchors[i].distance_to(actor.grounding.anchors[i]) > .001:
						anchors[i] = foot
					var offset := foot-anchors[i]
					drift = maxf(drift, Vector2(offset.x,offset.z).length())
				var residual := foot-actor.grounding.anchors[i]
				constraint_residual = maxf(constraint_residual, Vector2(residual.x,residual.z).length())
				previous_foot_transforms[i] = foot_world
				previous_support_local[i] = actor.grounding.support_local[i]
			previous_locked[i] = supported
			previous_regions[i] = region
			previous_lock_anchors[i] = actor.grounding.anchors[i]
		# Geometric skinning of sampled sole vertices, not an ankle-height proxy.
		if clock > .2:
			for side: String in sole_samples:
				for marker: Dictionary in sole_samples[side]:
					var position_value: Array = marker.position
					var rest_position := Vector3(position_value[0],position_value[1],position_value[2])
					var skinned := Vector3.ZERO
					for influence: Array in marker.weights:
						var binding: Dictionary = bindings[influence[0]]
						skinned += (final[binding.index] * (binding.inverse * rest_position)) * float(influence[1])
					var world := pose_world * skinned
					var hit := actor.grounding.ray_floor(world,.3,.3)
					if not hit.is_empty():
						penetration = maxf(penetration,hit.position.y-world.y)
						if hit.position.y-world.y > float(worst.get("depth",0)):
							var foot_index := 0 if side == "Left" else 1
							var foot := actor.grounding.actual_feet[foot_index]
							var target := actor.grounding.targets[foot_index].global_position
							worst = {"depth":hit.position.y-world.y,"time":clock,"side":side,"weights":marker.weights,
								"world":[world.x,world.y,world.z],"floor":hit.position.y,"foot":[foot.x,foot.y,foot.z],
								"target":[target.x,target.y,target.z],"state":String(actor.animator.state),"phase":actor.animator.phase}
	var v := actor.actual_velocity
	samples.append({"time":clock,"speed":Vector2(v.x,v.z).length(),"position":[actor.position.x,actor.position.y,actor.position.z],
		"state":String(actor.animator.state),"phase":actor.animator.phase,
		"pose_phase":actor.pose_recorder.get("final_phase"),"pose_state":String(actor.pose_recorder.get("final_state")),"grounded":actor.is_on_floor(),
		"drift":drift,"constraint_residual":constraint_residual,"penetration":penetration,"yaw":actor.facing_yaw,
		"blocked":actor.movement_blocked,"step_active":actor.step_active,
		"pelvis_offset_m":actor.grounding.pelvis_offset,"support_regions":actor.grounding.support_regions.duplicate(),
		"head_valid":head_valid,"head_y":head_y,"head_vertical_speed_mps":head_vertical_speed,
		"knee_flex_left_degrees":knee_flex.x,"knee_flex_right_degrees":knee_flex.y})
	if clock >= float(test.duration):
		_next_case()

func _finish() -> void:
	var failures: Array[String] = []
	if mesh_oracle.known_wall_intrusion_depth_m < .01:
		failures.append("independent wall oracle failed to detect known intrusive foot")
	for result: Dictionary in results:
		if result.name in ["idle", "walk", "jog"]:
			if result.body_height_after_settle.sample_count < 10:
				failures.append(result.name+": insufficient settled body height samples")
			elif result.body_height_after_settle.range_m > .003 or result.body_height_after_settle.min_m < -.003:
				failures.append(result.name+": flat body floor jitter or penetration > 3mm")
		if result.name in ["walk","jog"]:
			var expected := 1.4 if result.name == "walk" else 2.8
			if absf(result.mean_speed_after_settle-expected) > expected*.05:
				failures.append(result.name+": steady speed")
			if result.grounded_ratio < .95:
				failures.append(result.name+": flat grounded ratio < 95%")
			for side: String in ["Left", "Right"]:
				if result.eligible_support_samples[side] < 8:
					failures.append(result.name+": insufficient " + side + " grounded support samples")
			if result.support_drift_max_m > .020:
				failures.append(result.name+": support drift > 2cm")
			if result.head_height.sample_count < 10:
				failures.append(result.name+": missing steady post-IK head samples")
			elif result.head_height.peak_to_peak_m > .065:
				failures.append(result.name+": steady post-IK head excursion > 6.5cm")
			if result.sole_penetration_max_m > .010:
				failures.append(result.name+": sole penetration > 1cm")
		if result.name == "walk":
			for side: String in ["Left", "Right"]:
				var knee: Dictionary = result.midstance_knees[side]
				if knee.sample_count < 4:
					failures.append("walk: insufficient " + side + " midstance knee samples")
				elif knee.max_flex_degrees > 20.0:
					failures.append("walk: " + side + " midstance knee flex > 20 degrees")
		if result.name == "idle":
			if result.head_height.sample_count < 10:
				failures.append("idle: missing settled head samples")
			elif result.head_height.peak_to_peak_m > .001:
				failures.append("idle: settled head excursion > 1mm")
		if result.full_mesh_penetration_m > .010:
			failures.append(result.name+": full mesh penetration > 1cm")
		if result.name == "wall" and result.end_position[2] < -5.66:
			failures.append("wall collision")
		if result.name == "steps_up" and result.max_body_height_m < .59:
			failures.append("step ascent")
		if result.name == "over_limit_step" and result.max_body_height_m > .1:
			failures.append("over-limit step climbed")
		if String(result.name).begins_with("stairs_"):
			if result.max_body_height_m > .025:
				failures.append(result.name+": unsupported rise at stair side")
			for sample: Dictionary in result.samples:
				if sample.time > .8 and sample.speed > .3 and sample.state == "Idle":
					failures.append(result.name+": idle while sliding")
					break
			if result.name == "stairs_side_release":
				var last: Dictionary = result.samples[-1]
				if last.speed > .02 or last.state != "Idle":
					failures.append("stair-side release failed to settle")
			if result.name in ["stairs_side_left", "stairs_side_right"] and result.mean_speed_after_settle < .5:
				failures.append(result.name+": side slide stalled")
		if result.name == "stairs_corner_exit" and result.end_position[0] > 2.5:
			failures.append("stair-side corner exit blocked")
		if result.name == "stairs_side_reverse" and result.end_position[2] < -.8:
			failures.append("stair-side reverse blocked")
	var file := FileAccess.open(report_path,FileAccess.WRITE)
	file.store_string(JSON.stringify({"godot":Engine.get_version_info().string,"physics_rate":physics_rate,"render_rate":render_rate,"full_mesh_oracle":mesh_oracle,"failures":failures,"results":results},"\t"))
	file.close()
	print("VALIDATION_COMPLETE rate=",physics_rate," failures=",failures)
	get_tree().quit(0 if failures.is_empty() else 1)
