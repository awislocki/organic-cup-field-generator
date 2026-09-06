"""Run: blender --background --factory-startup --python tests/test_blender.py

Exercises production geometry, failure preservation, bed-fit export and camera
framing in Blender. All generated files go to a temporary directory.
"""
import importlib.util
import json
import math
import struct
import tempfile
from types import SimpleNamespace
from pathlib import Path
from xml.etree import ElementTree

import bpy
import bmesh
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("organic_cups", ROOT / "organic_cup_field_generator.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()
scene = bpy.context.scene
s = scene.ocf_settings


def operator_result(cls):
    # Blender turns ERROR reports into exceptions through bpy.ops; direct calls
    # let us assert the cancellation contract without swallowing real failures.
    op = SimpleNamespace(report=lambda level, message: print('EXPECTED_REPORT', message))
    return cls.execute(op, bpy.context)


def assert_connected_closed(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    assert all(e.is_manifold for e in bm.edges), obj.name
    assert all(e.is_contiguous for e in bm.edges), obj.name
    assert all(f.calc_area() > 1e-9 for f in bm.faces), obj.name
    assert bm.calc_volume(signed=True) > 0, obj.name
    remaining = set(bm.verts)
    pending = [remaining.pop()]
    while pending:
        for edge in pending.pop().link_edges:
            for vertex in edge.verts:
                if vertex in remaining:
                    remaining.remove(vertex)
                    pending.append(vertex)
    assert not remaining, f"Disconnected shells in {obj.name}"
    bm.free()


# Fresh installation must generate successfully without requiring Apply Preset.
assert s.output_mode == "NUMBERED_PIECES"
assert s.base_mode == "INDIVIDUAL_FEET"
assert s.density == bpy.types.Scene.bl_rna.properties['ocf_settings'].fixed_type.properties['density'].default
s.tile_x, s.tile_y = 15, -2
before = (s.tile_size_x, s.tile_size_y, s.tile_x, s.tile_y, s.wave_wavelength)
assert bpy.ops.ocf.generate_finished_work() == {"FINISHED"}
assert (s.tile_size_x, s.tile_size_y, s.tile_x, s.tile_y, s.wave_wavelength) == before
root = s.artwork_collection
manifest = json.loads(root["ocf_manifest"])
assert manifest['width'] == 600 and manifest['height'] == 1200
assert max(p['artwork_y_mm'] for p in manifest['pieces']) > 1150
assert min(p['artwork_y_mm'] for p in manifest['pieces']) < 50
assert len({p['piece_id'] for p in manifest['pieces']}) == len(manifest['pieces'])
assert {p['panel_row'] for p in manifest['pieces']} == set(range(1, 8))
objects = addon._artwork_objects(bpy.context)
for obj in objects:
    assert_connected_closed(obj)
    assert min(v.co.z for v in obj.data.vertices) == 0
print('FULL_ARTWORK_OK', len(objects), 'pieces; complete 600 x 1200 dimensions')

# Failed regeneration must preserve the complete old artwork and map.
old_ids = set(obj.as_pointer() for obj in objects)
old_manifest = root['ocf_manifest']
original_builder = addon._build_piece_mesh_data
calls = [0]
def fail_on_second(*args):
    calls[0] += 1
    if calls[0] == 2:
        raise RuntimeError('Injected generation failure')
    return original_builder(*args)
addon._build_piece_mesh_data = fail_on_second
s.finished_width, s.finished_height = 160, 120
assert operator_result(addon.OCF_OT_generate_modular_artwork) == {'CANCELLED'}
assert s.artwork_collection == root
assert root['ocf_manifest'] == old_manifest
assert set(o.as_pointer() for o in addon._artwork_objects(bpy.context)) == old_ids
addon._build_piece_mesh_data = original_builder
assert bpy.data.collections.get('OCF_Building') is None

# Export uses saved geometry/settings, even if controls have since changed.
with tempfile.TemporaryDirectory(prefix='ocf_test_') as tmp:
    package, plate_count = addon._export_print_package(bpy.context, tmp)
    saved = json.loads((package / 'manifest.json').read_text())
    assert saved['height'] == 1200
    assert plate_count > 1
    mapped_ids = [p['piece_id'] for plate in saved['print_plates'] for p in plate['pieces']]
    assert len(mapped_ids) == len(set(mapped_ids)) == len(objects)
    bounds = {p['piece_id']: p for p in saved['pieces']}
    for plate in saved['print_plates']:
        boxes = []
        for p in plate['pieces']:
            record = bounds[p['piece_id']]
            lo = [record['bounds_min'][i] + p['offset'][i] for i in range(3)]
            hi = [record['bounds_max'][i] + p['offset'][i] for i in range(3)]
            assert lo[0] >= 2.5-1e-5 and lo[1] >= 2.5-1e-5
            assert hi[0] <= 177.5+1e-5 and hi[1] <= 177.5+1e-5
            assert abs(lo[2]) < 1e-5
            for a, b in boxes:
                assert (lo[0] >= b[0] + s.batch_spacing - 1e-5
                        or a[0] >= hi[0] + s.batch_spacing - 1e-5
                        or lo[1] >= b[1] + s.batch_spacing - 1e-5
                        or a[1] >= hi[1] + s.batch_spacing - 1e-5)
            boxes.append((lo, hi))
        data = (package / 'plates' / (plate['plate']+'.stl')).read_bytes()
        triangles = struct.unpack('<I', data[80:84])[0]
        assert len(data) == 84 + 50*triangles
        for offset in range(84, len(data), 50):
            values = struct.unpack('<12fH', data[offset:offset+50])
            for v in (values[3:6], values[6:9], values[9:12]):
                assert 2.49 <= v[0] <= 177.51 and 2.49 <= v[1] <= 177.51
                assert -1e-5 <= v[2] <= s.printer_bed_z
    xml = ElementTree.parse(package / 'assembly.svg').getroot()
    assert xml.attrib['width'] == '600.0mm' and xml.attrib['height'] == '1200.0mm'
    assert len(list((package / 'regions').glob('*.svg'))) == 28
    objects[0].location.x += 1
    try:
        addon._export_print_package(bpy.context, tmp)
    except ValueError as error:
        assert 'was edited' in str(error)
    else:
        raise AssertionError('Stale map must not be exported after an edit')
    objects[0].location.x -= 1
    bpy.context.view_layer.update()
print('EXPORT_OK', plate_count, 'plates checked for fit, spacing, IDs and binary STL size')

# Camera fit is checked on every corner of every piece in both orientations.
old_camera = scene.camera
old_engine = scene.render.engine
for view in ('TOP', 'ANGLED'):
    s.render_view = view
    preview = addon._setup_render(bpy.context)
    assert scene.camera == old_camera and scene.render.engine == old_engine
    assert len([o for o in preview.objects if o.type == 'MESH']) == len(objects)
    for obj in objects:
        for corner in obj.bound_box:
            p = world_to_camera_view(preview, preview.camera, obj.matrix_world @ Vector(corner))
            assert 0 <= p.x <= 1 and 0 <= p.y <= 1 and p.z > 0, (view, obj.name, p[:])
print('CAMERA_OK portrait/top/angled')

# Successful regeneration replaces old geometry even when a preview links it.
s.form_style = 'MIXED'
s.block_fraction = 0.5
s.block_bevel = 0.0
assert bpy.ops.ocf.generate_finished_work() == {'FINISHED'}
assert len([c for c in bpy.data.collections if c.get('ocf_generated')]) == 1
objects = addon._artwork_objects(bpy.context)
for obj in objects:
    assert_connected_closed(obj)
s.finished_width, s.finished_height = 240, 100
assert bpy.ops.ocf.generate_finished_work() == {'FINISHED'}
s.render_view = 'TOP'
preview = addon._setup_render(bpy.context)
for obj in addon._artwork_objects(bpy.context):
    for corner in obj.bound_box:
        p = world_to_camera_view(preview, preview.camera, obj.matrix_world @ Vector(corner))
        assert 0 <= p.x <= 1 and 0 <= p.y <= 1
print('REGEN_AND_BLOCKS_OK landscape camera and zero bevel')

# Actual bed checks and a real voxel pass, using one small connected cup.
s.finished_width = s.finished_height = 40
s.form_style = 'ORGANIC_FUNNELS'
s.density = 6.6
s.filler_fraction = 0
s.merge_manifold = True
s.voxel_size = 0.4
assert bpy.ops.ocf.generate_finished_work() == {'FINISHED'}
for obj in addon._artwork_objects(bpy.context):
    assert_connected_closed(obj)
s.merge_manifold = False
previous_root = s.artwork_collection
s.finished_width = s.finished_height = 300
s.density = 1
s.printer_bed_x = s.printer_bed_y = 40
s.printer_margin = 10
assert operator_result(addon.OCF_OT_generate_modular_artwork) == {'CANCELLED'}
assert s.artwork_collection == previous_root
s.printer_bed_x = s.printer_bed_y = 180
s.printer_margin = 2.5
print('REMESH_AND_BED_REJECTION_OK')

# Both legacy panel modes must still work.
for mode in ('COMMON_PANEL', 'INDIVIDUAL_FEET'):
    s.output_mode = 'PANEL_MESHES'
    s.base_mode = mode
    s.tile_size_x = s.tile_size_y = 60
    s.density = 12
    s.form_style = 'ORGANIC_FUNNELS'
    assert bpy.ops.ocf.generate_field() == {'FINISHED'}
    assert len(addon._artwork_objects(bpy.context)) == 1
print('ALL_TESTS_PASSED', bpy.app.version_string)
addon.unregister()
