"""Refresh deforming sole bindings after editing a mesh or baked Actions.

Blender --background edited.blend --python tools/export_contact_metadata.py -- \
  --metadata=/path/motions.json --output=/path/motions.json --mesh=Humanoid_CC0

The mesh and armature must share unscaled, metre, Z-up rest-skeleton axes.
Normalize names to SkeletonProfileHumanoid. Existing durations/frame counts and
contact weights must already describe the edited Actions; this exports geometry,
not automatic footstrike detection. Normal editing never requires MPFB.
"""
import argparse
import bpy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mesh', default='Humanoid_CC0')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    metadata = json.loads(args.metadata.read_text())
    body = bpy.data.objects[args.mesh]
    rig = next(mod.object for mod in body.modifiers if mod.type == 'ARMATURE')
    identity = body.matrix_local
    if max(abs(identity[i][j]-(1. if i == j else 0.)) for i in range(4) for j in range(4)) > 1e-5:
        raise ValueError('Apply mesh transforms and align mesh/armature rest coordinates before exporting')
    rest = {bone.name: bone.matrix_local for bone in rig.data.bones if bone.use_deform}
    if not {'LeftFoot', 'RightFoot'}.issubset(rest):
        raise ValueError('Normalize deform bone names to SkeletonProfileHumanoid first')
    patches = {side: [v.index for v in body.data.vertices if v.co.z < .13 and v.co.x*sign > 0]
               for side, sign in [('Left', 1), ('Right', -1)]}
    influences = {}
    for side, indices in patches.items():
        if not indices:
            raise ValueError('No sole geometry: '+side)
        influences[side] = []
        for index in indices:
            vertex = body.data.vertices[index]
            weights = sorted([(body.vertex_groups[g.group].name, g.weight) for g in vertex.groups
                              if g.weight > .00001 and body.vertex_groups[g.group].name in rest],
                             key=lambda item: item[1], reverse=True)[:4]
            total = sum(w for _, w in weights)
            if total <= 0:
                raise ValueError('Unweighted sole vertex: '+str(index))
            influences[side].append([(bone, w/total) for bone, w in weights])
    for track in rig.animation_data.nla_tracks:
        track.mute = True
    for key in ['foot_ik_Left', 'foot_ik_Right', 'preview_root_motion']:
        if key in rig: rig[key] = 0.
    for name, info in metadata['clips'].items():
        if name not in bpy.data.actions:
            raise ValueError('Missing Action: '+name)
        count = info['frames']
        if round(info['duration']*metadata['fps']) != count:
            raise ValueError('Duration and frame count disagree: '+name)
        rig.animation_data.action = bpy.data.actions[name]
        rig.update_tag()
        offsets, materials = [], []
        for frame in range(count+1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            pose = rig.evaluated_get(graph).pose.bones
            evaluated = body.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            try:
                if len(mesh.vertices) != len(body.data.vertices):
                    raise ValueError('Disable topology-changing modifiers before exporting skin correspondence')
                frame_offsets, frame_materials = [], []
                for side in ['Left', 'Right']:
                    indices = patches[side]
                    points = np.asarray([list(mesh.vertices[i].co) for i in indices], dtype=float)
                    lo = float(points[:, 2].min()); softness = .00035
                    pressure = np.exp(-(points[:, 2]-lo)/softness)
                    total = float(pressure.sum()); pressure /= total
                    point = Vector((points*pressure[:, None]).sum(axis=0))
                    point.z = lo-softness*math.log(total)-.0007
                    foot = pose[side+'Foot'].matrix
                    offset = rest[side+'Foot'].to_3x3() @ (foot.to_3x3().inverted() @ (point-foot.translation))
                    frame_offsets.append([offset.x, offset.z, -offset.y])
                    bindings = {}
                    for index, skin, pressure_weight in zip(indices, influences[side], pressure):
                        for bone, skin_weight in skin:
                            weight = float(pressure_weight)*skin_weight
                            value = bindings.setdefault(bone, [Vector(), 0.])
                            value[0] += body.data.vertices[index].co*weight
                            value[1] += weight
                    frame_materials.append([{'bone': bone, 'position': [p.x, p.z, -p.y], 'weight': w}
                                            for bone, (p, w) in bindings.items() if w > 1e-12])
                offsets.append(frame_offsets)
                materials.append(frame_materials)
            finally:
                evaluated.to_mesh_clear()
        info['support_offsets'], info['support_materials'] = offsets, materials
        print('CONTACT_GEOMETRY', name, count+1, flush=True)
    metadata['schema_version'] = 3
    metadata['support_material_space'] = 'rest_skeleton'
    args.output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
    print('CONTACT_EXPORT_COMPLETE', args.output, hashlib.sha256(args.output.read_bytes()).hexdigest(), flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush()
    os._exit(0)
