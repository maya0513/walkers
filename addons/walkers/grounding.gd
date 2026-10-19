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
var _previous_support_materials: Array = [[], []]
var _previous_material_local: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var _lock_suspended: Array[bool] = [false, false]
var _lock_release: Array[float] = [0.0, 0.0]
var _obstacle_offsets: Array[Vector3] = [Vector3.ZERO, Vector3.ZERO]
var _previous_facing: Vector3 = Vector3.ZERO
var _steering_stride_scale: float = 1.0
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

func reset_contacts() -> void:
	locked = [false, false]
	anchors = [Vector3.ZERO, Vector3.ZERO]
	_was_contact = [false, false]
	_locked_regions = ["", ""]
	_previous_support_local = [Vector3.ZERO, Vector3.ZERO]
	_previous_support_materials = [[], []]
	_previous_material_local = [Vector3.ZERO, Vector3.ZERO]
	_lock_suspended = [false, false]
	_lock_release = [0.0, 0.0]
	_obstacle_offsets = [Vector3.ZERO, Vector3.ZERO]
	_previous_facing = Vector3.ZERO
	_steering_stride_scale = 1.0
	normals = [Vector3.UP, Vector3.UP]
	pelvis_offset = 0.0

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
				if _blocks_foot_from_side(world, wall.normal):
					var push: Vector3 = wall.normal * maxf(0.0, .022 - (world - wall.position).dot(wall.normal))
					if push.length_squared() > wall_push.length_squared():
						wall_push = push
		targets[i].global_position.y += minf(lift, .20)
		targets[i].global_position += wall_push.limit_length(.40)
		if wall_push.length() > .02:
			locked[i] = false
			_lock_suspended[i] = true
			_lock_release[i] = 0.0

