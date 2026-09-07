# Flowing Coral Reef — Blender add-on v2.0

A new composition and shell engine for the flowing coral reference. This is a
separate add-on, `flowing_coral_reef_generator.py`; it does not overwrite the
previous Organic Cup add-on or its generated objects.

## Install and make an artwork

1. Install the Python file using **Edit → Preferences → Add-ons → Install**
   (called **Install from Disk** in newer Blender versions), then enable it.
2. In the 3D View, press **N → Coral Reef**.
3. Choose **Flowing Reef (Recommended) → Apply Preset**.
4. Enter the **complete finished width and height in millimetres**.
5. Click **Generate Complete Reef**. All cups are composed together before
   assignment to assembly regions. No wave restart at region boundaries.
6. Use **Render Complete Reef** to see the full composition. **Soft Studio
   Lighting** uses Cycles and includes a display-only backing; disable it for a
   fast Workbench preview. The backing is never exported or printed.
7. **Export STLs & Numbered Maps** creates a new uniquely named output folder.

Keep one completed composition for the whole artwork. A new seed or changed
finished size changes the packing and the piece numbering. The separate legacy
tile operators remain available through Blender search for older workflows;
they share continuous height fields but do not produce one shared packing solve.
Use the complete-reef button for the reference effect.

## What changed visually

- Small, elongated cups form winding rivers between larger, open funnels.
- Size bands and orientation come from the **same stream function**. Independent
  noise no longer decides each visual feature in isolation.
- Variable-size placement reserves room for large forms before filling gaps.
- Smooth blends of neighboring cell constraints round the mouths, avoiding the
  sharp Voronoi corners and radial creases of an aggressively clipped cell.
- A second pass fits small cups into actual remaining footprint gaps. Gap filling
  is a maximum target, not a promise to force unprintably small forms into every void.
- Rim slope, off-centre throats and curved bodies reinforce the current. Heights
  vary with both local cup size and the full-artwork wave/undercurrent.

## Presets

| Preset | Purpose | Nominal wall | Relief ceiling* |
| --- | --- | --- | --- |
| Flowing Reef | Reference-oriented balance | 0.8 mm | 46 mm |
| Low-Material Reef | Lower relief, gentler tilt | 0.8 mm | 28 mm |
| Sculptural Reef | Deeper focal funnels | 1.0 mm | 58 mm |
| Tidal Ribbons | Stronger curling bands and elongated mouths | 0.8 mm | 46 mm |
| Rounded Blocks | Solid geometric columns | Not hollow | 46 mm |
| Reef + Blocks | Thin funnels mixed with solid columns | 0.8 mm funnels | 46 mm |

*The control is the central height above the foot, not the highest tilted rim.
Actual generated XYZ extents are checked against the printer before completion.
Applying a preset keeps the finished dimensions and seed, but resets shape/print
settings. Set your custom wall and quality after applying a preset.

Generation checks each numbered mesh for closed topology, consistent winding,
positive volume and non-adjacent face intersections. If an extreme configuration
folds a shell, generation stops and keeps the previous successful artwork. Try
a gentler preset, larger minimum scale or a thinner wall instead of exporting
the failed result. This preflight adds some generation time.

For a more obvious current, raise **Cluster Strength** and **Flow Alignment**.
**Flow Scale** changes the width/spacing of winding bands; start around 100–160 mm
for a 600 mm-wide piece. **Flow Swirl** increases their curvature. **Mouth
Elongation** strengthens the contrast between narrow river cups and broad funnels.
Density primarily changes the number/scale of forms, not the proportion of the
surface covered. Excess density with thick walls is rejected if cells are too small.

## Material efficiency is partly a modeling decision

The inner surface is derived from the outer surface by a nominal surface-normal
offset. It is not a second funnel that leaves thick wedges inside a bulging outer
body. The closed cavity floor, glue-foot transition and rounded lip are locally
thicker. Each cup is one connected closed mesh with an open mouth; there is no
shared printed backing and no mandatory voxel remesh.

The sidebar and JSON manifest report the **solid model volume**. The optional
mass display assumes 1.24 g/cm³, not a measured filament density. This excludes
brims, supports, purge and slicer-specific line-width behavior. It is an estimate,
not a guaranteed spool usage. Solid blocks depend much more on slicer infill.

