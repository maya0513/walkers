#!/usr/bin/env python3
"""Numerical observations of sampled full-body trajectories; no Blender dependency.

Position samples are evaluated FK poses in metres. Derivative limits here are
production regression limits, not clinical definitions of an ideal human gait.
The terminal duplicate is omitted when differentiating a periodic clip.
"""
import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDES = ('Left', 'Right')


def sub(a, b): return [x-y for x, y in zip(a, b)]
def dot(a, b): return sum(x*y for x, y in zip(a, b))
def length(a): return math.sqrt(dot(a, a))
def unit(a):
    n = length(a)
    return [x/n for x in a] if n else [0., 0., 0.]
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def scale(a, k): return [x*k for x in a]
def angle(a, b): return math.degrees(math.acos(max(-1., min(1., dot(unit(a), unit(b))))))


def extrema(values, epsilon=1e-6):
    """Count circular rises/falls, carrying sign through sampled plateaux."""
    signs = []
    for a, b in zip(values, values[1:]+values[:1]):
        if abs(b-a) > epsilon:
            signs.append(1 if b > a else -1)
    return {'maxima': sum(a > 0 > b for a, b in zip(signs, signs[1:]+signs[:1])),
            'minima': sum(a < 0 < b for a, b in zip(signs, signs[1:]+signs[:1]))}


def longest_run(mask):
    count, longest = 0, 0
    for value in mask+mask:
        count = count+1 if value else 0
        longest = max(count, longest)
    return min(len(mask), longest)


def trajectory(points, fps):
    velocities = [scale(sub(b, a), fps) for a, b in zip(points, points[1:]+points[:1])]
    delta = [sub(b, a) for a, b in zip(velocities, velocities[1:]+velocities[:1])]
    accelerations = [scale(v, fps) for v in delta]
    jerks = [scale(sub(b, a), fps) for a, b in zip(accelerations, accelerations[1:]+accelerations[:1])]
    ranked = sorted(range(len(delta)), key=lambda i: length(delta[i]), reverse=True)[:6]
    return {'peak_speed_mps': max(map(length, velocities)),
            'peak_acceleration_mps2': max(map(length, accelerations)),
            'peak_jerk_mps3': max(map(length, jerks)),
            'max_adjacent_velocity_change_mps': max(map(length, delta)),
            'rms_acceleration_mps2': math.sqrt(sum(dot(v, v) for v in accelerations)/len(accelerations)),
            'seam_velocity_difference_mps': length(sub(velocities[0], velocities[-1])),
            'longest_near_stationary_interval_seconds': longest_run([length(v) < .03 for v in velocities])/fps,
            'largest_velocity_changes': [{'frame': i+1, 'phase': (i+1)/len(points), 'mps': length(delta[i])} for i in ranked]}


