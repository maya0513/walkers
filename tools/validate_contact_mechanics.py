"""Blender geometric observations of articulated contact and trunk coordination.

Only clip duration/frame count comes from metadata. Foot patches are selected from
rest skin geometry and every observation comes from evaluated mesh/bones, never
from contact labels, authored support offsets or authoring curve functions.
Thresholds are production regression criteria, not clinical gait prescriptions.
"""
import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
SIDES = ('Left', 'Right')
CONTACT_TOLERANCE = .002


def span(values):
    return max(values)-min(values)


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[round((len(ordered)-1)*fraction)]


def degrees_xyz(matrix):
    return [math.degrees(value) for value in matrix.to_quaternion().to_euler('XYZ')]


def select_patches(body, rig):
    """Fixed material patches: lower skin, relative to the anatomical toe joint.

    Heel lies behind ankle; forefoot is immediately proximal to MTP/toe pivot;
    toe patch is distal to it. Top/dorsal skin cannot masquerade as a sole patch.
    """
    patches = {}
    bounds = {}
    for side, sign in (('Left', 1), ('Right', -1)):
        ankle = rig.data.bones[side+'Foot'].head_local
        joint = rig.data.bones[side+'Toes'].head_local
        sole = [v for v in body.data.vertices if v.co.x*sign > 0 and v.co.z < .025]
        groups = {
            'heel': [v.index for v in sole if v.co.y > ankle.y+.012],
            'forefoot': [v.index for v in sole if joint.y+.002 <= v.co.y <= joint.y+.040],
            'toes': [v.index for v in sole if v.co.y < joint.y-.022],
            # All lower foot/ankle skin, independent of the three landmark
            # patches. The anatomical joint-pad gap must not end support early.
            'whole_foot': [v.index for v in body.data.vertices if v.co.x*sign > 0 and v.co.z < .13],
        }
        if any(len(indices) < 5 for indices in groups.values()):
            raise ValueError('Insufficient independent sole patch vertices: '+side)
        patches[side] = groups
        bounds[side] = {name: {'vertex_count': len(indices),
                                 'rest_y_range_m': [min(body.data.vertices[i].co.y for i in indices), max(body.data.vertices[i].co.y for i in indices)],
                                 'rest_z_range_m': [min(body.data.vertices[i].co.z for i in indices), max(body.data.vertices[i].co.z for i in indices)]}
                        for name, indices in groups.items()}
    return patches, bounds


