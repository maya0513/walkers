class_name HumanoidMotor
extends CharacterBody3D
## Public API accepts a world-space heading and a speed in metres/second.
## Does not read Input, depend on a camera, or require an autoload.

signal footstep(side: StringName, world_position: Vector3, normal: Vector3)
signal state_changed(previous: StringName, current: StringName)

@export var config: LocomotionConfig = preload("res://addons/walkers/default_config.tres")
@export var debug_grounding: bool = false

var actual_velocity: Vector3 = Vector3.ZERO
var facing_yaw: float = 0.0
var requested_speed: float = 0.0
var requested_direction: Vector3 = Vector3.FORWARD
var animator: LocomotionAnimator
var grounding: HumanoidGrounding
var skeleton: Skeleton3D
var presentation: Node
var pose_recorder: SkeletonModifier3D
var movement_blocked: bool = false
var step_active: bool = false
var _step_visual_offset: float = 0.0
var _gravity: float = 9.8

@onready var visual: Node3D = $Visual

func _ready() -> void:
	config = config.duplicate()
	_gravity = float(ProjectSettings.get_setting("physics/3d/default_gravity", 9.8))
	var capsule: CapsuleShape3D = $CollisionShape3D.shape.duplicate()
	capsule.height = config.character_height
	capsule.radius = config.character_height * .1292
	$CollisionShape3D.shape = capsule
	$CollisionShape3D.position.y = config.character_height * .5
	floor_max_angle = deg_to_rad(config.max_slope_degrees + 0.5)
	floor_snap_length = config.floor_snap
	floor_constant_speed = true
	floor_stop_on_slope = true
	safe_margin = 0.002
	skeleton = _find_type(visual, "Skeleton3D") as Skeleton3D
	assert(skeleton != null, "The visual scene must contain a Skeleton3D")
	var player := _find_type(visual, "AnimationPlayer") as AnimationPlayer
	assert(player != null, "The visual scene must contain an AnimationPlayer")
	animator = LocomotionAnimator.new()
	animator.name = "LocomotionAnimator"
	add_child(animator)
	animator.initialize(player, $AnimationTree, config)
	animator.state_changed.connect(func(a: StringName, b: StringName) -> void: state_changed.emit(a, b))
	if config.use_library_sole_height:
		config.sole_height = float(animator.metadata.sole_height)
	skeleton.modifier_callback_mode_process = Skeleton3D.MODIFIER_CALLBACK_MODE_PROCESS_MANUAL
	grounding = HumanoidGrounding.new()
	grounding.name = "GroundTargets"
	skeleton.add_child(grounding)
	grounding.setup(self, config, animator)
	grounding.footstep.connect(func(s: StringName, p: Vector3, n: Vector3) -> void: footstep.emit(s, p, n))
	for solve_pass in range(3):
		var ik := TwoBoneIK3D.new()
		ik.name = "GroundedLegIK%d" % solve_pass
		skeleton.add_child(ik)
		ik.setting_count = 2
		for i in range(2):
			var side := "Left" if i == 0 else "Right"
			ik.set_root_bone_name(i, side + "UpperLeg")
			ik.set_middle_bone_name(i, side + "LowerLeg")
			ik.set_end_bone_name(i, side + "Foot")
			ik.set_target_node(i, ik.get_path_to(grounding.targets[i]))
			ik.set_pole_node(i, ik.get_path_to(grounding.poles[i]))
		var orientation: SkeletonModifier3D = load("res://addons/walkers/foot_orientation.gd").new()
		orientation.name = "FootOrientation%d" % solve_pass
		orientation.set("grounding", grounding)
		orientation.set("refine_targets", solve_pass < 2)
		skeleton.add_child(orientation)
		if solve_pass == 2:
			pose_recorder = orientation
	visual.rotation.y = facing_yaw + PI
	presentation = preload("res://addons/walkers/presentation.gd").new()
	presentation.name = "Presentation"
	add_child(presentation)
	presentation.setup(self)
	skeleton.advance(0.0)
	skeleton.notification(Skeleton3D.NOTIFICATION_UPDATE_SKELETON)
	presentation.capture_physics(true)

func set_move_intent(world_direction: Vector3, speed_mps: float) -> void:
	world_direction.y = 0
	if not world_direction.is_finite() or not is_finite(speed_mps):
		requested_speed = 0
		return
	requested_speed = clampf(speed_mps, 0.0, config.max_speed()) if world_direction.length_squared() > 0.0001 else 0.0
	if requested_speed > 0:
		requested_direction = world_direction.normalized()

func reset_at(position_on_floor: Vector3, yaw: float = 0.0) -> void:
	if is_instance_valid(presentation):
		presentation.restore_physics()
	global_position = position_on_floor
	velocity = Vector3.ZERO
	actual_velocity = Vector3.ZERO
	requested_speed = 0
	facing_yaw = yaw
	_step_visual_offset = 0
	step_active = false
	if is_instance_valid(grounding):
		grounding.reset_contacts()
	if is_instance_valid(animator):
		animator.reset_to_idle()
	visual.position.y = 0.0
	visual.rotation.y = facing_yaw + PI
	skeleton.advance(0.0)
	skeleton.notification(Skeleton3D.NOTIFICATION_UPDATE_SKELETON)
	if is_instance_valid(presentation):
		presentation.capture_physics(true)

