extends SceneTree

func _initialize() -> void:
	var runner := Node3D.new()
	runner.name = "RuntimeValidation"
	runner.set_script(load("res://tests/scenarios.gd"))
	root.add_child.call_deferred(runner)