def evaluate(rig, body, metadata):
    patches, bounds = select_patches(body, rig)
    rest = {b.name: b.matrix_local.copy() for b in rig.data.bones}
    rig['foot_ik_Left'] = rig['foot_ik_Right'] = 0.
    rig['preview_root_motion'] = 0.
    for track in rig.animation_data.nla_tracks:
        track.mute = True
    clips = {}
    for name, info in metadata['clips'].items():
        rig.animation_data.action = bpy.data.actions[name]
        rig.update_tag()
        rows = []
        for frame in range(info['frames']+1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            pose = rig.evaluated_get(graph).pose.bones
            evaluated_body = body.evaluated_get(graph)
            mesh = evaluated_body.to_mesh()
            if len(mesh.vertices) != len(body.data.vertices):
                raise ValueError('Evaluated mesh topology differs; cannot track material sole patches')
            rotations = {bone: pose[bone].matrix.to_3x3() @ rest[bone].to_3x3().inverted()
                         for bone in ('Hips', 'Spine', 'Chest', 'UpperChest', 'Head')}
            row = {'frame': frame, 'phase': frame/info['frames'], 'time_seconds': frame/60,
                   'pelvis_deformation_degrees_xyz': degrees_xyz(rotations['Hips']),
                   'chest_relative_pelvis_degrees_xyz': degrees_xyz(rotations['Hips'].inverted() @ rotations['Chest']),
                   'spine_relative_pelvis_degrees_xyz': degrees_xyz(rotations['Hips'].inverted() @ rotations['Spine']),
                   'upper_chest_relative_chest_degrees_xyz': degrees_xyz(rotations['Chest'].inverted() @ rotations['UpperChest']),
                   'head_position_m': list(pose['Head'].matrix.translation), 'feet': {}}
            for side in SIDES:
                foot = pose[side+'Foot'].matrix
                toe = pose[side+'Toes'].matrix
                relative = foot.to_3x3().inverted() @ toe.to_3x3()
                relative_rest = rest[side+'Foot'].to_3x3().inverted() @ rest[side+'Toes'].to_3x3()
                articulation = relative @ relative_rest.inverted()
                q = articulation.to_quaternion()
                joint_angle = math.degrees(min(q.angle, math.tau-q.angle))
                skin = {}
                for patch, indices in patches[side].items():
                    coords = [evaluated_body.matrix_world @ mesh.vertices[i].co for i in indices]
                    heights = [v.z for v in coords]
                    skin[patch] = {'minimum_height_m': min(heights),
                                   'height_05_percentile_m': percentile(heights, .05),
                                   'contact': min(heights) <= CONTACT_TOLERANCE,
                                   'lowest_vertex_index': indices[min(range(len(heights)), key=heights.__getitem__)]}
                hip, knee, ankle = [pose[side+n].matrix.translation for n in ('UpperLeg', 'LowerLeg', 'Foot')]
                knee_flex = 180-math.degrees((hip-knee).angle(ankle-knee))
                deformation = foot.to_3x3() @ rest[side+'Foot'].to_3x3().inverted()
                forward = deformation @ Vector((0, -1, 0))
                pitch = math.degrees(math.atan2(forward.z, -forward.y))
                row['feet'][side] = {'patches': skin, 'toe_relative_foot_angle_degrees': joint_angle,
                                     'toe_relative_foot_degrees_xyz': degrees_xyz(articulation),
                                     'foot_pitch_degrees': pitch, 'knee_flexion_degrees': knee_flex,
                                     'ankle_position_m': list(ankle), 'hip_position_m': list(hip)}
            evaluated_body.to_mesh_clear()
            rows.append(row)
        clips[name] = {'duration_seconds': info['duration'], 'baked_frame_intervals': info['frames'], 'samples': rows}
    return clips, bounds


def contact_cycle(rows, side):
    """Rotate each independent geometric cycle from peak airborne sole clearance."""
    n = len(rows)
    sole = [row['feet'][side]['patches']['whole_foot']['minimum_height_m'] for row in rows]
    start = max(range(n), key=sole.__getitem__)
    ordered = [(start+i) % n for i in range(1, n+1)]
    landed = next((i for i, k in enumerate(ordered) if sole[k] <= CONTACT_TOLERANCE), None)
    if landed is None:
        return {'landing_frame': None, 'contact_samples': 0, 'contact_sample_frames': [], 'patch_first_contact_delay_seconds': {}}
    grounded = []
    for index in ordered[landed:]+ordered[:landed]:
        if sole[index] > CONTACT_TOLERANCE and grounded:
            break
        grounded.append(index)
    contacts = {}
    for patch in ('heel', 'forefoot', 'toes'):
        first = next((i for i, k in enumerate(grounded) if rows[k]['feet'][side]['patches'][patch]['contact']), None)
        contacts[patch] = first/60 if first is not None else None
    return {'landing_frame': grounded[0], 'landing_phase': grounded[0]/n,
            'contact_samples': len(grounded), 'contact_sample_frames': grounded,
            'patch_first_contact_delay_seconds': contacts,
            'contact_duration_seconds': len(grounded)/60}


def summarize(clips, enforce):
    result, failures = {}, []
    for name, clip in clips.items():
        if name not in ('Walk', 'Jog'):
            continue
        rows = clip['samples'][:-1]
        torso = {}
        for key in ('pelvis_deformation_degrees_xyz', 'chest_relative_pelvis_degrees_xyz',
                    'spine_relative_pelvis_degrees_xyz', 'upper_chest_relative_chest_degrees_xyz'):
            torso[key] = {axis: {'min': min(row[key][i] for row in rows), 'max': max(row[key][i] for row in rows),
                                 'span': span([row[key][i] for row in rows])} for i, axis in enumerate(('sagittal_x', 'frontal_y', 'transverse_z'))}
        feet = {}
        for side in SIDES:
            feet_rows = [row['feet'][side] for row in rows]
            cycle = contact_cycle(rows, side)
            push_frames = []
            for k in cycle['contact_sample_frames']:
                f = rows[k]['feet'][side]
                if f['patches']['heel']['minimum_height_m'] > .025 and min(f['patches'][p]['minimum_height_m'] for p in ('forefoot', 'toes')) <= CONTACT_TOLERANCE:
                    push_frames.append(k)
            flexion = [f['toe_relative_foot_angle_degrees'] for f in feet_rows]
            metrics = {'geometric_contact_cycle': cycle,
                       'toe_relative_foot_angle_min_degrees': min(flexion),
                       'toe_relative_foot_angle_max_degrees': max(flexion),
                       'toe_relative_foot_angle_span_degrees': span(flexion),
                       'toe_relative_foot_max_degrees_while_geometrically_supported': max((rows[k]['feet'][side]['toe_relative_foot_angle_degrees'] for k in cycle['contact_sample_frames']), default=0),
                       'heel_raised_forefoot_supported_frames': push_frames,
                       'heel_raised_forefoot_supported_seconds': len(push_frames)/60,
                       'minimum_patch_height_m': min(p['minimum_height_m'] for f in feet_rows for p in f['patches'].values()),
                       'peak_sole_clearance_m': max(min(p['minimum_height_m'] for p in f['patches'].values()) for f in feet_rows),
                       'contact_tolerance_sensitivity': {str(tol): {'whole_foot_contact_samples': sum(f['patches']['whole_foot']['minimum_height_m'] <= tol for f in feet_rows), 'any_landmark_patch_contact_samples': sum(min(f['patches'][p]['minimum_height_m'] for p in ('heel', 'forefoot', 'toes')) <= tol for f in feet_rows), 'heel_raised_forefoot_supported_samples': sum(f['patches']['heel']['minimum_height_m'] > .025 and min(f['patches'][p]['minimum_height_m'] for p in ('forefoot', 'toes')) <= tol for f in feet_rows)} for tol in (.002, .003, .006)},
                       'patch_contact_fraction': {p: sum(f['patches'][p]['contact'] for f in feet_rows)/len(feet_rows) for p in ('heel', 'forefoot', 'toes')}}
            if cycle['contact_sample_frames']:
                supported = cycle['contact_sample_frames']
                first_part = supported[:max(2, round(len(supported)*.65))]
                final_part = supported[max(0, round(len(supported)*.65)): ]
                metrics['support_load_knee_flexion_max_degrees'] = max(rows[k]['feet'][side]['knee_flexion_degrees'] for k in first_part)
                metrics['late_support_knee_flexion_min_degrees'] = min(rows[k]['feet'][side]['knee_flexion_degrees'] for k in final_part)
                metrics['load_to_late_support_knee_extension_degrees'] = metrics['support_load_knee_flexion_max_degrees']-metrics['late_support_knee_flexion_min_degrees']
                metrics['late_support_foot_pitch_change_degrees'] = span([rows[k]['feet'][side]['foot_pitch_degrees'] for k in final_part])
            if push_frames:
                last = push_frames[-1]
                later = [(last+i) % len(rows) for i in range(1, max(3, round(len(rows)*.25))+1)]
                metrics['push_off_ankle_behind_hip_max_m'] = max(rows[k]['feet'][side]['ankle_position_m'][1]-rows[k]['feet'][side]['hip_position_m'][1] for k in push_frames)
                metrics['push_off_knee_flexion_min_degrees'] = min(rows[k]['feet'][side]['knee_flexion_degrees'] for k in push_frames)
                metrics['recovery_knee_flexion_max_degrees'] = max(rows[k]['feet'][side]['knee_flexion_degrees'] for k in later)
                metrics['post_support_knee_flexion_gain_degrees'] = metrics['recovery_knee_flexion_max_degrees']-rows[last]['feet'][side]['knee_flexion_degrees']
            feet[side] = metrics
            if enforce:
                if metrics['minimum_patch_height_m'] < -.01:
                    failures.append(name+': skinned sole penetrates floor >1cm: '+side)
                if metrics['toe_relative_foot_angle_span_degrees'] < 8:
                    failures.append(name+': toe joint remains effectively rigid: '+side)
                if metrics['toe_relative_foot_max_degrees_while_geometrically_supported'] < 8:
                    failures.append(name+': toe articulation is absent during actual sole support: '+side)
                if len(push_frames) < (3 if name == 'Walk' else 2):
                    failures.append(name+': missing heel-rise with geometric forefoot support: '+side)
                if metrics.get('post_support_knee_flexion_gain_degrees', 0) < 8:
                    failures.append(name+': missing knee recovery after distal support: '+side)
                if metrics.get('load_to_late_support_knee_extension_degrees', 0) < 3:
                    failures.append(name+': no knee extension after load absorption: '+side)
                if cycle['contact_samples'] < 4:
                    failures.append(name+': insufficient geometric support samples: '+side)
                delays = cycle['patch_first_contact_delay_seconds']
                if name == 'Walk' and (delays.get('heel') is None or delays.get('forefoot') is None or delays['heel'] >= delays['forefoot']):
                    failures.append('Walk: evaluated mesh lacks heel-before-forefoot contact: '+side)
                if name == 'Jog' and (any(delays.get(patch) is None for patch in ('heel', 'forefoot', 'toes')) or delays['forefoot'] > min(delays['heel'], delays['toes'])):
                    failures.append('Jog: chosen midfoot landing becomes toe/heel-first: '+side)
        if enforce:
            for axis in ('sagittal_x', 'frontal_y', 'transverse_z'):
                if torso['pelvis_deformation_degrees_xyz'][axis]['span'] < .5:
                    failures.append(name+': pelvis lacks distributed three-axis motion: '+axis)
            if torso['chest_relative_pelvis_degrees_xyz']['transverse_z']['span'] < 1.:
                failures.append(name+': chest and pelvis rotate as one rigid block')
            if max(v['span'] for v in torso['spine_relative_pelvis_degrees_xyz'].values()) < .5:
                failures.append(name+': no relative motion distributed through spine')
            if span([row['head_position_m'][2] for row in rows]) > .06:
                failures.append(name+': head excursion >6cm')
        result[name] = {'torso': torso, 'feet': feet,
                        'head_vertical_peak_to_peak_m': span([row['head_position_m'][2] for row in rows])}
    return result, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'reports/contact_mechanics.json')
    parser.add_argument('--metadata', type=Path, default=ROOT/'addons/walkers/assets/motions.json')
    parser.add_argument('--observe-only', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    rig, body = bpy.data.objects['Humanoid'], bpy.data.objects['Humanoid_CC0']
    metadata = json.loads(args.metadata.read_text())
    clips, patches = evaluate(rig, body, metadata)
    metrics, failures = summarize(clips, not args.observe_only)
    other_clips = {}
    for name, clip in clips.items():
        if name in ('Walk', 'Jog'):
            continue
        minimum = min(p['minimum_height_m'] for row in clip['samples'] for f in row['feet'].values() for p in f['patches'].values())
        other_clips[name] = {'evaluated_frames': len(clip['samples']), 'minimum_patch_height_m': minimum}
        if not args.observe_only and minimum < -.01:
            failures.append(name+': evaluated sole patch penetrates floor >1cm')
    report = {'measurement_source': {'kind': 'evaluated_Blender_mesh_and_FK', 'blend': Path(bpy.data.filepath).name,
                                      'blend_sha256': hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()},
              'validation_mode': 'observe_only' if args.observe_only else 'acceptance',
              'coordinate_system': '+X left, -Y forward, +Z up; metres; XYZ deformation rotations relative rest',
              'contact_tolerance_m': CONTACT_TOLERANCE, 'floor_z_m': 0,
              'contact_definition': 'cycle support uses the complete evaluated lower-foot skin envelope (rest Z<13cm), minimum height <= tolerance; heel/forefoot/toes landmark patch timings are separate proxies; not metadata support/IK weight',
              'limits_are': 'production visual regression checks, not medical recommendations or measured forces',
              'acceptance_thresholds': {'maximum_skin_penetration_m': .01, 'minimum_toe_articulation_span_degrees': 8, 'minimum_supported_toe_articulation_degrees': 8, 'heel_raise_minimum_m': .025, 'minimum_heel_raised_forefoot_support_frames': {'Walk': 3, 'Jog': 2}, 'minimum_post_support_knee_recovery_degrees': 8, 'minimum_load_to_late_support_knee_extension_degrees': 3, 'minimum_geometric_contact_samples': 4, 'minimum_pelvis_rotation_span_each_axis_degrees': .5, 'minimum_chest_relative_pelvis_yaw_span_degrees': 1, 'minimum_spine_relative_pelvis_motion_span_degrees': .5, 'maximum_head_vertical_range_m': .06, 'chosen_contact_order': {'Walk': 'heel strictly before forefoot', 'Jog': 'forefoot no later than heel or toes; simultaneous samples allowed'}},
              'kinematic_limitations': 'No force plate, muscle force, power or propulsion force is measured. Contact timing is quantized to 1/60s. Skin minimum is not pressure or contact area. Landmark patches intentionally leave gaps; only whole_foot defines cycle landing/support duration. Heel-raised distal-support counts require the selected forefoot/toes patches and remain a conservative anatomical proxy.',
              'patches': patches, 'clips': metrics, 'other_clips_mesh_clearance': other_clips, 'sampled_clips': clips, 'failures': failures}
    baseline_path = ROOT/'reports/contact_mechanics_before.json'
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())
        report['comparison_with_baseline'] = {'measurement_source': baseline['measurement_source'], 'clips': {}}
        for name in ('Walk', 'Jog'):
            previous, current = baseline['clips'][name], metrics[name]
            report['comparison_with_baseline']['clips'][name] = {
                'heel_raised_forefoot_supported_seconds': {side: {'before': previous['feet'][side]['heel_raised_forefoot_supported_seconds'], 'after': current['feet'][side]['heel_raised_forefoot_supported_seconds']} for side in SIDES},
                'pelvis_rotation_span_degrees_xyz': {axis: {'before': previous['torso']['pelvis_deformation_degrees_xyz'][axis]['span'], 'after': current['torso']['pelvis_deformation_degrees_xyz'][axis]['span']} for axis in ('sagittal_x', 'frontal_y', 'transverse_z')}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print('CONTACT_MECHANICS', json.dumps({'failures': failures, 'output': str(args.output)}), flush=True)
    os._exit(int(bool(failures)))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
