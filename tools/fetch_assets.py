#!/usr/bin/env python3
"""Fetch and pin the CC0 source assets. Only needed to rebuild, never at runtime."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "source" / "third_party"


def read(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Walkers-asset-builder/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    manifest_path = DEST / "manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    sources = []
    repositories = [
        ("makehumancommunity/mpfb2", "master", "makehuman", [
            "src/mpfb/data/3dobjs/base.obj",
            "src/mpfb/data/rigs/standard/rig.game_engine.json",
            "src/mpfb/data/rigs/standard/weights.game_engine.json",
            "src/mpfb/data/targets/macrodetails/macro.json",
            "src/mpfb/data/targets/macrodetails/african-male-young.target.gz",
            "src/mpfb/data/targets/macrodetails/asian-male-young.target.gz",
            "src/mpfb/data/targets/macrodetails/caucasian-male-young.target.gz",
            "src/mpfb/data/targets/macrodetails/universal-male-young-averagemuscle-averageweight.target.gz",
        ]),
        ("J-Ponzo/gltf-universal-animation-library", "main", "quaternius", [
            "glTF/AnimationLibrary_Godot_Standard.gltf",
            "README.md", "LICENSE",
        ]),
    ]
    for repository, branch, folder, paths in repositories:
        old = next((s for s in existing.get("sources", []) if s["repository"] == repository), None)
        commit = old["commit"] if old else json.loads(read(
            f"https://api.github.com/repos/{repository}/commits/{branch}"))["sha"]
        target = DEST / folder
        target.mkdir(exist_ok=True)
        files = []
        for path in paths:
            url = f"https://raw.githubusercontent.com/{repository}/{commit}/{path}"
            name = Path(path).name
            data = read(url)
            (target / name).write_bytes(data)
            files.append({"path": name, "url": url, "sha256": hashlib.sha256(data).hexdigest()})
            print(f"Fetched {folder}/{name}: {len(data):,} bytes", flush=True)
            if name.endswith(".gltf"):
                gltf = json.loads(data)
                for buffer in gltf.get("buffers", []):
                    uri = buffer.get("uri", "")
                    if uri and not uri.startswith("data:"):
                        buffer_url = url.rsplit("/", 1)[0] + "/" + uri
                        payload = read(buffer_url)
                        (target / uri).write_bytes(payload)
                        files.append({"path": uri, "url": buffer_url,
                                      "sha256": hashlib.sha256(payload).hexdigest()})
        sources.append({"repository": repository, "commit": commit, "license": "CC0-1.0",
                        "files": files})
    manifest_path.write_text(json.dumps({"sources": sources}, indent=2) + "\n")
    print("Source manifest written", flush=True)


if __name__ == "__main__":
    main()
