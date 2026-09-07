# Changelog

## 2.0.0 — 2026-09-07 — Flowing Coral Reef

- Separate `flowing_coral_reef_generator.py` add-on and `crf` namespace; the missing
  local v1.8 file was not restored or overwritten.
- Rebuilt the composition around one stream function shared by size bands and
  orientation. Adaptive seed placement preserves room for larger focal funnels.
- Smoothly blended cell constraints avoid sharp clipped-mouth corners. A planar
  footprint-distance pass inserts small cups into remaining gaps.
- Rebuilt cup hollowing as nominal surface-normal offsets, with a rounded lip,
  closed floor and connected flat glue foot. No shared backing in the recommended
  workflow, no mandatory voxel merge, no independently interpolated thick cavity.
- Model volume and explicitly assumed-density mass estimate in the sidebar;
  per-piece volume and full-job volume in the manifest.
- Flowing Reef, Low-Material Reef, Sculptural Reef and Tidal Ribbons presets.
- Separate soft Cycles studio scene and display-only backing; optional fast preview.
- New operating guide, real rendered examples and expanded Blender regression.
- Numbered generation runs a mesh preflight and rejects folded offset shells,
  retaining the last successful artwork when settings are geometrically invalid.

The default A1 Mini footprint remains 175 × 175 mm within a 180 mm bed. Brims,
supports, actual extrusion widths and physical print quality still need slicer
review and representative test prints; this release does not claim a guaranteed
support-free or minimum-mass optimum.

Blender 4.1.1 full-artwork regression: 1,429 pieces across 600 × 1200 mm,
28 spaced print batches at 3 mm spacing. Every piece passed closed/connected
topology, winding, positive-volume and non-adjacent self-intersection checks.
The dedicated 79-piece kernel case also passed nominal-offset, convex-cell
containment, deterministic-seed and shared-stream tangent tests. All six presets
passed small-scene geometry checks. These are geometric tests, not physical prints.

The workflow also passed on Blender 5.2.1 LTS. A reproducible preset measurement
at 600 × 450 mm yielded 365.12 cm³ for Flowing Reef and 328.33 cm³ for the final
Low-Material Reef (505 pieces each), approximately 10% less solid model volume.

## 1.8.0 — 2026-09-06

### Correctness

- Fixed silent truncation of large modular artworks: a 1,200 mm finished dimension
  previously passed through a tile property capped at 1,000 mm. Master generation
  now uses a plain settings snapshot and never mutates those UI controls.
- Both modular entry points fit the wave to the complete artwork consistently.
- Fresh-scene defaults match the recommended preset, including individual feet.
- Modular regeneration builds a staged replacement and retains the previous
  artwork if generation or printer-fit validation fails.
- Integral glue feet join directly to cup roots. A modular cup is one closed,
  connected mesh without buried caps or a mandatory voxel union.
- Zero-bevel blocks no longer contain duplicate rings and zero-area side faces.
- Actual generated dimensions, including voxel changes, are checked against the
  usable printer footprint and height.
- Saved map data belongs to the generated collection. Export checks that geometry
  and transforms still match the map, and ignores unapplied changes to UI settings.

### Workflow

- Added Frame All Panels and Render All Panels, with automatic straight-on or
  angled orthographic framing and adjustable image resolution.
- Studio previews use a separate Workbench scene and exclude guides/unrelated
  objects while retaining the original scene's render setup.
- Added full-scale numbered SVG mounting maps and per-region sheets, with foot
  outlines, mouth contours, orientation lines and a physical scale-check ruler.
- Added a print package exporter: individual binary STLs, conservative shelf-packed
  plate STLs, plate ID diagrams, CSV, settings/placement JSON and printing notes.
- Plate spacing and bed margins are explicit; export creates a unique directory.
- Modular Coral now uses 64 mouth segments and 18 height segments by default.

### Validation

The checked-in Blender regression exercises complete 600 × 1200 mm generation,
closed/connected surfaces with consistent winding and positive volume, a deliberate
mid-build failure, binary STL vertex bounds, plate spacing and IDs, SVG dimensions,
edited-piece rejection, camera framing in both portrait and landscape arrangements,
block geometry and legacy tile generation.

The reference seed produced 674 connected pieces and 36 plates at 3 mm spacing
with the final 64 × 18 mesh resolution. Lower draft resolution can change bounds
slightly and result in a different plate count.
The test and preview scripts are reproducible and do not require the original chat.
The preview image is rendered from the generated mesh by Blender.
The workflow passed on the installed Blender 4.1.1 and Blender 5.2.1 LTS runtimes.

### Remaining limits

- Packing is conservative, not an optimal nesting solver.
- SVGs are full-scale vector sheets, not automatically paginated PDFs.
- IDs are filenames/map labels, not physically engraved on pieces.
- Wall thickness is radial; arbitrary extreme settings still need slicer inspection
  for overhangs, local thickness and self-intersections.
- Studio previews do not simulate filament or layer lines.

## 1.7.0 — 2026-08-28

Initial GitHub release: global master composition, numbered glue-down pieces,
assembly-region collections, CSV placement data, existing panel and block modes.
