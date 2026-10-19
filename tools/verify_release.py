#!/usr/bin/env python3
"""Expand the ZIP into a new directory and import/start with empty caches."""
import hashlib
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
import sys
from pathlib import Path
from godot_validation_support import classify_errors

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("archive",nargs="?",type=Path,default=ROOT/"dist/Walkers-Godot4-Blender.zip")
    parser.add_argument("--allow-editor-socket-errors",action="store_true")
    options=parser.parse_args()
    archive=options.archive.resolve()
    godot=shutil.which("godot") or shutil.which("godot4")
    results={}
    with tempfile.TemporaryDirectory(prefix="walkers-release-") as directory:
        target=Path(directory)
        with zipfile.ZipFile(archive) as source:
            assert source.testzip() is None
            for name in source.namelist():
                assert name.startswith("Walkers/") and ".." not in Path(name).parts
            source.extractall(target)
        project=target/"Walkers"
        env=os.environ.copy()
        for key,folder in [("XDG_CONFIG_HOME","config"),("XDG_CACHE_HOME","cache"),("XDG_DATA_HOME","data")]:
            env[key]=str(target/folder)
        for name, args in [
            ("fresh_import",[godot,"--headless","--editor","--path",str(project),"--import"]),
            ("fresh_start",[godot,"--headless","--path",str(project),"--fixed-fps","60","--quit-after","120"]),
        ]:
            process=subprocess.run(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
            (ROOT/"reports"/(name+".log")).write_text(process.stdout)
            errors,limitations=classify_errors(process.stdout,options.allow_editor_socket_errors and name=="fresh_import")
            results[name]={"exit_code":process.returncode,"errors":errors}
            if limitations:results[name]["environment_limitations"]=limitations
            assert process.returncode==0 and not errors,process.stdout[-5000:]
    results["status"]="pass"
    report_name="runtime_release_validation.json" if archive.name=="Walkers-Godot-Project.zip" else "release_validation.json"
    (ROOT/"reports"/report_name).write_text(json.dumps(results,indent=2)+"\n")
    proof=dict(results)
    proof["archive_sha256"]=hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT/"dist"/(archive.stem+".verification.json")).write_text(json.dumps(proof,indent=2)+"\n")
    print(json.dumps(results,indent=2))

if __name__=="__main__":main()
