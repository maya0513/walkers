#!/usr/bin/env python3
"""Render genuine 60Hz Action samples and make matched before/after MP4s.

Usage (system Python, not Blender):
  /usr/bin/python3 tools/render_motion_comparison.py \
      --before /tmp/walkers-contact-before/source/character.blend \
      --before-metadata /tmp/walkers-contact-before/addons/walkers/assets/motions.json

Only one source cycle is rendered. ffmpeg repeats the actual cycle at 60fps,
without retiming GIF frames. Both figures retain the same scale, camera and light.
Workbench is the inexpensive inspection default; --engine eevee matches GIF light.
The old source must be supplied explicitly when reproducing a later comparison.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BODY_VIEWS = ('front', 'side', 'three_quarter')
VIEWS = BODY_VIEWS + tuple('feet_'+view for view in BODY_VIEWS)
VIEW_LABELS = {'front': '全身・正面', 'side': '全身・側面', 'three_quarter': '全身・斜め',
               'feet_front': '足元・正面', 'feet_side': '足元・側面', 'feet_three_quarter': '足元・斜め'}
BODY_PANEL_SIZE = (320, 400)
FEET_PANEL_SIZE = (640, 320)


def panel_size(view):
    return FEET_PANEL_SIZE if view.startswith('feet_') else BODY_PANEL_SIZE
FEET_TARGET_Z = .28
FEET_MIN_ORTHO = .8
FEET_FRAME_MARGIN = .06


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--before-metadata', type=Path)
    parser.add_argument('--after', type=Path, default=ROOT/'source/character.blend')
    parser.add_argument('--after-metadata', type=Path, default=ROOT/'addons/walkers/assets/motions.json')
    parser.add_argument('--output', type=Path, default=ROOT/'previews/comparison')
    parser.add_argument('--cache', type=Path, default=ROOT/'previews/.frames/comparison')
    parser.add_argument('--engine', choices=('workbench', 'eevee'), default='workbench')
    parser.add_argument('--clips', default='Walk,Jog')
    parser.add_argument('--views', default=','.join(VIEWS))
    parser.add_argument('--keep-frames', action='store_true')
    parser.add_argument('--framing', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--measure-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--metadata', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker-output', type=Path, help=argparse.SUPPRESS)
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)


def place_comparison_camera(camera, view, framing):
    import bpy
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    is_feet = view.startswith('feet_')
    base_view = view.removeprefix('feet_')
    width, height = panel_size(view)
    bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = width, height
    camera.data.sensor_fit = 'VERTICAL' if is_feet else 'AUTO'
    target_z = FEET_TARGET_Z if is_feet else .94
    camera.data.ortho_scale = framing.get(view, FEET_MIN_ORTHO) if is_feet else 2.22
    xy = {'front': (0, -5), 'side': (5, 0), 'three_quarter': (3.7, -5)}[base_view]
    camera.location = (*xy, target_z)
    camera.rotation_euler = (Vector((0, 0, target_z))-camera.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    floor = world_to_camera_view(bpy.context.scene, camera, Vector((0, 0, 0)))
    return {'target_z_m': target_z, 'orthographic_scale_m': camera.data.ortho_scale,
            'floor_y_px': round((1-floor.y)*height), 'floor_projected_v': floor.y, 'panel_pixels': [width, height],
            'sensor_fit': camera.data.sensor_fit,
            'view': view, 'label': VIEW_LABELS[view], 'framing': 'feet' if is_feet else 'whole_body'}


def measure_feet(args, rig, camera, meta):
    """Fit both feet across every source sample; use the same crop on both revisions.

    A fixed .8m high portrait crop can truncate a forward/rearward foot. Start at
    .8m, then grow the crop around z=.28 until all weighted foot vertices fit,
    including the animated toes. This is camera fitting, not a contact metric.
    """
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    body = bpy.data.objects['Humanoid_CC0']
    foot_groups = {g.index for g in body.vertex_groups if g.name in
                   ('LeftFoot', 'RightFoot', 'LeftToes', 'RightToes')}
    indices = [v.index for v in body.data.vertices
               if sum(g.weight for g in v.groups if g.group in foot_groups) > .1]
    if not indices:
        raise ValueError('No deforming foot/toe vertices found for comparison framing')
    feet_views = [view for view in args.views.split(',') if view.startswith('feet_')]
    required = {view: FEET_MIN_ORTHO for view in feet_views}
    bounds = {view: [1., 0., 1., 0.] for view in feet_views}
    sample_count = 0
    for clip in args.clips.split(','):
        rig.animation_data.action = bpy.data.actions[clip]
        for frame in range(meta['clips'][clip]['frames']):
            bpy.context.scene.frame_set(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = body.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh()
            points = [evaluated.matrix_world @ mesh.vertices[i].co for i in indices]
            evaluated.to_mesh_clear()
            for view in feet_views:
                place_comparison_camera(camera, view, {})
                projected = [world_to_camera_view(bpy.context.scene, camera, point) for point in points]
                extrema = [min(p.x for p in projected), max(p.x for p in projected),
                           min(p.y for p in projected), max(p.y for p in projected)]
                for k in (0, 2):
                    bounds[view][k] = min(bounds[view][k], extrema[k])
                    bounds[view][k+1] = max(bounds[view][k+1], extrema[k+1])
                expansion = max(abs(v-.5)/(.5-FEET_FRAME_MARGIN) for v in extrema)
                required[view] = max(required[view], FEET_MIN_ORTHO*expansion)
            sample_count += 1
    args.worker_output.mkdir(parents=True, exist_ok=True)
    (args.worker_output/'framing_measurement.json').write_text(json.dumps({
        'source_blend_sha256': hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        'source_metadata_sha256': hashlib.sha256(args.metadata.read_bytes()).hexdigest(),
        'sample_count': sample_count, 'foot_vertex_count': len(indices),
        'minimum_ortho_m': FEET_MIN_ORTHO, 'target_z_m': FEET_TARGET_Z,
        'margin_fraction': FEET_FRAME_MARGIN, 'required_ortho_m': required,
        'projected_bounds_at_minimum_ortho': bounds}, indent=2)+'\n')
    print('COMPARISON_FRAMING', required, flush=True)


def worker(args):
    import bpy
    sys.path.insert(0, str(ROOT/"tools"))
    from render_previews import setup
    rig, camera = setup(args.engine == 'eevee', args.engine == 'workbench')
    scene = bpy.context.scene
    meta = json.loads(args.metadata.read_text())
    if args.measure_only:
        measure_feet(args, rig, camera, meta)
        sys.stdout.flush()
        os._exit(0)
    framing = json.loads(args.framing.read_text()) if args.framing else {}
    cameras = {}
    for clip in args.clips.split(','):
        info = meta['clips'][clip]
        rig.animation_data.action = bpy.data.actions[clip]
        if not info['loop'] or abs(info['duration']*60-info['frames']) > 1e-5:
            raise ValueError('Comparison expects an exact 60Hz cyclic Action: '+clip)
        for view in args.views.split(','):
            cameras[view] = place_comparison_camera(camera, view, framing)
            out = args.worker_output/clip/view
            out.mkdir(parents=True, exist_ok=True)
            for frame in range(info['frames']):
                path = out/f'{frame:04d}.png'
                if path.exists():
                    continue
                scene.frame_set(frame)
                scene.render.filepath = str(path)
                bpy.ops.render.render(write_still=True)
            print('COMPARISON_RENDERED', clip, view, info['frames'], 'floor', cameras[view]['floor_y_px'], flush=True)
    (args.worker_output/'cameras.json').write_text(json.dumps(cameras, indent=2)+'\n')
    sys.stdout.flush()
    os._exit(0)


def executable(name):
    # mise shims can attempt to alter a read-only config during tool invocation.
    candidates = list((Path.home()/'.local/share/mise/installs/conda-ffmpeg').glob('*/bin/'+name))
    direct = shutil.which(name)
    if direct:
        candidates.append(Path(direct))
    for candidate in candidates:
        try:
            subprocess.run([str(candidate), '-version'], capture_output=True, check=True, timeout=5)
            return str(candidate)
        except (OSError, subprocess.SubprocessError):
            pass
    raise RuntimeError(name+' is required')


def write_gallery(inventory, output):
    pages = json.dumps(inventory['files'], ensure_ascii=False)
    (output/'index.html').write_text("""<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>歩行・ジョギングの比較</title>