func _physics_process(delta: float) -> void:
	if not is_instance_valid(animator):
		return
	presentation.restore_physics()
	var desired_speed := requested_speed
	step_active = false
	var horizontal := Vector3(velocity.x, 0, velocity.z)
	if desired_speed > .04:
		var target_yaw := atan2(-requested_direction.x, -requested_direction.z)
		var error := wrapf(target_yaw - facing_yaw, -PI, PI)
		facing_yaw += clampf(error, -config.turn_speed * delta, config.turn_speed * delta)
		# Steering remains interruptible. Slow a sharp reversal while facing catches up.
		var remaining := wrapf(target_yaw - facing_yaw, -PI, PI)
		desired_speed *= lerpf(.2, 1.0, maxf(0.0, cos(remaining)))
	var heading := Vector3(-sin(facing_yaw), 0, -cos(facing_yaw))
	var desired_velocity := heading * desired_speed
	var acceleration := config.braking if desired_speed < horizontal.length() else config.acceleration
	horizontal = horizontal.move_toward(desired_velocity, acceleration * delta)
	movement_blocked = false
	var before := global_position
	if (is_on_floor() or velocity.y >= -.7) and horizontal.length() > .01:
		step_active = _step_up(horizontal * delta)
	velocity.x = horizontal.x
	velocity.z = horizontal.z
	velocity.y = 0.0 if step_active or is_on_floor() else velocity.y - _gravity * delta
	move_and_slide()
	actual_velocity = (global_position - before) / delta
	var actual_speed := Vector2(actual_velocity.x, actual_velocity.z).length()
	for i in range(get_slide_collision_count()):
		if absf(get_slide_collision(i).get_normal().y) < .5:
			movement_blocked = true
	_step_visual_offset = lerpf(_step_visual_offset, 0.0, 1.0 - exp(-14.0 * delta))
	visual.position.y = _step_visual_offset
	visual.rotation.y = facing_yaw + PI
	var downhill := 0.0
	if is_on_floor():
		var tangent := heading.slide(get_floor_normal()).normalized()
		downhill = clampf(-tangent.y / maxf(sin(deg_to_rad(config.max_slope_degrees)), .001), 0, 1)
	animator.stride_scale = lerpf(1.0, config.downhill_stride_scale, downhill)
	# A wall can block forward motion while allowing a useful sideways slide.
	# Keep the gait and contact phase advancing whenever the body really moves.
	var animation_intent := maxf(desired_speed, actual_speed) if actual_speed > .08 else desired_speed
	if movement_blocked and actual_speed <= .08:
		animation_intent = 0.0
	animator.tick(delta, actual_speed, animation_intent)
	skeleton.advance(delta)
	# Flush the documented deferred skeleton update before capturing this tick.
	# Otherwise final_pose still describes the previous physics frame.
	skeleton.notification(Skeleton3D.NOTIFICATION_UPDATE_SKELETON)
	presentation.capture_physics()
	if global_position.y < -12:
		reset_at(Vector3(0, 0.04, 4))

func _step_up(motion: Vector3) -> bool:
	var obstacle := KinematicCollision3D.new()
	var blocked := test_move(global_transform, motion, obstacle)
	if blocked and obstacle.get_normal().y > cos(floor_max_angle):
		return false
	# A capsule's rounded bottom hits a stair corner with a diagonal normal.
	# Classify the actual top surface with a leading-footprint ray instead.
	# This support is recomputed from geometry every tick, never held by a timer.
	var capsule := $CollisionShape3D.shape as CapsuleShape3D
	var leading := global_position + motion + motion.normalized() * capsule.radius
	var query := PhysicsRayQueryParameters3D.create(
		leading + Vector3.UP * (config.step_height + .018),
		leading - Vector3.UP * .025, collision_mask, [get_rid()])
	var top := get_world_3d().direct_space_state.intersect_ray(query)
	if top.is_empty() or top.normal.y < cos(floor_max_angle):
		return false
	var height: float = top.position.y + .002 - global_position.y
	if height < -.018 or height > config.step_height + .015:
		return false
	if not blocked:
		if is_on_floor() or absf(height) > .018:
			return false
		# Edge support is useful only while the capsule centre is still over
		# the lower tread. Flat ground must attach through move_and_slide;
		# otherwise zero vertical velocity would prevent is_on_floor forever.
		var centre_query := PhysicsRayQueryParameters3D.create(
			global_position + Vector3.UP * .02,
			global_position - Vector3.UP * (config.step_height + .05), collision_mask, [get_rid()])
		var centre_floor := get_world_3d().direct_space_state.intersect_ray(centre_query)
		if centre_floor.is_empty() or global_position.y - centre_floor.position.y <= .025:
			return false
	if blocked and height <= .005:
		return false
	# Up and forward must both clear the complete capsule, so an adjacent
	# wall, a stair side or a low ceiling cannot grant a free vertical step.
	var rise := Vector3.UP * (config.step_height + .018)
	if test_move(global_transform, rise):
		return false
	var raised := global_transform
	raised.origin += rise
	if test_move(raised, motion):
		return false
	var landing := KinematicCollision3D.new()
	raised.origin += motion
	if not test_move(raised, -rise - Vector3.UP * .025, landing):
		return false
	# Correct only height; move_and_slide applies the forward movement once.
	global_position.y += height
	_step_visual_offset -= height
	return true

func _find_type(node: Node, type_name: String) -> Node:
	if node.is_class(type_name):
		return node
	for child: Node in node.get_children():
		var found := _find_type(child, type_name)
		if found != null:
			return found
	return null


func get_display_position() -> Vector3:
	return presentation.display_position if is_instance_valid(presentation) and presentation.initialized else global_position
