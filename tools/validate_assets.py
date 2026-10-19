#!/usr/bin/env python3
"""Check the delivered GLB, not just source metadata; no third-party dependencies."""
import hashlib
import json
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_glb(path):
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    assert struct.unpack_from("<I",data,4)[0] == 2
    length = struct.unpack_from("<I",data,12)[0]
    document = json.loads(data[20:20+length])
    start = 20+length
    bin_length = struct.unpack_from("<I",data,start)[0]
    return document, data[start+8:start+8+bin_length]


def accessor(document, blob, index):
    a = document["accessors"][index]
    b = document["bufferViews"][a["bufferView"]]
    components = {"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4,"MAT4":16}[a["type"]]
    assert a["componentType"] == 5126
    offset = b.get("byteOffset",0)+a.get("byteOffset",0)
    stride = b.get("byteStride",4*components)
    return [struct.unpack_from("<"+"f"*components,blob,offset+i*stride) for i in range(a["count"])]


def main():
    metadata = json.loads((ROOT/"addons/walkers/assets/motions.json").read_text())
    doc, blob = load_glb(ROOT/"addons/walkers/assets/humanoid.glb")
    report = {"animations":{},"asset_hashes_verified":0,"failures":[]}
    for animation in doc["animations"]:
        name = animation["name"]
        if name not in metadata["clips"]:
            report["failures"].append("unexpected clip: "+name)
            continue
        position_gap, angle_gap, sample_step = 0.0,0.0,0.0
        info = metadata["clips"][name]
        for channel in animation["channels"]:
            sampler = animation["samplers"][channel["sampler"]]
            values = accessor(doc,blob,sampler["output"])
            times = accessor(doc,blob,sampler["input"])
            for value in values:
                assert all(math.isfinite(v) for v in value)
            animated = any(math.dist(values[0],value)>1e-5 for value in values[1:])
            if len(times)>1 and animated:
                sample_step = max(sample_step,max(times[i+1][0]-times[i][0] for i in range(len(times)-1)))
            if info["loop"]:
                a,b = values[0],values[-1]
                if channel["target"]["path"] == "translation":
                    position_gap = max(position_gap,math.dist(a,b))
                elif channel["target"]["path"] == "rotation":
                    dot = abs(sum(x*y for x,y in zip(a,b)))/math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
                    angle_gap = max(angle_gap,math.degrees(2*math.acos(min(1,dot))))
        report["animations"][name] = {"loop":info["loop"],"position_gap_m":position_gap,
            "rotation_gap_degrees":angle_gap,"max_sample_step_seconds":sample_step}
        if position_gap>.005 or angle_gap>1.0:
            report["failures"].append(name+": loop seam")
        if sample_step>1/60+.0001:
            report["failures"].append(name+": not baked at 60fps")
    if set(report["animations"]) != set(metadata["clips"]):
        report["failures"].append("missing motion")
    manifest = json.loads((ROOT/"source/third_party/manifest.json").read_text())
    for source in manifest["sources"]:
        directory = "makehuman" if source["repository"].endswith("mpfb2") else "quaternius"
        for entry in source["files"]:
            payload = (ROOT/"source/third_party"/directory/entry["path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == entry["sha256"],entry["path"]
            report["asset_hashes_verified"] += 1
    (ROOT/"reports/asset_validation.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"clips":len(report["animations"]),"verified_sources":report["asset_hashes_verified"],"failures":report["failures"]},indent=2))
    raise SystemExit(bool(report["failures"]))


if __name__ == "__main__":
    main()
