extends RefCounted
## Independent check: read vertices, weights and inverse binds from the imported
## GLB surface, rather than using the sparse sole samples that drive grounding.

var points: Array[Dictionary] = []
var binds: Array[Dictionary] = []
var worst: Dictionary = {}
var probe := SphereShape3D.new()

func setup(mesh_instance: MeshInstance3D, skeleton: Skeleton3D) -> void:
	probe.radius = .0001
	var skin := mesh_instance.skin
	assert(skin != null)
	for i in range(skin.get_bind_count()):
		var bone := skeleton.find_bone(skin.get_bind_name(i))
		if bone < 0:
			bone = skin.get_bind_bone(i)
		assert(bone >= 0)
		binds.append({"index":bone,"inverse":skin.get_bind_pose(i),"name":skeleton.get_bone_name(bone)})
	for surface in range(mesh_instance.mesh.get_surface_count()):
		var arrays := mesh_instance.mesh.surface_get_arrays(surface)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var bones: PackedInt32Array = arrays[Mesh.ARRAY_BONES]
		var weights: PackedFloat32Array = arrays[Mesh.ARRAY_WEIGHTS]
		var influence_count := weights.size()/vertices.size()
		for i in range(vertices.size()):
			if vertices[i].y > .13:
				continue
			var influences: Array[Dictionary] = []
			for j in range(influence_count):
				var index := i*influence_count+j
				if weights[index] > .00001:
					influences.append({"bind":bones[index],"weight":weights[index]})
			points.append({"vertex":vertices[i],"influences":influences})

func penetration(poses: Array, world: Transform3D, grounding: HumanoidGrounding) -> float:
	var maximum := 0.0
	worst = {}
	for point: Dictionary in points:
		var skinned := Vector3.ZERO
		for influence: Dictionary in point.influences:
			var bind: Dictionary = binds[influence.bind]
			skinned += (poses[bind.index] * (bind.inverse * point.vertex)) * float(influence.weight)
		var position_value := world * skinned
		var hit := grounding.ray_floor(position_value,.35,.35)
		if not hit.is_empty():
			var depth: float = hit.position.y-position_value.y
			if depth > maximum:
				maximum = depth
				var influences: Array = []
				for influence: Dictionary in point.influences:
					influences.append([String(binds[influence.bind].name),influence.weight])
				worst = {"depth":depth,"rest":[point.vertex.x,point.vertex.y,point.vertex.z],
					"world":[position_value.x,position_value.y,position_value.z],"floor":hit.position.y,"influences":influences}
		var from := Vector3(world.origin.x,position_value.y,world.origin.z)
		var query := PhysicsRayQueryParameters3D.create(from,position_value,1,[grounding.motor.get_rid()])
		var wall := grounding.motor.get_world_3d().direct_space_state.intersect_ray(query)
		if not wall.is_empty() and absf(wall.normal.y) < .5 and _inside_collider(position_value, wall.collider_id, grounding):
			var wall_depth: float = (position_value-wall.position).length()
			if wall_depth > maximum:
				maximum = wall_depth
				worst = {"depth":wall_depth,"kind":"wall","world":[position_value.x,position_value.y,position_value.z],
					"hit":[wall.position.x,wall.position.y,wall.position.z],"normal":[wall.normal.x,wall.normal.y,wall.normal.z]}
	return maximum

func _inside_collider(position_value: Vector3, collider_id: int, grounding: HumanoidGrounding) -> bool:
	# A horizontal ray can cross a ramp's end face then leave through its
	# walkable top before reaching an airborne/trailing foot. Require actual
	# overlap at the material point before reporting wall penetration.
	var query := PhysicsShapeQueryParameters3D.new()
	query.shape = probe
	query.transform = Transform3D(Basis.IDENTITY, position_value)
	query.collision_mask = 1
	query.exclude = [grounding.motor.get_rid()]
	for hit: Dictionary in grounding.motor.get_world_3d().direct_space_state.intersect_shape(query, 8):
		if int(hit.collider_id) == collider_id:
			return true
	return false
