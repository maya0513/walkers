"""Blender 5.2: CC0 MakeHuman mesh + Quaternius motion, editable controls, GLB.

blender -b -noaudio --python tools/build_character.py
All motion samples are in metres, 60 Hz. Blender forward is -Y, Godot +Z.
"""
import bpy
import gzip
import json
import math
import os
import sys
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0,str(Path(__file__).parent))
from foot_geometry import samples as make_sole_samples

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "source/third_party"
OUT = ROOT / "addons/walkers/assets"
OUT.mkdir(parents=True, exist_ok=True)
FPS = 60
HEIGHT = 1.78
TAU = math.tau
Z = Vector((0, 0, 1))

NAMES = {"Root": "Root", "pelvis": "Hips", "spine_01": "Spine",
         "spine_02": "Chest", "spine_03": "UpperChest", "neck_01": "Neck", "head": "Head"}
SOURCE_NAMES = {"Root": "root", "Hips": "DEF-hips", "Spine": "DEF-spine.001",
                "Chest": "DEF-spine.002", "UpperChest": "DEF-spine.003",
                "Neck": "DEF-neck", "Head": "DEF-head"}
for side, label in [("l", "Left"), ("r", "Right")]:
    suffix = side.upper()
    for a, b, c in [("thigh", "UpperLeg", "thigh"), ("calf", "LowerLeg", "shin"),
                    ("foot", "Foot", "foot"), ("ball", "Toes", "toe"),
                    ("clavicle", "Shoulder", "shoulder"), ("upperarm", "UpperArm", "upper_arm"),
                    ("lowerarm", "LowerArm", "forearm"), ("hand", "Hand", "hand")]:
        NAMES[a + "_" + side] = label + b
        SOURCE_NAMES[label + b] = f"DEF-{c}.{suffix}"
    for finger in ["thumb", "index", "middle", "ring", "pinky"]:
        for segment, part in [(1, "Proximal"), (2, "Intermediate"), (3, "Distal")]:
            title = "Little" if finger == "pinky" else finger.title()
            name = label + title + part
            NAMES[f"{finger}_{segment:02d}_{side}"] = name
            stem = "thumb" if finger == "thumb" else "f_" + finger
            SOURCE_NAMES[name] = f"DEF-{stem}.{segment:02d}.{suffix}"


def log(*items):
    print("WALKERS:", *items, flush=True)


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def world_rotate(poses, bone, rotation):
    origin = poses[bone].translation.copy()
    transform = Matrix.Translation(origin) @ rotation.to_matrix().to_4x4() @ Matrix.Translation(-origin)
    for child in [bone] + DESC[bone]:
        poses[child] = transform @ poses[child]


def aim(poses, bone, child, point):
    current = poses[child].translation - poses[bone].translation
    desired = Vector(point) - poses[bone].translation
    if current.length > 1e-6 and desired.length > 1e-6:
        world_rotate(poses, bone, current.rotation_difference(desired))


def solve_leg(poses, side, target, foot_rotation=None):
    upper, lower, foot = [side + x for x in ["UpperLeg", "LowerLeg", "Foot"]]
    h, k, a = [poses[x].translation.copy() for x in [upper, lower, foot]]
    l1, l2 = (k-h).length, (a-k).length
    ray = Vector(target)-h
    distance = min(max(ray.length, abs(l1-l2)+0.005), l1+l2-0.004)
    direction = ray.normalized()
    pole = Vector((0, -1, 0))
    pole -= direction * pole.dot(direction)
    pole.normalize()
    along = (distance*distance + l1*l1-l2*l2)/(2*distance)
    bend = math.sqrt(max(0, l1*l1-along*along))
    knee = h + direction*along + pole*bend
    aim(poses, upper, lower, knee)
    aim(poses, lower, foot, h+direction*distance)
    if foot_rotation is not None:
        rotation = foot_rotation @ poses[foot].to_quaternion().inverted()
        world_rotate(poses, foot, rotation)