def summarize(samples, metadata, enforce=False):
    result, failures = {}, []
    for clip in ('Walk', 'Jog'):
        rows = samples[clip][:-1]
        info = metadata['clips'][clip]
        fps = len(rows)/info['duration']
        trajectories = {}
        for name in ('LeftFoot', 'RightFoot', 'LeftLowerLeg', 'RightLowerLeg', 'LeftHand', 'RightHand', 'Hips'):
            trajectories[name] = trajectory([row['positions'][name] for row in rows], fps)
        arms = {}
        for side in SIDES:
            swings, flexions, abductions, hand_offsets = [], [], [], []
            for row in rows:
                p = row['positions']
                up = unit(sub(p['Neck'], p['Chest']))
                left = unit(sub(p['LeftUpperArm'], p['RightUpperArm']))
                forward = unit(cross(left, up))
                shoulder, elbow, hand = (p[side+n] for n in ('UpperArm', 'LowerArm', 'Hand'))
                upper = sub(elbow, shoulder)
                swings.append(math.degrees(math.atan2(dot(upper, forward), -dot(upper, up))))
                flexions.append(180-angle(sub(shoulder, elbow), sub(hand, elbow)))
                abductions.append(math.degrees(math.atan2(abs(dot(upper, left)), -dot(upper, up))))
                hand_offsets.append(dot(sub(hand, shoulder), forward))
            arms[side] = {'upper_arm_sagittal_min_degrees': min(swings),
                          'upper_arm_sagittal_max_degrees': max(swings),
                          'elbow_flexion_min_degrees': min(flexions),
                          'elbow_flexion_max_degrees': max(flexions),
                          'elbow_flexion_span_degrees': max(flexions)-min(flexions),
                          'upper_arm_abduction_max_degrees': max(abductions),
                          'hand_forward_of_shoulder_min_m': min(hand_offsets),
                          'hand_forward_of_shoulder_max_m': max(hand_offsets)}
        pelvis_extrema = extrema([row['positions']['Hips'][2] for row in rows])
        result[clip] = {'duration_seconds': info['duration'], 'baked_frame_intervals': len(rows),
                        'speed_mps': info['nominal_speed'], 'cadence_steps_per_minute': 120/info['duration'],
                        'step_length_m': info['nominal_speed']*info['duration']/2,
                        'stride_length_m': info['nominal_speed']*info['duration'],
                        'trajectories': trajectories, 'arms_relative_to_chest': arms,
                        'pelvis_vertical_extrema_per_stride': pelvis_extrema}
        if not enforce:
            continue
        expected = (1.05, 63, 1.47) if clip == 'Walk' else (.7, 42, 1.96)
        if abs(info['duration']-expected[0]) > 1e-6 or len(rows) != expected[1] or abs(info['nominal_speed']*info['duration']-expected[2]) > 1e-6:
            failures.append(clip+': period/stride does not match the authored speed')
        if pelvis_extrema != {'maxima': 2, 'minima': 2}:
            failures.append(clip+': pelvis must have one rise/fall pair per step')
        # These reject the measured source discontinuities while allowing normal
        # acceleration during push-off and landing. Keep the raw values visible.
        limits = {'Foot': .85 if clip == 'Walk' else .95,
                  'LowerLeg': 1.6, 'Hand': .40, 'Hips': .22}
        for name, values in trajectories.items():
            stem = name.removeprefix('Left').removeprefix('Right')
            if values['max_adjacent_velocity_change_mps'] > limits[stem]:
                failures.append(clip+': abrupt baked velocity change: '+name)
        if clip == 'Jog':
            for side, values in arms.items():
                if values['upper_arm_sagittal_min_degrees'] > -20 or values['upper_arm_sagittal_max_degrees'] < 12:
                    failures.append('Jog: missing forward/rearward arm swing: '+side)
                if values['elbow_flexion_span_degrees'] < 12:
                    failures.append('Jog: elbow remains fixed: '+side)
                if values['hand_forward_of_shoulder_min_m'] > .03:
                    failures.append('Jog: hand never recovers beside the trunk: '+side)
    return {'validation_mode': 'acceptance' if enforce else 'observe_only',
            'coordinate_system': '+X left, -Y forward, +Z up; metres',
            'derivatives': 'cyclic forward finite differences at evaluated 60Hz poses; terminal duplicate excluded',
            'limits_are': 'production regression thresholds, not medical ideals',
            'clips': result, 'failures': failures}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples', type=Path, default=ROOT/'source/motion_samples.json')
    parser.add_argument('--metadata', type=Path, default=ROOT/'addons/walkers/assets/motions.json')
    parser.add_argument('--output', type=Path, default=ROOT/'reports/motion_curve_analysis.json')
    parser.add_argument('--observe-only', action='store_true')
    parser.add_argument('--evaluate-current-blend', action='store_true', help='Run inside Blender and evaluate its editable FK rig')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    metadata = json.loads(args.metadata.read_text())
    if args.evaluate_current_blend:
        import bpy
        rig = bpy.data.objects['Humanoid']
        rig['preview_root_motion'] = 0.
        rig['foot_ik_Left'] = rig['foot_ik_Right'] = 0.
        for track in rig.animation_data.nla_tracks:
            track.mute = True
        samples = {}
        for clip in ('Walk', 'Jog'):
            rig.animation_data.action = bpy.data.actions[clip]
            rig.update_tag()
            rows = []
            for frame in range(metadata['clips'][clip]['frames']+1):
                bpy.context.scene.frame_set(frame)
                bpy.context.view_layer.update()
                evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
                rows.append({'positions': {bone.name: list(bone.matrix.translation) for bone in evaluated.pose.bones}})
            samples[clip] = rows
        source = {'kind': 'evaluated_Blender_FK', 'blend': Path(bpy.data.filepath).name, 'blend_sha256': hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()}
    else:
        samples = json.loads(args.samples.read_text())
        source = {'kind': 'JSON_position_samples', 'samples': args.samples.name}
    report = summarize(samples, metadata, not args.observe_only)
    report['measurement_source'] = source
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print('MOTION_CURVE_ANALYSIS', report['failures'])
    if args.evaluate_current_blend:
        sys.stdout.flush()
        os._exit(int(bool(report['failures'])))
    raise SystemExit(bool(report['failures']))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        if '--evaluate-current-blend' in sys.argv:
            import traceback
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)
        raise
