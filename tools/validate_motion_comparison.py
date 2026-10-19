#!/usr/bin/env python3
"""Decode all comparison videos and verify identity, true durations and 60fps PTS."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
from render_motion_comparison import (executable, VIEWS, BODY_VIEWS, panel_size, FEET_TARGET_Z,
                                      FEET_MIN_ORTHO, FEET_FRAME_MARGIN)

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=ROOT/'previews/comparison')
    parser.add_argument('--output', type=Path, default=ROOT/'reports/comparison_validation.json')
    args = parser.parse_args()
    inventory = json.loads((args.directory/'inventory.json').read_text())
    ffmpeg, ffprobe = executable('ffmpeg'), executable('ffprobe')
    failures, files = [], {}
    expected = {f'{clip}_{view}_{speed}.mp4' for clip in ['Walk', 'Jog']
                for view in VIEWS for speed in ['normal', 'slow']}
    if inventory.get('source_fps') != 60 or inventory.get('encoded_fps') != 60:
        failures.append('source samples and encoded comparisons must be 60Hz')
    if inventory.get('schema') != 2:
        failures.append('comparison inventory must use camera-aware schema 2')
    listed = [entry['path'] for entry in inventory['files']]
    if set(listed) != expected or len(listed) != len(expected):
        failures.append('inventory does not list each of the 24 comparisons exactly once')
    actual = {p.name for p in args.directory.glob('*.mp4')}
    if expected != actual:
        failures.append('missing/unexpected comparison video: '+repr(expected ^ actual))
    current_hash = hashlib.sha256((ROOT/'source/character.blend').read_bytes()).hexdigest()
    if current_hash != inventory['source_hashes']['after_blend']:
        failures.append('comparison does not match current Blender source')
    metadata_hash = hashlib.sha256((ROOT/'addons/walkers/assets/motions.json').read_bytes()).hexdigest()
    if metadata_hash != inventory['source_hashes'].get('after_metadata'):
        failures.append('comparison does not match current motion metadata')
    camera_settings = inventory.get('camera_settings', {})
    if set(camera_settings) != set(VIEWS):
        failures.append('six shared camera settings are required')
    measurements = inventory.get('framing_measurements', {})
    framing_checks = {}
    for version in ('before', 'after'):
        measurement = measurements.get(version, {})
        if measurement.get('source_blend_sha256') != inventory['source_hashes'][version+'_blend']:
            failures.append(version+': framing measurement source differs from rendered source')
        if measurement.get('source_metadata_sha256') != inventory['source_hashes'].get(version+'_metadata'):
            failures.append(version+': framing metadata differs from rendered metadata')
        cycles = {entry['clip']: entry['source_cycle_seconds'][version] for entry in inventory['files']}
        expected_samples = sum(round(value*60) for value in cycles.values())
        if measurement.get('sample_count', 0) != expected_samples or measurement.get('foot_vertex_count', 0) < 1:
            failures.append(version+': framing must include all Walk/Jog 60Hz samples and foot/toe vertices')
    for view, camera in camera_settings.items():
        width, height = panel_size(view)
        if camera.get('panel_pixels') != [width, height] or camera.get('view') != view:
            failures.append(view+': inconsistent source panel or camera view')
        if camera.get('floor_y_px') != round((1-camera.get('floor_projected_v', -1))*height):
            failures.append(view+': floor line differs from Blender projection')
        if not 0 <= camera.get('floor_y_px', -1) < height:
            failures.append(view+': projected floor is outside the panel')
        if view in BODY_VIEWS:
            if abs(camera.get('target_z_m', -1)-.94) > 1e-6 or abs(camera.get('orthographic_scale_m', -1)-2.22) > 1e-6:
                failures.append(view+': whole-body framing changed')
            continue
        if camera.get('sensor_fit') != 'VERTICAL':
            failures.append(view+': landscape foot camera must preserve vertical orthographic scale')
        if abs(camera.get('target_z_m', -1)-FEET_TARGET_Z) > 1e-6:
            failures.append(view+': foot camera target height differs from shared framing')
        scale = camera.get('orthographic_scale_m', 0)
        requirements = [m.get('required_ortho_m', {}).get(view, float('inf')) for m in measurements.values()]
        required = max([FEET_MIN_ORTHO, *requirements])
        if not requirements or abs(scale-required) > 1e-6:
            failures.append(view+': foot crop does not fit both source measurements')
        projected_bounds = {}
        for version, measurement in measurements.items():
            raw = measurement.get('projected_bounds_at_minimum_ortho', {}).get(view, [])
            bounds = [.5+(v-.5)*FEET_MIN_ORTHO/scale for v in raw] if scale else []
            projected_bounds[version] = bounds
            if len(bounds) != 4 or min(bounds) < FEET_FRAME_MARGIN-1e-6 or max(bounds) > 1-FEET_FRAME_MARGIN+1e-6:
                failures.append(version+' '+view+': full-cycle foot mesh would clip the camera margin')
        framing_checks[view] = {'target_z_m': FEET_TARGET_Z, 'orthographic_scale_m': scale,
                                'projected_bounds': projected_bounds, 'margin_fraction': FEET_FRAME_MARGIN}
    for entry in inventory['files']:
        path = args.directory/entry['path']
        if not path.is_file():
            failures.append(path.name+': listed video is missing')
            continue
        view = entry['view']
        if entry.get('camera') != camera_settings.get(view):
            failures.append(path.name+': before/after shared camera evidence differs')
        expected_name = f"{entry['clip']}_{view}_{'normal' if entry['speed'] == 1 else 'slow'}.mp4"
        if path.name != expected_name or entry['speed'] not in (1., .5):
            failures.append(path.name+': identity or playback speed mismatch')
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != entry['sha256']:
            failures.append(path.name+': hash mismatch')
        probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_frames',
            '-show_entries', 'stream=width,height,r_frame_rate,duration:frame=best_effort_timestamp_time', '-of', 'json', str(path)]))
        times = [float(row['best_effort_timestamp_time']) for row in probe['frames']]
        gaps = [b-a for a, b in zip(times, times[1:])]
        stream = probe['streams'][0]
        if stream['r_frame_rate'] != '60/1' or len(times) != entry['output_frames']:
            failures.append(path.name+': frame count or frame rate mismatch')
        if not times or abs(times[0]) > 1e-6 or any(abs(gap-1/60) > 2e-6 for gap in gaps):
            failures.append(path.name+': irregular display timestamps')
        periods = [round(value*60) for value in entry['source_cycle_seconds'].values()]
        normal_frames = math.lcm(*periods)
        normal_frames *= max(1, math.ceil(360/normal_frames))
        if entry['output_frames'] != round(normal_frames/entry['speed']):
            failures.append(path.name+': output is not a full, equal-time repetition of source cycles')
        if abs(float(stream['duration'])-entry['duration_seconds']) > 1e-6:
            failures.append(path.name+': duration mismatch')
        width, height = panel_size(view)
        if [stream['width'], stream['height']] != [2*width, height+24]:
            failures.append(path.name+': dimensions differ from matched source cameras')
        decode = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-f', 'null', '-'], capture_output=True, text=True, timeout=120)
        if decode.returncode or decode.stderr.strip():
            failures.append(path.name+': full decode failed '+decode.stderr[-400:])
        files[path.name] = {'sha256': sha, 'decoded_frames': len(times), 'frame_rate': stream['r_frame_rate'],
            'duration_seconds': float(stream['duration']), 'view': view, 'camera': entry.get('camera'), 'speed': entry['speed'], 'source_cycle_seconds': entry['source_cycle_seconds'],
            'frame_interval_seconds_min': min(gaps, default=None), 'frame_interval_seconds_max': max(gaps, default=None), 'full_decode': 'pass' if not decode.returncode else 'fail'}
    report = {'status': 'pass' if not failures else 'fail', 'source_hashes': inventory['source_hashes'],
              'camera_framing_checks': framing_checks, 'expected_video_count': len(expected),
              'total_decoded_frames': sum(row['decoded_frames'] for row in files.values()), 'files': files,
              'visual_review': 'reports/comparison_visual_review.json',
              'scope': 'All pixels decoded and all PTS checked. Motion aesthetics are reviewed separately; timing checks alone do not establish natural motion.',
              'failures': failures}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print('COMPARISON_VALIDATION', len(files), 'videos', report['total_decoded_frames'], 'frames', failures)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