def read_makehuman():
    verts, uvs, faces, uv_faces, groups = [], [], [], [], {}
    group = ""
    for line in (SRC / "makehuman/base.obj").read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            x, y, z = map(float, parts[1:4])
            verts.append(Vector((x, -z, y))*0.1)
        elif parts[0] == "vt":
            uvs.append(tuple(map(float, parts[1:3])))
        elif parts[0] == "g":
            group = parts[1]
        elif parts[0] == "f":
            indices = [int(p.split("/")[0])-1 for p in parts[1:]]
            groups.setdefault(group, set()).update(indices)
            if group == "body":
                faces.append(indices)
                uv_faces.append([int(p.split("/")[1])-1 if "/" in p and p.split("/")[1] else 0 for p in parts[1:]])
    # Apply the official CC0 male macro stack to ALL vertices, including rig helpers.
    phenotype = [("african-male-young.target.gz", 1/3),
                 ("asian-male-young.target.gz", 1/3),
                 ("caucasian-male-young.target.gz", 1/3),
                 ("universal-male-young-averagemuscle-averageweight.target.gz", 1.0)]
    for filename, weight in phenotype:
        for line in gzip.open(SRC/"makehuman"/filename, "rt"):
            fields = line.split()
            if not fields or fields[0].startswith("#"): continue
            i, x, y, z = int(fields[0]), *map(float, fields[1:4])
            verts[i] += Vector((x, -z, y)) * (0.1*weight)
    used = sorted(groups["body"])
    remap = {old: new for new, old in enumerate(used)}
    mesh = bpy.data.meshes.new("MakeHuman_CC0_Surface")
    mesh.from_pydata([verts[v] for v in used], [], [[remap[i] for i in f] for f in faces])
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon, source in zip(mesh.polygons, uv_faces):
        for loop_index, uv_index in zip(polygon.loop_indices, source):
            uv.data[loop_index].uv = uvs[uv_index]
        polygon.use_smooth = True
    body = bpy.data.objects.new("Humanoid_CC0", mesh)
    bpy.context.collection.objects.link(body)
    material = bpy.data.materials.new("Porcelain • neutral study")
    material.diffuse_color = (0.48, 0.48, 0.48, 1)
    material.use_nodes = True
    shader = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if shader is None:
        shader = material.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
        material.node_tree.links.new(shader.outputs[0], output.inputs[0])
    shader.inputs["Base Color"].default_value = (0.48, 0.48, 0.48, 1)
    shader.inputs["Roughness"].default_value = 0.80
    body.data.materials.append(material)
    rigdata = json.loads((SRC / "makehuman/rig.game_engine.json").read_text())
    arm = bpy.data.armatures.new("Humanoid_Deform")
    rig = bpy.data.objects.new("Humanoid", arm)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    def point(spec):
        if spec.get("cube_name") in groups:
            indices = groups[spec["cube_name"]]
            return sum((verts[v] for v in indices), Vector()) / len(indices)
        if spec.get("vertex_indices"):
            indices = spec["vertex_indices"]
            return sum((verts[v] for v in indices), Vector())/len(indices)
        return Vector(spec["default_position"])

    for original, data in rigdata.items():
        bone = arm.edit_bones.new(NAMES[original])
        bone.head, bone.tail = point(data["head"]), point(data["tail"])
        bone.roll = data.get("roll", 0)
        bone.use_deform = original != "Root"
        if original == "Root":
            bone.tail = bone.head + Vector((0, 0, 0.12))
    for original, data in rigdata.items():
        if data["parent"]:
            arm.edit_bones[NAMES[original]].parent = arm.edit_bones[NAMES[data["parent"]]]
    bpy.ops.object.mode_set(mode="OBJECT")
    weights = json.loads((SRC / "makehuman/weights.game_engine.json").read_text())["weights"]
    vertex_weights = [[] for _ in used]
    for name, entries in weights.items():
        if name not in NAMES:
            continue
        for old, weight in entries:
            if old in remap and weight > 0.00001:
                vertex_weights[remap[old]].append((NAMES[name], weight))
    # Four influences, normalized once: export and Blender use the same skinning.
    for i, influences in enumerate(vertex_weights):
        influences.sort(key=lambda pair: pair[1], reverse=True)
        selected = influences[:4]
        total = sum(weight for _, weight in selected)
        vertex_weights[i] = [(name, weight/total) for name, weight in selected] if total else [("Hips", 1)]
    for name in NAMES.values():
        body.vertex_groups.new(name=name)
    for i, influences in enumerate(vertex_weights):
        for name, weight in influences:
            body.vertex_groups[name].add([i], weight, "REPLACE")
    mod = body.modifiers.new("Deformation", "ARMATURE")
    mod.object = rig
    body.parent = rig
    return rig, body, vertex_weights


