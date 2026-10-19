"""Readable initial viewport and embedded editing notes for the .blend source."""
import bpy
import sys
import os
from mathutils import Vector

def prepare():
    bpy.context.scene.unit_settings.system="METRIC"
    bpy.context.scene.unit_settings.scale_length=1.0
    orientation=(Vector((0,0,.9))-Vector((3,-5,2.3))).to_track_quat("-Z","Y")
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=="VIEW_3D":
                space=area.spaces.active
                space.region_3d.view_distance=3.2
                space.region_3d.view_location=(0,0,.9)
                space.region_3d.view_rotation=orientation
                space.shading.type="SOLID"
                space.shading.color_type="MATERIAL"
                space.overlay.show_relationship_lines=False
    notes=bpy.data.texts.get("START_HERE • Walkers") or bpy.data.texts.new("START_HERE • Walkers")
    notes.clear()
    notes.write("""WALKERS / Blender source

Read README.ja.md for the complete Japanese guide.
Humanoid = target rig. Humanoid_CC0 = MakeHuman CC0 surface.
REFERENCE collection = hidden original Quaternius rig and animations.

Select an Action in the Action Editor. Set playback range to frame 0 through
duration_seconds * 60 (e.g. Walk 0..63, Jog 0..42, Idle 0..192).
NLA tracks are muted for normal editing, and used for GLB export.

Custom Properties on Humanoid:
  foot_ik_Left / Right : 0 baked FK; 1 editable foot IK.
  CTRL_Foot_Left / Right and CTRL_Knee_Left / Right are already matched to FK.
  preview_root_motion : 1 full turning preview; 0 in-place export for Godot.
  preview_heading : authored turn preview yaw. Godot steering is interruptible.

Before export: preview_root_motion=0; bake edited IK if necessary;
foot_ik_Left=foot_ik_Right=0. Select only Humanoid and Humanoid_CC0.
Export GLB: NLA Tracks; deformation bones; frame step 1; scene 60fps.
Keep contacts and duration in motions.json consistent with edited Actions.

Character and motion assets: CC0. Tools: MIT. See THIRD_PARTY.md.
""")

if __name__=="__main__":
    prepare()
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print("SOURCE_PRESENTATION_SAVED",flush=True)
    os._exit(0)
