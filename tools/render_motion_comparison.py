#!/usr/bin/env python3
"""Render genuine 60Hz Action samples and make matched before/after MP4s.

Usage (system Python, not Blender):
  /usr/bin/python3 tools/render_motion_comparison.py \
      --before /tmp/walkers-rhythm-before/source/character.blend \
      --before-metadata /tmp/walkers-rhythm-before/addons/walkers/assets/motions.json

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
VIEWS = ('front', 'side', 'three_quarter')


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
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--metadata', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker-output', type=Path, help=argparse.SUPPRESS)
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)


def worker(args):
    import bpy
    sys.path.insert(0, str(ROOT/"tools"))
    from render_previews import setup, place_camera
    rig, camera = setup(args.engine == 'eevee')
    scene = bpy.context.scene
    if args.engine == 'workbench':
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.display.shading.light = 'STUDIO'
        scene.display.shading.studiolight_rotate_z = .4
        scene.display.shading.color_type = 'SINGLE'
        scene.display.shading.single_color = (.48, .48, .48)
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
        scene.display.shading.cavity_type = 'BOTH'
        scene.display.shading.background_type = 'WORLD'
        scene.display.shading.show_specular_highlight = False
        scene.display.render_aa = '8'
    meta = json.loads(args.metadata.read_text())
    for clip in args.clips.split(','):
        info = meta['clips'][clip]
        rig.animation_data.action = bpy.data.actions[clip]
        if not info['loop'] or abs(info['duration']*60-info['frames']) > 1e-5:
            raise ValueError('Comparison expects an exact 60Hz cyclic Action: '+clip)
        for view in args.views.split(','):
            floor = place_camera(camera, view)
            out = args.worker_output/clip/view
            out.mkdir(parents=True, exist_ok=True)
            for frame in range(info['frames']):
                path = out/f'{frame:04d}.png'
                if path.exists():
                    continue
                scene.frame_set(frame)
                scene.render.filepath = str(path)
                bpy.ops.render.render(write_still=True)
            print('COMPARISON_RENDERED', clip, view, info['frames'], 'floor', floor, flush=True)
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
<style>body{margin:24px;background:#fafaf8;color:#444;font:14px system-ui,sans-serif}h1{font-size:18px;font-weight:500}select{font:inherit;padding:5px;background:white;border:1px solid #ccc;margin-right:8px}video{display:block;width:min(100%,640px);margin:16px 0}p{max-width:700px;line-height:1.7}a{color:#555}</style>
<h1>修正前後の比較</h1><select id="clip"></select><select id="view"></select><select id="speed"><option value="1">通常速度</option><option value="0.5">0.5倍速</option></select>
<video controls loop playsinline id="video"></video><p id="timing"></p><p>左が修正前、右が修正後です。同じ縮尺・視点・照明で、BlenderのActionを60Hzで新規に評価しています。スローは元60Hzの姿勢を毎秒30枚ずつ送り、出力60fpsへ複製しています。GIFの時間丸めを含みません。</p>
<p><a href="../../docs/gait_reference.ja.md">歩行・ジョギングの見方と参考文献</a> · <a href="README.ja.md">生成条件</a> · <a href="../index.html">連続画像・GIF</a></p>
<script>const data=__DATA__,clip=document.querySelector('#clip'),view=document.querySelector('#view'),speed=document.querySelector('#speed'),video=document.querySelector('#video');clip.innerHTML=[...new Set(data.map(x=>x.clip))].map(x=>'<option>'+x+'</option>').join('');view.innerHTML=[...new Set(data.map(x=>x.view))].map(x=>'<option value="'+x+'">'+({front:'正面',side:'側面',three_quarter:'斜め'}[x])+'</option>').join('');view.value='side';function show(){let x=data.find(x=>x.clip===clip.value&&x.view===view.value&&x.speed===Number(speed.value));video.src=x.path;document.querySelector('#timing').textContent='元の1周期: 修正前 '+x.source_cycle_seconds.before.toFixed(2)+'秒 / 修正後 '+x.source_cycle_seconds.after.toFixed(2)+'秒。一歩: 修正前 '+(x.source_step_lengths_m.before*100).toFixed(1)+'cm / 修正後 '+(x.source_step_lengths_m.after*100).toFixed(1)+'cm。';}clip.onchange=view.onchange=speed.onchange=show;show();</script></html>""".replace('__DATA__', pages))


def main():
    args = arguments()
    if args.worker:
        worker(args)
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
    for version, blend, metadata in [('before', args.before, args.before_metadata), ('after', args.after, args.after_metadata)]:
        command = [blender, '-b', str(blend), '-noaudio', '--python-exit-code', '1', '--python', str(Path(__file__)), '--',
                   '--worker', '--metadata', str(metadata), '--worker-output', str(args.cache/version),
                   '--engine', args.engine, '--clips', args.clips, '--views', args.views]
        with (args.cache/(version+'.log')).open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    before = json.loads(args.before_metadata.read_text())
    after = json.loads(args.after_metadata.read_text())
    inventory = {'source_fps': 60, 'encoded_fps': 60, 'render_engine': args.engine,
                 'sampling': 'fresh Action samples, one terminal-free cycle, looped at true 60Hz; no GIF input',
                 'source_hashes': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in [('before_blend', args.before), ('after_blend', args.after)]},
                 'files': []}
    for clip in args.clips.split(','):
        # 6.3s is an integer number of all old/new walk and jog cycles.
        periods = [before['clips'][clip]['frames'], after['clips'][clip]['frames']]
        normal_frames = math.lcm(*periods)
        normal_frames *= max(1, math.ceil(360/normal_frames))
        for view in args.views.split(','):
            for slow in (False, True):
                speed = .5 if slow else 1.
                input_fps = int(60*speed)
                output_frames = round(normal_frames/speed)
                path = args.output/f'{clip}_{view}_{"slow" if slow else "normal"}.mp4'
                floor_y = round((.94/2.22+.5)*400)
                filtergraph = (
                    "color=c=0xfafaf8:s=320x400:r=60[bg0];"
                    "color=c=0xfafaf8:s=320x400:r=60[bg1];"
                    f"[bg0][0:v]overlay=shortest=1:format=auto,format=rgb24,drawbox=x=0:y={floor_y}:w=320:h=1:color=0xc3c3bf:t=fill,"
                    "pad=iw:ih+24:0:24:color=0xfafaf8,drawtext=text='Before':x=10:y=5:fontsize=14:fontcolor=0x555555[a];"
                    f"[bg1][1:v]overlay=shortest=1:format=auto,format=rgb24,drawbox=x=0:y={floor_y}:w=320:h=1:color=0xc3c3bf:t=fill,"
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
                                           'source_cycle_seconds': {'before': periods[0]/60, 'after': periods[1]/60},
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
正確な原周期・歩幅・フレーム数・ハッシュはinventory.jsonに記録しています。

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
