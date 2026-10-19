extends SkeletonModifier3D
## Applied after the native leg solver. Capture the final pose for diagnostics.

var grounding: HumanoidGrounding
var final_pose: Array[Transform3D] = []
var final_world_transform: Transform3D = Transform3D.IDENTITY
var final_phase: float = 0.0
var final_state: StringName = &"Idle"
var refine_targets: bool = false

func _process_modification_with_delta(_delta: float) -> void:
	if not is_instance_valid(grounding):
		return
	var skeleton := get_skeleton()
	for i in range(2):
		var bone := skeleton.find_bone("LeftFoot" if i == 0 else "RightFoot")
		var pose := skeleton.get_bone_global_pose(bone)
		pose.basis = skeleton.global_basis.inverse() * grounding.desired_basis[i]
		skeleton.set_bone_global_pose(bone, pose)
		grounding.actual_feet[i] = skeleton.global_transform * pose.origin
		grounding.actual_support_points[i] = skeleton.global_transform * (pose.origin + pose.basis * grounding.support_local[i])
	if refine_targets:
		grounding.refine_from_skinned_soles()
	else:
		final_world_transform = skeleton.global_transform
		final_phase = grounding.animator.phase
		final_state = grounding.animator.state
		final_pose.clear()
		for i in range(skeleton.get_bone_count()):
			final_pose.append(skeleton.get_bone_global_pose(i))

