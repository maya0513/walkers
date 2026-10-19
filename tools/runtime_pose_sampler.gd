extends Node3D
## Physics-order adapter for the headless measurement SceneTree script.
var owner_recorder: SceneTree

func _physics_process(delta: float) -> void:
	owner_recorder.tick(delta)
