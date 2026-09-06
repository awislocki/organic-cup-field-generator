# Organic Cup Field Generator — guide

Version 1.8.0 · Blender 4.x · numeric dimensions in millimetres

## Install or update

1. Download organic_cup_field_generator.py.
2. Open Blender Preferences → Add-ons → Install from Disk. In earlier Blender
   4.x versions the button is simply **Install**.
3. Install the file and enable **Organic Cup Field Generator**. Disable an older
   copy first, and restart Blender after replacing it.
4. Open the 3D View sidebar with **N**, then choose **Organic Cups**.
5. In an existing saved scene, choose **Modular Coral (Recommended)** and click
   **Apply Selected Preset**. Updating the add-on retains old scene values.

A fresh scene starts with consistent Modular Coral settings. Applying a preset
preserves artwork dimensions and seed, resets manual tiles to 175 × 175 mm, and
turns voxel remeshing off for the design pass.

## Generate the full artwork

1. Set **Finished Width** and **Finished Height** to the assembled artwork size.
   The default 600 × 1200 mm is an example, not a printer-bed dimension.
2. Keep **Numbered Glue-Down Pieces** and **Individual Glue Feet** selected.
3. Click **Generate Finished Work**, then **Frame All Panels**.

The master field is solved over the exact dimensions before assignment to assembly
regions. A rim may cross a region boundary; its root centre determines the owning
region. Join/align backing sections before installing pieces spanning their seam.

A 180 × 180 mm bed minus 2.5 mm per side gives a usable 175 × 175 mm footprint.
The default artwork has 4 × 7 assembly regions, each 150 × 171.43 mm. Regions
organize mounting; print plates are packed separately at export.

The default seed produced 674 pieces and 36 print plates at 3 mm spacing during
regression testing. Counts vary with seed and settings. Limits of 1,500 primary
pieces, 2,200 estimated total pieces and 8 million source vertices prevent
unbounded generation.

Modular regeneration is staged: a failed attempt leaves the previous successful
artwork and placement data intact. Correct the setting reported by Blender and
regenerate.

## View and render every panel

The **View & Render** box is at the top of the sidebar.

- **Frame All Panels** selects and frames the active generated artwork.
- **Straight On** looks directly into the openings.
- **Angled Relief** reveals the height wave and interiors.
- **Image Long Edge** sets image resolution.
- **Render All Panels** automatically fits every piece and opens a studio render.
  Save it with **Render Result → Image → Save As**.

A separate **OCF Artwork Preview** scene uses Blender's Workbench studio renderer
and includes only generated meshes. Guides and unrelated objects are excluded;
the original scene's camera, lights and renderer are retained. This design preview
does not simulate filament or layer lines.

If the render window does not open, switch an editor to **Image Editor** and select
**Render Result**. To customize the camera or renderer, switch to the preview scene
in Blender's scene selector. The add-on render button restores its studio setup
each time it is used.

## Export a print and assembly package

1. Finalize and inspect the composition.
2. Set **Print Spacing**; default 3 mm between complete XY bounding boxes.
3. Choose **Export Print & Assembly Package** and select a destination.
4. A new uniquely named folder is created for every export.

| File/folder | Purpose |
| --- | --- |
| pieces/P01-001.stl | One named connected part per file, useful for reprints |
| plates/plate_001.stl | Separated parts arranged within the usable print bed |
| plates/plate_001.svg | Piece-ID diagram for labeling that plate after printing |
| assembly.svg | Full-size numbered artwork map |
| regions/P01.svg | Full-size placement map for one assembly region |
| assembly.csv | IDs, position, rotation, height, size and colour group |
| manifest.json | Settings, contours, actual bounds and plate assignments |
| PRINT_ME_FIRST.md | Instructions for this job |

Packing uses conservative rectangular bounds and preserves orientation. It does
not guarantee the minimum possible plate count. Different assembly regions may
share a print plate.

Import one plate STL at a time into Bambu Studio and keep its parts together and
their relative positions unchanged. Each cup has one connected foot-and-body
surface and starts at Z = 0. IDs are filenames and map labels, not engravings:
label the pieces as they come off the bed.

The writer outputs numeric millimetres directly without an STL extension. Verify
dimensions in the slicer. Added brims are not included in spacing allowances;
increase spacing or reduce brim width where necessary.

The package uses saved generation data. Changing controls without regenerating
does not change its map. Editing a generated mesh, transform, parent or modifier
causes package export to request regeneration, keeping the parts synchronized with
their placement data.

