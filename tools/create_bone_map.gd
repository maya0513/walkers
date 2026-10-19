extends SceneTree

func _initialize() -> void:
	var map := BoneMap.new()
	map.profile = SkeletonProfileHumanoid.new()
	for i in range(map.profile.bone_size):
		var name: StringName = map.profile.get_bone_name(i)
		var mapped := name
		if String(name).ends_with("ThumbMetacarpal"):
			mapped = StringName(String(name).replace("Metacarpal", "Proximal"))
		elif String(name).ends_with("ThumbProximal"):
			mapped = StringName(String(name).replace("Proximal", "Intermediate"))
		if name in [&"Jaw", &"LeftEye", &"RightEye"]:
			continue
		map.set_skeleton_bone_name(name, mapped)
	var result := ResourceSaver.save(map,"res://addons/walkers/humanoid_bone_map.tres")
	var model: Node = load("res://addons/walkers/assets/humanoid.glb").instantiate()
	var skeleton: Skeleton3D = model.find_child("Skeleton3D", true, false)
	if skeleton == null:
		for child: Node in model.get_children():
			if child is Skeleton3D:
				skeleton = child
	assert(skeleton != null)
	print("Skeleton path: ", model.get_path_to(skeleton))
	var import_settings := ConfigFile.new()
	import_settings.load("res://addons/walkers/assets/humanoid.glb.import")
	import_settings.set_value("params", "animation/fps", 60)
	import_settings.set_value("params", "animation/import_rest_as_RESET", true)
	import_settings.set_value("params", "_subresources", {"nodes": {
		"PATH:" + String(model.get_path_to(skeleton)): {"retarget/bone_map": map,
		"retarget/bone_renamer/rename_bones": false}}})
	import_settings.save("res://addons/walkers/assets/humanoid.glb.import")
	model.free()
	print("BONEMAP ", result)
	quit(0 if result == OK else 1)
