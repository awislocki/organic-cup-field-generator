# Organic Cup Field Generator

`organic_cup_field_generator.py` is a Blender 4.x add-on for dense wall-relief
fields of smooth hollow calla/tulip-like cups. The reference-style defaults favor
thin continuous rims, rounded-triangular and teardrop mouths, large-to-small
clusters, coordinated swirls, and broad height relief with flowing depressions.
Version 1.7 adds a modular coral workflow inspired by the construction logic of
large assembled wall-art systems: the complete composition is packed once, then
its separate glue-down pieces are numbered and assigned to assembly regions.
Each organic form remains an original asymmetric funnel with a broad mouth and
curved cavity tapering toward a small, off-centre dark throat.

The modular organization takes visual and workflow cues from Paragami's Coral
Sponge examples and numbered-layout assembly method. It does not include, trace,
or reproduce Paragami model files or proprietary block geometry.

The add-on can generate one test tile, a manually sized panel grid, or a complete
numbered modular artwork for an exact finished size. Shared-base panels remain
separate objects; modular cups remain separate objects inside region collections.

## Install or update

1. In Blender 4.x, open **Edit → Preferences → Add-ons**.
2. Use the upper-right add-on menu and choose **Install from Disk**.
3. Select `organic_cup_field_generator.py` and enable **Organic Cup Field
   Generator**. When replacing an earlier version, disable it first and restart
   Blender after installing the new file.
4. In the 3D View, press **N** and open the **Organic Cups** tab.
5. Choose a **Style Preset** and click **Apply Selected Preset** before
   regenerating. This is especially important in an existing `.blend`: Blender
   preserves old scene values when an add-on is updated.

## Included style presets

- **Modular Coral (Recommended)** is the primary no-backing workflow. It creates
  a lower-density family of larger coral/tulip funnels, solves the entire artwork
  as one field, gives each piece a glue foot, and produces a numbered assembly
  map. This is the closest construction method to the Paragami Coral Sponge
  reference while using newly generated geometry.
- **Dense Cellular Panel** is the closest shared-base match to the large
  wall panels: low relief, nearly complete coverage, many fillers, restrained
  lean, and small off-centre throats.
- **Balanced Funnels** keeps more height and a broad general-purpose mixture of
  hero, medium, and small forms.
- **Deep Hero Funnels** uses fewer cups, a larger hero tier, smaller throats, and
  deeper cavities like the close reference view.
- **Strong Undercurrent** emphasizes directional lean, curling streamlines, and
  deeper trough channels across the global wave.
- **Glue-Down Funnels** removes the shared backing and gives every funnel a
  closed, flat mounting foot for printing as separate pieces and gluing to a
  wood, acrylic, metal, or printed panel.
- **Funnels + Blocks** mixes asymmetric hollow funnels with solid rounded-square
  columns while preserving the global height field.
- **Rounded Block Field** creates only solid rounded-square columns with
  clustered widths, rotations, and varying wave-driven heights.

Applying any preset preserves the finished artwork dimensions and random seed,
but resets manual tile dimensions to `175 × 175 mm`. This is exactly 5 mm smaller
than the A1 Mini's nominal 180 mm XY bed.

## Mounting and form modes

**Mounting Mode** is independent of the selected look:

- **Common Panel** creates the original closed rectangular backing.
- **Individual Glue Feet** omits that backing. Every funnel or block receives a
  small closed pad at Z = 0. **Glue Foot Thickness** controls pad thickness and
  **Glue Foot Flange** controls extra bonding area around the attachment root.

**Form Type** can be **Organic Funnels**, **Funnels + Blocks**, or **Rounded
Blocks**. In mixed mode, **Block Fraction** controls the ratio. **Block Bevel**
rounds the vertical and top edges. Blocks are solid, closed forms suitable for
straightforward FDM printing.

## Generate the complete artwork

1. Stay in **Object Mode**.
2. Under **Finished Work / A1 Mini**, enter the exact assembled width and height.
   The included `600 × 1200 mm` values are only an editable starting example.
3. Keep the A1 Mini bed at `180 × 180 × 180 mm`. The default 2.5 mm margin per
   side gives a practical maximum panel footprint of `175 × 175 mm`. Manual tile
   defaults and all included presets use the same 175 mm footprint.
4. Read the live plan shown in the sidebar. For the starting example it reports
   `4 × 7 = 28` equal panels, each `150 × 171.43 mm`.
