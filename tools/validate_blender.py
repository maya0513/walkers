"""Validate evaluated editable poses and metadata, including matched FK/IK controls.

These are geometric acceptance checks, not a substitute for motion review.
Blender coordinates are metres, +X left, -Y forward, +Z up.
"""
import bpy
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
SIDES = ["Left", "Right"]


def angular_difference(a, b):
    angle = a.rotation_difference(b).angle
    return math.degrees(min(angle, math.tau-angle))


def select_action(rig, name):
    rig.animation_data.action = bpy.data.actions[name]
    rig["foot_ik_Left"] = rig["foot_ik_Right"] = 0.0
    rig["preview_root_motion"] = 0.0
    rig.update_tag()


def evaluated_pose(rig, frame):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {bone.name: bone.matrix.copy() for bone in evaluated.pose.bones}


def check_postures(rig, metadata, failures):
    result = {}
    select_action(rig, "Idle")
    baseline = evaluated_pose(rig, 0)
    idle_translation, idle_rotation, idle_scale = 0., 0., 0.
    for frame in range(metadata["clips"]["Idle"]["frames"]+1):
        pose = evaluated_pose(rig, frame)
        for name, matrix in pose.items():
            before = baseline[name]
            idle_translation = max(idle_translation, (matrix.translation-before.translation).length)
            idle_rotation = max(idle_rotation, angular_difference(before.to_quaternion(), matrix.to_quaternion()))
            idle_scale = max(idle_scale, (matrix.to_scale()-before.to_scale()).length)
    result["Idle"] = {"evaluated_frames": metadata["clips"]["Idle"]["frames"]+1,
                      "evaluated_bones": len(baseline), "max_bone_translation_change_m": idle_translation,
                      "max_bone_rotation_change_degrees": idle_rotation, "max_bone_scale_change": idle_scale}
    if idle_translation > 1e-6 or idle_rotation > .01 or idle_scale > 1e-6:
        failures.append("Idle: evaluated bones are not constant")
    rest = {bone.name: bone.matrix_local.to_quaternion() for bone in rig.data.bones}
    for name, track, lean_limit in [("Walk", .10, 6.), ("Jog", .04, 12.)]:
        select_action(rig, name)
        leans, widths, abductions, hip_positions, head_positions = [], [], [], [], []
        knees, pitches = {s: [] for s in SIDES}, {s: [] for s in SIDES}
        midstance_flexion = {s: [] for s in SIDES}
        for frame in range(metadata["clips"][name]["frames"]+1):
            p = evaluated_pose(rig, frame)
            hip_positions.append(p["Hips"].translation.copy())
            head_positions.append(p["Head"].translation.copy())
            torso = p["Neck"].translation-p["Hips"].translation
            leans.append(math.degrees(math.atan2(abs(torso.y), torso.z)))
            widths.append(p["LeftFoot"].translation.x-p["RightFoot"].translation.x)
            for side in SIDES:
                upper_arm = p[side+"LowerArm"].translation-p[side+"UpperArm"].translation
                abductions.append(math.degrees(math.atan2(abs(upper_arm.x), -upper_arm.z)))
                hip, knee, ankle = [p[side+n].translation for n in ["UpperLeg", "LowerLeg", "Foot"]]
                # Keep walking stance extended as the body passes over the foot.
                # A low, nearly constant pelvis must not pass as a bobbing fix.
                side_phase = (frame/metadata["clips"][name]["frames"] + (0 if side == "Left" else .5)) % 1
                if name == "Walk" and .20 <= side_phase <= .30:
                    flexion = 180-math.degrees((hip-knee).angle(ankle-knee))
                    midstance_flexion[side].append({"frame": frame, "side_phase": side_phase, "degrees": flexion})
                axis = ankle-hip
                nearest = hip+axis*((knee-hip).dot(axis)/axis.length_squared)
                knees[side].append(-(knee-nearest).y)
                rotation = p[side+"Foot"].to_quaternion() @ rest[side+"Foot"].inverted()
                forward = rotation @ Vector((0, -1, 0))
                pitches[side].append(math.degrees(math.atan2(forward.z, -forward.y)))
        hip_adjacent = max((b-a).length for a, b in zip(hip_positions, hip_positions[1:]))
        hip_seam_velocity = ((hip_positions[1]-hip_positions[0])-(hip_positions[-1]-hip_positions[-2])).length*metadata["fps"]
        vertical = {}
        for label, positions in [("hips", hip_positions), ("head", head_positions)]:
            vertical[label] = {
                "height_min_m": min(p.z for p in positions),
                "height_max_m": max(p.z for p in positions),
                "vertical_peak_to_peak_m": max(p.z for p in positions)-min(p.z for p in positions),
                "vertical_peak_speed_mps": max(abs(b.z-a.z) for a, b in zip(positions, positions[1:]))*metadata["fps"],
                "max_adjacent_displacement_m": max((b-a).length for a, b in zip(positions, positions[1:])),
                "seam_velocity_difference_mps": ((positions[1]-positions[0])-(positions[-1]-positions[-2])).length*metadata["fps"],
            }
            values = vertical[label]
            if values["vertical_peak_to_peak_m"] > .06:
                failures.append(name+": "+label+" vertical excursion >6cm")
            if values["vertical_peak_speed_mps"] > .80:
                failures.append(name+": "+label+" vertical speed >0.80m/s")
            if values["max_adjacent_displacement_m"] > .02:
                failures.append(name+": "+label+" jumps >2cm per baked frame")
            if values["seam_velocity_difference_mps"] > .30:
                failures.append(name+": "+label+" loop velocity discontinuity >0.30m/s")
        if vertical["head"]["vertical_peak_to_peak_m"] < .001:
            failures.append(name+": head is artificially locked in height")
        metrics = {"evaluated_frames": len(widths), "vertical_motion": vertical, "hips_max_adjacent_displacement_m": hip_adjacent,
                   "hips_seam_velocity_difference_mps": hip_seam_velocity, "hips_to_neck_lean_max_degrees": max(leans),
                   "upper_arm_abduction_max_degrees": max(abductions),
                   "foot_track_width_min_m": min(widths), "foot_track_width_max_m": max(widths),
                   "foot_track_width_mean_m": sum(widths)/len(widths),
                   "knee_forward_offset_min_m": {s: min(knees[s]) for s in SIDES},
                   "foot_pitch_min_degrees": {s: min(pitches[s]) for s in SIDES},
                   "foot_pitch_max_degrees": {s: max(pitches[s]) for s in SIDES},
                   "foot_pitch_span_degrees": {s: max(pitches[s])-min(pitches[s]) for s in SIDES}}
        if name == "Walk":
            metrics["midstance_knee_flexion"] = {
                side: {"samples": rows, "max_degrees": max((row["degrees"] for row in rows), default=None)}
                for side, rows in midstance_flexion.items()}
            for side, rows in midstance_flexion.items():
                if not rows:
                    failures.append("Walk: missing midstance knee samples: "+side)
                elif max(row["degrees"] for row in rows) > 20.:
                    failures.append("Walk: midstance knee flexion >20 degrees: "+side)
        result[name] = metrics
        if max(leans) > lean_limit:
            failures.append(name+": hips-to-neck lean")
        if max(abductions) > 12.:
            failures.append(name+": upper-arm abduction")
        if any(abs(width-track) > .03 for width in widths):
            failures.append(name+": foot track width")
        if min(widths) <= 0:
            failures.append(name+": feet crossed")
        if any(min(values) < -.002 for values in knees.values()):
            failures.append(name+": knee bends behind hip-ankle plane")
        if name == "Jog" and any(max(values)-min(values) <= 10 for values in pitches.values()):
            failures.append("Jog: foot pitch lacks stance-to-push-off change")
    return result


