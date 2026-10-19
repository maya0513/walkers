#!/usr/bin/env python3
"""Plain GIFs from actual 25 Hz Godot captures; no decorative overlays."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def make_frames(paths, palette, duration):
    for path in paths:
        with Image.open(path) as image:
            frame = image.convert("RGB").resize((768, 480), Image.Resampling.LANCZOS)
        yield frame.quantize(palette=palette, dither=Image.Dither.NONE), duration
    reset = Image.new("RGB", (768, 480), (250, 250, 248))
    ImageDraw.Draw(reset).text((384, 466), "reset", fill=(140, 140, 136), anchor="mm")
    yield reset.quantize(palette=palette, dither=Image.Dither.NONE), 320


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT/"reports/captures/runtime")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int)
    parser.add_argument("--slow-start", type=int, default=36)
    parser.add_argument("--slow-end", type=int, default=175)
    parser.add_argument("--keep-frames", "--keepframes", action="store_true")
    args = parser.parse_args()
    available = sorted(args.directory.glob("[0-9][0-9][0-9][0-9].png"))
    if not available:
        raise ValueError("Capture actual Godot viewport frames first")
    end = args.end or int(available[-1].stem)
    paths = [args.directory/f"{index:04d}.png" for index in range(args.start, end+1)]
    if len(paths) < 2 or not all(path.exists() for path in paths):
        raise ValueError("Expected consecutively numbered actual viewport frames")
    out = ROOT/"previews/gifs"
    out.mkdir(exist_ok=True, parents=True)
    reference = Image.new("RGB", (1152, 240), (250, 250, 248))
    for column, fraction in enumerate([.1, .4, .7]):
        with Image.open(paths[min(len(paths)-1, round((len(paths)-1)*fraction))]) as image:
            reference.paste(image.convert("RGB").resize((384, 240)), (384*column, 0))
    palette = reference.quantize(colors=128, dither=Image.Dither.NONE)
    # Reserve an exact plain reset colour in the common palette.
    colours = palette.getpalette()
    colours[-3:] = [250, 250, 248]
    palette.putpalette(colours)
    slow = [path for path in paths if args.slow_start <= int(path.stem) <= args.slow_end]
    if len(slow) < 2:
        slow = paths
    report = {"source": "Actual Godot viewport", "capture_fps": 25, "gifs": {}}
    for name, selected, duration in [("Runtime", paths, 40), ("Runtime_slow", slow, 100)]:
        frames = list(make_frames(selected, palette, duration))
        temporary = out/("."+name+".gif")
        frames[0][0].save(temporary, save_all=True, append_images=[image for image, _ in frames[1:]],
                          duration=[milliseconds for _, milliseconds in frames], loop=0, disposal=1, optimize=False)
        expected_duration = len(selected)*duration+320
        with Image.open(temporary) as image:
            actual_duration = 0
            for index in range(image.n_frames):
                image.seek(index)
                image.load()
                actual_duration += image.info.get("duration", 0)
            if actual_duration != expected_duration or image.info.get("loop") != 0:
                raise ValueError("Runtime GIF failed decode/duration validation")
        temporary.replace(out/(name+".gif"))
        report["gifs"][name+".gif"] = {"captured_frames": len(selected), "first_frame": selected[0].stem,
            "last_frame": selected[-1].stem, "frame_duration_ms": duration, "reset_ms": 320,
            "duration_ms": expected_duration, "sha256": hashlib.sha256((out/(name+".gif")).read_bytes()).hexdigest()}
        print("CAPTURE_GIF", name, len(selected), flush=True)
    with Image.open(paths[min(len(paths)-1, len(paths)//3)]) as image:
        image.convert("RGB").save(ROOT/"previews/runtime.jpg", quality=93)
    (ROOT/"previews/runtime_inventory.json").write_text(json.dumps(report, indent=2)+"\n")
    if not args.keep_frames:
        shutil.rmtree(args.directory)


if __name__ == "__main__":
    main()