5. For the modular method, choose **Numbered Glue-Down Pieces** and
   **Individual Glue Feet**. Leave **Voxel Merge / Manifold Output** off for the
   first design pass, then click **Generate Finished Work**.
6. Blender creates one master composition, panel-region collections and outline
   guides, separate objects named `P01-001`, `P01-002`, and so on, and a Text
   Editor data block named `OCF_Assembly_Map.csv`.
7. Inspect the complete assembled view. Adjust the field and regenerate until
   the composition is right. Panel boundaries do not influence packing or the
   height field.
8. Use **Save Assembly Map CSV** to save piece ID, assembly region, local and
   artwork coordinates, rotation, height, mouth diameter, form type, and one of
   five optional colour groups.
9. Enable **Voxel Merge / Manifold Output** only for the production pass if your
   slicer does not reliably unite the overlapping foot and cup shells. In the
   numbered workflow each piece is remeshed independently.

The automatic planner uses equal assembly-region dimensions, so it never creates
one narrow remainder strip. It also optionally scales the main wavelength to the
full artwork instead of restarting a small wave on every panel.

## Modular assembly workflow

The recommended workflow is meant for cups glued to a separate wood, acrylic,
metal, foam, or printed backboard:

1. Apply **Modular Coral (Recommended)**.
2. Enter the full finished width and height—not the printer-bed size.
3. Generate the finished work. The master packing solution is calculated over
   the complete dimensions before A1 Mini-sized assembly regions are assigned.
4. Use the viewport outline empties and the CSV map to mark the same grid on the
   backing. A cup whose rim crosses a grid line stays whole; its glue-foot centre
   determines which region owns it.
5. Print pieces in manageable slicer plates. The assembly-region collections are
   an organizational map, not pre-nested build plates; let Bambu Studio arrange
   selected pieces inside the 180 × 180 mm bed.
6. Dry-fit a region before gluing. Install seam-crossing pieces after adjoining
   backing sections are in their final aligned position.

The optional colour group is derived from the same continuous cluster and height
fields. It can be ignored for a single-colour artwork or used to organize up to
five filament colours without changing the composition.

## Reference-style controls

- **Density** is the primary cup count per 100 × 100 mm. The shared-panel presets
  use higher density; Modular Coral uses fewer, larger forms plus a smaller
  secondary tier from **Gap Fillers**.
- **Gap Fillers** place a second tier of small cups into the largest remaining
  voids, producing the tightly nested large/medium/tiny hierarchy in the photos.
  They are skipped automatically when a remaining void cannot hold a printable
  cup, rather than being forced into an intersection.
- **Hero Cup Fraction** promotes a controlled portion of primary cups into a
  distinctly larger tier. This creates focal funnels surrounded by cascades of
  medium and tiny cups instead of a field of similarly sized openings.
- **Packing Tightness** grows mouths toward weighted neighbor boundaries while
  retaining a very small printable seam between forms.
- **Minimum/Maximum Scale** provide the broad small-to-large size range visible in
  the references. **Cluster Strength/Scale** gather related sizes into pools and
  ribbons instead of distributing them independently.
- **Mouth Shape Variation** produces smooth amoeba and teardrop irregularity.
  **Mouth Elongation** ranges from near-round openings to long oval/calla forms.
- **Throat Size** controls the small cavity floor. **Throat Offset** moves that
  floor toward the narrow end of the teardrop, producing the asymmetric horn
  interiors and dark off-centre focal points visible in the references.
- **Tulip Form** creates a narrow root, softly swollen belly, slight upper neck,
  and flared opening. **Rim Scallop** defaults near zero because the reference
  rims are smooth and continuous; raise it only if visible lobes are wanted.
- **Height / Radius Limit** prevents tiny gap-fillers from becoming long stalks.
  Small cups stay shallow, medium cups form the cellular texture, and only broad
  cups can rise into the wave crests. Increase it only for a taller tube field.
- **Maximum Lean**, **Bend Variation**, and **Crest Size Correlation** coordinate
  low, strongly swept cups with the undercurrent and larger cups with the crests.
- **Flow Alignment**, **Flow Swirl**, and **Flow Scale** align mouth axes, lean,
  and primary bend to a continuous curl field. This creates the fans, ribbons,
  and vortices seen in the reference rather than unrelated random rotations.
