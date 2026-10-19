#!/usr/bin/env python3
"""Decode all delivered strips and GIF frames; individual source frames are temporary."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ["front", "side", "three_quarter"]


def validate_dataset(directory, require_runtime=True):
    directory = Path(directory)
    inventory = json.loads((directory/"inventory.json").read_text())
    failures, sheets, decoded_frames, gifs = [], 0, 0, {}
    divisions = inventory["pose_divisions"]
    expected_gifs = set()
    floor_lines = set()
    optional_runtime = {"Runtime.gif", "Runtime_slow.gif"}
    for clip, info in inventory["clips"].items():
        if set(info["views"]) != set(VIEWS):
            failures.append(clip+": missing view")
        for view, record in info["views"].items():
            expected_gifs.add(Path(record["gif"]).name)
            floor_lines.add(record["strip"]["floor_y"])
            path = directory/record["sheet"]
            try:
                with Image.open(path) as image:
                    image.load()
                    if list(image.size) != record["strip"]["size"] or image.height != 300 or image.width < (divisions+1)*40:
                        failures.append(str(path)+": strip dimensions")
                    if max(ImageStat.Stat(image.convert("RGB")).var) < 5:
                        failures.append(str(path)+": blank strip")
                sheets += 1
            except (OSError, ValueError) as error:
                failures.append(str(path)+": "+str(error))
            if record["strip"]["pose_count"] != divisions+1:
                failures.append(clip+" "+view+": boundary poses missing")
            if info["loop"] and record["strip"]["boundary_mean_pixel_difference"] > .5:
                failures.append(clip+" "+view+": rendered cycle boundary differs")
            times = record["animation"]["sample_times_seconds"]
            if not times or abs(times[0]) > 1e-6:
                failures.append(clip+" "+view+": missing initial sample")
            if info["loop"]:
                expected_count = max(1, round(info["duration"]*25))
                gaps = [b-a for a, b in zip(times, times[1:])]+[info["duration"]-times[-1]]
                if len(times) != expected_count or any(abs(gap-info["duration"]/expected_count) > 1e-6 for gap in gaps):
                    failures.append(clip+" "+view+": GIF cycle phase is not uniformly sampled")
                animation = record["animation"]
                encoded = len(times)*.04
                if abs(animation.get("source_duration_seconds", -1)-info["duration"]) > 1e-6 or abs(animation.get("encoded_motion_duration_seconds", -1)-encoded) > 1e-6 or abs(animation.get("encoded_to_source_duration_ratio", -1)-encoded/info["duration"]) > 1e-6:
                    failures.append(clip+" "+view+": missing/inaccurate GIF timing provenance")
            else:
                for a, b in zip(times, times[1:]):
                    if abs((b-a)-.04) > 1e-6 and not (b == times[-1] and 0 < b-a <= .04+1e-6):
                        failures.append(clip+" "+view+": event GIF was not sampled at 25Hz")
            if info["loop"] and times[-1] >= info["duration"]:
                failures.append(clip+" "+view+": duplicated GIF cycle boundary")
            if not info["loop"] and abs(times[-1]-info["duration"]) > 1e-6:
                failures.append(clip+" "+view+": event end pose missing")
            if record["animation"]["reset_ms"] != (0 if info["loop"] else 320):
                failures.append(clip+" "+view+": reset interval")
    if "shared_vertical_crop" not in inventory or len(floor_lines) != 1:
        failures.append("strips do not share one scale/floor line")
    if require_runtime:
        expected_gifs.update(["Runtime.gif", "Runtime_slow.gif"])
    for path in sorted((directory/"gifs").glob("*.gif")):
        if path.name not in expected_gifs:
            if path.name in optional_runtime and not require_runtime:
                continue
            failures.append("unexpected/stale GIF: "+path.name)
            continue
        try:
            with Image.open(path) as image:
                duration, distinct = 0, image.n_frames
                for index in range(image.n_frames):
                    image.seek(index)
                    image.load()
                    duration += image.info.get("duration", 0)
                    if image.info.get("duration", 0) <= 0:
                        failures.append(path.name+": nonpositive frame duration")
                if image.info.get("loop") != 0:
                    failures.append(path.name+": not looping")
                if distinct < 2 and not path.name.startswith("Idle_"):
                    failures.append(path.name+": frozen")
                gifs[path.name] = {"frames": distinct, "duration_ms": duration, "size": list(image.size)}
                decoded_frames += distinct
        except (OSError, ValueError) as error:
            failures.append(path.name+": "+str(error))
    for name in expected_gifs-set(gifs):
        failures.append("missing GIF: "+name)
    for clip, info in inventory["clips"].items():
        for view, record in info["views"].items():
            name = Path(record["gif"]).name
            if name in gifs:
                if gifs[name]["duration_ms"] != record["animation"]["duration_ms"]:
                    failures.append(name+": duration mismatch")
                if gifs[name]["size"] != [320, 400]:
                    failures.append(name+": unexpected dimensions")
    return {"pose_divisions": divisions, "poses_per_strip": divisions+1,
            "decoded_pose_strips": sheets, "decoded_gif_frames": decoded_frames,
            "gifs": gifs, "failures": failures}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--no-runtime", action="store_true")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    directory = args.directory or ROOT/"previews"/("probe" if args.probe else "")
    report = validate_dataset(directory, require_runtime=not (args.probe or args.no_runtime))
    expected_clips = {"Idle", "Walk", "Jog"} if args.probe else set(json.loads((ROOT/"addons/walkers/assets/motions.json").read_text())["clips"])
    delivered_clips = set(json.loads((directory/"inventory.json").read_text())["clips"])
    if delivered_clips != expected_clips:
        report["failures"].append("missing/unexpected motion in inventory")
    report_path = ROOT/"reports"/("probe_validation.json" if args.probe else "preview_validation.json")
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2)+"\n")
    print("PREVIEW_VALIDATION", report["decoded_pose_strips"], "strips", len(report["gifs"]), "GIF", report["decoded_gif_frames"], "frames", report["failures"])
    raise SystemExit(bool(report["failures"]))


if __name__ == "__main__":
    main()
