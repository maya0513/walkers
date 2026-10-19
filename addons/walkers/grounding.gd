class_name HumanoidGrounding
extends SkeletonModifier3D
## Runs before native TwoBoneIK3D; a final modifier restores foot orientation.

signal footstep(side: StringName, world_position: Vector3, normal: Vector3)

var motor: CharacterBody3D
var config: LocomotionConfig
var animator: LocomotionAnimator
var targets: Array[Node3D] = []
var poles: Array[Node3D] = []
var locked: Array[bool] = [false, false]
var anchors: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var desired_basis: Array[Basis] = [Basis.IDENTITY, Basis.IDENTITY]
var actual_feet: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var actual_support_points: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var support_regions: Array[String] = ["sole", "sole"]
var support_local: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var _locked_regions: Array[String] = ["", ""]
var _previous_support_local: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var _was_contact: Array[bool] = [false, false]
var normals: Array[Vector3] = [Vector3.UP, Vector3.UP]
var contact_weights := Vector2.ONE
var pelvis_offset: float = 0.0
var debug_enabled: bool = false
var _indices: Array[int] = []
var _sole_up: Array[Vector3] = []
var _sole_samples: Dictionary = {}
var _bindings: Dictionary = {}
var _obstacle_near: Array[bool] = [false, false]

func setup(body: CharacterBody3D, settings: LocomotionConfig, driver: LocomotionAnimator) -> void:
	motor = body
	config = settings
	animator = driver
	var skeleton := get_skeleton()
	var sole_file := config.sole_samples_file
	if FileAccess.file_exists(sole_file):
		_sole_samples = JSON.parse_string(FileAccess.get_file_as_string(sole_file))
	for i in range(skeleton.get_bone_count()):
		_bindings[skeleton.get_bone_name(i)] = {"index": i, "inverse": skeleton.get_bone_global_rest(i).affine_inverse()}
	for side: String in ["Left", "Right"]:
		var index := skeleton.find_bone(side + "Foot")
		_indices.append(index)
		_sole_up.append(skeleton.get_bone_global_rest(index).basis.inverse() * Vector3.UP)
		var target := Node3D.new()
		target.name = side + "FootTarget"
		motor.add_child(target)
		targets.append(target)
		var pole := Node3D.new()
		pole.name = side + "KneePole"
		motor.add_child(pole)
		poles.append(pole)

func ray_floor(position: Vector3, above: float = 0.4, below: float = 0.5) -> Dictionary:
	var query := PhysicsRayQueryParameters3D.create(position + Vector3.UP * above, position - Vector3.UP * below, 1, [motor.get_rid()])
	return motor.get_world_3d().direct_space_state.intersect_ray(query)

func _reachable_floor(hit: Dictionary) -> bool:
	if hit.is_empty():
		return false
	var continuous_slope: bool = hit.normal.y < .999 and hit.normal.y > cos(deg_to_rad(config.max_slope_degrees + .5))
	return continuous_slope or hit.position.y - motor.global_position.y <= config.step_height + .06

func refine_from_skinned_soles() -> void:
	# A second solve accounts for skin weights shared with the shin, which a
	# rigid-foot prediction cannot capture on stairs and steep surfaces.
	var skeleton := get_skeleton()
	for i in range(2):
		var side := "Left" if i == 0 else "Right"
		var lift := 0.0
		var wall_push := Vector3.ZERO
		for marker: Dictionary in _sole_samples.get(side, []):
			var p: Array = marker.position
			var rest_position := Vector3(p[0], p[1], p[2])
			var skinned := Vector3.ZERO
			for influence: Array in marker.weights:
				var binding: Dictionary = _bindings[influence[0]]
				skinned += (skeleton.get_bone_global_pose(binding.index) * (binding.inverse * rest_position)) * float(influence[1])
			var world := skeleton.global_transform * skinned
			var hit := ray_floor(world, .35, .35)
			if _reachable_floor(hit):
				lift = maxf(lift, hit.position.y + .001 - world.y)
			# A trailing foot can remain beside an obstacle after the capsule has
			# turned away. Check each footprint even when forward motion is free.
			var from := Vector3(motor.global_position.x, world.y, motor.global_position.z)
			var query := PhysicsRayQueryParameters3D.create(from, world, 1, [motor.get_rid()])
			var wall := motor.get_world_3d().direct_space_state.intersect_ray(query)
			if not wall.is_empty() and absf(wall.normal.y) < .5:
				if _tall_wall_toward(world):
					var push: Vector3 = wall.normal * ((world - wall.position).length() + .022)
					if push.length_squared() > wall_push.length_squared():
						wall_push = push
		targets[i].global_position.y += minf(lift, .20)
		targets[i].global_position += wall_push.limit_length(.40)
		if wall_push.length() > .02:
			locked[i] = false