- **Wave Amplitude/Wavelength/Direction** define the broad relief across the whole
  assembly. **Broad Wave Cycles** is used when automatic artwork fitting is on.
- **Undercurrent Depth/Scale/Direction** add warped channels that only push cup
  groups downward. Height noise adds restrained secondary variation.

Packing uses point relaxation, collision-aware radius reduction, and weighted
neighborhood-cell clipping at every wall ring. Lean and bend are constrained to
the same cells. This substantially reduces intersections while allowing adjacent
mouths to mold around one another. The reference preset also flares the bodies
earlier and biases each belly toward its flow direction, hiding the attachment
roots and avoiding the look of vertically extruded, diagonally cut pipes.

## Panel continuity and seams

Wave, height noise, undercurrent, clustering, and orientation flow are evaluated
in global millimeter coordinates. **Generate Finished Work** and **Generate Panel
Set** therefore preserve one continuous field across every panel coordinate.

In **Panel Meshes** mode, each physical tile still owns its cups and backing plate;
cups stop at its edge clearance. In **Numbered Glue-Down Pieces** mode, the full
artwork is packed first and the region grid is applied afterward. Rims can cross a
region boundary without clipping, so the wave and cellular packing have no
rectangular restart. This assumes the separate backing sections are aligned before
those seam-crossing pieces are glued down.

The **Manual Panel Set** section remains available for testing specific tile
coordinates. **Generate Field** replaces one coordinate; **Generate Panel Set**
creates the requested manual X-by-Y grid. **Generate Finished Work** calculates
those values automatically from the artwork and printer dimensions. Generated
object names include their X/Y panel coordinates, and finished-work objects also
store the effective panel grid and wave settings as custom properties.

## A1 Mini and FDM notes

- The A1 Mini build volume is 180 × 180 × 180 mm and its included nozzle is
  0.4 mm. The planner defaults to smaller 175 mm maximum panels to leave room for
  dimensional error and slicer behavior.
- Print shared-base panels flat-base-down with openings upward. For modular mode,
  print individual pieces foot-down. Verify dimensions in Bambu Studio.
- In **Numbered Glue-Down Pieces**, every cup is its own named Blender object.
  Export a manageable selection at a time and use the slicer's arrangement tool;
  do not attempt to print the entire assembled XY layout on one plate.
- Piece IDs restart inside each assembly region, and the CSV preserves exact
  placement and rotation. Marking the grid and piece IDs lightly on the backing
  greatly reduces assembly errors.
- The dark throat is a closed cavity floor, not a through-hole in the backing.
  Increasing **Throat Size** makes the deepest region easier to resolve with a
  large nozzle; decreasing it creates a sharper visual funnel.
- The 0.8 mm reference-style wall targets two 0.4 mm lines and produces a thin
  rim. If the slicer gives an inconsistent wall path, increase it to 1.0–1.2 mm
  or tune line width/wall loops.
- The 2.0 mm base is a practical starting point. Large finished works may benefit
  from ribs or a separate mounting frame after small-panel testing.
- Strong tilt and deep cups may create unsupported inner-wall regions. Inspect the
  layer preview and reduce lean/bend if support would be trapped inside a cavity.
- Preview output contains individually closed cup shells intersecting a closed
  base. Use **Manifold Output** for final production so Blender voxel-unions those
  roots and the backing plate.
- Start voxel size near half the wall thickness. Smaller values preserve thin
  rims but require more memory; larger values are faster and soften detail.
- Generate a full preview set before manifold output. Voxel-remeshing dozens of
  panels can take several minutes even though panels are processed separately.
- The dense preset can approach ten thousand cups on a large artwork. For quick
  composition drafts, lower **Density**, **Gap Fillers**, or mesh segment counts;
  restore the desired quality only for the final pass.
- Blender can be configured automatically to Metric/Millimeters with unit scale
  `0.001`. STL has no inherent unit metadata, so the slicer's reported dimensions
  are the final check.

Blender's voxel remesher can expand or soften an edge by approximately one voxel.
The printer margin and final slicer inspection are especially important when a
panel is close to the bed limit.

A1 Mini specifications above follow the official [Bambu Lab A1 Mini quick-start
guide](https://cdn1.bambulab.com/documentation/quick-start-f507128172bdf/Quick%20start%20guide%20-%20A1%20mini-EN.pdf).
