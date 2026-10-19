class_name LocomotionConfig
extends Resource
## Metres, seconds and radians. One resource per movement style.

@export_group("Movement")
@export var walk_speed: float = 1.4
@export var jog_speed: float = 2.8
@export var acceleration: float = 3.5
@export var braking: float = 4.5
@export var turn_speed: float = 8.5
@export var hard_turn_angle: float = 125.0
@export var max_slope_degrees: float = 25.0
@export var step_height: float = 0.15
@export var floor_snap: float = 0.23
@export_range(0.5, 1.0) var downhill_stride_scale: float = 0.7

@export_group("Grounding")
@export var foot_lock: bool = true
@export var pelvis_limit: float = 0.16
@export var foot_correction_limit: float = 0.26
@export var sole_height: float = 0.075
@export var grounding_speed: float = 16.0
@export var character_height: float = 1.78
@export var use_library_sole_height: bool = true
@export_file("*.json") var sole_samples_file: String = "res://addons/walkers/assets/sole_samples.json"

@export_group("Motion library")
@export var motion_metadata: String = "res://addons/walkers/assets/motions.json"
@export var walk_animation: StringName = &"Walk"
@export var jog_animation: StringName = &"Jog"
@export var walk_stride_length: float = 1.47
@export var jog_stride_length: float = 1.96
@export var extra_gaits: Array[LocomotionGait] = []

func max_speed() -> float:
	var result := jog_speed
	for gait: LocomotionGait in extra_gaits:
		result = maxf(result, gait.speed)
	return result

func gait_points() -> Array[Dictionary]:
	var result: Array[Dictionary] = [
		{"animation":walk_animation,"speed":walk_speed,"stride":walk_stride_length,"transition":"Walk"},
		{"animation":jog_animation,"speed":jog_speed,"stride":jog_stride_length,"transition":"Jog"}]
	for gait: LocomotionGait in extra_gaits:
		result.append({"animation":gait.animation,"speed":gait.speed,"stride":gait.stride_length,"transition":gait.transition_prefix})
	result.sort_custom(func(a: Dictionary,b: Dictionary) -> bool: return a.speed < b.speed)
	return result

