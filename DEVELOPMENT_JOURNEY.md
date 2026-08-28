# Development Journey

This document records how the Organic Cup Field Generator evolved from a
single-form experiment into a modular system for producing a complete,
multi-region wall artwork on a Bambu Lab A1 Mini.

It is not a transcript. It captures the important observations, unsuccessful
directions, engineering decisions, and practical constraints that shaped the
current add-on.

## 1. The original problem

The starting point was a single organic cup generator for Blender. It could make
one smooth, hollow, asymmetric form with controls for mouth width, depth, height,
wall thickness, taper, bulge, constriction, irregularity, bend, lean, rim, bevel,
and subdivision.

That was useful for finding an individual silhouette, but the intended artwork
was never about one cup. The target was a dense field of hundreds of related
forms that appeared to grow around one another.

The essential requests were:

- many cups packed tightly together;
- random but related amoeba and teardrop openings;
- tulip-like swelling rather than straight tubes;
- variable height, lean, rotation, and bend;
- a broad height wave across the entire wall piece;
- an undercurrent that selectively pushed groups downward;
- multiple printable sections whose flow remained continuous after assembly;
- output that could be produced on a Bambu Lab A1 Mini.

## 2. What the visual references revealed

The supplied reference photographs showed several qualities that a simple
scatter system could not reproduce.

### The openings were not pipe ends

The first generated fields read as upright tubes with diagonally cut tops. The
references instead showed flower- or coral-like funnels:

- broad, soft mouths;
- rounded triangular, oval, and teardrop silhouettes;
- thin continuous rims;
- swollen bodies that flared early from narrow roots;
- small, dark, often off-center throats;
- curved interiors rather than cylindrical holes.

This led to a true funnel construction. The outer body and inner cavity are
generated separately, with the inner surface tapering toward a small displaced
floor. The body profile uses a narrow root, early belly, slight upper neck, and
mouth flare. The result reads more like a calla lily or coral polyp than a cut
tube.

### Randomness alone did not create flow

Independent random rotation, lean, and height made the field visually noisy.
The references contained local variation, but neighboring forms participated in
larger ribbons, fans, vortices, crests, and depressions.

The solution was to evaluate several deterministic fields in global millimeter
coordinates:

- a broad directional sine wave for the overall relief;
- continuous fractal noise for secondary variation;
- a warped directional undercurrent that only subtracts height;
- a low-frequency clustering field that influences scale and placement;
- a curl-like orientation field shared by mouth rotation, lean, and bend.

Because all of these use global coordinates and a master seed, the same location
always receives the same field values.

### The composition needed hierarchy

Uniformly sized cups produced a repetitive texture. The references depended on a
clear hierarchy:

- occasional large hero funnels;
- a supporting population of medium forms;
- small cups filling the largest remaining gaps.

The generator therefore creates a primary population and then searches for
available voids for a secondary filler tier. Large forms are more likely in
selected clusters and near wave crests. Tiny fillers receive a height cap based
on their radius so they remain shallow instead of becoming thin stalks.

## 3. Packing and the molded-together appearance

Simple random placement caused intersections, while conservative spacing exposed
too much backing. The desired result required both dense coverage and controlled
separation.

The packing system developed in layers:

1. Candidate centers are selected with a balance of point separation and the
   continuous cluster field.
2. Pairwise relaxation pushes crowded centers apart.
3. Collision-aware scaling reduces unresolved bounding-radius conflicts.
4. Small filler forms are placed in the largest viable remaining gaps.
5. Weighted Voronoi-like half-planes define a local cell around every form.
6. Every outer wall ring is clipped to that cell.
7. Inward-only circular smoothing softens the clipped corners without crossing
   the collision boundary.
8. Lean and bend offsets are constrained to the same cell.

This lets adjacent mouths expand toward one another and visually mold together
while retaining a small printable seam.

## 4. The first panel strategy and why it was incomplete