<style>body{margin:24px;background:#fafaf8;color:#444;font:14px system-ui,sans-serif}h1{font-size:18px;font-weight:500}select{font:inherit;padding:5px;background:white;border:1px solid #ccc;margin-right:8px}video{display:block;width:min(100%,1280px);margin:16px 0}p{max-width:700px;line-height:1.7}a{color:#555}</style>
<h1>修正前後の比較</h1><select id="clip"></select><select id="view"></select><select id="speed"><option value="1">通常速度</option><option value="0.5">0.5倍速</option></select>
<video controls loop playsinline id="video"></video><p id="timing"></p><p id="framing"></p><p>左が修正前、右が修正後です。同じ縮尺・視点・照明で、BlenderのActionを60Hzで新規に評価しています。スローは元60Hzの姿勢を毎秒30枚ずつ送り、出力60fpsへ複製しています。GIFの時間丸めを含みません。</p>
<p><a href="../../docs/gait_reference.ja.md">歩行・ジョギングの見方と参考文献</a> · <a href="README.ja.md">生成条件</a> · <a href="../index.html">連続画像・GIF</a></p>
<script>const data=__DATA__,clip=document.querySelector('#clip'),view=document.querySelector('#view'),speed=document.querySelector('#speed'),video=document.querySelector('#video');clip.innerHTML=[...new Set(data.map(x=>x.clip))].map(x=>'<option>'+x+'</option>').join('');view.innerHTML=[...new Set(data.map(x=>x.view))].map(x=>'<option value="'+x+'">'+(__LABELS__[x])+'</option>').join('');view.value='side';function show(){let x=data.find(x=>x.clip===clip.value&&x.view===view.value&&x.speed===Number(speed.value));video.src=x.path;video.style.width='min(100%,'+(x.view.startsWith('feet_')?1280:640)+'px)';document.querySelector('#timing').textContent='元の1周期: 修正前 '+x.source_cycle_seconds.before.toFixed(2)+'秒 / 修正後 '+x.source_cycle_seconds.after.toFixed(2)+'秒。一歩: 修正前 '+(x.source_step_lengths_m.before*100).toFixed(1)+'cm / 修正後 '+(x.source_step_lengths_m.after*100).toFixed(1)+'cm。';document.querySelector('#framing').textContent=x.camera.label+'：片側'+x.camera.panel_pixels.join('×')+'px、注視高さ'+x.camera.target_z_m.toFixed(2)+'m、正投影の範囲'+x.camera.orthographic_scale_m.toFixed(2)+'m。足元は両版の足先の全軌道が収まる共通範囲です。';}clip.onchange=view.onchange=speed.onchange=show;show();</script></html>""".replace('__DATA__', pages).replace('__LABELS__', json.dumps(VIEW_LABELS, ensure_ascii=False)))


def main():
    args = arguments()
    if args.worker:
        worker(args)
    if set(args.views.split(','))-set(VIEWS):
        raise ValueError('Unknown comparison view')
    if not args.before or not args.before_metadata:
        raise SystemExit('--before and --before-metadata are required')
    os.environ.setdefault('XDG_CACHE_HOME', '/tmp/walkers-comparison-cache')
    Path(os.environ['XDG_CACHE_HOME']).mkdir(parents=True, exist_ok=True)
    ffmpeg, ffprobe = executable('ffmpeg'), executable('ffprobe')
    blender = shutil.which('blender')
    if not blender:
        raise RuntimeError('Blender is required')
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(b''.join(p.read_bytes() for p in (args.before, args.before_metadata, args.after, args.after_metadata, Path(__file__), ROOT/'tools/render_previews.py'))+args.engine.encode()).hexdigest()
    marker = args.cache/'signature.txt'
    if marker.exists() and marker.read_text() != signature:
        shutil.rmtree(args.cache)
        args.cache.mkdir()
    marker.write_text(signature)
    sources = [('before', args.before, args.before_metadata), ('after', args.after, args.after_metadata)]
    measurements = {}
    for version, blend, metadata in sources:
        command = [blender, '-b', str(blend), '-noaudio', '--python-exit-code', '1', '--python', str(Path(__file__)), '--',
                   '--worker', '--measure-only', '--metadata', str(metadata), '--worker-output', str(args.cache/version),
                   '--engine', args.engine, '--clips', args.clips, '--views', args.views]
        with (args.cache/(version+'_measurement.log')).open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
        measurements[version] = json.loads((args.cache/version/'framing_measurement.json').read_text())
    framing = {view: max(row['required_ortho_m'][view] for row in measurements.values())
               for view in args.views.split(',') if view.startswith('feet_')}
    framing_path = args.cache/'framing.json'
    framing_path.write_text(json.dumps(framing))
    camera_records = {}
    for version, blend, metadata in sources:
        command = [blender, '-b', str(blend), '-noaudio', '--python-exit-code', '1', '--python', str(Path(__file__)), '--',
                   '--worker', '--framing', str(framing_path), '--metadata', str(metadata), '--worker-output', str(args.cache/version),
                   '--engine', args.engine, '--clips', args.clips, '--views', args.views]
        with (args.cache/(version+'.log')).open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
        camera_records[version] = json.loads((args.cache/version/'cameras.json').read_text())
    if camera_records['before'] != camera_records['after']:
        raise RuntimeError('Before and after source cameras differ')
    before = json.loads(args.before_metadata.read_text())
    after = json.loads(args.after_metadata.read_text())
    inventory = {'schema': 2, 'source_fps': 60, 'encoded_fps': 60, 'render_engine': args.engine,
                 'sampling': 'fresh Action samples, one terminal-free cycle, looped at true 60Hz; no GIF input',
                 'source_hashes': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in [('before_blend', args.before), ('after_blend', args.after),
                        ('before_metadata', args.before_metadata), ('after_metadata', args.after_metadata)]},
                 'framing_measurements': measurements, 'camera_settings': camera_records['after'],
                 'visual_review_note': 'Decoded frames and equal timestamps do not establish real-time aesthetic viewing; record actual review method separately.',
                 'files': []}
    for clip in args.clips.split(','):
        # Use an integer number of both source cycles, at least six seconds.
        periods = [before['clips'][clip]['frames'], after['clips'][clip]['frames']]
        normal_frames = math.lcm(*periods)
        normal_frames *= max(1, math.ceil(360/normal_frames))
        for view in args.views.split(','):
            for slow in (False, True):
                speed = .5 if slow else 1.
                input_fps = int(60*speed)
                output_frames = round(normal_frames/speed)
                path = args.output/f'{clip}_{view}_{"slow" if slow else "normal"}.mp4'
                camera_info = camera_records['after'][view]
                floor_y = camera_info['floor_y_px']
                width, height = camera_info['panel_pixels']
                filtergraph = (
                    f"color=c=0xfafaf8:s={width}x{height}:r=60[bg0];"
                    f"color=c=0xfafaf8:s={width}x{height}:r=60[bg1];"
                    f"[bg0][0:v]overlay=shortest=1:format=auto,format=rgb24,drawbox=x=0:y={floor_y}:w={width}:h=1:color=0xc3c3bf:t=fill,"
                    "pad=iw:ih+24:0:24:color=0xfafaf8,drawtext=text='Before':x=10:y=5:fontsize=14:fontcolor=0x555555[a];"
                    f"[bg1][1:v]overlay=shortest=1:format=auto,format=rgb24,drawbox=x=0:y={floor_y}:w={width}:h=1:color=0xc3c3bf:t=fill,"
                    "pad=iw:ih+24:0:24:color=0xfafaf8,drawtext=text='After':x=10:y=5:fontsize=14:fontcolor=0x555555[b];"
                    "[a][b]hstack=inputs=2,format=yuv420p[out]")
                command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                           '-stream_loop', '-1', '-framerate', str(input_fps), '-i', str(args.cache/'before'/clip/view/'%04d.png'),
                           '-stream_loop', '-1', '-framerate', str(input_fps), '-i', str(args.cache/'after'/clip/view/'%04d.png'),
                           '-filter_complex', filtergraph, '-map', '[out]', '-r', '60', '-frames:v', str(output_frames),
                           '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-threads', '4', '-movflags', '+faststart', str(path)]
                subprocess.run(command, check=True, timeout=180)
                probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                                                           '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames,duration', '-of', 'json', str(path)]))['streams'][0]
                if probe['r_frame_rate'] != '60/1' or int(probe['nb_read_frames']) != output_frames:
                    raise RuntimeError('Incorrect comparison timing: '+str(path))
                subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True, timeout=120)
                inventory['files'].append({'path': path.name, 'clip': clip, 'view': view, 'speed': speed,
                                           'camera': camera_info, 'source_cycle_seconds': {'before': periods[0]/60, 'after': periods[1]/60},
                                           'source_step_lengths_m': {label: meta['clips'][clip]['duration']*meta['clips'][clip]['nominal_speed']/2 for label, meta in [('before', before), ('after', after)]},
                                           'output_frames': output_frames, 'duration_seconds': output_frames/60,
                                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'probe': probe})
                print('COMPARISON_ENCODED', path.name, output_frames, flush=True)
    (args.output/'inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')
    (args.output/'README.ja.md').write_text('''# 歩行・ジョギングの修正前後比較

左が修正前、右が修正後です。人物の縮尺・視点・照明は共通です。
`normal`は実時間、`slow`は0.5倍速で、いずれも60fpsのMP4です。
GIFからの変換ではなく、BlenderのActionを新規に60Hzで評価しています。
スローは元60Hzサンプルを30Hzで送り、60fpsへ複製して表示します。
そのためスロー映像の独立した姿勢サンプル数は毎秒30枚です。
輪郭・リズム・手足の運びを見やすくするためWorkbenchの検査用照明を使っています。
全身の正面・側面・斜めと、足元の正面・側面・斜めを比較できます。
全身は片側320×400px、注視高さ0.94m・正投影範囲2.22mです。
足元は両足を大きく見られる横長の片側640×320px、注視高さ0.28mを共通にします。
足元カメラは縦範囲を基準にし、範囲0.8mを最小値として、
両版の全周期の足・つま先メッシュが画面の内側6%へ収まるまで各視点を広げます。
そのため側面では、足が前後に開いても途切れずに見られます。
床線はBlenderカメラから床上の点を実際に投影して決定します。
原周期・歩幅・フレーム数・カメラ値・範囲の計測・ハッシュはinventory.jsonに記録しています。

数値検証は全フレームの復号と表示時刻を対象にします。美的な動作レビューとは別です。
姿勢列だけを確認した場合は、実時間で映像を視聴したと記載しないでください。

再生成には旧版のBlenderとmotions.jsonを明示的に渡します。
`tools/render_motion_comparison.py --help`を参照してください。
''')
    write_gallery(inventory, args.output)
    if not args.keep_frames:
        shutil.rmtree(args.cache)


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        if '--worker' in sys.argv:
            import traceback
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)
        raise
