#!/usr/bin/env python3
"""Make plain per-view GIFs and tight horizontal pose strips, then validate/publish."""
import argparse
import html
import json
import shutil
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ["front", "side", "three_quarter"]
PAPER = (250, 250, 248)
INK = (70, 70, 68)


def font(size):
    for path in ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def read_frame(cache, record):
    with Image.open(cache/record["path"]) as source:
        return source.convert("RGBA")


def plain(source, floor_y):
    result = Image.new("RGBA", source.size, PAPER+(255,))
    ImageDraw.Draw(result).line((0, floor_y, source.width, floor_y), fill=(195, 195, 191, 255), width=1)
    result.alpha_composite(source)
    return result.convert("RGB")


def pose_strip(cache, records, floor_y, path, crop_bounds, clip):
    images = [read_frame(cache, record) for record in records]
    boxes = [image.getchannel("A").getbbox() for image in images]
    if any(box is None for box in boxes):
        raise ValueError(f"Empty body image: {path}")
    if any(box[0] < 2 or box[1] < 2 or box[2] > images[0].width-2 or box[3] > images[0].height-2 for box in boxes):
        raise ValueError(f"Clipped body image: {path}; widen the rendering camera")
    # One vertical crop for the complete dataset preserves scale across clips/views.
    top, bottom = crop_bounds
    image_height, label_height = 276, 24
    scale = image_height/(bottom-top)
    pieces = []
    crop_records = []
    for index, (image, box) in enumerate(zip(images, boxes)):
        # Keep body scale and floor height identical; remove only empty side margins.
        left, right = max(0, box[0]-7), min(image.width, box[2]+7)
        crop = plain(image, floor_y).crop((left, top, right, bottom))
        width = max(46, round(crop.width*scale))
        piece = Image.new("RGB", (width, image_height+label_height), PAPER)
        resized = crop.resize((round(crop.width*scale), image_height), Image.Resampling.LANCZOS)
        piece.paste(resized, ((width-resized.width)//2, 0))
        draw = ImageDraw.Draw(piece)
        draw.text((5, image_height+1), f"{index+1:02d} {100*index/(len(images)-1):g}%", fill=INK, font=font(11))
        if clip in ["Walk", "Jog"] and index in [0, (len(images)-1)//2, len(images)-1]:
            label = "R contact" if index == (len(images)-1)//2 else "L contact"
            draw.text((5, image_height+13), label, fill=INK, font=font(9))
        pieces.append(piece)
        crop_records.append([left, top, right, bottom])
    strip = Image.new("RGB", (sum(piece.width for piece in pieces), 300), PAPER)
    cursor = 0
    for piece in pieces:
        strip.paste(piece, (cursor, 0))
        cursor += piece.width
    strip.save(path, optimize=True)
    # Exact boundary images are retained as measurements, not extra individual files.
    delta = ImageChops.difference(plain(images[0], floor_y), plain(images[-1], floor_y))
    return {"pose_count": len(images), "size": list(strip.size), "floor_y": round((floor_y-top)*scale),
            "boundary_mean_pixel_difference": sum(ImageStat.Stat(delta).mean)/3,
            "source_crops": crop_records}


def animation(cache, records, floor_y, loop, path):
    images = [plain(read_frame(cache, record), floor_y) for record in records]
    if not loop:
        reset = Image.new("RGB", images[0].size, PAPER)
        d = ImageDraw.Draw(reset)
        d.text((reset.width//2, reset.height-18), "reset", fill=(140, 140, 136), font=font(10), anchor="mm")
        images.extend(reset.copy() for _ in range(8))
    reference = Image.new("RGB", (320*3, 400), PAPER)
    for column, index in enumerate([0, len(records)//3, 2*len(records)//3]):
        reference.paste(images[index], (column*320, 0))
    palette = reference.quantize(colors=128, dither=Image.Dither.NONE)
    indexed = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    indexed[0].save(path, save_all=True, append_images=indexed[1:], duration=40, loop=0, disposal=1, optimize=False)
    return {"sample_count": len(records), "duration_ms": len(images)*40, "reset_ms": 0 if loop else 320,
            "sample_times_seconds": [record["time"] for record in records], "size": [320, 400]}


def gallery(clips, probe):
    names = "".join(f'<option>{html.escape(name)}</option>' for name in clips)
    return '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>移動モーション</title>
<style>body{margin:24px;background:#fafaf8;color:#444;font:14px system-ui,sans-serif}header{display:flex;align-items:center;gap:16px;flex-wrap:wrap}h1{font-size:18px;font-weight:500;margin:0}select,button,input{font:inherit}select,button{padding:5px;background:white;border:1px solid #ccc}#gif{width:320px;height:400px;display:block;margin:16px 0}.strip{overflow-x:auto;border-bottom:1px solid #ddd;margin:16px 0;padding-bottom:8px}.strip img{max-width:none;display:block;height:300px}label{display:inline-flex;align-items:center;gap:6px}p{max-width:850px;line-height:1.7}a{color:#555}#status{font-size:12px;color:#777}</style>
<header><h1>移動モーション</h1><select id="motion">OPTIONS</select><select id="view"><option value="side">側面</option><option value="front">正面</option><option value="three_quarter">斜め</option></select><button id="restart">先頭から</button><a id="download" download>GIF</a></header>
<img id="gif" alt="モーションGIF"><p id="status"></p><label>連続画像の倍率 <input id="zoom" type="range" min="50" max="200" value="100" step="10"><output id="zoomvalue">100%</output></label>
<div id="strips"></div><p>1周期は同じ足の接地から次の同じ足の接地まで。連続画像は0〜100%をBOUNDARY分割し、両端の姿勢を含みます。GIFはActionを25Hzで直接描画した画像です。発進・停止・旋回には空白のリセット区間があります。<a href="GUIDE">日本語ガイド</a></p>
<script>const motion=document.querySelector('#motion'),view=document.querySelector('#view'),gif=document.querySelector('#gif'),zoom=document.querySelector('#zoom');function scale(){document.querySelectorAll('.strip img').forEach(i=>i.style.height=(300*zoom.value/100)+'px');document.querySelector('#zoomvalue').value=zoom.value+'%'}function show(){let n=motion.value,v=view.value;gif.src='gifs/'+n+'_'+v+'.gif';document.querySelector('#download').href=gif.src;document.querySelector('#strips').innerHTML=['side','front','three_quarter'].map(v=>'<div>'+({side:'側面',front:'正面',three_quarter:'斜め'}[v])+'</div><div class="strip"><a href="sheets/'+n+'_'+v+'.png"><img alt="'+n+' '+v+'" src="sheets/'+n+'_'+v+'.png"></a></div>').join('');scale()}motion.onchange=view.onchange=show;zoom.oninput=scale;document.querySelector('#restart').onclick=()=>gif.src=gif.src.split('?')[0]+'?t='+Date.now();show();</script></html>'''.replace("OPTIONS", names).replace("BOUNDARY", "8" if probe else "32").replace("GUIDE", "../../README.ja.md" if probe else "../README.ja.md")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--keep-frames", "--keepframes", action="store_true")
    args = parser.parse_args()
    cache = ROOT/"previews/.frames"/("probe" if args.probe else "full")
    manifest = json.loads((cache/"manifest.json").read_text())
    expected = ["Idle", "Walk", "Jog"] if args.probe else list(json.loads((ROOT/"addons/walkers/assets/motions.json").read_text())["clips"])
    if set(manifest["clips"]) != set(expected):
        raise ValueError("Render all expected clips before assembly")
    destination = ROOT/"previews"/("probe" if args.probe else "")
    stage = ROOT/"previews"/(".probe-next" if args.probe else ".next")
    if stage.exists():
        shutil.rmtree(stage)
    (stage/"sheets").mkdir(parents=True)
    (stage/"gifs").mkdir()
    inventory = {"version": 2, "asset_sha256": manifest["asset_sha256"], "probe": args.probe,
                 "pose_divisions": manifest["pose_divisions"], "gif_fps": 25, "clips": {}}
    tops, bottoms = [], []
    for clip in expected:
        for rendered in manifest["clips"][clip]["views"].values():
            for record in rendered["poses"]:
                box = read_frame(cache, record).getchannel("A").getbbox()
                if box is None:
                    raise ValueError("Empty body image: "+record["path"])
                tops.append(box[1])
                bottoms.append(max(rendered["floor_y"], box[3]))
    crop_bounds = [max(0, min(tops)-8), min(manifest["render_size"][1], max(bottoms)+5)]
    inventory["shared_vertical_crop"] = crop_bounds
    for clip in expected:
        record = manifest["clips"][clip]
        if set(record["views"]) != set(VIEWS):
            raise ValueError(f"Missing rendered view: {clip}")
        result = {"duration": record["duration"], "loop": record["loop"], "views": {}}
        for view in VIEWS:
            rendered = record["views"][view]
            stem = clip+"_"+view
            strip = pose_strip(cache, rendered["poses"], rendered["floor_y"], stage/"sheets"/(stem+".png"), crop_bounds, clip)
            gif = animation(cache, rendered["gif"], rendered["floor_y"], record["loop"], stage/"gifs"/(stem+".gif"))
            result["views"][view] = {"sheet": "sheets/"+stem+".png", "gif": "gifs/"+stem+".gif", "strip": strip, "animation": gif}
        inventory["clips"][clip] = result
        print("ASSEMBLED", clip, flush=True)
    (stage/"inventory.json").write_text(json.dumps(inventory, indent=2)+"\n")
    (stage/"index.html").write_text(gallery(expected, args.probe))
    from validate_previews import validate_dataset
    report = validate_dataset(stage, require_runtime=False)
    if report["failures"]:
        raise ValueError("Replacement validation failed: "+repr(report["failures"]))
    # Preserve runtime GIFs until actual viewport capture replaces them separately.
    if not args.probe:
        for name in ["Runtime.gif", "Runtime_slow.gif"]:
            previous = destination/"gifs"/name
            if previous.exists():
                shutil.copy2(previous, stage/"gifs"/name)
    if args.probe:
        backup = destination.with_name(".probe-previous")
        if backup.exists(): shutil.rmtree(backup)
        if destination.exists(): destination.rename(backup)
        stage.rename(destination)
        if backup.exists(): shutil.rmtree(backup)
    else:
        destination.mkdir(exist_ok=True)
        for name in ["sheets", "gifs", "inventory.json", "index.html"]:
            current = destination/name
            if current.is_dir(): shutil.rmtree(current)
            elif current.exists(): current.unlink()
            (stage/name).rename(current)
        stage.rmdir()
        # Superseded individual frames and decorative/stale review boards.
        for name in ["poses", "probe_eevee", "QA"]:
            old = destination/name
            if old.exists(): shutil.rmtree(old)
        for name in ["overview.jpg"]:
            (destination/name).unlink(missing_ok=True)
    if not args.keep_frames:
        shutil.rmtree(cache)
    print("PREVIEWS_PUBLISHED", destination, "raw_frames_kept", args.keep_frames)


if __name__ == "__main__":
    main()