The initial multi-panel implementation generated each printer-sized tile
separately. Global wave and noise coordinates ensured that height values did not
restart, which was an important improvement.

However, each tile still solved its own point packing and clipped cups at its own
edge. The result could retain a continuous height trend while revealing straight
panel boundaries in the actual cellular pattern. It was mathematically
continuous in some fields but not compositionally continuous.

This distinction became central:

> A continuous field is not enough if the objects sampling that field are
> independently regenerated at every tile.

The shared-base panel mode remains useful because it produces directly printable
tiles. It is no longer the recommended method for the seamless glue-down artwork.

## 5. Learning from modular wall-art systems

The Paragami website provided a useful construction reference. Its public Coral
Sponge examples present large compositions as many individual blocks, while the
assembly package is organized around numbered pieces and a layout recording each
piece's position, orientation, and color.

The important lesson was the system, not the proprietary geometry:

- design the whole artwork first;
- keep pieces individually manufacturable;
- organize them into a limited, understandable assembly structure;
- identify every piece;
- provide an explicit placement map;
- allow one composition to span many practical production batches.

The Organic Cup Field Generator adopts that workflow with independently generated
cup geometry. No Paragami model data is included or reproduced.

## 6. The master modular workflow

Version 1.7 changes the order of operations for the recommended mode.

### Previous order

1. Divide the artwork into panels.
2. Generate and pack each panel independently.
3. Place the panels together.

### Current modular order

1. Generate and pack one master field over the exact finished dimensions.
2. Build every cup as a separate object with a flat glue foot.
3. Calculate equal A1 Mini-sized assembly regions.
4. Assign each cup to a region according to the center of its glue foot.
5. Keep any mouth that crosses a region boundary intact.
6. Create a named Blender collection and viewport outline for each region.
7. Number pieces within their owning region.
8. Generate a CSV assembly map.

This makes panel boundaries an assembly concern rather than a geometry-generation
boundary. The ocean-current wave, clustering, orientation, and packing all belong
to one artwork.

## 7. Numbering and the assembly map

Piece IDs use a region-and-piece format such as `P03-017`.

The generated CSV contains:

- piece ID;
- assembly-region label;
- panel column and row;
- local coordinates inside the region;
- coordinates across the complete artwork;
- rotation in degrees;
- height;
- approximate mouth diameter;
- form type;
- an optional five-level color group.

The color group is derived from the same height and cluster fields. A single-color
artwork can ignore it. A multicolor artwork can use it as a consistent grouping
system without changing placement.

Blender also stores these values as custom properties on every generated object.
The CSV is first written to a Blender Text data block and can then be saved from
the sidebar.

## 8. A1 Mini constraints

The Bambu Lab A1 Mini has a nominal 180 × 180 × 180 mm build volume. The add-on
uses a default 2.5 mm margin on every XY side, producing a 175 × 175 mm practical
maximum region or shared-base tile.

For a full artwork, the automatic planner:

- determines the required number of columns and rows;
- divides the artwork into equal regions;
- avoids a narrow remainder strip;
- optionally fits the broad wave wavelength to the assembled dimensions;
- checks the configured Z capacity;
- estimates piece and source-vertex counts before generation.

In modular mode, assembly regions are not pre-nested build plates. Pieces remain
in their final artwork positions in Blender so the composition can be inspected.
Selected groups should be exported and arranged in Bambu Studio for efficient
printing.

## 9. Glue feet and manifold output

The no-backing mode gives every form a small, closed, flat pad at Z = 0. The pad
provides a predictable contact surface for wood, acrylic, metal, foam, or another
backboard material. Its thickness and flange are adjustable.

In preview output, the closed foot and closed cup overlap. Many slicers combine
overlapping closed shells successfully, but the add-on also offers voxel-remeshed
manifold output. In numbered mode each piece is remeshed independently, avoiding
an enormous whole-artwork voxel operation.

Voxel remeshing is intentionally optional because it:

