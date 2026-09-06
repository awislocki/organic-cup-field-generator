"""Render real generated geometry using the add-on's own automatic camera.

blender --background --factory-startup --python tests/render_preview.py
"""
import importlib.util
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('organic_cups', root / 'organic_cup_field_generator.py')
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()
s = bpy.context.scene.ocf_settings
s.finished_width = 900
s.finished_height = 450
s.render_pixels = 1600
s.render_view = 'ANGLED'
assert bpy.ops.ocf.generate_finished_work() == {'FINISHED'}
preview = addon._setup_render(bpy.context)
directory = root / 'docs'
directory.mkdir(exist_ok=True)
preview.render.filepath = str(directory / 'modular_coral_preview.png')
bpy.ops.render.render(scene=preview.name, write_still=True)
print('PREVIEW_SAVED', preview.render.filepath)
addon.unregister()
