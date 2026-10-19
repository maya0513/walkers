extends SceneTree
## Display interpolation must not change physics, IK snapshots or footstep counts.
var failures: Array[String] = []
var measured: Dictionary = {}
var actor: HumanoidMotor
var steps := 0

func _initialize() -> void:
	_run.call_deferred()

func _check(value: bool, message: String) -> void:
	if not value:
		failures.append(message)

func _run() -> void:
	Engine.physics_ticks_per_second = 60
	var stage: Node3D = load("res://demo/main.tscn").instantiate()
	root.add_child(stage)
	actor = stage.player
	stage.adapter.set_physics_process(false)
	actor.presentation.set_process(false)
	actor.footstep.connect(func(_s: StringName, _p: Vector3, _n: Vector3) -> void: steps += 1)
	for i in range(150):
		actor.set_move_intent(Vector3.FORWARD, 1.4)
		await physics_frame
		await process_frame
	actor.set_physics_process(false)
	var display: Node = actor.presentation
	var saved_root := actor.global_transform
	var saved_velocity := actor.actual_velocity
	var saved_phase: float = actor.pose_recorder.final_phase
	var saved_record: Array = actor.pose_recorder.final_pose.duplicate()
	var captures: int = display.physics_captures
	var events := steps
	var evaluations: int = actor.pose_recorder.evaluation_count
	_check(evaluations == captures, "IK evaluation count differs from physics snapshot count")
	var max_pose_error := 0.0
	var max_rotation_error := 0.0
	var max_final_pose_error := 0.0
	var displayed_positions: Array[Vector3] = []
	for alpha: float in [0.0, .25, .5, .75, 1.0]:
		display.render_at(alpha)
		var expected: Transform3D = display.previous_transform.interpolate_with(display.current_transform, alpha)
		max_pose_error = maxf(max_pose_error, actor.visual.global_position.distance_to(expected.origin))
		max_rotation_error = maxf(max_rotation_error, actor.visual.global_basis.get_rotation_quaternion().angle_to(expected.basis.get_rotation_quaternion()))
		displayed_positions.append(actor.visual.global_position)
		for bone in range(actor.skeleton.get_bone_count()):
			var pose: Transform3D = display.previous_pose[bone].interpolate_with(display.current_pose[bone], alpha)
			max_pose_error = maxf(max_pose_error, actor.skeleton.get_bone_pose(bone).origin.distance_to(pose.origin))
		_check(actor.get_display_position().distance_to(expected.origin) < .00001, "camera display anchor diverged")
	_check(displayed_positions[0].distance_to(displayed_positions[-1]) > .015, "test did not sample two moving physics frames")
	_check(max_pose_error < .00001 and max_rotation_error < .001, "display transform/pose interpolation mismatch")
	_check(actor.global_transform == saved_root and actor.actual_velocity == saved_velocity, "display modified character physics")
	_check(display.physics_captures == captures and steps == events, "render repeated physics evaluation or footstep event")
	_check(actor.pose_recorder.final_phase == saved_phase and actor.pose_recorder.final_pose == saved_record, "display contaminated final physics diagnostics")
	for i in range(5):
		display.render_at(float(i) / 4.0)
		await process_frame
	_check(actor.pose_recorder.evaluation_count == evaluations, "display replayed skeleton modifiers")
	_check(steps == events, "display frames repeated footstep events")
	var display_evaluations: int = actor.pose_recorder.evaluation_count - evaluations
	display.restore_physics()
	for bone in range(actor.skeleton.get_bone_count()):
		_check(actor.skeleton.get_bone_pose(bone).is_equal_approx(display.physics_pose[bone]), "physics pose restoration mismatch")
	display.render_at(1.0)
	for bone in range(actor.skeleton.get_bone_count()):
		max_final_pose_error = maxf(max_final_pose_error, actor.skeleton.get_bone_global_pose(bone).origin.distance_to(saved_record[bone].origin))
	_check(max_final_pose_error < .00001, "snapshot omitted final IK pose")
	_check(actor.visual.global_transform.is_equal_approx(display.current_transform), "physics world transform restoration mismatch")
	actor.reset_at(Vector3(2, .04, 4), .8)
	display.render_at(0)
	var start := actor.visual.global_transform
	display.render_at(1)
	_check(start.is_equal_approx(actor.visual.global_transform), "reset left stale transform interpolation history")
	_check(display.previous_pose == display.current_pose, "reset left stale bone interpolation history")
	measured = {"physics_hz":60,"render_fractions":[0,.25,.5,.75,1],"physics_frame_distance_m":displayed_positions[0].distance_to(displayed_positions[-1]),"maximum_pose_error_m":max_pose_error,"maximum_final_ik_snapshot_error_m":max_final_pose_error,"maximum_rotation_error_radians":max_rotation_error,"footsteps":events,"physics_modifier_evaluations":evaluations,"physics_snapshot_captures":captures,"display_modifier_evaluations":display_evaluations,"physics_snapshot_isolation":true,"reset_history_cleared":true,"failures":failures}
	var file := FileAccess.open("res://reports/presentation.json", FileAccess.WRITE)
	file.store_string(JSON.stringify(measured,"\t"))
	print("PRESENTATION_PASS" if failures.is_empty() else JSON.stringify(failures))
	quit(0 if failures.is_empty() else 1)
