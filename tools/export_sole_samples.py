"""Blender: export a spatial sole envelope for a replacement humanoid.
Model must be in metres, Z-up, -Y forward, unscaled, with Humanoid bone names.
Use --mesh=ObjectName --output=/absolute/path.json after Blender's -- separator.
"""
import bpy
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).parent))
from foot_geometry import samples

def main():
    name="Humanoid_CC0"
    output=ROOT/"addons/walkers/assets/sole_samples.json"
    for arg in sys.argv:
        if arg.startswith("--mesh="):name=arg.split("=",1)[1]
        if arg.startswith("--output="):output=Path(arg.split("=",1)[1])
    body=bpy.data.objects[name]
    armature=next(mod.object for mod in body.modifiers if mod.type=="ARMATURE")
    bone_names={b.name for b in armature.data.bones if b.use_deform}
    assert {"LeftFoot","RightFoot"}.issubset(bone_names),"Normalize bones to SkeletonProfileHumanoid names first"
    vertices=[v.co.copy() for v in body.data.vertices]
    weights=[]
    for vertex in body.data.vertices:
        influences=sorted([(body.vertex_groups[g.group].name,g.weight) for g in vertex.groups if g.weight>.00001 and body.vertex_groups[g.group].name in bone_names],key=lambda x:x[1],reverse=True)[:4]
        total=sum(w for _,w in influences)
        weights.append([(n,w/total) for n,w in influences] if total else [("Hips",1.0)])
    data=samples(vertices,weights)
    output.write_text(json.dumps(data,indent=2)+"\n")
    print("SOLE_GEOMETRY", {k:len(v) for k,v in data.items()},flush=True)
    os._exit(0)

if __name__=="__main__":
    try:main()
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
