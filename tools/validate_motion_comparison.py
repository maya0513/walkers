#!/usr/bin/env python3
"""Decode all comparison videos and verify identity, true durations and 60fps PTS."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from render_motion_comparison import executable

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
                for view in ['front', 'side', 'three_quarter'] for speed in ['normal', 'slow']}
    actual = {p.name for p in args.directory.glob('*.mp4')}
    if expected != actual:
        failures.append('missing/unexpected comparison video: '+repr(expected ^ actual))
    current_hash = hashlib.sha256((ROOT/'source/character.blend').read_bytes()).hexdigest()
    if current_hash != inventory['source_hashes']['after_blend']:
        failures.append('comparison does not match current Blender source')
    for entry in inventory['files']:
        path = args.directory/entry['path']
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
        if abs(float(stream['duration'])-entry['duration_seconds']) > 1e-6:
            failures.append(path.name+': duration mismatch')
        if [stream['width'], stream['height']] != [640, 424]:
            failures.append(path.name+': dimensions differ from matched source cameras')
        decode = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-f', 'null', '-'], capture_output=True, text=True, timeout=120)
        if decode.returncode or decode.stderr.strip():
            failures.append(path.name+': full decode failed '+decode.stderr[-400:])
        files[path.name] = {'sha256': sha, 'decoded_frames': len(times), 'frame_rate': stream['r_frame_rate'],
            'duration_seconds': float(stream['duration']), 'speed': entry['speed'], 'source_cycle_seconds': entry['source_cycle_seconds'],
            'frame_interval_seconds_min': min(gaps), 'frame_interval_seconds_max': max(gaps), 'full_decode': 'pass' if not decode.returncode else 'fail'}
    report = {'status': 'pass' if not failures else 'fail', 'source_hashes': inventory['source_hashes'],
              'total_decoded_frames': sum(row['decoded_frames'] for row in files.values()), 'files': files,
              'visual_review': 'reports/comparison_visual_review.json',
              'scope': 'All pixels decoded and all PTS checked. Motion aesthetics are reviewed separately; timing checks alone do not establish natural motion.',
              'failures': failures}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print('COMPARISON_VALIDATION', len(files), 'videos', report['total_decoded_frames'], 'frames', failures)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
