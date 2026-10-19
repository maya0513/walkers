#!/usr/bin/env python3
"""Self-contained releases; omit temporary frame caches and obsolete review boards."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".godot", ".agents", ".aws", ".codex", "__pycache__", "dist", ".cache", ".frames"}
PREVIEW_TEMP = {"poses", "probe", "probe_eevee", "QA", ".next", ".probe-next", ".probe-previous"}


def include(path):
    relative = path.relative_to(ROOT)
    if any(part in IGNORED for part in relative.parts):
        return False
    if relative.parts[:2] == ("reports", "captures"):
        return False
    if len(relative.parts) > 1 and relative.parts[0] == "previews" and relative.parts[1] in PREVIEW_TEMP:
        return False
    if path.suffix in [".blend1", ".log", ".pyc", ".tmp"]:
        return False
    if path.suffix == ".import" and relative.parts[0] in ["source", "previews", "docs"]:
        return False
    return not path.name.startswith("core")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = ROOT/"dist"
    target.mkdir(exist_ok=True)
    (target/".gdignore").touch()
    archive = target/"Walkers-Godot4-Blender.zip"
    temporary = target/".Walkers-Godot4-Blender.zip"
    files = []
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and include(path):
                relative = path.relative_to(ROOT)
                output.write(path, "Walkers/"+str(relative))
                files.append(str(relative))
    temporary.replace(archive)
    runtime = target/"Walkers-Godot-Project.zip"
    temporary = target/".Walkers-Godot-Project.zip"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for folder in ["addons", "demo", "docs"]:
            for path in sorted((ROOT/folder).rglob("*")):
                if path.is_file() and include(path):
                    output.write(path, "Walkers/"+str(path.relative_to(ROOT)))
        for name in ["project.godot", "export_presets.cfg", "LICENSE", "LICENSE-ASSETS.txt", "THIRD_PARTY.md", "README.ja.md"]:
            output.write(ROOT/name, "Walkers/"+name)
        output.writestr("Walkers/README.md", """# Walkers — 実行用Godotプロジェクト

Godot 4.7.2でproject.godotを開き、初回インポート後にF5で実行します。
実行時にBlenderやネット接続は不要です。操作方法はREADME.ja.mdを参照してください。

別プロジェクトではaddons/walkersを同じ場所へコピーし、character.tscnを配置します。
set_move_intent(world_direction, speed_mps)を呼ぶと移動します。
床は衝突レイヤー1、キャラクターは2です。Exportではassets/*.jsonを含めます。

人間向けの歩行・ジョギング解説はdocs/gait_reference.ja.mdに収録しています。
Blenderソース、各視点の横長連続ポーズ画像、GIF、検証結果は
Walkers-Godot4-Blender.zip（全成果物版）に収録しています。
個別のレンダリング画像は再生成可能な作業用データとして配布版から省いています。

コードはMIT、モデルとモーションはCC0。LICENSEとTHIRD_PARTY.mdを参照してください。
""")
    temporary.replace(runtime)
    (target/"SHA256SUMS.txt").write_text(digest(archive)+"  "+archive.name+"\n"+digest(runtime)+"  "+runtime.name+"\n")
    for path in [archive, runtime]:
        print(json.dumps({"archive": str(path), "files": len(files) if path == archive else None,
                          "bytes": path.stat().st_size, "sha256": digest(path)}, indent=2))


if __name__ == "__main__":
    main()
