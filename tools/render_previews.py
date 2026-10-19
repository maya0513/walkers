"""Render the delivered Actions, with separate 25 Hz animation samples.

Quick review: blender -b source/character.blend --python tools/render_previews.py -- --probe --eevee
Full set:    blender -b source/character.blend --python tools/render_previews.py -- --workbench
Published previews stay intact until assemble_previews.py validates a replacement.
"""
import argparse
import bpy
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ["front", "side", "three_quarter"]


def options():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--eevee", action="store_true")
    parser.add_argument("--workbench", action="store_true")
    parser.add_argument("--clips")
    parser.add_argument("--views")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])


def setup(eevee, workbench=False):
    scene = bpy.context.scene
    rig = bpy.data.objects["Humanoid"]
    body = bpy.data.objects["Humanoid_CC0"]
    # Only the delivered deforming body belongs in the study images.
    for obj in scene.objects:
        obj.hide_render = obj not in [rig, body]
    rig.hide_render = body.hide_render = False
    for track in rig.animation_data.nla_tracks:
        track.mute = True
    rig["preview_root_motion"] = 1.0
    scene.render.engine = "BLENDER_WORKBENCH" if workbench else ("BLENDER_EEVEE" if eevee else "CYCLES")
    if workbench:
        scene.display.shading.light = "STUDIO"
        scene.display.shading.studiolight_rotate_z = .4
        scene.display.shading.color_type = "SINGLE"
        scene.display.shading.single_color = (.48, .48, .48)
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
        scene.display.shading.cavity_type = "BOTH"
        scene.display.shading.background_type = "WORLD"
        scene.display.shading.show_specular_highlight = False
        scene.display.render_aa = "8"
    if eevee and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 16
    scene.cycles.device = "CPU"
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 320, 400
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.render.threads_mode, scene.render.threads = "FIXED", 8
    scene.view_settings.view_transform = "AgX"
    scene.world = bpy.data.worlds.new("PreviewWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.clear()
    background = scene.world.node_tree.nodes.new("ShaderNodeBackground")
    background.inputs[0].default_value = (.8, .8, .8, 1)
    background.inputs[1].default_value = .7
    output = scene.world.node_tree.nodes.new("ShaderNodeOutputWorld")
    scene.world.node_tree.links.new(background.outputs[0], output.inputs[0])
    for name, location, energy, size in [
        ("PreviewKey", (3, -4, 6), 380, 5),
        ("PreviewFill", (-3, -1, 3), 220, 5),
        ("PreviewRim", (1, 3, 4), 180, 4)]:
        light = bpy.data.lights.new(name, "AREA")
        light.energy, light.shape, light.size = energy, "DISK", size
        obj = bpy.data.objects.new(name, light)
        scene.collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = (Vector((0, 0, .9))-obj.location).to_track_quat("-Z", "Y").to_euler()
    camera = bpy.data.objects.new("PreviewCamera", bpy.data.cameras.new("PreviewCamera"))
    scene.collection.objects.link(camera)
    camera.data.type, camera.data.ortho_scale = "ORTHO", 2.22
    scene.camera = camera
    return rig, camera


def place_camera(camera, view):
    # A horizontal optical axis keeps the floor on one line in every strip.
    camera.location = {"front": (0, -5, .94), "side": (5, 0, .94),
                       "three_quarter": (3.7, -5, .94)}[view]
    camera.rotation_euler = (Vector((0, 0, .94))-camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()
    floor = world_to_camera_view(bpy.context.scene, camera, Vector((0, 0, 0)))
    return round((1-floor.y)*400)


def main():
    args = options()
    metadata_path = ROOT/"addons/walkers/assets/motions.json"
    meta = json.loads(metadata_path.read_text())
    blend_path = Path(bpy.data.filepath)
    digest = hashlib.sha256(blend_path.read_bytes()+metadata_path.read_bytes()+Path(__file__).read_bytes()
                            +json.dumps({"eevee": args.eevee, "workbench": args.workbench}).encode()).hexdigest()
    cache = ROOT/"previews/.frames"/("probe" if args.probe else "full")
    manifest_path = cache/"manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if manifest.get("asset_sha256") != digest:
        if cache.exists():
            shutil.rmtree(cache)
        manifest = {"version": 3, "asset_sha256": digest, "probe": args.probe,
                    "render_size": [320, 400], "pose_divisions": 8 if args.probe else 32,
                    "gif_fps": 25, "clips": {}}
    cache.mkdir(parents=True, exist_ok=True)
    clips = args.clips.split(",") if args.clips else (["Idle", "Walk", "Jog"] if args.probe else list(meta["clips"]))
    views = args.views.split(",") if args.views else VIEWS
    if set(clips)-set(meta["clips"]) or set(views)-set(VIEWS):
        raise ValueError("Unknown clip or view")
    rig, camera = setup(args.eevee, args.workbench)
    scene = bpy.context.scene
    divisions = manifest["pose_divisions"]
    for clip in clips:
        info = meta["clips"][clip]
        rig.animation_data.action = bpy.data.actions[clip]
        entry = manifest["clips"].setdefault(clip, {"duration": info["duration"], "loop": info["loop"], "views": {}})
        pose_times = [info["duration"]*i/divisions for i in range(divisions+1)]
        if info["loop"]:
            # All phase gaps, including the last-to-first gap, are identical.
            # GIF durations are multiples of 40ms; retain the exact Action time
            # separately rather than introducing one short terminal interval.
            sample_count = max(1, round(info["duration"]*25))
            gif_times = [i*info["duration"]/sample_count for i in range(sample_count)]
        else:
            gif_times = [i/25 for i in range(max(1, math.ceil(info["duration"]*25-1e-8)))]
            gif_times.append(info["duration"])
        for view in views:
            floor_y = place_camera(camera, view)
            record = {"floor_y": floor_y, "poses": [], "gif": []}
            for kind, times in [("poses", pose_times), ("gif", gif_times)]:
                for i, seconds in enumerate(times):
                    frame = info["frames"]*seconds/info["duration"]
                    scene.frame_set(math.floor(frame), subframe=frame-math.floor(frame))
                    relative = Path(clip)/view/kind/f"{i:03d}.png"
                    path = cache/relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if args.overwrite or not path.exists():
                        scene.render.filepath = str(path)
                        bpy.ops.render.render(write_still=True)
                    record[kind].append({"path": str(relative), "time": seconds})
            entry["views"][view] = record
            print(f"PREVIEW {clip} {view} {len(pose_times)} poses / {len(gif_times)} direct GIF samples", flush=True)
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2)+"\n")
        temporary.replace(manifest_path)
    print("PREVIEWS_RENDERED", cache, flush=True)
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