def check_metadata(metadata, failures):
    valid = {"heel", "sole", "ball", "toes", "air"}
    if metadata.get("schema_version") not in [2, 3]:
        failures.append("support metadata schema version")
    for side in SIDES:
        points = metadata.get("support_points", {}).get(side, {})
        if set(points) != valid-{"air"} or any(len(v) != 3 or not all(math.isfinite(n) for n in v) for v in points.values()):
            failures.append("invalid support geometry: "+side)
    result = {}
    for name, info in metadata["clips"].items():
        contacts, regions = info.get("contacts", []), info.get("support_regions", [])
        count = info["frames"]+1
        if len(contacts) != count or len(regions) != count:
            failures.append(name+": support/contact sample count")
            continue
        if any(len(row) != 2 or not all(math.isfinite(v) and 0 <= v <= 1 for v in row) for row in contacts):
            failures.append(name+": invalid contacts")
            continue
        if any(len(row) != 2 or any(v not in valid for v in row) for row in regions):
            failures.append(name+": invalid support regions")
            continue
        if metadata.get("schema_version") == 3:
            offsets = info.get("support_offsets", [])
            if len(offsets) != count or any(len(row) != 2 or any(len(point) != 3 or not all(math.isfinite(v) for v in point) for point in row) for row in offsets):
                failures.append(name+": invalid continuous support offsets")
            elif info["loop"] and any((Vector(offsets[0][side])-Vector(offsets[-1][side])).length > 1e-5 for side in [0, 1]):
                failures.append(name+": support offsets differ at loop boundary")
        if name in ["Walk", "Jog"]:
            samples = contacts[:-1]
            # A 1.05s walk is 63 baked intervals: the opposite foot's half
            # cycle lands between samples, so interpolate instead of truncating.
            def half_cycle(index):
                shifted = (index+len(samples)*.5) % len(samples)
                lower = math.floor(shifted)
                fraction = shifted-lower
                return samples[lower][1]*(1-fraction)+samples[(lower+1)%len(samples)][1]*fraction
            symmetry_error = max(abs(samples[i][0]-half_cycle(i)) for i in range(len(samples)))
            flight_fraction = sum(max(row) < .01 for row in samples)/len(samples)
            support_regions = {s: sorted({row[i] for row in regions}) for i, s in enumerate(SIDES)}
            # Odd sample counts cannot express a half-cycle exactly. A short
            # C2 contact ramp can have ~0.09 interpolation error at 63 samples.
            symmetry_tolerance = .12 if len(samples) % 2 else .06
            result[name] = {"left_right_half_cycle_contact_error": symmetry_error,
                            "contact_symmetry_sampling_tolerance": symmetry_tolerance,
                            "flight_fraction": flight_fraction, "support_regions": support_regions}
            if symmetry_error > symmetry_tolerance or any(max(row[i] for row in samples) < .99 for i in [0, 1]):
                failures.append(name+": contacts do not alternate at half cycle")
            for i in [0, 1]:
                if any(region[i] == "air" and contact[i] > .01 for contact, region in zip(contacts, regions)):
                    failures.append(name+": air region has contact weight")
            if name == "Jog" and (flight_fraction < .10 or any(not {"sole", "ball", "toes", "air"}.issubset(values) for values in support_regions.values())):
                failures.append("Jog: missing flight or changing support regions")
            if name == "Walk" and any(not valid.issubset(values) for values in support_regions.values()):
                failures.append("Walk: missing heel-to-toe support regions")
    return result