func _process_modification_with_delta(delta: float) -> void:
	if not is_instance_valid(motor) or _indices.size() != 2:
		return
	var skeleton := get_skeleton()
	var skeleton_world := skeleton.global_transform
	var facing := skeleton_world.basis.z.normalized()
	var yaw_rate := 0.0
	if delta > 0.0 and _previous_facing.length_squared() > .5:
		yaw_rate = absf(atan2(_previous_facing.cross(facing).y, _previous_facing.dot(facing))) / delta
	_previous_facing = facing
	var sharp_turn := yaw_rate > 2.5
	# Fast pivots use compact stepping. A full forward stride aimed through a
	# nearby wall otherwise needs a lateral correction across the opposite leg.
	_steering_stride_scale = lerpf(_steering_stride_scale, .25 if sharp_turn else 1.0, 1.0 - exp(-config.grounding_speed * delta))
	var raw: Array[Transform3D] = []
	var hits: Array[Dictionary] = []
	var desired_pelvis := 0.0
	var grounded: bool = motor.is_on_floor() or motor.get("step_active") == true
	for i in range(2):
		var pose := skeleton_world * skeleton.get_bone_global_pose(_indices[i])
		var local_foot := skeleton.get_bone_global_pose(_indices[i]).origin
		var local_hips := skeleton.get_bone_global_pose(skeleton.find_bone("Hips")).origin
		pose.origin += skeleton_world.basis.z * (local_foot.z - local_hips.z) * (animator.stride_scale * _steering_stride_scale - 1.0)
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
		# Separate onset and release thresholds: a blend may dip below the onset
		# threshold while the same foot is still in contact. Do not emit twice.
		if on_contact:
			_was_contact[i] = true
		elif weight <= .2:
			_was_contact[i] = false
		if not config.foot_lock or weight < .2 or (not continuous_support and support_regions[i] == "air"):
			locked[i] = false
			_lock_suspended[i] = false
			_lock_release[i] = 0.0
		if sharp_turn:
			if locked[i]:
				_lock_release[i] = 1.0
			locked[i] = false
			_lock_suspended[i] = true
		if weight > 0.01:
			normals[i] = hit.normal
			# Rotate the authored pose by the terrain slope, preserving heel/toe roll.
			var slope := Quaternion(Vector3.UP, normals[i])
			basis = Basis(Quaternion.IDENTITY.slerp(slope, weight)) * basis
			var source_support := corrected + basis * support_local[i]
			var floor_target: Vector3 = hit.position
			if (locked[i] or _lock_release[i] > 0.0) and continuous_support:
				# A rolling contact migrates over the floor. Advance only by the
				# local support-point change, preserving the previous support pivot
				# during authored ankle rotation. Body/ankle translation is excluded.
				var deformation := Vector3.ZERO
				if animator.support_materials.size() == 2 and not _previous_support_materials[i].is_empty():
					# Toe bending moves a fixed skin point relative to the ankle.
					# That movement must be compensated, not counted as the contact
					# rolling onto a different point of the sole.
					deformation = _material_local(i, _previous_support_materials[i]) - _previous_material_local[i]
				var rolling := basis * (support_local[i] - _previous_support_local[i] - deformation)
				anchors[i] += rolling.slide(normals[i])
			if locked[i] and not continuous_support and _locked_regions[i] != support_regions[i]:
				locked[i] = false
			if locked[i] and source_support.distance_to(anchors[i]) > config.foot_correction_limit:
				# A collision slide can carry the body past a planted leg's reach.
				# Release gradually and wait for the next contact before anchoring;
				# reacquiring now would teleport the same planted foot to a new point.
				locked[i] = false
				_lock_suspended[i] = true
				_lock_release[i] = 1.0
			if config.foot_lock and on_contact and not locked[i] and not _lock_suspended[i]:
				anchors[i] = hit.position
				locked[i] = true
				_locked_regions[i] = support_regions[i]
			if locked[i]:
				floor_target = anchors[i]
			elif _lock_release[i] > 0.0:
				var r := _lock_release[i]
				var release_weight := r * r * r * (10.0 + r * (-15.0 + 6.0 * r))
				floor_target = hit.position.lerp(anchors[i], release_weight)
				_lock_release[i] = maxf(0.0, r - delta / .12)
			corrected += (floor_target - source_support).limit_length(config.foot_correction_limit) * weight
		# Retract the foot before a wall or an over-height riser. Legal low
		# steps continue through sole clearance instead of being treated as walls.
		var forward := skeleton_world.basis.z.normalized()
		var from := Vector3(motor.global_position.x, corrected.y + .035, motor.global_position.z)
		var query := PhysicsRayQueryParameters3D.create(from, corrected + forward * .25 + Vector3.UP * .035, 1, [motor.get_rid()])
		var obstacle := motor.get_world_3d().direct_space_state.intersect_ray(query)
		var wall_correction := Vector3.ZERO
		_obstacle_near[i] = not obstacle.is_empty() and absf(obstacle.normal.y) < .5
		if not obstacle.is_empty() and absf(obstacle.normal.y) < .5:
			if _blocks_foot_from_side(corrected + forward * .25, obstacle.normal):
				# Correct only the wall-normal distance. Copying the ray's hit
				# position also overwrites tangential travel and snaps the foot
				# along the face when a corner changes which ray first intersects.
				wall_correction = obstacle.normal * maxf(0.0, .25 - (corrected - obstacle.position).dot(obstacle.normal))
				locked[i] = false
				_lock_suspended[i] = true
				_lock_release[i] = 0.0
		var obstacle_offset := _obstacle_offsets[i].lerp(wall_correction, 1.0 - exp(-config.grounding_speed * delta))
		if wall_correction.length_squared() > .000001:
			# Enforce new clearance immediately, while releasing old clearance
			# smoothly when a ray clears a corner. Releasing an unnecessary offset
			# is safe; interpolating into a newly detected wall would penetrate it.
			var normal := wall_correction.normalized()
			obstacle_offset += normal * maxf(0.0, wall_correction.length() - obstacle_offset.dot(normal))
		_obstacle_offsets[i] = obstacle_offset
		corrected += obstacle_offset
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
		if animator.support_materials.size() == 2:
			_previous_support_materials[i] = animator.support_materials[i]
			_previous_material_local[i] = _material_local(i, animator.support_materials[i])
		else:
			_previous_support_materials[i] = []
		desired_basis[i] = basis
		targets[i].global_transform = Transform3D(basis, corrected)
		var side := "Left" if i == 0 else "Right"
		var knee: Vector3 = skeleton_world * skeleton.get_bone_global_pose(skeleton.find_bone(side + "LowerLeg")).origin
		poles[i].global_position = knee + motor.get_node("Visual").global_basis.z * 0.6

func _material_local(index: int, material: Array) -> Vector3:
	var skeleton := get_skeleton()
	var position := Vector3.ZERO
	for binding: Dictionary in material:
		var bone: int = _bindings[String(binding.bone)].index
		var pose := skeleton.get_bone_global_pose(bone)
		var local_position: Vector3 = binding.position
		if animator.metadata.get("support_material_space", "bone_local") == "rest_skeleton":
			# Humanoid retargeting may reorient imported bone rest axes. Keep
			# bindings in rest-skeleton space and resolve against the actual rest.
			var inverse: Transform3D = _bindings[String(binding.bone)].inverse
			local_position = inverse.basis * local_position + inverse.origin * float(binding.weight)
		position += pose.basis * local_position + pose.origin * float(binding.weight)
	return skeleton.get_bone_global_pose(_indices[index]).affine_inverse() * position


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

func _blocks_foot_from_side(position_value: Vector3, normal: Vector3) -> bool:
	var travel := Vector3(motor.actual_velocity.x, 0, motor.actual_velocity.z)
	# A low tread is traversable from its front. While the capsule slides along
	# its side, however, do not let a foot enter that tread and then snap back
	# when the next, taller riser becomes the first ray hit.
	var side_slide: bool = motor.get("movement_blocked") == true and travel.length() > .08 and absf(normal.dot(travel.normalized())) < .5
	return side_slide or _tall_wall_toward(position_value)