- takes longer;
- can soften thin rims;
- can close a very small throat if the voxel size is too large;
- is unnecessary during composition development.

The recommended workflow is to finalize the seed and proportions in preview mode,
then enable manifold output only for the production pass if required by the
slicer.

## 10. Shape families and presets

Several directions were retained instead of being discarded:

- **Modular Coral**: the recommended numbered glue-down workflow;
- **Dense Cellular Panel**: high-density, low-relief shared panels;
- **Balanced Funnels**: a general-purpose organic field;
- **Deep Hero Funnels**: fewer, deeper focal forms;
- **Strong Undercurrent**: pronounced directional sweep and troughs;
- **Glue-Down Funnels**: the earlier per-tile no-backing configuration;
- **Funnels + Blocks**: organic cups mixed with rounded solid columns;
- **Rounded Block Field**: only varying-height rounded blocks.

The block family answers the request for cube-like forms of varying height while
preserving the same global wave and clustering controls. It remains secondary to
the coral/tulip direction.

## 11. Print-oriented defaults

The recommended organic preset begins with:

- a 0.8 mm wall, targeting two lines with a 0.4 mm nozzle;
- a 1.2 mm glue foot;
- a 1.4 mm foot flange;
- smooth rims with rim scalloping disabled;
- off-center throats;
- moderate lean and bend;
- a broad wave plus a downward undercurrent;
- a lower count of larger forms than the earlier dense-tile presets.

These are starting points, not universal slicer settings. Every final piece should
be checked in layer preview, especially strongly leaning funnels and very small
throats.

## 12. Validation performed

The geometry core is covered by Blender-independent smoke tests that exercise:

- default funnel meshes;
- dense stress settings;
- individual glue feet;
- rounded blocks and mixed geometry;
- closed-edge manifold checks on source components;
- deterministic global fields and panel planning.

The add-on was also loaded and exercised in Blender 4.1.1. Validation included:

- class registration and preset application;
- standard preview generation;
- manual multi-panel generation;
- automatic finished-work planning;
- glue-foot and block modes;
- voxel-remeshed output;
- a six-region master modular artwork;
- creation and disk export of its assembly CSV.

## 13. Known limitations

- Collision-aware cells substantially reduce intersections, but aggressive lean,
  extreme mouth variation, or unsuitable custom settings can still create forms
  that are difficult to print.
- The region collections do not automatically optimize print-bed nesting.
- The CSV is a coordinate map rather than a graphical full-scale poster layout.
- Seam-crossing cups assume adjoining backing sections are aligned before those
  cups are glued down.
- Very large artwork dimensions or excessive density can exceed the safety limits
  intended to keep Blender responsive.
- Voxel remeshing can remove fine detail when its voxel size approaches the wall
  thickness.

## 14. Recommended production sequence

1. Install or update the add-on.
2. Apply **Modular Coral (Recommended)** so old `.blend` values do not persist.
3. Enter the exact finished artwork dimensions.
4. Generate in preview mode.
5. Inspect the artwork from the front and at a grazing angle.
6. Adjust scale hierarchy, mouth shape, wave, and undercurrent if needed.
7. Regenerate with the same seed while tuning; randomize only when a new
   composition is wanted.
8. Save the assembly CSV.
9. Test-print representative small, medium, hero, and strongly leaning pieces.
10. Enable manifold output only if the slicer needs it.
11. Export manageable groups and arrange them in Bambu Studio.
12. Mark the assembly-region grid and IDs on the backboard.
13. Dry-fit each region.
14. Align adjoining backing sections and install seam-crossing pieces.
15. Glue the remaining pieces using the CSV and Blender view as guides.

## 15. Current state

Version 1.7.0 is the first release that treats the wall piece as one master
composition and the printer-sized divisions as a downstream assembly system.
That architectural change is the most important step in moving from a field of
random cups toward the intended flowing, tightly packed coral artwork.