def make_t_pose(rig, body, vertex_weights):
    global DESC
    DESC = {b.name: [c.name for c in b.children_recursive] for b in rig.data.bones}
    rests = {b.name: b.matrix_local.copy() for b in rig.data.bones}
    poses = {n: m.copy() for n, m in rests.items()}
    for side, sign in [("Left", 1), ("Right", -1)]:
        for upper, lower in [("UpperArm", "LowerArm"), ("LowerArm", "Hand")]:
            n, c = side+upper, side+lower
            direction = (poses[c].translation-poses[n].translation).normalized()
            world_rotate(poses, n, direction.rotation_difference(Vector((sign, 0, 0))))
        for upper, lower in [("UpperLeg", "LowerLeg"), ("LowerLeg", "Foot")]:
            n, c = side+upper, side+lower
            direction = (poses[c].translation-poses[n].translation).normalized()
            world_rotate(poses, n, direction.rotation_difference(Vector((0, 0, -1))))
    inverse = {n: m.inverted() for n, m in rests.items()}
    for v, influences in zip(body.data.vertices, vertex_weights):
        p = v.co.copy()
        v.co = sum(((poses[n] @ inverse[n] @ p)*weight for n, weight in influences), Vector())
    floor = min(v.co.z for v in body.data.vertices)
    scale = HEIGHT/(max(v.co.z for v in body.data.vertices)-floor)
    for vertex in body.data.vertices:
        vertex.co.z -= floor
        vertex.co *= scale
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for bone in rig.data.edit_bones:
        old_length = bone.length
        m = poses[bone.name]
        bone.head = (m.translation-Vector((0, 0, floor)))*scale
        bone.tail = ((m @ Vector((0, old_length, 0)))-Vector((0, 0, floor)))*scale
        bone.align_roll(m.to_3x3() @ Vector((0, 0, 1)))
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


def source_sample(source_rig, source_actions, source_name, phase):
    action = source_actions[source_name]
    source_rig.animation_data.action = action
    start, end = action.frame_range
    frame = start + (end-start) * phase
    bpy.context.scene.frame_set(int(frame), subframe=frame-int(frame))
    return {b.name: b.matrix.copy() for b in source_rig.pose.bones}


def create_controls(rig):
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for side in ["Left", "Right"]:
        foot = rig.data.edit_bones[side+"Foot"]
        b = rig.data.edit_bones.new("CTRL_Foot_"+side)
        b.head, b.tail = foot.head, foot.head+Vector((0, -.22, 0))
        b.use_deform = False
        pole = rig.data.edit_bones.new("CTRL_Knee_"+side)
        pole.head = rig.data.edit_bones[side+"LowerLeg"].head+Vector((0, -.65, 0))
        pole.tail = pole.head+Vector((0, 0, .10))
        pole.use_deform = False
    bpy.ops.object.mode_set(mode="POSE")
    for side in ["Left", "Right"]:
        shin = rig.pose.bones[side+"LowerLeg"]
        constraint = shin.constraints.new("IK")
        constraint.name = "Editing IK • enable with foot_ik property"
        constraint.target = rig
        constraint.subtarget = "CTRL_Foot_"+side
        constraint.pole_target = rig
        constraint.pole_subtarget = "CTRL_Knee_"+side
        constraint.chain_count = 2
        constraint.use_stretch = False
        constraint.influence = 0
        rig["foot_ik_"+side] = 0.0
        rig.id_properties_ui("foot_ik_"+side).update(min=0.0, max=1.0,
            description="0: baked FK playback; 1: editable foot IK. Duplicate an Action before editing.")
        driver = constraint.driver_add("influence").driver
        driver.expression = "weight"
        variable = driver.variables.new()
        variable.name = "weight"
        variable.targets[0].id = rig
        variable.targets[0].data_path = '["foot_ik_'+side+'"]'
        rotation = rig.pose.bones[side+"Foot"].constraints.new("COPY_ROTATION")
        rotation.name = "Editing IK • foot orientation"
        rotation.target = rig
        rotation.subtarget = "CTRL_Foot_"+side
        rotation.target_space = "POSE"
        rotation.owner_space = "POSE"
        rotation.mix_mode = "REPLACE"
        rotation.influence = 0.0
        driver = rotation.driver_add("influence").driver
        driver.expression = "weight"
        variable = driver.variables.new()
        variable.name = "weight"
        variable.targets[0].id = rig
        variable.targets[0].data_path = '["foot_ik_'+side+'"]'
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.show_in_front = True
    controls = rig.data.collections.new("Foot IK controls")
    deform = rig.data.collections.new("Deformation • baked FK")
    for bone in rig.data.bones:
        (controls if bone.name.startswith("CTRL_") else deform).assign(bone)