Measured at 600 × 450 mm, seed 240531: Flowing Reef produced 505 pieces and
365.12 cm³ of solid model volume; Low-Material Reef retained 505 pieces and used
328.33 cm³, about **10% less**. At the stated density assumption this is roughly
453 g versus 407 g before slicer overhead. This compares two relief presets, not
identical geometry. See `docs/reef_material_comparison.json`; reproduce with
`tests/measure_reef.py`.

Use **Low-Material Reef** to reduce relief first. Do not scale the whole STL down
to save material: that also thins walls and shrinks the assembly coordinates.
Changing wall thickness requires regeneration; surface offsets have geometric
limits on very small or tightly curved forms. Nominal vertex offsets are not a
guarantee of exact thickness everywhere between tessellated faces.

## A1 Mini printing and assembly

- Default printer volume is **180 × 180 × 180 mm**. A 2.5 mm margin on each XY
  edge leaves **175 × 175 mm**, the requested 5 mm total reduction.
- Every cup has a flat integral glue foot. Print **feet down, mouths up**.
- Export contains `pieces/` reprint STLs, `plates/` spaced STL batches and matching
  ID diagrams, `regions/` mounting maps, a full-size SVG, CSV and JSON manifest.
- STL coordinates are numeric millimetres. In Bambu Studio, preserve each plate's
  existing part arrangement; don't independently rescale or reorient the pieces.
- Print spacing defaults to 3 mm. Slicer-added brims/supports are **not** included
  in that spacing or the bed margin. Check and repack in the slicer if needed.
- Start with a few large, small and highly tilted cups, using your normal material
  profile and a 0.4 mm nozzle. Try 0.16–0.20 mm layers as a starting experiment.
  Inspect whether the 0.8 mm model walls become continuous extrusion paths.
- These are real hollow shells, not vase-mode paths. Do not use spiral/vase mode
  for a batch. Infill cannot remove material already required to represent the shell.
- Thin curved rims and steeper overhangs are not guaranteed support-free. Inspect
  the layer preview and a physical test; lowering lean/relief and changing print
  orientation have trade-offs. Avoid automatically filling every cavity with
  difficult-to-remove support. No physical A1 Mini test has been performed here.
- The mounting regions are organizational, not cut lines through cups. Join the
  backing panels first, then glue the numbered pieces; cups can bridge seams.
- Print mounting SVGs at 100%, not fit-to-page, and measure the 20 mm scale ruler.
  IDs live in filenames and diagrams, not embossed onto each foot. Label parts as
  you unload a plate. No structural wall-mounting hardware is generated.

Printer specifications: [Bambu Lab A1 Mini quick-start guide](https://cdn1.bambulab.com/documentation/quick-start-f507128172bdf/Quick%20start%20guide%20-%20A1%20mini-EN.pdf).

## Preview and reproducibility

`docs/flowing_reef_top.png` and `docs/flowing_reef_angled.png` are actual Blender
renders, not AI mockups. The sample is 600 × 450 mm. A local `flowing_reef_demo.blend`
is also generated by the render script; it is intentionally excluded from Git
because it is a large derived binary. Regenerate it with:

```text
blender --background --factory-startup --python-exit-code 1 --python tests/render_reef.py
blender --background --factory-startup --python-exit-code 1 --python tests/test_reef.py
```

The test covers full-size generation, connected manifold topology, positive
volume, injected failure preservation, exported STL bed bounds/spacing/IDs,
assembly dimensions, stale-map rejection, camera framing, blocks, remeshing,
repeatable specs, nominal shell offsets, stream tangents and representative
self-intersection/cell-containment checks. Validation is not a substitute for
slicer preview and a test print.

The workflow regression passed on Blender 4.1.1 and Blender 5.2.1 LTS. The final
low-material preset was also regenerated and preflighted at 600 × 450 mm in
Blender 4.1.1, with four reef presets checked separately for geometric intersections.

This is an original procedural interpretation of the supplied photographs, not
a copy of proprietary Paragami meshes or templates. Version 1.8 and its historical
documentation remain in the repository; the new namespace is `crf`, so the two
add-ons can coexist.