func _process_modification_with_delta(delta: float) -> void:
	if not is_instance_valid(motor) or _indices.size() != 2:
		return
	var skeleton := get_skeleton()
	var skeleton_world := skeleton.global_transform
	var raw: Array[Transform3D] = []
	var hits: Array[Dictionary] = []
	var desired_pelvis := 0.0
	var grounded: bool = motor.is_on_floor() or motor.get("step_active") == true
	for i in range(2):
		var pose := skeleton_world * skeleton.get_bone_global_pose(_indices[i])
		var local_foot := skeleton.get_bone_global_pose(_indices[i]).origin
		var local_hips := skeleton.get_bone_global_pose(skeleton.find_bone("Hips")).origin
		pose.origin += skeleton_world.basis.z * (local_foot.z - local_hips.z) * (animator.stride_scale - 1.0)
		raw.append(pose)
		var authored_support := pose.origin + pose.basis * _support_offset(i, animator.support_regions[i])
		var hit := ray_floor(authored_support)
		if not _reachable_floor(hit):
			hit = {}
		hits.append(hit)
		if grounded and not hit.is_empty() and animator.contacts[i] > .5:
			var offset := _support_offset(i, animator.support_regions[i])
			var support := pose.origin + pose.basis * offset
			var difference: float = hit.position.y - support.y
			desired_pelvis = minf(desired_pelvis, difference)
	desired_pelvis = clampf(desired_pelvis, -config.pelvis_limit, config.pelvis_limit)
	pelvis_offset = lerpf(pelvis_offset, desired_pelvis, 1.0 - exp(-config.grounding_speed * delta))
	var hips := skeleton.find_bone("Hips")
	var hip_pose := skeleton.get_bone_global_pose(hips)
	hip_pose.origin += skeleton_world.basis.inverse() * (Vector3.UP * pelvis_offset)
	skeleton.set_bone_global_pose(hips, hip_pose)
	contact_weights = animator.contacts
	for i in range(2):
		var pose := raw[i]
		var hit := hits[i]
		var weight: float = contact_weights[i] if grounded and not hit.is_empty() else 0.0
		var corrected := pose.origin + Vector3.UP * pelvis_offset
		var basis := pose.basis
		support_regions[i] = animator.support_regions[i]
		support_local[i] = _support_offset(i, support_regions[i])
		var continuous_support := animator.support_offsets.size() == 2
		var on_contact := weight > .72 and (continuous_support or support_regions[i] != "air")
		if on_contact and not _was_contact[i] and animator.state != &"Idle":
			footstep.emit(&"Left" if i == 0 else &"Right", hit.position, hit.normal)
		_was_contact[i] = on_contact if weight > .2 else false
		if not config.foot_lock or weight < .2 or (not continuous_support and support_regions[i] == "air"):
			locked[i] = false
		if weight > 0.01:
			normals[i] = hit.normal
			# Rotate the authored pose by the terrain slope, preserving heel/toe roll.
			var slope := Quaternion(Vector3.UP, normals[i])
			basis = Basis(Quaternion.IDENTITY.slerp(slope, weight)) * basis
			var source_support := corrected + basis * support_local[i]
			var floor_target: Vector3 = hit.position
			if locked[i] and continuous_support:
				# A rolling contact migrates over the floor. Advance only by the
				# local support-point change, preserving the previous support pivot
				# during authored ankle rotation. Body/ankle translation is excluded.
				var rolling := basis * (support_local[i] - _previous_support_local[i])
				anchors[i] += rolling.slide(normals[i])
			if locked[i] and ((not continuous_support and _locked_regions[i] != support_regions[i]) or source_support.distance_to(anchors[i]) > config.foot_correction_limit):
				locked[i] = false
			if config.foot_lock and on_contact and not locked[i]:
				anchors[i] = hit.position
				locked[i] = true
				_locked_regions[i] = support_regions[i]
			if locked[i]:
				floor_target = anchors[i]
			corrected += (floor_target - source_support).limit_length(config.foot_correction_limit) * weight
		# Retract the foot before a wall or an over-height riser. Legal low
		# steps continue through sole clearance instead of being treated as walls.
		var forward := skeleton_world.basis.z.normalized()
		var from := Vector3(motor.global_position.x, corrected.y + .035, motor.global_position.z)
		var query := PhysicsRayQueryParameters3D.create(from, corrected + forward * .25 + Vector3.UP * .035, 1, [motor.get_rid()])
		var obstacle := motor.get_world_3d().direct_space_state.intersect_ray(query)
		_obstacle_near[i] = not obstacle.is_empty() and absf(obstacle.normal.y) < .5
		if not obstacle.is_empty() and absf(obstacle.normal.y) < .5:
			if _tall_wall_toward(corrected + forward * .25):
				var safe_point: Vector3 = obstacle.position + obstacle.normal * .25
				corrected.x = safe_point.x
				corrected.z = safe_point.z
				locked[i] = false
		# Predict the skinned sole after foot alignment. This preserves clearance
		# even when the toe articulation changes the ankle-to-ground distance.
		var side_name := "Left" if i == 0 else "Right"
		var source_foot := skeleton_world * skeleton.get_bone_global_pose(_indices[i])
		var rotation_delta := basis * source_foot.basis.inverse()
		var lift := -INF
		for marker: Dictionary in _sole_samples.get(side_name, []):
			var p: Array = marker.position
			var rest_position := Vector3(p[0], p[1], p[2])
			var skinned := Vector3.ZERO
			for influence: Array in marker.weights:
				var binding: Dictionary = _bindings[influence[0]]
				skinned += (skeleton.get_bone_global_pose(binding.index) * (binding.inverse * rest_position)) * float(influence[1])
			var world := corrected + rotation_delta * (skeleton_world * skinned - source_foot.origin)
			var sole_hit := ray_floor(world, .32, .32)
			if _reachable_floor(sole_hit):
				lift = maxf(lift, sole_hit.position.y + .001 - world.y)
		if is_finite(lift):
			corrected.y += clampf(lift, -.15, config.foot_correction_limit) * (1.0 if lift > 0 else weight)
		_previous_support_local[i] = support_local[i]
		desired_basis[i] = basis
		targets[i].global_transform = Transform3D(basis, corrected)
		var side := "Left" if i == 0 else "Right"
		var knee: Vector3 = skeleton_world * skeleton.get_bone_global_pose(skeleton.find_bone(side + "LowerLeg")).origin
		poles[i].global_position = knee + motor.get_node("Visual").global_basis.z * 0.6


