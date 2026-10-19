class_name LocomotionAnimator
extends Node
## Manual physics evaluation. Both gaits have a one-second normalized timeline.

signal state_changed(previous: StringName, current: StringName)

var tree: AnimationTree
var player: AnimationPlayer
var playback: AnimationNodeStateMachinePlayback
var config: LocomotionConfig
var metadata: Dictionary
var state: StringName = &"Idle"
var state_time: float = 0.0
var phase: float = 0.0
var blend: float = 0.0
var contacts: Vector2 = Vector2.ONE
var support_regions: Array[String] = ["sole", "sole"]
# Schema 3 offsets are in rest-skeleton space, relative to each ankle.
var support_offsets: Array[Vector3] = []
var next_left: bool = true
var forced_turn: bool = false
var gaits: Array[Dictionary] = []
var stride_scale: float = 1.0

func initialize(animation_player: AnimationPlayer, animation_tree: AnimationTree, settings: LocomotionConfig) -> void:
	player = animation_player
	tree = animation_tree
	config = settings
	gaits = config.gait_points()
	metadata = JSON.parse_string(FileAccess.get_file_as_string(config.motion_metadata))
	for gait_point: Dictionary in gaits:
		assert(metadata.clips.has(String(gait_point.animation)), "Missing gait metadata: " + String(gait_point.animation))
		assert(float(gait_point.stride) > 0.0, "Stride length must be positive")
	var library := AnimationLibrary.new()
	for clip: String in metadata.clips:
		for imported: StringName in player.get_animation_list():
			if String(imported) == clip or String(imported).ends_with("/" + clip):
				var animation: Animation = player.get_animation(imported).duplicate(true)
				animation.loop_mode = Animation.LOOP_LINEAR if metadata.clips[clip].loop else Animation.LOOP_NONE
				library.add_animation(clip, animation)
				break
		assert(library.has_animation(clip), "Missing locomotion animation: " + clip)
	for old: StringName in player.get_animation_library_list():
		player.remove_animation_library(old)
	player.add_animation_library(&"", library)
	player.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	tree.anim_player = tree.get_path_to(player)
	tree.root_node = tree.get_path_to(player.get_node(player.root_node))
	tree.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	tree.deterministic = true
	var machine := AnimationNodeStateMachine.new()
	for clip: String in metadata.clips:
		if clip in ["Walk", "Jog"]:
			continue
		var node := AnimationNodeAnimation.new()
		node.animation = clip
		machine.add_node(clip, node)
	var space := AnimationNodeBlendSpace1D.new()
	space.min_space = 0.0
	space.max_space = float(gaits[-1].speed)
	space.sync_mode = AnimationNodeBlendSpace1D.SYNC_MODE_CYCLIC_CONSTANT
	space.cyclic_length = 1.0
	for point: Dictionary in gaits:
		var clip_node := AnimationNodeAnimation.new()
		clip_node.animation = point.animation
		clip_node.use_custom_timeline = true
		clip_node.timeline_length = 1.0
		clip_node.stretch_time_scale = true
		clip_node.loop_mode = Animation.LOOP_LINEAR
		space.add_blend_point(clip_node, point.speed, -1, point.animation)
	var move := AnimationNodeBlendTree.new()
	move.add_node(&"Gait", space)
	move.add_node(&"Phase", AnimationNodeTimeSeek.new())
	move.connect_node(&"Phase", 0, &"Gait")
	move.connect_node(&"output", 0, &"Phase")
	machine.add_node(&"Move", move)
	var states := machine.get_node_list()
	for a: StringName in states:
		for b: StringName in states:
			if a == b or a in [&"Start", &"End"] or b in [&"Start", &"End"]:
				continue
			var transition := AnimationNodeStateMachineTransition.new()
			transition.xfade_time = 0.14
			transition.reset = true
			machine.add_transition(a, b, transition)
	tree.tree_root = machine
	tree.active = true
	playback = tree.get("parameters/playback")
	playback.start(&"Idle")
	tree.advance(0)

func change(next_state: StringName, enter_phase: float = 0.0) -> void:
	if state == next_state:
		return
	var previous := state
	state = next_state
	state_time = 0.0
	playback.travel(state)
	if state == &"Move":
		phase = enter_phase
		tree.set("parameters/Move/Phase/seek_request", phase)
	state_changed.emit(previous, state)

func begin_turn(angle: float) -> void:
	forced_turn = true
	var magnitude := "180" if absf(angle) > deg_to_rad(135) else "90"
	change(StringName("Turn" + magnitude + ("L" if angle > 0 else "R")))

func turn_duration() -> float:
	return float(metadata.clips[String(state)].duration) if String(state).begins_with("Turn") else 0.0

