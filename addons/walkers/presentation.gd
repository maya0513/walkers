extends Node
## Rendering owns an interpolated copy; physics and diagnostics retain exact poses.
## One tick of visual latency is intentional, as with engine physics interpolation.
var motor: HumanoidMotor
var visual: Node3D
var skeleton: Skeleton3D
var previous_transform := Transform3D.IDENTITY
var current_transform := Transform3D.IDENTITY
var previous_pose: Array[Transform3D] = []
var current_pose: Array[Transform3D] = []
var physics_pose: Array[Transform3D] = []
var initialized := false
var modifiers: Array[SkeletonModifier3D] = []
var modifier_states: Array[bool] = []
var physics_captures := 0
var display_position := Vector3.ZERO

func setup(body: HumanoidMotor) -> void:
	motor = body
	visual = body.visual
	skeleton = body.skeleton
	# Run before the camera, which follows the same displayed world position.
	process_priority = -20
	visual.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	for child: Node in skeleton.get_children():
		if child is SkeletonModifier3D:
			modifiers.append(child)
			modifier_states.append(child.active)

func restore_physics() -> void:
	if not initialized:
		return
	visual.global_transform = current_transform
	_apply_pose(physics_pose)
	for i in range(modifiers.size()):
		modifiers[i].active = modifier_states[i]

func capture_physics(reset_history: bool = false) -> void:
	var next_pose: Array[Transform3D] = []
	physics_pose.clear()
	var final_globals: Array = motor.pose_recorder.final_pose
	for i in range(skeleton.get_bone_count()):
		# Godot restores pre-modifier poses after advance(). Capture these for
		# physics restoration, and derive the displayed locals from the recorder
		# that runs inside the final modifier, before that restoration occurs.
		physics_pose.append(skeleton.get_bone_pose(i))
		var parent := skeleton.get_bone_parent(i)
		if final_globals.size() == skeleton.get_bone_count():
			next_pose.append(final_globals[i] if parent < 0 else final_globals[parent].affine_inverse() * final_globals[i])
		else:
			next_pose.append(physics_pose[-1])
	if initialized and not reset_history:
		previous_transform = current_transform
		previous_pose = current_pose
	else:
		previous_transform = visual.global_transform
		previous_pose = next_pose.duplicate()
	current_transform = visual.global_transform
	current_pose = next_pose
	display_position = current_transform.origin
	initialized = true
	physics_captures += 1
	for modifier: SkeletonModifier3D in modifiers:
		modifier.active = false

func _apply_pose(poses: Array[Transform3D]) -> void:
	for i in range(poses.size()):
		skeleton.set_bone_pose(i, poses[i])

func render_at(fraction: float) -> void:
	if not initialized:
		return
	# Bone setters also queue a skeleton update in manual mode. Disable the
	# solver while displaying snapshots, so render frames cannot rerun IK.
	for modifier: SkeletonModifier3D in modifiers:
		modifier.active = false
	var alpha := clampf(fraction, 0, 1)
	visual.global_transform = previous_transform.interpolate_with(current_transform, alpha)
	for i in range(current_pose.size()):
		skeleton.set_bone_pose(i, previous_pose[i].interpolate_with(current_pose[i], alpha))
	display_position = visual.global_position

func _process(_delta: float) -> void:
	render_at(Engine.get_physics_interpolation_fraction())
