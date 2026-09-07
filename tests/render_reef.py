"""Actual mesh preview: blender -b --factory-startup --python tests/render_reef.py"""
import importlib.util
import json
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reef', root / 'flowing_coral_reef_generator.py')
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()
s = bpy.context.scene.crf_settings
addon._apply_style_preset(s, 'PARAGAMI_CORAL')
s.finished_width, s.finished_height = 600, 450
s.render_pixels = 1600
s.render_view = 'TOP'
assert bpy.ops.crf.generate_finished_work() == {'FINISHED'}
manifest = addon._manifest(bpy.context)
print('GENERATED', len(manifest['pieces']), manifest['volume_cm3'], flush=True)
preview = addon._setup_render(bpy.context)
preview.display.shading.show_cavity = True
preview.display.shading.cavity_type = 'WORLD'
preview.display.shading.curvature_ridge_factor = 1.0
preview.display.shading.curvature_valley_factor = 1.0
preview.display.shading.cavity_ridge_factor = 1.0
preview.display.shading.cavity_valley_factor = 1.4
preview.render.filepath = str(root / 'docs' / 'flowing_reef_top.png')
bpy.ops.render.render(scene=preview.name, write_still=True)
s.render_view = 'ANGLED'
preview = addon._setup_render(bpy.context)
preview.display.shading.show_cavity = True
preview.display.shading.cavity_type = 'WORLD'
preview.render.filepath = str(root / 'docs' / 'flowing_reef_angled.png')
bpy.ops.render.render(scene=preview.name, write_still=True)
from mathutils import Vector
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            space = area.spaces.active
            space.clip_end = 100000
            space.shading.color_type = 'MATERIAL'
            space.overlay.show_extras = False
            space.region_3d.view_location = Vector((0, 0, 15))
            space.region_3d.view_distance = 780
            space.region_3d.view_rotation = preview.camera.rotation_euler.to_quaternion()
            space.region_3d.view_perspective = 'ORTHO'
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'flowing_reef_demo.blend'))
print('REEF_PREVIEW_SAVED', flush=True)
