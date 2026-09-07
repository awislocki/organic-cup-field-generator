"""Measure two presets at identical artwork dimensions/seed (not identical shapes)."""
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
s.finished_width, s.finished_height = 600, 450
results = []
for preset in ('PARAGAMI_CORAL', 'DENSE_MOSAIC'):
    addon._apply_style_preset(s, preset)
    assert bpy.ops.crf.generate_finished_work() == {'FINISHED'}
    data = addon._manifest(bpy.context)
    results.append(dict(preset=preset, width_mm=data['width'], height_mm=data['height'],
                        seed=data['seed'], pieces=len(data['pieces']),
                        model_volume_cm3=data['volume_cm3'],
                        assumed_mass_g=round(data['volume_cm3']*1.24, 1)))
    print('MEASUREMENT', results[-1], flush=True)
report = dict(version=addon.VERSION, blender=bpy.app.version_string, results=results,
              note='Different compositions/presets at the same size and seed. Mass assumes 1.24 g/cm3. '
              'Excludes supports, brims, purge and slicer line-width effects; not a physical test.')
(root / 'docs' / 'reef_material_comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
addon.unregister()