def main():
    rig = bpy.data.objects["Humanoid"]
    body = bpy.data.objects["Humanoid_CC0"]
    metadata = json.loads((ROOT/"addons/walkers/assets/motions.json").read_text())
    failures = []
    postures = check_postures(rig, metadata, failures)
    support = check_metadata(metadata, failures)
    # Derive the trajectories independently from the editable Blender rig, not
    # from the author's JSON samples. This also catches IK branch discontinuity.
    sys.path.insert(0, str(ROOT/"tools"))
    from analyze_motion_curves import summarize
    evaluated_samples = {}
    for clip in ["Walk", "Jog"]:
        select_action(rig, clip)
        evaluated_samples[clip] = [
            {"positions": {name: list(matrix.translation) for name, matrix in evaluated_pose(rig, frame).items()}}
            for frame in range(metadata["clips"][clip]["frames"]+1)]
    curves = summarize(evaluated_samples, metadata, enforce=True)
    curves["measurement_source"] = {"kind": "evaluated_Blender_FK", "blend": Path(bpy.data.filepath).name,
                                    "blend_sha256": hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()}
    failures.extend(curves["failures"])
    from validate_author_curves import check as check_author_curves
    author_curves = check_author_curves(rig, body)
    failures.extend(author_curves["failures"])
    (ROOT/"reports/author_curve_continuity.json").write_text(json.dumps(author_curves, indent=2)+"\n")
    (ROOT/"reports/motion_curve_analysis.json").write_text(json.dumps(curves, indent=2)+"\n")
    before_path = ROOT/"reports/motion_curve_before.json"
    if before_path.exists():
        before = json.loads(before_path.read_text())
        comparison = {"measurement": "both versions independently evaluated Blender FK at 60Hz",
                      "before_source": before.get("measurement_source"), "after_source": curves["measurement_source"], "clips": {}}
        for clip in ["Walk", "Jog"]:
            old, new = before["clips"][clip], curves["clips"][clip]
            comparison["clips"][clip] = {
                "period_seconds": {"before": old["duration_seconds"], "after": new["duration_seconds"]},
                "cadence_steps_per_minute": {"before": old["cadence_steps_per_minute"], "after": new["cadence_steps_per_minute"]},
                "step_length_m": {"before": old["step_length_m"], "after": new["step_length_m"]},
                "pelvis_vertical_extrema_per_stride": {"before": old["pelvis_vertical_extrema_per_stride"], "after": new["pelvis_vertical_extrema_per_stride"]},
                "arms_relative_to_chest": {"before": old["arms_relative_to_chest"], "after": new["arms_relative_to_chest"]},
                "adjacent_velocity_change": {}}
            for bone, values in new["trajectories"].items():
                original = old["trajectories"][bone]["max_adjacent_velocity_change_mps"]
                updated = values["max_adjacent_velocity_change_mps"]
                comparison["clips"][clip]["adjacent_velocity_change"][bone] = {
                    "before_mps": original, "after_mps": updated, "reduction_percent": 100*(1-updated/original)}
        (ROOT/"reports/motion_curve_comparison.json").write_text(json.dumps(comparison, indent=2)+"\n")
    position_error, rotation_error, knee_error = 0., 0., 0.
    for name in ["Idle", "Walk", "Jog", "Turn90L", "Turn180R"]:
        select_action(rig, name)
        for fraction in [0, .25, .5, .75, 1]:
            rig["foot_ik_Left"] = rig["foot_ik_Right"] = 0.0
            rig.update_tag()
            p = evaluated_pose(rig, round(metadata["clips"][name]["frames"]*fraction))
            rig["foot_ik_Left"] = rig["foot_ik_Right"] = 1.0
            rig.update_tag()
            ik = evaluated_pose(rig, round(metadata["clips"][name]["frames"]*fraction))
            for side in SIDES:
                foot = side+"Foot"
                position_error = max(position_error, (ik[foot].translation-p[foot].translation).length)
                rotation_error = max(rotation_error, angular_difference(p[foot].to_quaternion(), ik[foot].to_quaternion()))
                knee = side+"LowerLeg"
                knee_error = max(knee_error, (ik[knee].translation-p[knee].translation).length)
    height = max(v.co.z for v in body.data.vertices)-min(v.co.z for v in body.data.vertices)
    if abs(height-1.78) > .001: failures.append("model scale")
    if metadata.get("phenotype", {}).get("gender") != "male": failures.append("male phenotype metadata")
    if position_error > .002: failures.append("FK/IK foot position match")
    if rotation_error > 1.: failures.append("FK/IK foot orientation match")
    if knee_error > .005: failures.append("FK/IK knee match")
    for name in metadata["clips"]:
        if name not in bpy.data.actions: failures.append("missing Action: "+name)
    for side in SIDES:
        for stem in ["CTRL_Foot_", "CTRL_Knee_"]:
            if rig.data.bones[stem+side].use_deform: failures.append("control exported as deformation")
    report = {"blender": bpy.app.version_string, "actions": len(metadata["clips"]), "height_m": height,
              "phenotype": metadata.get("phenotype"), "postures": postures, "support": support, "motion_curves": curves, "authored_continuity": author_curves,
              "fk_ik_foot_position_error_m": position_error, "fk_ik_foot_rotation_error_degrees": rotation_error,
              "fk_ik_knee_displacement_m": knee_error, "failures": failures}
    (ROOT/"reports/blender_validation.json").write_text(json.dumps(report, indent=2)+"\n")
    print("BLENDER_VALIDATION", json.dumps(report), flush=True)
    os._exit(0 if not failures else 1)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