**Save Assembly Map CSV** exports just the coordinate table.

## Mounting maps

SVG files specify physical millimetre dimensions. Print at **100% / actual size**,
then measure the included **20 mm ruler**. Do not use fit-to-page. Use a vector
editor to tile or convert a master SVG larger than your paper. Region maps are
usually small enough for an ordinary page.

- Pale contours show projected mouths.
- Dashed contours show glue feet.
- Crosses mark root centres.
- Short lines indicate the shape's local X direction.
- IDs match individual files and plate diagrams.

Coordinates start at the artwork's bottom-left. The SVG Y axis is flipped to match.
Exported geometry already includes the listed rotation; do not apply that rotation
a second time. Colour groups are optional suggestions from the height/cluster
fields.

The CSV height_mm is actual total mesh height, including foot and highest rim.
For compatibility, mouth_diameter_mm keeps its old name but now stores the larger
actual X/Y mesh extent, rather than requested radius × 2. Complete contours and
bounds are in manifest.json.

## Shape and flow controls

- **Density**: primary cups per 100 × 100 mm. Lower values make fewer, larger forms.
- **Gap Fillers**: secondary cups where printable space remains.
- **Hero Cup Fraction / Minimum / Maximum Scale**: size hierarchy.
- **Cluster Strength / Scale**: grouping of related sizes.
- **Packing Tightness**: expansion toward weighted neighbour boundaries.
- **Mouth Shape Variation / Elongation**: irregularity and long openings.
- **Throat Size / Offset**: the narrow, displaced cavity floor.
- **Tulip Form**: narrow roots, early bellies and flared mouths.
- **Rim Scallop**: optional lobing; zero produces continuous rims.
- **Height / Radius Limit**: prevents tiny fillers becoming long stalks.
- **Lean / Tilt / Bend Variation**: body sweep.
- **Flow Alignment / Swirl / Scale**: coordinated mouth axes and bends.
- **Wave Amplitude / Direction**: broad relief.
- **Fit Broad Wave to Finished Work / Broad Wave Cycles**: wavelength from the full
  artwork span.
- **Noise Amplitude / Scale**: secondary height variation.
- **Undercurrent Depth / Scale / Direction**: channels lowering selected groups.
- **Mouth / Height Segments**: geometric resolution. Modular Coral uses 64 / 18;
  reduce these for quick drafts.

Fields use deterministic global coordinates. Modular artwork fixes the origin at
its centre; manual tile coordinates apply to the legacy workflow. A different
finished size recomputes packing, so separately generated artworks are not
guaranteed to have matching mouths at their boundaries.

## Other presets and legacy panels

Presets include Dense Cellular Panel, Balanced Funnels, Deep Hero Funnels, Strong
Undercurrent, Glue-Down Funnels, Funnels + Blocks and Rounded Block Field.

**Generate Field** makes one manual tile. **Generate Panel Set** makes the manual
grid. For shared backing panels choose **Panel Meshes** and **Common Panel**, then
**Generate Finished Work**.

Legacy panels share global height and orientation fields but pack independently
inside each tile; straight seams can remain visible. Modular mode avoids that
packing restart.

## Printing limits

- Test-print a small, medium, large and strongly leaning form first.
- Default 0.8 mm walls target two 0.4 mm lines; inspect actual toolpaths. The wall
  setting is radial and does not guarantee minimum surface-normal thickness.
- Closed topology does not guarantee support-free printing or freedom from every
  self-intersection under extreme custom settings.
- Throats have closed floors rather than drainage holes.
- Voxel remeshing is optional for connected modular pieces. Voxel size must be
  at most 60% of wall thickness to help preserve openings.
- Shared-base previews still have overlapping cup/base solids; voxel union remains
  available when a connected panel is needed.
- Actual modular piece bounds, including remesh changes, are checked against
  usable XY and configured Z dimensions before replacing the previous artwork.
- The A1 Mini's nominal build volume is 180 × 180 × 180 mm. Check dimensions,
  adhesion, brims and overhangs in Bambu Studio.

## Validation

From the repository root:

    blender --background --factory-startup --python-exit-code 1 --python tests/test_blender.py

Tests cover full 600 × 1200 mm geometry, connected closed pieces, failure
preservation, plate fit/spacing, STL bounds, SVG maps, stale-map detection, camera
framing, zero-bevel blocks and legacy generation. Exports use a temporary directory.

Recreate the checked-in preview from actual generated geometry:

    blender --background --factory-startup --python tests/render_preview.py