func tick(delta: float, speed: float, intent_speed: float) -> void:
	var moving := intent_speed > 0.04
	var gait_mix := _gait_mix(intent_speed)
	var gait: String = String(gait_mix.b.transition if gait_mix.weight > .5 else gait_mix.a.transition)
	var stop_mix := _gait_mix(speed)
	var stop_prefix: String = String(stop_mix.b.transition if stop_mix.weight > .5 else stop_mix.a.transition)
	var side := "L" if next_left else "R"
	if String(state).begins_with("Turn"):
		forced_turn = false
		if moving:
			change(StringName("Start" + gait + side))
		elif state_time >= turn_duration():
			change(&"Idle")
	elif state == &"Idle":
		if moving:
			change(StringName("Start" + gait + side))
			next_left = not next_left
	elif String(state).begins_with("Start"):
		if not moving:
			change(StringName("Stop" + stop_prefix + side))
		elif state_time >= float(metadata.clips[String(state)].duration) - 0.02:
			change(&"Move", float(metadata.clips[String(state)].exit_phase))
	elif state == &"Move":
		if not moving:
			change(StringName("Stop" + stop_prefix + ("L" if contacts.x > contacts.y else "R")))
	elif String(state).begins_with("Stop"):
		if moving:
			change(StringName("Start" + gait + side))
		elif state_time >= float(metadata.clips[String(state)].duration) - 0.02:
			change(&"Idle")
	var rate := 1.0
	if state == &"Move":
		blend = clampf((speed - config.walk_speed) / (config.jog_speed - config.walk_speed), 0.0, 1.0)
		tree.set("parameters/Move/Gait/blend_position", speed)
		var mix := _gait_mix(speed)
		var stride := lerpf(float(mix.a.stride), float(mix.b.stride), float(mix.weight))
		rate = speed / maxf(stride * stride_scale, 0.01)
		phase = fposmod(phase + delta * rate, 1.0)
		# The distance phase is the single clock, including during crossfades.
		tree.set("parameters/Move/Phase/seek_request", phase)
	state_time += delta * rate
	tree.advance(delta * rate)
	if state == &"Move":
		var mix := _gait_mix(speed)
		contacts = _sample_contacts(String(mix.a.animation), phase).lerp(_sample_contacts(String(mix.b.animation), phase), float(mix.weight))
	else:
		contacts = _sample_contacts(String(state), state_time / maxf(float(metadata.clips[String(state)].duration), 0.001))

	_update_support_regions(speed)
	_update_support_offsets(speed)

func _update_support_regions(speed: float) -> void:
	if state == &"Move":
		var mix := _gait_mix(speed)
		var point: Dictionary = mix.b if float(mix.weight) > .5 else mix.a
		support_regions = _sample_regions(String(point.animation), phase)
	else:
		support_regions = _sample_regions(String(state), state_time / maxf(float(metadata.clips[String(state)].duration), .001))

func _sample_contacts(clip: String, normalized: float) -> Vector2:
	var samples: Array = metadata.clips[clip].contacts
	var index := clampf(normalized, 0.0, 1.0) * (samples.size() - 1)
	var a := mini(int(index), samples.size() - 1)
	var b := mini(a + 1, samples.size() - 1)
	return Vector2(samples[a][0], samples[a][1]).lerp(Vector2(samples[b][0], samples[b][1]), index - a)

func _gait_mix(speed: float) -> Dictionary:
	for i in range(1, gaits.size()):
		if speed <= float(gaits[i].speed):
			var weight := clampf((speed-float(gaits[i-1].speed))/maxf(float(gaits[i].speed)-float(gaits[i-1].speed),.01),0,1)
			return {"a":gaits[i-1],"b":gaits[i],"weight":weight}
	return {"a":gaits[-1],"b":gaits[-1],"weight":0.0}

func _sample_regions(clip: String, normalized: float) -> Array[String]:
	var info: Dictionary = metadata.clips[clip]
	if not info.has("support_regions"):
		return ["sole", "sole"]
	var samples: Array = info.support_regions
	var sample: Array = samples[clampi(int(clampf(normalized, 0, 1) * (samples.size()-1)), 0, samples.size()-1)]
	return [String(sample[0]), String(sample[1])]

func _update_support_offsets(speed: float) -> void:
	if state == &"Move":
		var mix := _gait_mix(speed)
		var a := _sample_support_offsets(String(mix.a.animation), phase)
		var b := _sample_support_offsets(String(mix.b.animation), phase)
		if a.size() == 2 and b.size() == 2:
			support_offsets = [a[0].lerp(b[0], float(mix.weight)), a[1].lerp(b[1], float(mix.weight))]
		else:
			support_offsets = []
	else:
		support_offsets = _sample_support_offsets(String(state), state_time / maxf(float(metadata.clips[String(state)].duration), .001))

func _sample_support_offsets(clip: String, normalized: float) -> Array[Vector3]:
	var samples: Array = metadata.clips[clip].get("support_offsets", [])
	if samples.is_empty():
		return []
	var index := clampf(normalized, 0, 1) * (samples.size() - 1)
	var a := mini(int(index), samples.size() - 1)
	var b := mini(a + 1, samples.size() - 1)
	var values: Array[Vector3] = []
	for side in range(2):
		var left: Array = samples[a][side]
		var right: Array = samples[b][side]
		values.append(Vector3(left[0],left[1],left[2]).lerp(Vector3(right[0],right[1],right[2]), index - a))
	return values