func _support_offset(index: int, region: String) -> Vector3:
	if animator.support_offsets.size() == 2:
		return get_skeleton().get_bone_global_rest(_indices[index]).basis.inverse() * animator.support_offsets[index]
	var side := "Left" if index == 0 else "Right"
	var points: Dictionary = animator.metadata.get("support_points", {}).get(side, {})
	if points.is_empty():
		return get_skeleton().get_bone_global_rest(_indices[index]).basis.inverse() * Vector3(0, -config.sole_height, 0)
	var point: Array = points.get(region, points["sole"])
	var offset := Vector3(point[0], point[1], point[2])
	if region == "sole":
		# Flat support describes the heel/forefoot ground plane, not the raised
		# skin under the arch. Grounding the arch would sink the pelvis and then
		# sole-clearance would raise the foot, bending the knee twice.
		offset.y = -config.sole_height
	return get_skeleton().get_bone_global_rest(_indices[index]).basis.inverse() * offset

func _tall_wall_toward(position_value: Vector3) -> bool:
	# Start outside colliders at body centre. A downward ray starting inside a
	# tall wall can hit the floor below and incorrectly classify it as a low step.
	var height := motor.global_position.y + config.step_height + .025
	var from := Vector3(motor.global_position.x, height, motor.global_position.z)
	var toward := Vector3(position_value.x, height, position_value.z)
	var query := PhysicsRayQueryParameters3D.create(from, toward, 1, [motor.get_rid()])
	var hit := motor.get_world_3d().direct_space_state.intersect_ray(query)
	return not hit.is_empty() and absf(hit.normal.y) < .5