def main():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    # Import the freely distributed glTF, not the paid Blender source.
    bpy.ops.import_scene.gltf(filepath=str(SRC/"quaternius/AnimationLibrary_Godot_Standard.gltf"))
    src_rig = next(obj for obj in scene.objects if obj.type == "ARMATURE")
    source_actions = {a.name: a for a in bpy.data.actions}
    log("Source rig", src_rig.name, "bones", len(src_rig.data.bones), "actions", list(source_actions))
    source_rest = {b.name: b.matrix_local.copy() for b in src_rig.data.bones}
    src_rig.animation_data_create()
    rig, body, vertex_weights = read_makehuman()
    make_t_pose(rig, body, vertex_weights)
    bones = sorted(rig.data.bones, key=lambda b: len(b.parent_recursive))
    rest = {b.name: b.matrix_local.copy() for b in bones}
    parents = {b.name: b.parent.name if b.parent else None for b in bones}
    local = {b.name: (rest[parents[b.name]].inverted() @ rest[b.name] if parents[b.name] else rest[b.name]) for b in bones}
    target_hip = rest["Hips"].translation.copy()
    src_hip = source_rest["DEF-hips"].translation.copy()
    hip_scale = target_hip.z/max(src_hip.z, .1)
    foot_rest = {s: rest[s+"Foot"].to_quaternion() for s in ["Left", "Right"]}
    ankle_z = sum(rest[s+"Foot"].translation.z for s in ["Left", "Right"])/2
    sole_vertices = {s: [v.co.copy() - rest[s+"Foot"].translation for v in body.data.vertices
                         if v.co.z < .12 and (v.co.x > 0 if s == "Left" else v.co.x < 0)]
                     for s in ["Left", "Right"]}
    sole_samples = make_sole_samples([v.co.copy() for v in body.data.vertices],vertex_weights)
    (OUT/"sole_samples.json").write_text(json.dumps(sole_samples, indent=2)+"\n")
    # Bone ancestry, not Blender's arbitrary data order, drives retargeting.
    global DESC
    DESC = {b.name: [c.name for c in b.children_recursive] for b in bones}

    def retarget(source_name, phase):
        sampled = source_sample(src_rig, source_actions, source_name, phase)
        poses = {}
        for b in bones:
            n = b.name
            if n == "Root":
                poses[n] = rest[n].copy()
                continue
            source = SOURCE_NAMES.get(n)
            rotation = (sampled[source].to_quaternion() @ source_rest[source].to_quaternion().inverted()
                        @ rest[n].to_quaternion()) if source in sampled else rest[n].to_quaternion()
            position = poses[parents[n]] @ local[n].translation if parents[n] else rest[n].translation
            if n == "Hips":
                delta = (sampled["DEF-hips"].translation-src_hip)*hip_scale
                # Keep the original torso sway; remove long-range displacement.
                delta.x = max(-.045, min(.045, delta.x))
                delta.y = max(-.055, min(.055, delta.y))
                delta.z = max(-.09, min(.065, delta.z))
                position = target_hip+delta
            poses[n] = Matrix.LocRotScale(position, rotation, Vector((1, 1, 1)))
        return poses

    from motion_authoring import Author, DURATIONS
    author = Author(rest, body, solve_leg, aim, world_rotate)
    gait, standing = author.gait, author.standing

    def blend_pose(a, b, weight):
        return {n: Matrix.LocRotScale(a[n].translation.lerp(b[n].translation, weight),
                      a[n].to_quaternion().slerp(b[n].to_quaternion(), weight), Vector((1, 1, 1))) for n in a}

    clips = [("Idle", 3.2, True, "idle", "", 0),
             ("Walk", .9, True, "gait", "Walk", 0), ("Jog", .7, True, "gait", "Jog", 0)]
    for g in ["Walk", "Jog"]:
        for side, phase in [("L", 0), ("R", .5)]:
            clips += [(f"Start{g}{side}", .55 if g=="Walk" else .45, False, "start", g, phase),
                      (f"Stop{g}{side}", .48 if g=="Walk" else .60, False, "stop", g, phase)]
    for angle, duration in [(90, .30), (180, .45)]:
        for side, sign in [("L", 1), ("R", -1)]:
            clips.append((f"Turn{angle}{side}", duration, False, "turn", "", math.radians(angle)*sign))
    rig.animation_data_create()
    metadata = {"fps": FPS, "height": HEIGHT, "forward": "+Z", "sole_height": ankle_z,
                "bones": {n: list(rest[n].translation) for n in rest}, "clips": {},
                "schema_version": 2, "support_points": author.support_metadata(),
                "phenotype": {"gender":"male", "age":"adult", "muscle":"average", "weight":"average", "height_m":HEIGHT}}
    sampled_motion = {}
    for name, duration, loop, kind, g, parameter in clips:
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        rig.animation_data.action = action
        count = round(duration*FPS)
        contact_samples = []
        support_samples = []
        frames = []
        previous_q = {}
        for f in range(count+1):
            u = f/count
            if kind == "idle":
                poses, contacts = standing(u), [1, 1]
            elif kind == "gait":
                poses, contacts = gait(g, u % 1)
            elif kind in ["start", "stop"]:
                cycle = DURATIONS[g]
                phase = (parameter+u*duration/cycle) % 1
                moving, contacts = gait(g, phase)
                weight = smooth(u) if kind == "start" else 1-smooth(u)
                poses = blend_pose(standing(0), moving, weight)
                contacts = [1-weight+weight*c for c in contacts]
            else:
                poses = standing(0)
                # Root yaw is supplied by the motor. These are counter-rotated
                # planted-foot poses, so world-space feet do not swivel in place.
                yaw = parameter*smooth(u)
                left_move = 0.12 < u < .50
                right_move = .52 < u < .90
                contacts = [0 if left_move else 1, 0 if right_move else 1]
                for side, sign, begin, end in [("Left", 1, .12, .50), ("Right", -1, .52, .90)]:
                    progress = smooth((u-begin)/(end-begin))
                    foot_yaw = parameter*progress-yaw
                    old = author.idle[side+"Foot"].translation.copy()
                    position = Quaternion(Z, foot_yaw) @ old
                    if begin < u < end:
                        position.z += .075*math.sin(math.pi*(u-begin)/(end-begin))
                    solve_leg(poses, side, position, Quaternion(Z, foot_yaw) @ foot_rest[side])
                # Head and chest lead the pelvis by a small bounded amount.
                world_rotate(poses, "Chest", Quaternion(Z, .08*math.sin(math.pi*u)*math.copysign(1, parameter)))
            for b in bones:
                n = b.name
                parent_pose = poses[parents[n]] if parents[n] else Matrix.Identity(4)
                basis = local[n].inverted() @ parent_pose.inverted() @ poses[n]
                pb = rig.pose.bones[n]
                q = basis.to_quaternion().normalized()
                if n in previous_q and q.dot(previous_q[n]) < 0:
                    q.negate()
                previous_q[n] = q.copy()
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = q
                pb.location = basis.translation if n == "Hips" else Vector((0, 0, 0))
                pb.scale = (1, 1, 1)
                pb.keyframe_insert("rotation_quaternion", frame=f)
                if n == "Hips":
                    pb.keyframe_insert("location", frame=f)
            contact_samples.append(contacts)
            support_phase = u % 1 if kind == "gait" else (parameter+u*duration/DURATIONS[g]) % 1 if kind in ["start","stop"] else 0
            regions = author.support(g if kind in ["gait","start","stop"] else "", support_phase)
            support_samples.append(regions)
            frames.append({"positions": {n: list(m.translation) for n,m in poses.items()},
                           "hips": list(poses["Hips"].translation)})
        # Persist the authored contact curves as ordinary Action channels too.
        rig["contact_left"], rig["contact_right"] = 1.0, 1.0
        rig["preview_heading"] = 0.0
        for f, values in enumerate(contact_samples):
            for key, value in zip(["contact_left", "contact_right"], values):
                rig[key] = value
                rig.keyframe_insert(data_path='["'+key+'"]', frame=f)
            rig["preview_heading"] = parameter*smooth(f/count) if kind == "turn" else 0.0
            rig.keyframe_insert(data_path='["preview_heading"]', frame=f)
        action["duration_seconds"] = duration
        action["loop"] = loop
        action["source"] = "Walkers authored relaxed locomotion; Quaternius CC0 retained as reference"
        metadata["clips"][name] = {"duration": duration, "loop": loop, "frames": count,
            "type": kind, "contacts": contact_samples, "support_regions":support_samples, "nominal_speed": 1.4 if name=="Walk" else 2.8 if name=="Jog" else 0,
            "exit_phase": (parameter+duration/DURATIONS[g]) % 1 if kind=="start" else 0,
            "turn_radians": parameter if kind=="turn" else 0}
        sampled_motion[name] = frames
        log("Baked", name, count+1, "samples")
    # Source armature stays in the editable file as a hidden reference collection.
    reference = bpy.data.collections.new("REFERENCE • Quaternius CC0")
    scene.collection.children.link(reference)
    for obj in list(scene.objects):
        if obj not in [rig, body]:
            for collection in list(obj.users_collection):
                collection.objects.unlink(obj)
            reference.objects.link(obj)
            obj.hide_render = True
            obj.hide_set(True)
    reference.hide_render = True
    create_controls(rig)
    rig["preview_root_motion"] = 0.0
    rig.id_properties_ui("preview_root_motion").update(min=0.0,max=1.0,
        description="1: preview authored turn yaw in Blender; 0: in-place runtime export. Motor supplies this yaw in Godot.")
    rig.rotation_mode = "XYZ"
    root_driver = rig.driver_add("rotation_euler",2).driver
    root_driver.expression = "heading * enabled"
    for var_name, data_path in [("heading", '["preview_heading"]'),("enabled", '["preview_root_motion"]')]:
        variable = root_driver.variables.new()
        variable.name = var_name
        variable.targets[0].id = rig
        variable.targets[0].data_path = data_path
    # Match editable IK controls to every baked FK frame before exposing sliders.
    # Switching to IK therefore preserves the pose instead of snapping to T-pose.
    for name, duration, *_ in clips:
        rig.animation_data.action = bpy.data.actions[name]
        for f in range(round(duration*FPS)+1):
            scene.frame_set(f)
            for side in ["Left", "Right"]:
                control = rig.pose.bones["CTRL_Foot_"+side]
                control.rotation_mode = "QUATERNION"
                control.matrix = rig.pose.bones[side+"Foot"].matrix.copy()
                control.keyframe_insert("location", frame=f)
                control.keyframe_insert("rotation_quaternion", frame=f)
                pole = rig.pose.bones["CTRL_Knee_"+side]
                matrix = pole.matrix.copy()
                matrix.translation = rig.pose.bones[side+"LowerLeg"].head+Vector((0, -.65, 0))
                pole.matrix = matrix
                pole.keyframe_insert("location", frame=f)
    rig.animation_data.action = bpy.data.actions["Idle"]
    scene.frame_set(0)
    for side in ["Left", "Right"]:
        expected = rig.pose.bones[side+"LowerLeg"].head.copy()
        constraint = rig.pose.bones[side+"LowerLeg"].constraints[0]
        rig["foot_ik_"+side] = 1.0
        best = (float("inf"), 0.0)
        for i in range(72):
            angle = -math.pi+i*math.tau/72
            constraint.pole_angle = angle
            bpy.context.view_layer.update()
            error = (rig.pose.bones[side+"LowerLeg"].head-expected).length
            if error < best[0]:
                best = error, angle
        center = best[1]
        for i in range(41):
            angle = center + math.radians((i-20)*.25)
            constraint.pole_angle = angle
            bpy.context.view_layer.update()
            error = (rig.pose.bones[side+"LowerLeg"].head-expected).length
            if error < best[0]:
                best = error, angle
        constraint.pole_angle = best[1]
        rig["foot_ik_"+side] = 0.0
        bpy.context.view_layer.update()
        log("Matched editing IK", side, "knee error", best[0])
    # The FK hip twist varies through a cycle. Match the pole angle per frame,
    # rather than assuming the angle calibrated in Idle also fits every pose.
    max_knee_error = 0.0
    for name, duration, *_ in clips:
        rig.animation_data.action = bpy.data.actions[name]
        for f in range(round(duration*FPS)+1):
            rig["foot_ik_Left"] = rig["foot_ik_Right"] = 0.0
            rig.update_tag()
            scene.frame_set(f)
            bpy.context.view_layer.update()
            expected = {s: rig.pose.bones[s+"LowerLeg"].head.copy() for s in ["Left","Right"]}
            heads = {s: rig.pose.bones[s+"UpperLeg"].head.copy() for s in ["Left","Right"]}
            feet = {s: rig.pose.bones[s+"Foot"].head.copy() for s in ["Left","Right"]}
            rig["foot_ik_Left"] = rig["foot_ik_Right"] = 1.0
            rig.update_tag()
            bpy.context.view_layer.update()
            for side in ["Left","Right"]:
                constraint = rig.pose.bones[side+"LowerLeg"].constraints[0]
                axis = (feet[side]-heads[side]).normalized()
                desired = expected[side]-heads[side]
                desired -= axis*desired.dot(axis)
                for _ in range(2):
                    actual = rig.pose.bones[side+"LowerLeg"].head-heads[side]
                    actual -= axis*actual.dot(axis)
                    if actual.length < 1e-6 or desired.length < 1e-6:
                        break
                    delta = math.atan2(axis.dot(actual.cross(desired)), actual.dot(desired))
                    base = constraint.pole_angle
                    best = ((rig.pose.bones[side+"LowerLeg"].head-expected[side]).length,base)
                    for angle in [base+delta,base-delta]:
                        constraint.pole_angle = (angle+math.pi)%math.tau-math.pi
                        rig.update_tag()
                        bpy.context.view_layer.update()
                        error = (rig.pose.bones[side+"LowerLeg"].head-expected[side]).length
                        if error < best[0]:best=error,constraint.pole_angle
                    constraint.pole_angle = best[1]
                    rig.update_tag()
                    bpy.context.view_layer.update()
                constraint.keyframe_insert("pole_angle",frame=f)
                max_knee_error = max(max_knee_error,(rig.pose.bones[side+"LowerLeg"].head-expected[side]).length)
        log("Matched IK poles",name)
    rig["foot_ik_Left"] = rig["foot_ik_Right"] = 0.0
    rig.update_tag()
    log("Editing IK knee match maximum",max_knee_error)
    rig["README"] = "Metres; forward -Y; 60 fps. Actions: Idle / Walk / Jog / Start / Stop / Turn. Foot IK properties default 0 for baked FK. See README.ja.md."
    rig.animation_data.action = bpy.data.actions["Idle"]
    scene.frame_start, scene.frame_end = 0, 192
    scene.frame_set(0)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    body.select_set(True)
    metadata["sole_height"] = ankle_z
    (OUT/"motions.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+"\n")
    (ROOT/"source/motion_samples.json").write_text(json.dumps(sampled_motion)+"\n")
    # Store all actions as NLA tracks: glTF exports only this armature's tracks.
    rig.animation_data.action = None
    for name, duration, *_ in clips:
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        strip = track.strips.new(name, 0, bpy.data.actions[name])
        strip.name = name
        track.mute = True
    # Export only the target rig and surface. Blender controls are excluded.
    for track in rig.animation_data.nla_tracks:
        track.mute = False
    log("Exporting GLB")
    bpy.ops.export_scene.gltf(filepath=str(OUT/"humanoid.glb"), export_format="GLB",
        use_selection=True, export_animations=True, export_animation_mode="NLA_TRACKS",
        export_nla_strips=True, export_force_sampling=True, export_frame_step=1,
        export_def_bones=True, export_skins=True, export_yup=True,
        export_apply=False, export_cameras=False, export_lights=False,
        export_extras=False)
    for track in rig.animation_data.nla_tracks:
        track.mute = True
    rig["preview_root_motion"] = 1.0
    rig.animation_data.action = bpy.data.actions["Idle"]
    scene.frame_set(0)
    from blender_presentation import prepare
    prepare()
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"source/character.blend"))
    (ROOT/"reports").mkdir(exist_ok=True)
    (ROOT/"reports/character_build.json").write_text(json.dumps({"status":"complete", "blender":bpy.app.version_string,
        "vertices":len(body.data.vertices), "polygons":len(body.data.polygons), "bones":len(bones),
        "actions":len(clips), "fps":FPS, "height":HEIGHT}, indent=2))
    log("BUILD_COMPLETE")
    # Some sandbox PulseAudio implementations hang in Blender's shutdown hook.
    # Everything is saved synchronously above; bypass that external audio hook.
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
