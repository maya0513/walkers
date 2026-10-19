"""Round-trip actual evaluated mesh contact against delivered metadata."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    original = ROOT/'addons/walkers/assets/motions.json'
    with tempfile.TemporaryDirectory(prefix='walkers-contact-export-') as directory:
        output = Path(directory)/'motions.json'
        result = subprocess.run([shutil.which('blender'), '-b', str(ROOT/'source/character.blend'), '-noaudio',
            '--python', str(ROOT/'tools/export_contact_metadata.py'), '--', '--metadata='+str(original),
            '--output='+str(output)], capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError(result.stdout[-1500:]+result.stderr[-1500:])
        before, after = json.loads(original.read_text()), json.loads(output.read_text())
        maximum = max(math.dist(a, b) for clip in before['clips']
            for old, new in zip(before['clips'][clip]['support_offsets'], after['clips'][clip]['support_offsets'])
            for a, b in zip(old, new))
        samples = sum(len(clip['support_offsets'])*2 for clip in after['clips'].values())
        weight_error = max(abs(sum(entry['weight'] for entry in foot)-1)
            for clip in after['clips'].values() for frame in clip['support_materials'] for foot in frame)
        failures = []
        if maximum > .00002: failures.append('Evaluated mesh contact differs from delivered authored support by >20 micrometres')
        if weight_error > 1e-6: failures.append('Exported support material skin weights do not sum to one')
        if after['support_material_space'] != 'rest_skeleton': failures.append('Missing rest-skeleton material coordinate marker')
        report = {'status':'fail' if failures else 'pass', 'source_blend_sha256':hashlib.sha256((ROOT/'source/character.blend').read_bytes()).hexdigest(),
            'motion_metadata_sha256':hashlib.sha256(original.read_bytes()).hexdigest(), 'clips':len(after['clips']),
            'foot_samples':samples, 'maximum_offset_difference_m':maximum, 'maximum_weight_sum_error':weight_error,
            'method':'Regenerate bindings from Blender evaluated skinned mesh and compare with delivered analytic-author metadata; no Action or mesh edits.',
            'failures':failures}
        (ROOT/'reports/contact_export_validation.json').write_text(json.dumps(report, indent=2)+'\n')
        print('CONTACT_EXPORT_VALIDATION', samples, maximum, failures)
        raise SystemExit(bool(failures))


if __name__ == '__main__': main()
