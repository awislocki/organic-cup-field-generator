bl_info = {
    "name": "Flowing Coral Reef Generator",
    "author": "OpenAI",
    "version": (2, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Coral Reef",
    "description": "Generate packed, hollow organic cup fields with globally continuous heights",
    "category": "Object",
}

"""Flowing Coral Reef Generator for Blender 4.x.

Individual glue-down forms are connected closed surfaces with integral flat feet.
Shared-base previews contain closed cup shells overlapping a closed base plate;
optional voxel remeshing unions those components. Artwork is composed globally
before assignment to assembly regions, with SVG maps and spaced STL print plates.

All authored dimensions are numeric millimeters.  When ``configure_scene_units``
is enabled (the default), Blender is set to Metric / Millimeters / 0.001 unit
scale. The built-in package writer exports numeric millimeters independently of
scene display units; external exporters require their own unit settings.
"""

import math
import random
import secrets
import time
import traceback
import json
import struct
import tempfile
import hashlib
from types import SimpleNamespace
from xml.sax.saxutils import escape
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup


ADDON_PREFIX = "CRF_"
ASSEMBLY_TEXT_NAME = "CRF_Assembly_Map.csv"
VERSION = "2.0.0"
UINT32_MASK = 0xFFFFFFFF
TAU = math.tau


# -----------------------------------------------------------------------------
# Deterministic global fields


def _clamp(value, low, high):
    return max(low, min(high, value))


def _lerp(a, b, t):
    return a + (b - a) * t


def _smoothstep(t):
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _mix_angle(angle_a, angle_b, factor):
    """Shortest-path circular interpolation without a wrap discontinuity."""
    factor = _clamp(factor, 0.0, 1.0)
    x = (1.0 - factor) * math.cos(angle_a) + factor * math.cos(angle_b)
    y = (1.0 - factor) * math.sin(angle_a) + factor * math.sin(angle_b)
    if abs(x) + abs(y) < 1.0e-9:
        return angle_b
    return math.atan2(y, x)


def _panel_plan(settings):
    """Return columns, rows, and equal panel dimensions for the finished work."""
    usable_x = settings.printer_bed_x - 2.0 * settings.printer_margin
    usable_y = settings.printer_bed_y - 2.0 * settings.printer_margin
    if usable_x <= 0.0 or usable_y <= 0.0:
        raise ValueError("Printer margin leaves no usable XY build area")
    columns = max(1, math.ceil(settings.finished_width / usable_x - 1.0e-9))
    rows = max(1, math.ceil(settings.finished_height / usable_y - 1.0e-9))
    panel_x = settings.finished_width / columns
    panel_y = settings.finished_height / rows
    return columns, rows, panel_x, panel_y, usable_x, usable_y


def _snapshot(settings, **overrides):
    """Plain numeric settings; never route artwork dimensions through RNA limits."""
    values = {
        name: getattr(settings, name)
        for name in CRFSettings.__annotations__
        if hasattr(settings, name) and name != "artwork_collection"
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _validate_settings(settings):
    for minimum, maximum, label in (
        (settings.min_cup_scale, settings.max_cup_scale, "Scale"),
        (settings.min_height, settings.max_height, "Height"),
        (settings.min_petals, settings.max_petals, "Rim lobes"),
    ):
        if minimum > maximum:
            raise ValueError(f"{label}: minimum must not exceed maximum")
    if settings.wall_thickness >= settings.min_height * 0.45:
        raise ValueError("Wall thickness is too large for the minimum height")
    _panel_plan(settings)


def _master_settings(settings):
    config = _snapshot(
        settings, tile_size_x=settings.finished_width,
        tile_size_y=settings.finished_height, tile_x=0, tile_y=0,
    )
    if config.auto_fit_wave_to_artwork:
        direction = math.radians(config.wave_direction)
        span = (abs(config.finished_width * math.cos(direction))
                + abs(config.finished_height * math.sin(direction)))
        config.wave_wavelength = span / config.wave_cycles_across_artwork
    return config


def _estimated_source_vertices(cup_count, settings):
    funnel_vertices = (
        (2 * (settings.vertical_segments + 1) + 5) * settings.radial_segments
    )
    block_vertices = 4 * settings.radial_segments
    if settings.form_style == "ROUNDED_BLOCKS":
        vertices_per_form = block_vertices
    else:
        # Mixed mode uses the more conservative all-funnel estimate.
        vertices_per_form = funnel_vertices
    if settings.base_mode == "INDIVIDUAL_FEET":
        vertices_per_form += 2 * settings.radial_segments
    shared_base_vertices = 8 if settings.base_mode == "COMMON_PANEL" else 0
    return shared_base_vertices + max(0, cup_count) * vertices_per_form


def _base_cup_count(area, settings):
    return max(1, int(round(settings.density * area / 10000.0)))


def _estimated_cup_count(area, settings):
    primary = _base_cup_count(area, settings)
    return primary + int(round(primary * settings.filler_fraction))


def _packing_gap(settings):
    """Small positive gap between weighted cup cells, in millimeters."""
    tightness = _clamp(settings.packing_tightness, 0.0, 1.0)
    return max(0.10, settings.wall_thickness * (0.32 - 0.20 * tightness))


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _mix32(value):
    value &= UINT32_MASK
    value ^= value >> 16
    value = (value * 0x7FEB352D) & UINT32_MASK
    value ^= value >> 15
    value = (value * 0x846CA68B) & UINT32_MASK
    value ^= value >> 16
    return value & UINT32_MASK


def _combined_seed(*values):
    """Stable integer mixing; unlike hash(), this is repeatable across sessions."""
    result = 0xA511E9B3
    for value in values:
        result ^= _mix32(int(value) + 0x9E3779B9)
        result = _mix32(result)
    return result


def _hash01(ix, iy, seed):
    mixed = _combined_seed(seed, ix * 0x1F123BB5, iy * 0x5F356495)
    return mixed / float(UINT32_MASK)


def _value_noise_2d(x, y, seed):
    """Continuous value noise in [-1, 1] using global integer lattice points."""
    ix = math.floor(x)
    iy = math.floor(y)
    fx = x - ix
    fy = y - iy
    sx = _fade(fx)
    sy = _fade(fy)

    n00 = _hash01(ix, iy, seed) * 2.0 - 1.0
    n10 = _hash01(ix + 1, iy, seed) * 2.0 - 1.0
    n01 = _hash01(ix, iy + 1, seed) * 2.0 - 1.0
    n11 = _hash01(ix + 1, iy + 1, seed) * 2.0 - 1.0

    nx0 = _lerp(n00, n10, sx)
    nx1 = _lerp(n01, n11, sx)
    return _lerp(nx0, nx1, sy)


def _fbm_2d(x, y, seed, octaves=4):
    total = 0.0
    amplitude = 1.0
    normalizer = 0.0
    frequency = 1.0
    for octave in range(octaves):
        octave_seed = _combined_seed(seed, 0xB5297A4D + octave * 1013)
        total += amplitude * _value_noise_2d(
            x * frequency, y * frequency, octave_seed
        )
        normalizer += amplitude
        amplitude *= 0.5
        frequency *= 2.03
    return total / max(normalizer, 1.0e-9)


def _cluster_value(global_x, global_y, settings):
    scale = max(18.0, settings.cluster_scale)
    noise = _fbm_2d(
        global_x / scale,
        global_y / scale,
        _combined_seed(settings.random_seed, 0xC10C7E),
        octaves=3,
    )
    # The extra broad wave gives clusters a legible large-scale rhythm.
    broad = math.sin(
        TAU * (global_x * 0.67 + global_y * 0.31) / max(scale * 2.4, 1.0)
        + (_combined_seed(settings.random_seed, 47) / UINT32_MASK) * TAU
    )
    return _clamp(0.5 + 0.40 * noise + 0.10 * broad, 0.0, 1.0)


def _orientation_flow_angle(global_x, global_y, settings):
    """Low-frequency curl field used by mouth rotation, lean, and bend."""
    scale = max(18.0, settings.orientation_flow_scale)
    step = max(0.75, scale * 0.018)
    seed = _combined_seed(settings.random_seed, 0xC041A)

    def sample(x, y):
        return _fbm_2d(x / scale, y / scale, seed, octaves=4)

    gradient_x = sample(global_x + step, global_y) - sample(
        global_x - step, global_y
    )
    gradient_y = sample(global_x, global_y + step) - sample(
        global_x, global_y - step
    )
    curl_x = gradient_y
    curl_y = -gradient_x
    magnitude = math.hypot(curl_x, curl_y)
    if magnitude > 1.0e-8:
        curl_x /= magnitude
        curl_y /= magnitude
    else:
        curl_x, curl_y = 1.0, 0.0

    broad_angle = math.radians(settings.wave_direction)
    broad_x = math.cos(broad_angle)
    broad_y = math.sin(broad_angle)
    swirl = settings.flow_swirl
    flow_x = (1.0 - swirl) * broad_x + swirl * curl_x
    flow_y = (1.0 - swirl) * broad_y + swirl * curl_y
    if abs(flow_x) + abs(flow_y) < 1.0e-8:
        return broad_angle
    return math.atan2(flow_y, flow_x)


def _height_at(global_x, global_y, settings):
    direction = math.radians(settings.wave_direction)
    projected = global_x * math.cos(direction) + global_y * math.sin(direction)
    transverse = -global_x * math.sin(direction) + global_y * math.cos(direction)
    wavelength = max(settings.wave_wavelength, 1.0)
    seed_phase = (_combined_seed(settings.random_seed, 0xFACE) / UINT32_MASK) * TAU

    phase = TAU * projected / wavelength + seed_phase
    wave = settings.wave_amplitude * (
        0.72 * math.sin(phase)
        + 0.20 * math.sin(phase * 0.51 + 1.35)
        + 0.08 * math.sin(TAU * transverse / (wavelength * 1.7) - 0.6)
    )

    noise_scale = max(settings.noise_scale, 2.0)
    noise = settings.noise_amplitude * _fbm_2d(
        global_x / noise_scale,
        global_y / noise_scale,
        _combined_seed(settings.random_seed, 0x71E1D),
        octaves=4,
    )

    # A separate directional field only subtracts height.  Its warped channels
    # read as a submerged current pressing selected groups downward while the
    # broad sine wave remains legible across the full assembled panel set.
    current_direction = math.radians(settings.undercurrent_direction)
    current_along = (
        global_x * math.cos(current_direction)
        + global_y * math.sin(current_direction)
    )
    current_across = (
        -global_x * math.sin(current_direction)
        + global_y * math.cos(current_direction)
    )
    current_scale = max(settings.undercurrent_scale, 6.0)
    current_seed = _combined_seed(settings.random_seed, 0x0CE4A)
    current_warp = _fbm_2d(
        global_x / (current_scale * 1.8),
        global_y / (current_scale * 1.8),
        current_seed,
        octaves=3,
    )
    current_phase = (
        TAU
        * (
            current_across
            + current_along * 0.16
            + current_warp * current_scale * 0.42
        )
        / current_scale
        + (_combined_seed(settings.random_seed, 0xD0A1) / UINT32_MASK) * TAU
    )
    current_channel = 0.5 + 0.5 * math.sin(current_phase)
    current_channel = _smoothstep((current_channel - 0.38) / 0.62) ** 1.55
    current_patch = 0.5 + 0.5 * _fbm_2d(
        global_x / (current_scale * 0.82),
        global_y / (current_scale * 0.82),
        _combined_seed(current_seed, 0xA11CE),
        octaves=3,
    )
    undercurrent = -settings.undercurrent_depth * current_channel * (
        0.28 + 0.72 * current_patch
    )

    minimum = settings.min_height
    maximum = settings.max_height
    midpoint = 0.5 * (minimum + maximum)
    micro_variation = (
        0.035
        * (maximum - minimum)
        * _value_noise_2d(
            global_x / 24.0,
            global_y / 24.0,
            _combined_seed(settings.random_seed, 0x51A11),
        )
    )
    return _clamp(
        midpoint + wave + noise + undercurrent + micro_variation,
        minimum,
        maximum,
    )


# -----------------------------------------------------------------------------
# Packing and cup specifications


# -----------------------------------------------------------------------------
# Mesh construction


def _centerline_offset(spec, t):
    bend_envelope = math.sin(math.pi * t)
    s_curve = math.sin(TAU * t)
    return (
        spec["lean_x"] * t
        + spec["bend_x"] * bend_envelope
        + spec["bend2_x"] * s_curve,
        spec["lean_y"] * t
        + spec["bend_y"] * bend_envelope
        + spec["bend2_y"] * s_curve,
    )


def _mouth_factor(spec, theta):
    value = 1.0
    value += spec["elongation"] * math.cos(2.0 * theta)
    # A first/second harmonic blend produces an amoeba-like teardrop rather
    # than merely translating a circular ring.
    value += spec["teardrop"] * (
        0.72 * math.cos(theta)
        - 0.23 * math.cos(2.0 * theta)
        + spec["teardrop_bias"] * math.cos(3.0 * theta)
    )
    for harmonic, coefficient, phase in spec["coefficients"]:
        value += coefficient * math.cos(harmonic * theta + phase)
    value += spec["petal_radial"] * math.cos(
        spec["petal_count"] * theta + spec["petal_phase"]
    )
    return _clamp(value, 0.62, 1.44)


def _petal_drop_at(spec, theta):
    """Downward lip offset: petal tips stay high and valleys sweep lower."""
    petal_wave = 0.5 + 0.5 * math.cos(
        spec["petal_count"] * theta + spec["petal_phase"]
    )
    pointed_tip = petal_wave ** 1.45
    return spec["petal_drop"] * (1.0 - pointed_tip)


def _radial_limits(spec, t, settings, count):
    offset_x, offset_y = _centerline_offset(spec, t)
    edge = settings.edge_clearance
    xmin = -settings.tile_size_x * 0.5 + edge
    xmax = settings.tile_size_x * 0.5 - edge
    ymin = -settings.tile_size_y * 0.5 + edge
    ymax = settings.tile_size_y * 0.5 - edge
    minimum_outer = settings.wall_thickness * 1.95

    # Lean and bend are also constrained to the cup's packing cell.  This keeps
    # a strongly leaning centerline from escaping the cell before its radius is
    # evaluated, which would otherwise force a tiny or inverted wall ring.
    for _pass in range(8):
        for nx, ny, plane_limit in spec["planes"]:
            excess = (
                offset_x * nx
                + offset_y * ny
                - (plane_limit - minimum_outer)
            )
            if excess > 0.0:
                offset_x -= nx * excess
                offset_y -= ny * excess

        center_x = _clamp(
            spec["x"] + offset_x,
            xmin + minimum_outer,
            xmax - minimum_outer,
        )
        center_y = _clamp(
            spec["y"] + offset_y,
            ymin + minimum_outer,
            ymax - minimum_outer,
        )
        offset_x = center_x - spec["x"]
        offset_y = center_y - spec["y"]

    center_x = spec["x"] + offset_x
    center_y = spec["y"] + offset_y

    # Tulip/calla bodies flare early, hiding the narrow attachment roots below
    # a broad shoulder instead of reading as isolated straight stalks.
    ease = _smoothstep(t ** 0.45)
    profile = (
        spec["root_ratio"]
        + (1.0 - spec["root_ratio"]) * ease
        + spec["belly"] * math.sin(math.pi * t)
    )
    # The upper constriction gives the swollen body and opening flare of a
    # tulip.  It returns to zero at the lip, so the final mouth still packs to
    # its weighted cell boundary.
    upper_t = _clamp((t - 0.53) / 0.47, 0.0, 1.0)
    profile -= spec["neck"] * math.sin(math.pi * upper_t)
    variation_envelope = 0.16 + 0.84 * ease
    # Let the mouth expand far enough to meet its weighted Voronoi-like cell.
    # The cell itself remains the hard collision boundary, so stronger fill
    # creates the molded-together reference look without inviting intersections.
    fill = 1.0 + (0.35 + 0.80 * settings.packing_tightness) * ease

    desired = []
    limits = []
    for segment in range(count):
        theta = TAU * segment / count
        world_theta = theta + spec["rotation"]
        ux = math.cos(world_theta)
        uy = math.sin(world_theta)
        shape = 1.0 + (_mouth_factor(spec, theta) - 1.0) * variation_envelope
        # A side-biased middle flare makes the body sweep like a calla instead
        # of looking like a vertical cylinder with an obliquely cut top.
        shape *= 1.0 + spec["sweep"] * (math.sin(math.pi * t) ** 1.2) * math.cos(
            world_theta - spec["lean_direction"]
        )
        raw_radius = spec["radius"] * profile * shape * fill

        allowed = float("inf")
        if ux > 1.0e-7:
            allowed = min(allowed, (xmax - center_x) / ux)
        elif ux < -1.0e-7:
            allowed = min(allowed, (xmin - center_x) / ux)
        if uy > 1.0e-7:
            allowed = min(allowed, (ymax - center_y) / uy)
        elif uy < -1.0e-7:
            allowed = min(allowed, (ymin - center_y) / uy)

        for nx, ny, plane_limit in spec["planes"]:
            denominator = ux * nx + uy * ny
            if denominator <= 1.0e-6:
                continue
            numerator = plane_limit - (offset_x * nx + offset_y * ny)
            allowed = min(allowed, numerator / denominator)

        allowed = max(minimum_outer, allowed)
        desired.append(max(minimum_outer, raw_radius))
        limits.append(allowed)

    radii = [min(desired[i], limits[i]) for i in range(count)]
    # Inward-only circular smoothing rounds Voronoi corners without violating
    # the collision cell that produced the limit.
    for _pass in range(5):
        smoothed = []
        for i in range(count):
            candidate = (
                0.22 * radii[(i - 1) % count]
                + 0.56 * radii[i]
                + 0.22 * radii[(i + 1) % count]
            )
            smoothed.append(min(limits[i], max(minimum_outer, candidate)))
        radii = smoothed

    return radii, offset_x, offset_y


def _append_ring(vertices, spec, radii, offset_x, offset_y, z):
    ring = []
    count = len(radii)
    for segment, radius in enumerate(radii):
        theta = TAU * segment / count + spec["rotation"]
        z_value = z[segment] if isinstance(z, (list, tuple)) else z
        ring.append(len(vertices))
        vertices.append(
            (
                spec["x"] + offset_x + math.cos(theta) * radius,
                spec["y"] + offset_y + math.sin(theta) * radius,
                z_value,
            )
        )
    return ring


def _ring_z_values(spec, t, base_top, height, radii):
    nominal_z = base_top + height * t
    petal_envelope = _smoothstep((t - 0.46) / 0.54)
    tilt_envelope = _smoothstep((t - 0.10) / 0.90)
    tilt_slope = math.tan(spec["tilt_angle"] * 0.82)
    largest_radius = max(radii)
    if tilt_slope > 1.0e-8 and largest_radius > 1.0e-8:
        tilt_scale = min(1.0, (height * 0.42) / (largest_radius * tilt_slope))
    else:
        tilt_scale = 0.0
    count = len(radii)
    return [
        nominal_z
        - _petal_drop_at(spec, TAU * segment / count) * petal_envelope
        - radii[segment]
        * tilt_slope
        * tilt_scale
        * tilt_envelope
        * math.cos(
            TAU * segment / count + spec["rotation"] - spec["lean_direction"]
        )
        for segment in range(count)
    ]


def _bridge_outer(faces, lower, upper):
    count = len(lower)
    for i in range(count):
        j = (i + 1) % count
        faces.append((lower[i], lower[j], upper[j], upper[i]))


def _bridge_inner(faces, lower, upper):
    count = len(lower)
    for i in range(count):
        j = (i + 1) % count
        faces.append((lower[i], upper[i], upper[j], lower[j]))


def _support_top(settings):
    if settings.base_mode == "INDIVIDUAL_FEET":
        return settings.individual_base_thickness
    return settings.base_thickness


def _block_footprint(spec, settings, count):
    """Rounded-square radial footprint clipped to the same packing cell."""
    edge = settings.edge_clearance
    xmin = -settings.tile_size_x * 0.5 + edge
    xmax = settings.tile_size_x * 0.5 - edge
    ymin = -settings.tile_size_y * 0.5 + edge
    ymax = settings.tile_size_y * 0.5 - edge
    center_x = spec["x"]
    center_y = spec["y"]
    minimum_outer = settings.wall_thickness * 1.45
    target = spec["radius"] * (0.82 + 0.08 * settings.packing_tightness)
    desired = []
    limits = []

    for segment in range(count):
        theta = TAU * segment / count
        world_theta = theta + spec["rotation"]
        ux = math.cos(world_theta)
        uy = math.sin(world_theta)
        square_factor = 1.0 / max(
            (abs(math.cos(theta)) ** 6.0 + abs(math.sin(theta)) ** 6.0)
            ** (1.0 / 6.0),
            1.0e-6,
        )
        raw_radius = target * square_factor

        allowed = float("inf")
        if ux > 1.0e-7:
            allowed = min(allowed, (xmax - center_x) / ux)
        elif ux < -1.0e-7:
            allowed = min(allowed, (xmin - center_x) / ux)
        if uy > 1.0e-7:
            allowed = min(allowed, (ymax - center_y) / uy)
        elif uy < -1.0e-7:
            allowed = min(allowed, (ymin - center_y) / uy)
        for nx, ny, plane_limit in spec["planes"]:
            denominator = ux * nx + uy * ny
            if denominator > 1.0e-6:
                allowed = min(allowed, plane_limit / denominator)

        desired.append(max(minimum_outer, raw_radius))
        limits.append(max(minimum_outer, allowed))

    radii = [min(desired[i], limits[i]) for i in range(count)]
    for _pass in range(2):
        smoothed = []
        for i in range(count):
            candidate = (
                0.10 * radii[(i - 1) % count]
                + 0.80 * radii[i]
                + 0.10 * radii[(i + 1) % count]
            )
            smoothed.append(min(limits[i], max(minimum_outer, candidate)))
        radii = smoothed
    return radii


def _append_block(vertices, faces, spec, settings):
    """Closed solid rounded-square column with a globally driven height."""
    radial_count = settings.radial_segments
    radii = _block_footprint(spec, settings, radial_count)
    support_top = _support_top(settings)
    embed = min(support_top * 0.32, 0.55)
    bottom_z = (0.0 if settings.base_mode == "INDIVIDUAL_FEET"
                else support_top - embed)
    top_z = support_top + spec["height"]
    total_height = top_z - bottom_z
    bevel = min(
        settings.block_bevel,
        total_height * 0.22,
        min(radii) * 0.28,
    )
    inset = bevel * 0.35
    inset_radii = [max(settings.wall_thickness, radius - inset) for radius in radii]

    levels = (
        (bottom_z, inset_radii),
        (bottom_z + bevel, radii),
        (top_z - bevel, radii),
        (top_z, inset_radii),
    )
    if bevel < 1e-8:
        levels = ((bottom_z, radii), (top_z, radii))
    rings = [
        _append_ring(vertices, spec, level_radii, 0.0, 0.0, z)
        for z, level_radii in levels
    ]
    faces.append(tuple(reversed(rings[0])))
    for lower, upper in zip(rings[:-1], rings[1:]):
        _bridge_outer(faces, lower, upper)
    faces.append(tuple(rings[-1]))


def _append_base(vertices, faces, settings):
    x0 = -settings.tile_size_x * 0.5
    x1 = settings.tile_size_x * 0.5
    y0 = -settings.tile_size_y * 0.5
    y1 = settings.tile_size_y * 0.5
    z0 = 0.0
    z1 = settings.base_thickness
    start = len(vertices)
    vertices.extend(
        (
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, z1),
            (x1, y0, z1),
            (x1, y1, z1),
            (x0, y1, z1),
        )
    )
    faces.extend(
        (
            (start + 0, start + 3, start + 2, start + 1),
            (start + 4, start + 5, start + 6, start + 7),
            (start + 0, start + 1, start + 5, start + 4),
            (start + 1, start + 2, start + 6, start + 5),
            (start + 2, start + 3, start + 7, start + 6),
            (start + 3, start + 0, start + 4, start + 7),
        )
    )


def _reef_stream(x, y, settings):
    """One continuous stream function: size bands and directions share contours."""
    scale = max(20.0, settings.orientation_flow_scale)
    angle = math.radians(settings.wave_direction)
    u = (x * math.cos(angle) + y * math.sin(angle)) / scale
    v = (-x * math.sin(angle) + y * math.cos(angle)) / scale
    phase = TAU * _hash01(83, 19, settings.random_seed)
    return (v + settings.flow_swirl * (
        0.68 * math.sin(1.45 * u + 0.70 * math.sin(0.9 * v + phase))
        + 0.34 * math.sin(2.5 * u - 0.65 * v + phase)
    ))


def _reef_field(x, y, settings):
    psi = _reef_stream(x, y, settings)
    broad = 0.5 + 0.5 * math.sin(TAU * psi)
    # Wide small-cup rivers alternate with islands of broad open funnels.
    island = _smoothstep((broad - 0.20) / 0.80) ** 1.35
    step = 0.1
    dx = _reef_stream(x + step, y, settings) - _reef_stream(x - step, y, settings)
    dy = _reef_stream(x, y + step, settings) - _reef_stream(x, y - step, settings)
    angle = math.atan2(-dx, dy)
    return island, angle


def _reef_specs(settings):
    """Adaptive best-candidate packing followed by shared convex cell constraints.

    Unlike uniform seeds with independently randomized radii, local target size
    affects where seeds are placed. Small elongated cells form continuous rivers.
    All pairwise constraints are symmetric: their limits sum to distance - gap.
    """
    area = settings.tile_size_x * settings.tile_size_y
    count = min(1500, _base_cup_count(area, settings))
    spacing = math.sqrt(area / max(count, 1))
    rng = random.Random(_combined_seed(settings.random_seed, settings.tile_x, settings.tile_y, 927))
    half_x, half_y = settings.tile_size_x / 2, settings.tile_size_y / 2
    ox, oy = settings.tile_x * settings.tile_size_x, settings.tile_y * settings.tile_size_y
    guard = max(settings.wall_thickness * 4, settings.edge_clearance + 2, spacing * 0.25)
    points, weights, fields, flows = [], [], [], []
    for index in range(count):
        best = None
        for attempt in range(36):
            x, y = rng.uniform(-half_x + guard, half_x - guard), rng.uniform(-half_y + guard, half_y - guard)
            island, angle = _reef_field(x + ox, y + oy, settings)
            weight = _lerp(settings.min_cup_scale, settings.max_cup_scale,
                           _lerp(rng.uniform(0.15, 0.85), island, settings.cluster_strength))
            if points:
                ca, sa = math.cos(angle), math.sin(angle)
                stretch = 1.0 + 0.65 * (1 - island) * settings.flow_alignment
                score = min(
                    math.hypot(((x - px) * ca + (y - py) * sa) / stretch,
                               (-(x - px) * sa + (y - py) * ca) * stretch) / (weight + w)
                    for (px, py), w in zip(points, weights)
                )
            else:
                score = 1
            if best is None or score > best[0]:
                best = score, x, y, weight, island, angle
        _, x, y, weight, island, angle = best
        points.append((x, y))
        weights.append(weight)
        fields.append(island)
        flows.append(angle)

    gap = max(0.35, settings.wall_thickness * 0.55)
    specs = []
    for index, ((x, y), weight, island, angle) in enumerate(zip(points, weights, fields, flows)):
        planes = [(1., 0., half_x - settings.edge_clearance - x),
                  (-1., 0., half_x - settings.edge_clearance + x),
                  (0., 1., half_y - settings.edge_clearance - y),
                  (0., -1., half_y - settings.edge_clearance + y)]
        # Including every pair provides an actual separation guarantee. Prune
        # only planes that cannot meet the bounded tile rectangle's ray circle.
        for j, ((px, py), w) in enumerate(zip(points, weights)):
            if j == index:
                continue
            distance = math.hypot(px - x, py - y)
            limit = distance * weight / (weight + w) - gap / 2
            planes.append(((px - x) / distance, (py - y) / distance, limit))
        minimum = min(p[2] for p in planes)
        if minimum < settings.wall_thickness * 2.6:
            raise ValueError("Some cells are too narrow for this wall. Lower Density or increase Minimum Scale.")
        # Distant constraints beyond the maximum local cell radius are redundant.
        probes = []
        for k in range(48):
            ca, sa = math.cos(TAU * k / 48), math.sin(TAU * k / 48)
            probes.append(min(d / (nx * ca + ny * sa) for nx, ny, d in planes if nx * ca + ny * sa > 1e-8))
        bound = max(probes) * 1.5
        planes = [p for p in planes if p[2] < bound]
        radius = sorted(probes)[len(probes) // 2]
        rotation = angle + math.radians(settings.base_rotation)
        rotation += math.radians(rng.uniform(-settings.rotation_variation, settings.rotation_variation)) * (1 - settings.flow_alignment)
        height_field = _height_at(x + ox, y + oy, settings)
        height = _clamp(
            radius * (1.25 + 0.85 * island) + 0.4 * (height_field - (settings.min_height + settings.max_height) / 2)
            - settings.undercurrent_depth * (1 - island) * 0.22,
            settings.min_height, settings.max_height,
        )
        height = min(height, settings.min_height * 0.4 + radius * settings.height_radius_limit)
        form_type = "BLOCK" if (settings.form_style == "ROUNDED_BLOCKS" or
                    (settings.form_style == "MIXED" and rng.random() < settings.block_fraction)) else "FUNNEL"
        spec = dict(index=index, form_type=form_type, x=x, y=y, global_x=x + ox, global_y=y + oy,
                    radius=radius, height=height, cluster=island, river=1-island, planes=planes,
                    rotation=rotation, root_ratio=0.22, coefficients=[], elongation=0,
                    teardrop=0, teardrop_bias=0, throat_radius=radius * settings.throat_size,
                    throat_offset=0, throat_direction=rotation, throat_oval=0, belly=0,
                    neck=0, sweep=0, petal_count=3, petal_phase=0, petal_radial=0, petal_drop=0,
                    lean_x=0, lean_y=0, bend_x=0, bend_y=0, bend2_x=0, bend2_y=0,
                    lean_direction=rotation + math.pi / 2, tilt_angle=0)
        n = settings.radial_segments
        variation = settings.mouth_variation
        aspect = 1.0 + settings.mouth_elongation * (0.6 + 3.3 * (1-island))
        triangle_phase = rng.uniform(-0.4, 0.4)
        desired = []
        for j in range(n):
            theta = TAU * j / n
            ca, sa = math.cos(theta + rotation), math.sin(theta + rotation)
            limit = min(d / (nx * ca + ny * sa) for nx, ny, d in planes if nx * ca + ny * sa > 1e-9)
            ellipse = 1 / math.sqrt(math.cos(theta)**2 / aspect + math.sin(theta)**2 * aspect)
            organic = 1 + variation * (0.17 * math.cos(3 * theta + triangle_phase) + 0.10 * math.cos(theta - 0.4))
            target = radius * 1.45 * ellipse * organic
            # Blend ALL neighboring constraints analytically. A hard minimum
            # makes polygonal mouths and radial creases; this smooth minimum
            # produces softly molded organic outlines while staying in-cell.
            power = 5.0
            inverse = (1 / target) ** power + sum(
                (max(0, nx*ca + ny*sa) / d)**power for nx, ny, d in planes)
            rr = inverse ** (-1 / power)
            desired.append(rr * _lerp(0.86, 0.985, settings.packing_tightness))
        for _ in range(3):
            desired = [min(r, (desired[(j-1) % n] + 2*r + desired[(j+1) % n]) / 4)
                       for j, r in enumerate(desired)]
        spec["reef_mouth"] = desired
        spec["reef_root"] = min(
            max(settings.wall_thickness * 3.1,
                min(min(desired) * 0.48, radius * (0.15 + settings.throat_size))),
            minimum * 0.80, min(desired) * 0.78,
        )
        # Root displacement makes a curved, off-centre throat, but both ends
        # remain in the same convex cell. The body interpolates between them.
        root_shift = min(minimum * 0.25, radius * settings.throat_offset * 0.7,
                         max(0, minimum-spec["reef_root"]) * 0.6)
        spec["reef_root_xy"] = (-math.cos(spec["lean_direction"]) * root_shift,
                                -math.sin(spec["lean_direction"]) * root_shift)
        spec["reef_rim_slope"] = math.tan(math.radians(settings.max_lean * (0.25 + 0.75*(1-island))))
        spec["reef_bend"] = settings.bend_variation * rng.uniform(0.6, 1.0)
        specs.append(spec)
    return (_reef_fill_gaps(specs, settings, rng)
            if settings.form_style != "ROUNDED_BLOCKS" else specs)


def _reef_fill_gaps(specs, settings, rng):
    """Fit small forms in actual leftover mouth gaps without shrinking heroes.

    A planar BVH gives distance to every primary footprint, not merely nearby
    centres. Subsequent fillers reserve conservative bounding disks. Projection
    clearance includes the rounded lip's possible outward extension.
    """
    from mathutils.bvhtree import BVHTree
    from mathutils import Vector
    vertices, polygons = [], []
    for spec in specs:
        n = len(spec['reef_mouth'])
        first = len(vertices)
        vertices.extend((spec['x'] + r*math.cos(TAU*j/n + spec['rotation']),
                         spec['y'] + r*math.sin(TAU*j/n + spec['rotation']), 0)
                        for j, r in enumerate(spec['reef_mouth']))
        polygons.append(tuple(range(first, first+n)))
    tree = BVHTree.FromPolygons(vertices, polygons, all_triangles=False)
    half_x = settings.tile_size_x/2 - settings.edge_clearance
    half_y = settings.tile_size_y/2 - settings.edge_clearance
    margin = settings.wall_thickness*1.3 + 0.35
    minimum = settings.wall_thickness*4.8
    fillers = []
    target = round(len(specs)*settings.filler_fraction)
    for _ in range(target):
        best = None
        for _ in range(120):
            x, y = rng.uniform(-half_x, half_x), rng.uniform(-half_y, half_y)
            distance = tree.find_nearest(Vector((x, y, 0)))[3]
            available = min(distance, half_x-abs(x), half_y-abs(y)) - margin
            for fx, fy, radius in fillers:
                available = min(available, math.hypot(x-fx, y-fy)-radius-margin)
            if best is None or available > best[0]:
                best = available, x, y
        radius, x, y = best
        if radius < minimum:
            continue
        # Reuse the complete schema but replace every spatial/shape-dependent
        # field. Filler mouths stay in their reserved disk at every height.
        template = min(specs, key=lambda s: (s['x']-x)**2 + (s['y']-y)**2)
        spec = dict(template)
        gx = x + settings.tile_x*settings.tile_size_x
        gy = y + settings.tile_y*settings.tile_size_y
        island, angle = _reef_field(gx, gy, settings)
        rotation = angle + math.radians(settings.base_rotation)
        n = settings.radial_segments
        aspect = 1.25 + settings.mouth_elongation*0.8
        mouth = [radius * 0.99 * (1 + .06*math.cos(3*TAU*j/n)) / 1.06 /
                 math.sqrt(math.cos(TAU*j/n)**2 + (aspect*math.sin(TAU*j/n))**2)
                 for j in range(n)]
        spec.update(index=len(specs), x=x, y=y, global_x=gx, global_y=gy,
                    form_type='FUNNEL', radius=radius, height=max(settings.min_height,
                    min(settings.max_height, radius*1.4)), cluster=island, river=1.,
                    rotation=rotation, lean_direction=rotation+math.pi/2,
                    reef_mouth=mouth, reef_root=max(settings.wall_thickness*2.7, radius*.24),
                    reef_root_xy=(0., 0.), reef_rim_slope=math.tan(math.radians(settings.max_lean*.75)),
                    reef_bend=0., planes=[(math.cos(TAU*j/32), math.sin(TAU*j/32), radius) for j in range(32)])
        specs.append(spec)
        fillers.append((x, y, radius))
    return specs


def _reef_outer_rings(spec, settings):
    """A single flaring horn surface; the inside is derived from its normals."""
    n, levels = settings.radial_segments, settings.vertical_segments
    root = spec["reef_root"]
    rx, ry = spec["reef_root_xy"]
    support = _support_top(settings)
    height = spec["height"]
    radii = spec["reef_mouth"]
    rotation = spec["rotation"]
    max_tilt = max(abs(r * math.sin(TAU*j/n) * spec["reef_rim_slope"]) for j, r in enumerate(radii))
    tilt_scale = min(1.0, height * 0.44 / max(max_tilt, 1e-9))
    rings = []
    for k in range(levels + 1):
        t = k / levels
        # A progressively opening trumpet: no cylindrical stalk, no hollowing
        # wedge. The square-root-like profile stays concave and gently flares.
        flare = (t + 0.12) ** 0.72 - 0.12 ** 0.72
        flare /= 1.12 ** 0.72 - 0.12 ** 0.72
        shift = (1-t) ** (1.2 + spec["reef_bend"])
        ring = []
        for j, mouth in enumerate(radii):
            theta = TAU * j / n
            radius = _lerp(root, mouth, flare)
            x = rx * shift + radius * math.cos(theta + rotation)
            y = ry * shift + radius * math.sin(theta + rotation)
            z = support + height*t - mouth * math.sin(theta) * spec["reef_rim_slope"] * tilt_scale * t**1.65
            ring.append((spec["x"] + x, spec["y"] + y, z))
        rings.append(ring)
    return rings


def _reef_append_cup(vertices, faces, spec, settings):
    from mathutils import Vector
    outer = _reef_outer_rings(spec, settings)
    n, levels = settings.radial_segments, settings.vertical_segments
    wall = settings.wall_thickness
    inner, normals, tangents = [], [], []
    for k, ring in enumerate(outer):
        inner_ring, ns, ts = [], [], []
        for j, co in enumerate(ring):
            along = Vector(outer[min(k+1, levels)][j]) - Vector(outer[max(0, k-1)][j])
            around = Vector(ring[(j+1) % n]) - Vector(ring[(j-1) % n])
            normal = around.cross(along).normalized()
            tangent = normal.cross(around).normalized()
            # A geometric normal offset, not a separately interpolated cavity.
            inner_ring.append(tuple(Vector(co) - wall * normal))
            ns.append(normal)
            ts.append(tangent)
        inner.append(inner_ring)
        normals.append(ns)
        tangents.append(ts)

    def add_ring(points):
        ids = list(range(len(vertices), len(vertices) + len(points)))
        vertices.extend(points)
        return ids

    # Make the cavity floor horizontal, above the glue contact surface. Only
    # this root transition is deliberately thicker than the nominal shell.
    # Lower to the lowest root sample. Raising to the highest sample can cut
    # across the first inner wall ring of a small, highly tilted cup.
    floor_z = min(p[2] for p in inner[0])
    inner[0] = [(p[0], p[1], floor_z) for p in inner[0]]
    outer_ids = [add_ring(r) for r in outer]
    inner_ids = [add_ring(r) for r in inner]
    for lo, hi in zip(outer_ids, outer_ids[1:]):
        _bridge_outer(faces, lo, hi)
    for lo, hi in zip(inner_ids, inner_ids[1:]):
        _bridge_inner(faces, lo, hi)
    faces.append(tuple(inner_ids[0]))
    # Semicircular lip follows the cross-section; added material is local only.
    previous = outer_ids[-1]
    for step in range(1, 4):
        phi = math.pi * step / 4
        crown = []
        for j, p in enumerate(outer[-1]):
            normal, tangent = normals[-1][j], tangents[-1][j]
            co = Vector(p) + wall/2 * ((math.cos(phi)-1) * normal + math.sin(phi) * tangent)
            crown.append(tuple(co))
        ring = add_ring(crown)
        _bridge_outer(faces, previous, ring)
        previous = ring
    _bridge_outer(faces, previous, inner_ids[-1])

    radii, dx, dy = _reef_foot_radii(spec, settings)
    bottom_z = 0 if settings.base_mode == "INDIVIDUAL_FEET" else max(0, settings.base_thickness-wall)
    foot = _append_ring(vertices, spec, radii, dx, dy, bottom_z)
    bevel = _append_ring(vertices, spec, radii, dx, dy, _support_top(settings)*0.55)
    faces.append(tuple(reversed(foot)))
    _bridge_outer(faces, foot, bevel)
    _bridge_outer(faces, bevel, outer_ids[0])


def _reef_foot_radii(spec, settings):
    # Convex-cell containment includes the entire pad, not only the mouth.
    dx, dy = spec["reef_root_xy"]
    available = min(d - nx*dx - ny*dy for nx, ny, d in spec["planes"])
    radius = min(spec["reef_root"] + settings.foot_flange, available * 0.92)
    return [radius] * settings.radial_segments, dx, dy


def _mesh_volume_mm3(mesh):
    mesh.calc_loop_triangles()
    return abs(sum(mesh.vertices[t.vertices[0]].co.dot(
        mesh.vertices[t.vertices[1]].co.cross(mesh.vertices[t.vertices[2]].co))
        for t in mesh.loop_triangles) / 6)


def _validate_print_mesh(mesh, piece_id):
    """Reject folded shells as well as open topology before publishing a job.

    This is a geometric preflight, not a slicer/support or physical-strength test.
    """
    import bmesh
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.normal_update()
        if (not all(e.is_manifold and e.is_contiguous for e in bm.edges)
                or any(f.calc_area() < 1e-9 for f in bm.faces)
                or bm.calc_volume(signed=True) <= 0):
            raise ValueError(f"{piece_id}: invalid shell topology; reduce shape extremes or wall thickness")
        tree = BVHTree.FromBMesh(bm)
        bm.faces.ensure_lookup_table()
        for a, b in tree.overlap(tree):
            if a < b and not set(bm.faces[a].verts).intersection(bm.faces[b].verts):
                raise ValueError(f"{piece_id}: offset shell folds into itself; use a gentler preset, "
                                 "larger minimum scale or smaller wall thickness")
    finally:
        bm.free()




def _make_specs(settings):
    return _reef_specs(settings)


def _append_cup(vertices, faces, spec, settings):
    return _reef_append_cup(vertices, faces, spec, settings)


def _foot_radii(spec, settings):
    if "reef_mouth" in spec:
        return _reef_foot_radii(spec, settings)
    raise ValueError("Unsupported non-reef funnel specification")


def _build_mesh_data(settings, progress_callback=None):
    specs = _make_specs(settings)
    vertices = []
    faces = []
    if settings.base_mode == "COMMON_PANEL":
        _append_base(vertices, faces, settings)
    base_face_count = len(faces)

    for index, spec in enumerate(specs):
        if spec["form_type"] == "BLOCK":
            _append_block(vertices, faces, spec, settings)
        else:
            _append_cup(vertices, faces, spec, settings)
        if progress_callback:
            progress_callback(index + 1, len(specs))

    return vertices, faces, base_face_count, specs


def _build_piece_mesh_data(spec, settings):
    """Build one glue-down form around its own object origin."""
    vertices = []
    faces = []
    foot_face_count = 0
    if spec["form_type"] == "BLOCK":
        _append_block(vertices, faces, spec, settings)
    else:
        _append_cup(vertices, faces, spec, settings)

    origin_x = spec["x"]
    origin_y = spec["y"]
    local_vertices = [
        (x - origin_x, y - origin_y, z) for x, y, z in vertices
    ]
    return local_vertices, faces, foot_face_count


def _vertex_bounds(vertices):
    low = tuple(min(v[i] for v in vertices) for i in range(3))
    high = tuple(max(v[i] for v in vertices) for i in range(3))
    return low, high


def _mesh_fingerprint(mesh):
    digest = hashlib.sha256()
    for vertex in mesh.vertices:
        digest.update(struct.pack('<3f', *vertex.co))
    for polygon in mesh.polygons:
        digest.update(struct.pack('<I', len(polygon.vertices)))
        digest.update(struct.pack(f'<{len(polygon.vertices)}I', *polygon.vertices))
    return digest.hexdigest()


ASSEMBLY_COLUMNS = (
    "piece_id",
    "panel",
    "panel_column",
    "panel_row",
    "local_x_mm",
    "local_y_mm",
    "artwork_x_mm",
    "artwork_y_mm",
    "rotation_degrees",
    "height_mm",
    "mouth_diameter_mm",
    "form_type",
    "colour_group",
)


def _csv_cell(value):
    text = str(value)
    if any(character in text for character in (",", '"', "\n")):
        return '"' + text.replace('"', '""') + '"'
    return text


def _assembly_csv(rows):
    lines = [",".join(ASSEMBLY_COLUMNS)]
    for row in rows:
        lines.append(",".join(_csv_cell(row[column]) for column in ASSEMBLY_COLUMNS))
    return "\n".join(lines) + "\n"


def _write_assembly_text(rows):
    text_block = bpy.data.texts.get(ASSEMBLY_TEXT_NAME)
    if text_block is None:
        text_block = bpy.data.texts.new(ASSEMBLY_TEXT_NAME)
    else:
        text_block.clear()
    text_block.write(_assembly_csv(rows))
    return text_block


# -----------------------------------------------------------------------------
# Blender integration


def _tile_suffix(tile_x, tile_y):
    def component(value):
        return f"m{abs(value)}" if value < 0 else f"p{value}"

    return f"X{component(tile_x)}_Y{component(tile_y)}"


def _remove_generated_collection(collection_name):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        return

    def remove_branch(branch):
        for child in list(branch.children):
            remove_branch(child)
        for obj in list(branch.objects):
            mesh = obj.data if obj.type == "MESH" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(branch)

    remove_branch(collection)


def _get_preview_material():
    material = bpy.data.materials.get("CRF Warm Porcelain")
    if material is None:
        material = bpy.data.materials.new("CRF Warm Porcelain")
        material.diffuse_color = (0.63, 0.55, 0.40, 1.0)
        material.roughness = 0.58
        material.metallic = 0.0
    return material


def _apply_manifold_remesh(context, obj, settings):
    modifier = obj.modifiers.new("CRF Manifold Union", "REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = settings.voxel_size
    modifier.use_remove_disconnected = False
    modifier.use_smooth_shade = True
    modifier.adaptivity = settings.voxel_adaptivity

    for selected in list(context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)


class CRFSettings(PropertyGroup):
    artwork_collection: PointerProperty(type=bpy.types.Collection)
    studio_render: BoolProperty(name="Soft Studio Lighting", default=True,
        description="Cycles with a neutral backdrop and soft shadows; turn off for a fast Workbench preview")
    render_view: EnumProperty(
        name="Camera View", items=(("TOP", "Straight On", "View every opening from above"),
                                   ("ANGLED", "Angled Relief", "Show the height wave and cavities")),
        default="ANGLED",
    )
    render_pixels: IntProperty(name="Image Long Edge (px)", default=1600, min=256, max=6000)
    batch_spacing: FloatProperty(
        name="Print Spacing (mm)", default=3.0, min=0.5, max=20.0,
        description="Clearance between piece bounding boxes on exported print plates",
    )
    style_preset: EnumProperty(
        name="Style Preset",
        description="Reference-oriented starting point; apply it before generating",
        items=(
            ("PARAGAMI_CORAL", "Flowing Reef (Recommended)", "Broad funnels separated by winding small-cup rivers"),
            ("DENSE_MOSAIC", "Low-Material Reef", "Lower relief and gentler lean; same nominal 0.8 mm shell"),
            ("DEEP_HERO", "Sculptural Reef", "Deeper focal cups, stronger relief, 1 mm shell"),
            ("STRONG_CURRENT", "Tidal Ribbons", "Tighter curls and more strongly elongated mouths"),
            ("ROUNDED_BLOCKS", "Rounded Blocks", "Solid rounded-square columns with flowing heights"),
            ("MIXED_GEOMETRY", "Reef + Blocks", "Mix thin funnels with solid geometric forms"),
        ),
        default="PARAGAMI_CORAL",
    )
    output_mode: EnumProperty(
        name="Piece Output",
        description="Create one mesh per assembly region or individually numbered glue-down pieces",
        items=(
            (
                "PANEL_MESHES",
                "Panel Meshes",
                "Generate one mesh object per A1 Mini panel",
            ),
            (
                "NUMBERED_PIECES",
                "Numbered Glue-Down Pieces",
                "Generate the full composition once as separate named pieces and create an assembly map",
            ),
        ),
        default="NUMBERED_PIECES",
    )
    base_mode: EnumProperty(
        name="Mounting Mode",
        description="Choose a shared backing panel or separate flat glue feet",
        items=(
            (
                "COMMON_PANEL",
                "Common Panel",
                "Generate one closed rectangular backing plate",
            ),
            (
                "INDIVIDUAL_FEET",
                "Individual Glue Feet",
                "Omit the shared panel and give every form a small closed flat base",
            ),
        ),
        default="INDIVIDUAL_FEET",
    )
    form_style: EnumProperty(
        name="Form Type",
        description="Geometry family used for the field",
        items=(
            (
                "ORGANIC_FUNNELS",
                "Organic Funnels",
                "Asymmetric hollow tapered funnels",
            ),
            (
                "MIXED",
                "Funnels + Blocks",
                "Mix hollow organic funnels with solid rounded blocks",
            ),
            (
                "ROUNDED_BLOCKS",
                "Rounded Blocks",
                "Solid rounded-square columns at varying heights",
            ),
        ),
        default="ORGANIC_FUNNELS",
    )
    tile_size_x: FloatProperty(
        name="Tile X (mm)",
        description="Finished tile width in millimeters",
        default=175.0,
        min=20.0,
        max=1000.0,
        precision=1,
    )
    tile_size_y: FloatProperty(
        name="Tile Y (mm)",
        description="Finished tile depth in millimeters",
        default=175.0,
        min=20.0,
        max=1000.0,
        precision=1,
    )
    base_thickness: FloatProperty(
        name="Base Thickness (mm)",
        description="Thickness of the common closed backing plate",
        default=2.0,
        min=0.6,
        max=20.0,
        precision=2,
    )
    individual_base_thickness: FloatProperty(
        name="Glue Foot Thickness (mm)",
        description="Thickness of each form's separate flat mounting foot",
        default=1.2,
        min=0.6,
        max=6.0,
        precision=2,
    )
    foot_flange: FloatProperty(
        name="Glue Foot Flange (mm)",
        description="Extra footprint around the narrow attachment root",
        default=1.4,
        min=0.0,
        max=5.0,
        precision=2,
    )
    density: FloatProperty(
        name="Density",
        description="Approximate cups per 100 x 100 mm area",
        default=14.0,
        min=1.0,
        max=90.0,
        precision=1,
    )
    filler_fraction: FloatProperty(
        name="Gap Fillers",
        description="Extra small cups placed into the largest voids as a fraction of the main count",
        default=0.65,
        min=0.0,
        max=1.25,
        subtype="FACTOR",
    )
    packing_tightness: FloatProperty(
        name="Packing Tightness",
        description="How closely neighboring mouths fill their shared weighted cells",
        default=0.99,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    hero_fraction: FloatProperty(
        name="Hero Cup Fraction",
        description="Fraction of primary cups promoted into the largest scale tier",
        default=0.15,
        min=0.0,
        max=0.45,
        subtype="FACTOR",
    )
    block_fraction: FloatProperty(
        name="Block Fraction",
        description="Fraction of forms changed to rounded blocks in mixed mode",
        default=0.30,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    block_bevel: FloatProperty(
        name="Block Bevel (mm)",
        description="Rounded edge size for geometric block forms",
        default=1.2,
        min=0.0,
        max=8.0,
        precision=2,
    )
    min_cup_scale: FloatProperty(
        name="Minimum Scale",
        description="Smallest cup relative to automatically calculated spacing",
        default=0.42,
        min=0.25,
        max=2.0,
        precision=2,
    )
    max_cup_scale: FloatProperty(
        name="Maximum Scale",
        description="Largest cup relative to automatically calculated spacing",
        default=1.90,
        min=0.25,
        max=2.5,
        precision=2,
    )
    cluster_strength: FloatProperty(
        name="Cluster Strength",
        description="Bias placement and cup size toward a global continuous cluster field",
        default=0.94,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    cluster_scale: FloatProperty(
        name="Cluster Scale (mm)",
        description="Approximate width of broad cup clusters",
        default=155,
        min=10.0,
        max=1000.0,
        precision=1,
    )
    random_seed: IntProperty(
        name="Random Seed",
        description="Master seed; keep identical across a multi-tile set",
        default=240531,
        min=0,
        max=2147483647,
    )
    min_height: FloatProperty(
        name="Minimum Height (mm)",
        description="Lowest cup mouth above the top of the base",
        default=7,
        min=3.0,
        max=300.0,
        precision=1,
    )
    max_height: FloatProperty(
        name="Maximum Height (mm)",
        description="Highest cup mouth above the top of the base",
        default=46,
        min=4.0,
        max=400.0,
        precision=1,
    )
    height_radius_limit: FloatProperty(
        name="Height / Radius Limit",
        description="Maximum slenderness; keeps tiny filler cups shallow while large cups form the crests",
        default=2.15,
        min=1.2,
        max=8.0,
        precision=2,
    )
    wall_thickness: FloatProperty(
        name="Wall Thickness (mm)",
        description="Nominal surface-normal offset; rounded rim and glue foot are locally thicker",
        default=0.8,
        min=0.4,
        max=8.0,
        precision=2,
    )
    mouth_variation: FloatProperty(
        name="Mouth Shape Variation",
        description="Strength of amoeba, teardrop, and harmonic mouth distortion",
        default=0.65,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    tulip_strength: FloatProperty(
        name="Tulip Form",
        description="Blend toward narrow roots, round bellies, and a softly flared calla-like mouth",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    petal_depth: FloatProperty(
        name="Rim Scallop",
        description="Optional rim lobing; keep low for the smooth reference style",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    min_petals: IntProperty(
        name="Minimum Rim Lobes",
        description="Smallest harmonic lobe count when Rim Scallop is above zero",
        default=3,
        min=3,
        max=10,
    )
    max_petals: IntProperty(
        name="Maximum Rim Lobes",
        description="Largest harmonic lobe count when Rim Scallop is above zero",
        default=4,
        min=3,
        max=12,
    )
    max_lean: FloatProperty(
        name="Maximum Lean / Tilt (degrees)",
        description="Maximum centerline lean in degrees",
        default=46,
        min=0.0,
        max=60.0,
        precision=1,
    )
    bend_variation: FloatProperty(
        name="Bend Variation",
        description="Centerline bend as a fraction of cup radius",
        default=0.58,
        min=0.0,
        max=1.2,
        precision=2,
    )
    base_rotation: FloatProperty(
        name="Base Rotation (degrees)",
        description="Common rotation offset for all organic mouth shapes",
        default=0.0,
        min=-360.0,
        max=360.0,
        precision=1,
    )
    rotation_variation: FloatProperty(
        name="Rotation Variation (degrees)",
        description="Random rotation range around the base rotation",
        default=82,
        min=0.0,
        max=180.0,
        precision=1,
    )
    mouth_elongation: FloatProperty(
        name="Mouth Elongation",
        description="Stretch mouths from rounded triangles toward long teardrop and oval forms",
        default=0.36,
        min=0.0,
        max=0.48,
        precision=2,
    )
    throat_size: FloatProperty(
        name="Throat Size",
        description="Size of the small dark cavity floor relative to the cup radius",
        default=0.09,
        min=0.04,
        max=0.35,
        precision=2,
    )
    throat_offset: FloatProperty(
        name="Throat Offset",
        description="How far the narrow funnel throat shifts away from the mouth center",
        default=0.31,
        min=0.0,
        max=0.65,
        precision=2,
    )
    height_size_correlation: FloatProperty(
        name="Crest Size Correlation",
        description="Make crest cups larger and undercurrent cups smaller",
        default=0.78,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    flow_alignment: FloatProperty(
        name="Flow Alignment",
        description="Align mouth rotation, lean, and bend to one continuous global vector field",
        default=0.97,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    flow_swirl: FloatProperty(
        name="Flow Swirl",
        description="Blend the broad wave direction toward curling local streamlines",
        default=0.93,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    orientation_flow_scale: FloatProperty(
        name="Flow Scale (mm)",
        description="Feature size of coherent mouth-orientation swirls",
        default=135,
        min=12.0,
        max=3000.0,
        precision=1,
    )
    wave_amplitude: FloatProperty(
        name="Wave Amplitude (mm)",
        description="Height added and removed by the broad directional wave",
        default=13,
        min=0.0,
        max=100.0,
        precision=1,
    )
    wave_wavelength: FloatProperty(
        name="Wave Wavelength (mm)",
        description="Distance between broad height-wave peaks",
        default=620,
        min=8.0,
        max=20000.0,
        precision=1,
    )
    wave_direction: FloatProperty(
        name="Wave Direction (degrees)",
        description="Travel direction of the global height wave",
        default=28.0,
        min=-360.0,
        max=360.0,
        precision=1,
    )
    noise_amplitude: FloatProperty(
        name="Noise Amplitude (mm)",
        description="Height contribution of the continuous global noise field",
        default=3,
        min=0.0,
        max=100.0,
        precision=1,
    )
    noise_scale: FloatProperty(
        name="Noise Scale (mm)",
        description="Feature scale of the global height noise",
        default=185,
        min=5.0,
        max=2000.0,
        precision=1,
    )
    undercurrent_depth: FloatProperty(
        name="Undercurrent Depth (mm)",
        description="Maximum downward pressure from the warped current channels",
        default=13,
        min=0.0,
        max=100.0,
        precision=1,
    )
    undercurrent_scale: FloatProperty(
        name="Undercurrent Scale (mm)",
        description="Width and spacing of the downward-flowing channels",
        default=112,
        min=8.0,
        max=1000.0,
        precision=1,
    )
    undercurrent_direction: FloatProperty(
        name="Undercurrent Direction (degrees)",
        description="Direction of the warped downward current bands",
        default=-18.0,
        min=-360.0,
        max=360.0,
        precision=1,
    )
    finished_width: FloatProperty(
        name="Finished Width (mm)",
        description="Exact assembled artwork width used by automatic panel planning",
        default=600.0,
        min=40.0,
        max=10000.0,
        precision=1,
    )
    finished_height: FloatProperty(
        name="Finished Height (mm)",
        description="Exact assembled artwork height used by automatic panel planning",
        default=1200.0,
        min=40.0,
        max=10000.0,
        precision=1,
    )
    printer_bed_x: FloatProperty(
        name="Printer Bed X (mm)",
        description="A1 Mini nominal printable width is 180 mm",
        default=180.0,
        min=40.0,
        max=1000.0,
        precision=1,
    )
    printer_bed_y: FloatProperty(
        name="Printer Bed Y (mm)",
        description="A1 Mini nominal printable depth is 180 mm",
        default=180.0,
        min=40.0,
        max=1000.0,
        precision=1,
    )
    printer_bed_z: FloatProperty(
        name="Printer Bed Z (mm)",
        description="A1 Mini nominal printable height is 180 mm",
        default=180.0,
        min=40.0,
        max=1000.0,
        precision=1,
    )
    printer_margin: FloatProperty(
        name="Bed Margin / Side (mm)",
        description="Safety margin removed from every side of the nominal print bed",
        default=2.5,
        min=0.0,
        max=30.0,
        precision=1,
    )
    auto_fit_wave_to_artwork: BoolProperty(
        name="Fit Broad Wave to Finished Work",
        description="Scale the main wavelength from the full assembled dimensions",
        default=True,
    )
    wave_cycles_across_artwork: FloatProperty(
        name="Broad Wave Cycles",
        description="Approximate number of main wave cycles across the finished work",
        default=1.35,
        min=0.25,
        max=8.0,
        precision=2,
    )
    tile_x: IntProperty(
        name="Tile X",
        description="Global horizontal tile coordinate used by all continuous fields",
        default=0,
        min=-10000,
        max=10000,
    )
    tile_y: IntProperty(
        name="Tile Y",
        description="Global vertical tile coordinate used by all continuous fields",
        default=0,
        min=-10000,
        max=10000,
    )
    panel_count_x: IntProperty(
        name="Panels X",
        description="Number of separate tiles to generate horizontally in one set",
        default=2,
        min=1,
        max=30,
    )
    panel_count_y: IntProperty(
        name="Panels Y",
        description="Number of separate tiles to generate vertically in one set",
        default=2,
        min=1,
        max=30,
    )
    layout_tiles_in_grid: BoolProperty(
        name="Lay Out at Tile Coordinates",
        description="Place generated objects side by side in the scene; disable for origin-centered export",
        default=True,
    )
    edge_clearance: FloatProperty(
        name="Edge Clearance (mm)",
        description="Distance between cup walls and the tile edge",
        default=1,
        min=0.0,
        max=20.0,
        precision=2,
    )
    radial_segments: IntProperty(
        name="Mouth Segments",
        description="Vertices around each cup; 32-40 is a useful print range",
        default=64,
        min=12,
        max=96,
    )
    vertical_segments: IntProperty(
        name="Height Segments",
        description="Rings along each cup wall",
        default=24,
        min=3,
        max=32,
    )
    merge_manifold: BoolProperty(
        name="Voxel Merge / Manifold Output",
        description="Union cup roots and base into one print-oriented voxel-remeshed surface",
        default=False,
    )
    voxel_size: FloatProperty(
        name="Voxel Size (mm)",
        description="Manifold remesh resolution; use roughly one-half of wall thickness",
        default=0.4,
        min=0.20,
        max=5.0,
        precision=2,
    )
    voxel_adaptivity: FloatProperty(
        name="Voxel Adaptivity",
        description="Reduce polygon count after voxel union; zero preserves the most detail",
        default=0.0,
        min=0.0,
        max=0.5,
        subtype="FACTOR",
    )
    configure_scene_units: BoolProperty(
        name="Configure Scene for Millimeters",
        description="Set Metric units with a 0.001 scale so one authored unit is one millimeter",
        default=True,
    )
    assembly_csv_path: StringProperty(
        name="Assembly CSV",
        description="Destination for the numbered placement map",
        default="//organic_cup_assembly_map.csv",
        subtype="FILE_PATH",
    )


PRESET_LABELS = {
    "PARAGAMI_CORAL": "Modular Coral",
    "DENSE_MOSAIC": "Dense Cellular",
    "BALANCED_FUNNELS": "Balanced Funnels",
    "DEEP_HERO": "Deep Hero Funnels",
    "STRONG_CURRENT": "Strong Undercurrent",
    "GLUE_DOWN_FUNNELS": "Glue-Down Funnels",
    "MIXED_GEOMETRY": "Funnels + Blocks",
    "ROUNDED_BLOCKS": "Rounded Block Field",
}


def _apply_style_preset(settings, preset_id):
    values = dict(tile_size_x=175., tile_size_y=175., printer_bed_x=180.,
        printer_bed_y=180., printer_bed_z=180., printer_margin=2.5,
        output_mode="NUMBERED_PIECES", base_mode="INDIVIDUAL_FEET",
        form_style="ORGANIC_FUNNELS", individual_base_thickness=1.2, foot_flange=1.,
        packing_tightness=.99, wall_thickness=.8, density=14., filler_fraction=.65,
        min_cup_scale=.52, max_cup_scale=1.9, cluster_strength=.94,
        min_height=7., max_height=46., height_radius_limit=2.5,
        mouth_variation=.65, mouth_elongation=.36, throat_size=.09, throat_offset=.31,
        max_lean=46., bend_variation=.58, rotation_variation=65.,
        flow_alignment=.97, flow_swirl=.93, orientation_flow_scale=135.,
        wave_amplitude=13., wave_wavelength=620., wave_direction=28.,
        noise_amplitude=2., undercurrent_depth=10., edge_clearance=1.,
        merge_manifold=False, radial_segments=64, vertical_segments=24)
    if preset_id == "DENSE_MOSAIC":
        values.update(density=14., min_height=6., max_height=28., wall_thickness=.8,
                      height_radius_limit=1.35, max_lean=28., undercurrent_depth=7.)
    elif preset_id == "DEEP_HERO":
        values.update(density=11., min_height=10., max_height=58., wall_thickness=1.,
                      height_radius_limit=3., max_lean=52., mouth_elongation=.40)
    elif preset_id == "STRONG_CURRENT":
        values.update(flow_swirl=1., cluster_strength=1., mouth_elongation=.44,
                      max_lean=54., orientation_flow_scale=110.)
    elif preset_id == "ROUNDED_BLOCKS":
        values.update(form_style="ROUNDED_BLOCKS", density=14., block_bevel=1.2)
    elif preset_id == "MIXED_GEOMETRY":
        values.update(form_style="MIXED", block_fraction=.25)
    for name, value in values.items():
        setattr(settings, name, value)


class CRF_OT_apply_style_preset(Operator):
    bl_idname = "crf.apply_style_preset"
    bl_label = "Apply Style Preset"
    bl_description = (
        "Apply the selected look and a 175 mm A1 Mini-safe manual tile while preserving artwork size and seed"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.crf_settings
        _apply_style_preset(settings, settings.style_preset)
        self.report(
            {"INFO"},
            f"Applied {PRESET_LABELS.get(settings.style_preset, 'style')} preset at 175 mm",
        )
        return {"FINISHED"}


class CRF_OT_apply_reference_preset(Operator):
    """Compatibility alias retained for existing scenes and internal tests."""

    bl_idname = "crf.apply_reference_preset"
    bl_label = "Apply Reference Look"
    bl_description = "Apply the recommended Dense Cellular preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.crf_settings
        settings.style_preset = "DENSE_MOSAIC"
        _apply_style_preset(settings, "DENSE_MOSAIC")
        self.report({"INFO"}, "Applied Dense Cellular preset at 175 mm")
        return {"FINISHED"}


class CRF_OT_randomize_seed(Operator):
    bl_idname = "crf.randomize_seed"
    bl_label = "Randomize Seed"
    bl_description = "Choose a new master seed; click Generate Field to rebuild"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.crf_settings.random_seed = secrets.randbelow(2147483647)
        self.report({"INFO"}, "Seed randomized; click Generate Field to rebuild")
        return {"FINISHED"}


class CRF_OT_generate_field(Operator):
    bl_idname = "crf.generate_field"
    bl_label = "Generate Field"
    bl_description = "Generate or replace the field for the current tile coordinate"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.mode == "OBJECT"

    def execute(self, context):
        settings = context.scene.crf_settings
        if settings.min_cup_scale > settings.max_cup_scale:
            self.report({"ERROR"}, "Minimum cup scale must not exceed maximum scale")
            return {"CANCELLED"}
        if settings.min_height > settings.max_height:
            self.report({"ERROR"}, "Minimum height must not exceed maximum height")
            return {"CANCELLED"}
        if settings.min_petals > settings.max_petals:
            self.report({"ERROR"}, "Minimum petals must not exceed maximum petals")
            return {"CANCELLED"}
        if settings.wall_thickness >= settings.min_height * 0.45:
            self.report({"ERROR"}, "Wall thickness is too large for the minimum height")
            return {"CANCELLED"}

        estimated_count = _estimated_cup_count(
            settings.tile_size_x * settings.tile_size_y,
            settings,
        )
        if estimated_count > 450:
            self.report({"ERROR"}, "Settings exceed the 450-cup safety limit")
            return {"CANCELLED"}
        if _estimated_source_vertices(estimated_count, settings) > 8_000_000:
            self.report(
                {"ERROR"},
                "Source mesh would exceed 8 million vertices; reduce quality or density",
            )
            return {"CANCELLED"}

        if settings.merge_manifold:
            if settings.voxel_size >= settings.wall_thickness:
                self.report(
                    {"WARNING"},
                    "Voxel Size is at least the wall thickness and may soften or close thin rims",
                )
            if (
                settings.tile_size_x + 2.0 * settings.voxel_size
                > settings.printer_bed_x
                or settings.tile_size_y + 2.0 * settings.voxel_size
                > settings.printer_bed_y
            ):
                self.report(
                    {"WARNING"},
                    "Voxel remesh may expand beyond the configured printer XY bed; use the finished-work planner",
                )
            z_extent = _support_top(settings) + settings.max_height + settings.wall_thickness
            estimated_voxels = (
                (settings.tile_size_x / settings.voxel_size)
                * (settings.tile_size_y / settings.voxel_size)
                * (z_extent / settings.voxel_size)
            )
            if estimated_voxels > 60_000_000:
                self.report(
                    {"ERROR"},
                    "Voxel grid is too large; increase Voxel Size or disable Manifold Output",
                )
                return {"CANCELLED"}

        start_time = time.perf_counter()
        window_manager = context.window_manager
        window_manager.progress_begin(0, max(estimated_count, 1))

        try:
            if settings.configure_scene_units:
                context.scene.unit_settings.system = "METRIC"
                context.scene.unit_settings.length_unit = "MILLIMETERS"
                context.scene.unit_settings.scale_length = 0.001

            def update_progress(done, total):
                window_manager.progress_update(min(done, total))

            vertices, faces, base_face_count, specs = _build_mesh_data(
                settings, update_progress
            )

            suffix = _tile_suffix(settings.tile_x, settings.tile_y)
            collection_name = f"{ADDON_PREFIX}Tile_{suffix}"
            _remove_generated_collection(collection_name)
            collection = bpy.data.collections.new(collection_name)
            context.scene.collection.children.link(collection)

            mesh = bpy.data.meshes.new(f"{ADDON_PREFIX}Mesh_{suffix}")
            mesh.from_pydata(vertices, [], faces)
            mesh.validate(verbose=False)
            mesh.update(calc_edges=True)

            obj = bpy.data.objects.new(f"{ADDON_PREFIX}Field_{suffix}", mesh)
            collection.objects.link(obj)
            obj.data.materials.append(_get_preview_material())
            obj.color = (0.42, 0.68, 0.57, 1.0)

            if settings.layout_tiles_in_grid:
                obj.location.x = settings.tile_x * settings.tile_size_x
                obj.location.y = settings.tile_y * settings.tile_size_y

            # Keep the square plate crisp while smoothing all organic components.
            for polygon in mesh.polygons:
                polygon.use_smooth = polygon.index >= base_face_count

            obj["crf_generator_version"] = VERSION
            obj["crf_seed"] = settings.random_seed
            obj["crf_tile_x"] = settings.tile_x
            obj["crf_tile_y"] = settings.tile_y
            obj["crf_tile_size_mm"] = (
                settings.tile_size_x,
                settings.tile_size_y,
            )
            obj["crf_cup_count"] = len(specs)
            obj["crf_form_count"] = len(specs)
            obj["crf_wall_mm"] = settings.wall_thickness
            obj["crf_mounting_mode"] = settings.base_mode
            obj["crf_form_style"] = settings.form_style
            obj["crf_output"] = "PREVIEW_CLOSED_SHELLS"

            for selected in list(context.selected_objects):
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj

            if settings.merge_manifold:
                _apply_manifold_remesh(context, obj, settings)
                obj.name = f"{ADDON_PREFIX}Manifold_{suffix}"
                obj.data.name = f"{ADDON_PREFIX}ManifoldMesh_{suffix}"
                obj["crf_output"] = "VOXEL_MANIFOLD"
                obj["crf_voxel_size_mm"] = settings.voxel_size

            context.scene["crf_panel_objects"] = json.dumps([obj.name])

        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Organic field generation failed: {exc}")
            return {"CANCELLED"}
        finally:
            window_manager.progress_end()

        elapsed = time.perf_counter() - start_time
        output_label = "manifold" if settings.merge_manifold else "preview"
        self.report(
            {"INFO"},
            f"Generated {len(specs)} forms ({output_label}) in {elapsed:.1f} seconds",
        )
        return {"FINISHED"}


class CRF_OT_generate_panel_set(Operator):
    bl_idname = "crf.generate_panel_set"
    bl_label = "Generate Panel Set"
    bl_description = (
        "Generate separate aligned panels with continuous global height and orientation fields"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.mode == "OBJECT"

    def execute(self, context):
        settings = context.scene.crf_settings
        panel_total = settings.panel_count_x * settings.panel_count_y
        cups_per_panel = _estimated_cup_count(
            settings.tile_size_x * settings.tile_size_y,
            settings,
        )
        if panel_total * cups_per_panel > 10000:
            self.report(
                {"ERROR"},
                "Panel set exceeds the 10,000-cup safety limit; lower density or panel count",
            )
            return {"CANCELLED"}
        if _estimated_source_vertices(
            panel_total * cups_per_panel,
            settings,
        ) > 8_000_000:
            self.report(
                {"ERROR"},
                "Panel set would exceed 8 million source vertices; reduce quality or density",
            )
            return {"CANCELLED"}

        start_x = settings.tile_x
        start_y = settings.tile_y
        original_layout = settings.layout_tiles_in_grid
        generated_objects = []
        started = time.perf_counter()
        failure = None

        try:
            # A set is always laid out in its assembled position so the global
            # wave and undercurrent can be inspected across panel boundaries.
            settings.layout_tiles_in_grid = True
            for panel_y in range(settings.panel_count_y):
                for panel_x in range(settings.panel_count_x):
                    settings.tile_x = start_x + panel_x
                    settings.tile_y = start_y + panel_y
                    result = bpy.ops.crf.generate_field()
                    if "FINISHED" not in result:
                        raise RuntimeError(
                            f"tile ({settings.tile_x}, {settings.tile_y}) did not finish"
                        )
                    generated_objects.append(context.view_layer.objects.active)
        except Exception as exc:
            traceback.print_exc()
            failure = exc
        finally:
            settings.tile_x = start_x
            settings.tile_y = start_y
            settings.layout_tiles_in_grid = original_layout

        for selected in list(context.selected_objects):
            selected.select_set(False)
        for obj in generated_objects:
            if obj is not None and context.view_layer.objects.get(obj.name) is not None:
                obj.select_set(True)
        if generated_objects:
            context.view_layer.objects.active = generated_objects[-1]

        if failure is not None:
            self.report(
                {"ERROR"},
                f"Panel-set generation stopped after {len(generated_objects)} panels: {failure}",
            )
            return {"CANCELLED"}

        elapsed = time.perf_counter() - started
        context.scene["crf_panel_objects"] = json.dumps([obj.name for obj in generated_objects])
        self.report(
            {"INFO"},
            f"Generated {panel_total} panels with continuous global height and flow fields in {elapsed:.1f} seconds",
        )
        return {"FINISHED"}


class CRF_OT_generate_modular_artwork(Operator):
    bl_idname = "crf.generate_modular_artwork"
    bl_label = "Generate Numbered Artwork"
    bl_description = (
        "Generate one continuous master composition, divide it into assembly regions, "
        "and create every glue-down form as a numbered object"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.mode == "OBJECT"

    def execute(self, context):
        settings = context.scene.crf_settings
        staging = None
        wm = context.window_manager
        started = time.perf_counter()
        try:
            _validate_settings(settings)
            if settings.base_mode != "INDIVIDUAL_FEET":
                raise ValueError("Numbered artwork requires Individual Glue Feet")
            columns, rows, panel_x, panel_y, usable_x, usable_y = _panel_plan(settings)
            config = _master_settings(settings)
            estimated = _estimated_cup_count(config.finished_width * config.finished_height, config)
            primary = _base_cup_count(config.finished_width * config.finished_height, config)
            if primary > 1500 or estimated > 2200:
                raise ValueError("Artwork exceeds 1,500 primary / 2,200 total pieces; lower Density")
            if _estimated_source_vertices(estimated, config) > 8_000_000:
                raise ValueError("Artwork exceeds 8 million source vertices; reduce quality")
            if config.merge_manifold and config.voxel_size > config.wall_thickness * 0.6:
                raise ValueError("Use Voxel Size at most 60% of Wall Thickness to preserve openings")

            wm.progress_begin(0, max(estimated, 1))
            specs = _make_specs(config)
            # Stage the complete replacement. A failure must leave the last good
            # artwork, its placement map, and the user's settings untouched.
            staging = bpy.data.collections.new("CRF_Building")
            context.scene.collection.children.link(staging)
            staging["crf_generated"] = True
            panels = {}
            for row in range(rows):
                for column in range(columns):
                    number = row * columns + column + 1
                    label = f"P{number:02d}_R{row + 1:02d}_C{column + 1:02d}"
                    collection = bpy.data.collections.new(f"CRF_{label}")
                    staging.children.link(collection)
                    guide = bpy.data.objects.new(f"CRF_GUIDE_{label}", None)
                    guide.empty_display_type = "CUBE"
                    guide.empty_display_size = 1.0
                    guide.location = (
                        -config.finished_width / 2 + (column + 0.5) * panel_x,
                        -config.finished_height / 2 + (row + 0.5) * panel_y, 0,
                    )
                    guide.scale = (panel_x / 2, panel_y / 2, 0.05)
                    guide.hide_render = True
                    guide.show_name = True
                    collection.objects.link(guide)
                    panels[column, row] = (number, label, collection)

            def region(spec):
                x = spec["x"] + config.finished_width / 2
                y = spec["y"] + config.finished_height / 2
                return (min(columns - 1, max(0, int(x / panel_x))),
                        min(rows - 1, max(0, int(y / panel_y))))

            specs.sort(key=lambda s: (region(s)[1], region(s)[0], s["y"], s["x"]))
            counts, records, created = {}, [], []
            for index, spec in enumerate(specs):
                column, row = region(spec)
                number, label, collection = panels[column, row]
                counts[column, row] = counts.get((column, row), 0) + 1
                piece_id = f"P{number:02d}-{counts[column, row]:03d}"
                vertices, faces, _ = _build_piece_mesh_data(spec, config)
                mesh = bpy.data.meshes.new(f"CRF_Mesh_{piece_id}")
                mesh.from_pydata(vertices, [], faces)
                mesh.update(calc_edges=True)
                obj = bpy.data.objects.new(f"CRF_{piece_id}_{spec['form_type']}", mesh)
                collection.objects.link(obj)
                obj.location = (spec["x"], spec["y"], 0)
                obj.data.materials.append(_get_preview_material())
                if config.merge_manifold:
                    low, high = _vertex_bounds([v.co for v in mesh.vertices])
                    voxel_count = math.prod(
                        (high[i] - low[i] + 2 * config.voxel_size) / config.voxel_size
                        for i in range(3)
                    )
                    if voxel_count > 60_000_000:
                        raise ValueError(f"{piece_id}: voxel grid too large; reduce height or quality")
                    _apply_manifold_remesh(context, obj, config)
                for polygon in obj.data.polygons:
                    polygon.use_smooth = len(polygon.vertices) == 4

                _validate_print_mesh(obj.data, piece_id)

                low, high = _vertex_bounds([v.co for v in obj.data.vertices])
                dimensions = [high[i] - low[i] for i in range(3)]
                if (dimensions[0] > usable_x or dimensions[1] > usable_y
                        or dimensions[2] > config.printer_bed_z):
                    raise ValueError(
                        f"{piece_id} is {dimensions[0]:.1f} x {dimensions[1]:.1f} x "
                        f"{dimensions[2]:.1f} mm; increase Density or reduce height to fit the bed"
                    )
                x = spec["x"] + config.finished_width / 2
                y = spec["y"] + config.finished_height / 2
                local_x, local_y = x - column * panel_x, y - row * panel_y
                score = _clamp(
                    0.55 * spec["cluster"] + 0.45 * (spec["height"] - config.min_height)
                    / max(config.max_height - config.min_height, 1e-6), 0, 0.999999,
                )
                colour = 1 + int(score * 5)
                # Store actual generated contours and dimensions, not requested
                # radii. Cell clipping, tilt and remeshing can change those sizes.
                radii, offset_x, offset_y = (
                    (_block_footprint(spec, config, config.radial_segments), 0, 0)
                    if spec["form_type"] == "BLOCK"
                    else (spec["reef_mouth"], 0, 0)
                )
                outline = [
                    [x + offset_x + r * math.cos(TAU * j / len(radii) + spec["rotation"]),
                     y + offset_y + r * math.sin(TAU * j / len(radii) + spec["rotation"])]
                    for j, r in enumerate(radii)
                ]
                pad, pad_x, pad_y = (
                    (_block_footprint(spec, config, config.radial_segments), 0, 0)
                    if spec["form_type"] == "BLOCK" else _foot_radii(spec, config)
                )
                foot_outline = [
                    [x + pad_x + r * math.cos(TAU * j / len(pad) + spec["rotation"]),
                     y + pad_y + r * math.sin(TAU * j / len(pad) + spec["rotation"])]
                    for j, r in enumerate(pad)
                ]
                record = dict(
                    piece_id=piece_id, panel=label, panel_column=column + 1,
                    panel_row=row + 1, local_x_mm=round(local_x, 3),
                    local_y_mm=round(local_y, 3), artwork_x_mm=round(x, 3),
                    artwork_y_mm=round(y, 3),
                    rotation_degrees=round(math.degrees(spec["rotation"]), 3),
                    height_mm=round(dimensions[2], 3),
                    mouth_diameter_mm=round(max(dimensions[:2]), 3),
                    form_type=spec["form_type"], colour_group=colour,
                    outline=outline, foot_outline=foot_outline,
                    bounds_min=list(low), bounds_max=list(high),
                    volume_mm3=round(_mesh_volume_mm3(obj.data), 3),
                    flow_river=round(spec.get("river", 0), 4),
                )
                records.append(record)
                obj["crf_generator_version"] = VERSION
                obj["crf_piece_id"] = piece_id
                obj["crf_panel"] = label
                obj["crf_panel_column"] = column + 1
                obj["crf_panel_row"] = row + 1
                obj["crf_local_xy_mm"] = (local_x, local_y)
                obj["crf_artwork_xy_mm"] = (x, y)
                obj["crf_rotation_degrees"] = record["rotation_degrees"]
                obj["crf_height_mm"] = dimensions[2]
                obj["crf_colour_group"] = colour
                obj["crf_seed"] = config.random_seed
                obj["crf_output"] = "CONNECTED_GLUE_DOWN_PIECE"
                obj["crf_mesh_signature"] = _mesh_fingerprint(obj.data)
                created.append(obj)
                wm.progress_update(index + 1)

            manifest = dict(
                version=VERSION, width=config.finished_width, height=config.finished_height,
                columns=columns, rows=rows, panel_width=panel_x, panel_height=panel_y,
                usable_x=usable_x, usable_y=usable_y, seed=config.random_seed,
                wave_wavelength=config.wave_wavelength, settings=vars(config), pieces=records,
            )
            manifest["volume_cm3"] = round(sum(r["volume_mm3"] for r in records) / 1000, 2)
            staging["crf_manifest"] = json.dumps(manifest)
            staging["crf_generator_version"] = VERSION
            staging["crf_seed"] = config.random_seed
            staging["crf_piece_count"] = len(created)
            staging["crf_finished_size_mm"] = (config.finished_width, config.finished_height)
            staging["crf_panel_size_mm"] = (panel_x, panel_y)
            staging["crf_panel_columns"] = columns
            staging["crf_panel_rows"] = rows

            old = settings.artwork_collection
            if old and old.get("crf_generated"):
                # A collection used in another scene is retained there.
                shared_with_other_scene = any(
                    s != context.scene and old in tuple(s.collection.children_recursive)
                    for s in bpy.data.scenes
                )
                if shared_with_other_scene:
                    if old.name in context.scene.collection.children:
                        context.scene.collection.children.unlink(old)
                else:
                    _remove_generated_collection(old.name)
            staging.name = "CRF_Modular_Artwork"
            settings.artwork_collection = staging
            _write_assembly_text(records)
            if config.configure_scene_units:
                context.scene.unit_settings.system = "METRIC"
                context.scene.unit_settings.length_unit = "MILLIMETERS"
                context.scene.unit_settings.scale_length = 0.001
            for selected in list(context.selected_objects):
                selected.select_set(False)
            for obj in created:
                obj.select_set(True)
            context.view_layer.objects.active = created[-1] if created else None
            context.view_layer.update()
            self.report(
                {"INFO"}, f"Created {len(created)} connected pieces over "
                f"{config.finished_width:.0f} x {config.finished_height:.0f} mm "
                f"in {time.perf_counter() - started:.1f}s",
            )
            return {"FINISHED"}
        except Exception as exc:
            if staging and staging != settings.artwork_collection:
                _remove_generated_collection(staging.name)
            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            wm.progress_end()

class CRF_OT_export_assembly_csv(Operator):
    bl_idname = "crf.export_assembly_csv"
    bl_label = "Save Assembly Map"
    bl_description = "Save the generated numbered piece placement map as CSV"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.csv", options={"HIDDEN"})

    def invoke(self, context, event):
        default_path = bpy.path.abspath(context.scene.crf_settings.assembly_csv_path)
        self.filepath = default_path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        root = context.scene.crf_settings.artwork_collection
        text_block = bpy.data.texts.get(ASSEMBLY_TEXT_NAME)
        if text_block is None:
            self.report({"ERROR"}, "Generate numbered artwork before saving its map")
            return {"CANCELLED"}
        target = Path(bpy.path.abspath(self.filepath))
        if target.suffix.lower() != ".csv":
            target = target.with_suffix(".csv")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (_assembly_csv(json.loads(root["crf_manifest"])["pieces"])
                   if root and root.get("crf_manifest") else text_block.as_string())
        target.write_text(content, encoding="utf-8", newline="")
        context.scene.crf_settings.assembly_csv_path = str(target)
        self.report({"INFO"}, f"Saved assembly map: {target.name}")
        return {"FINISHED"}


class CRF_OT_generate_finished_work(Operator):
    bl_idname = "crf.generate_finished_work"
    bl_label = "Generate Finished Work"
    bl_description = (
        "Auto-plan equal A1 Mini panels for the exact finished size and generate them together"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.mode == "OBJECT"

    def execute(self, context):
        settings = context.scene.crf_settings
        if settings.output_mode == "NUMBERED_PIECES":
            return bpy.ops.crf.generate_modular_artwork()
        try:
            columns, rows, panel_x, panel_y, usable_x, usable_y = _panel_plan(
                settings
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        panel_total = columns * rows
        total_cups = panel_total * _estimated_cup_count(
            panel_x * panel_y,
            settings,
        )
        if total_cups > 10000:
            self.report(
                {"ERROR"},
                "Finished work exceeds the 10,000-cup safety limit; lower Density or reduce its size",
            )
            return {"CANCELLED"}
        if _estimated_source_vertices(total_cups, settings) > 8_000_000:
            self.report(
                {"ERROR"},
                "Finished work would exceed 8 million source vertices; reduce quality or density",
            )
            return {"CANCELLED"}
        crown_and_remesh = settings.wall_thickness * 0.35
        if settings.merge_manifold:
            crown_and_remesh += settings.voxel_size
        if _support_top(settings) + settings.max_height + crown_and_remesh > settings.printer_bed_z:
            self.report(
                {"ERROR"},
                "Maximum cup height exceeds the configured printer Z capacity",
            )
            return {"CANCELLED"}

        previous = {
            "tile_size_x": settings.tile_size_x,
            "tile_size_y": settings.tile_size_y,
            "panel_count_x": settings.panel_count_x,
            "panel_count_y": settings.panel_count_y,
            "wave_wavelength": settings.wave_wavelength,
            "layout_tiles_in_grid": settings.layout_tiles_in_grid,
        }
        result = {"CANCELLED"}
        try:
            settings.tile_size_x = panel_x
            settings.tile_size_y = panel_y
            settings.panel_count_x = columns
            settings.panel_count_y = rows
            settings.layout_tiles_in_grid = True
            if settings.auto_fit_wave_to_artwork:
                direction = math.radians(settings.wave_direction)
                projected_span = (
                    abs(settings.finished_width * math.cos(direction))
                    + abs(settings.finished_height * math.sin(direction))
                )
                settings.wave_wavelength = projected_span / max(
                    settings.wave_cycles_across_artwork,
                    0.01,
                )
            effective_wave_wavelength = settings.wave_wavelength

            if settings.output_mode == "NUMBERED_PIECES":
                result = bpy.ops.crf.generate_modular_artwork()
            else:
                result = bpy.ops.crf.generate_panel_set()
            if "FINISHED" not in result:
                self.report({"ERROR"}, "Finished-work panel generation did not complete")
                return {"CANCELLED"}

            for obj in context.selected_objects:
                if not obj.name.startswith(ADDON_PREFIX):
                    continue
                obj["crf_finished_width_mm"] = settings.finished_width
                obj["crf_finished_height_mm"] = settings.finished_height
                obj["crf_panel_columns"] = columns
                obj["crf_panel_rows"] = rows
                obj["crf_panel_width_mm"] = panel_x
                obj["crf_panel_height_mm"] = panel_y
                obj["crf_printer_usable_xy_mm"] = (usable_x, usable_y)
                obj["crf_effective_wave_wavelength_mm"] = effective_wave_wavelength
                obj["crf_wave_direction_degrees"] = settings.wave_direction
                obj["crf_wave_cycles_across_artwork"] = (
                    settings.wave_cycles_across_artwork
                )
        finally:
            settings.tile_size_x = previous["tile_size_x"]
            settings.tile_size_y = previous["tile_size_y"]
            settings.panel_count_x = previous["panel_count_x"]
            settings.panel_count_y = previous["panel_count_y"]
            settings.wave_wavelength = previous["wave_wavelength"]
            settings.layout_tiles_in_grid = previous["layout_tiles_in_grid"]

        self.report(
            {"INFO"},
            (
                f"Generated {columns} x {rows} = {panel_total} panels, "
                f"{panel_x:.1f} x {panel_y:.1f} mm each"
            ),
        )
        return {"FINISHED"}



# -----------------------------------------------------------------------------
# Framing, rendering and self-contained assembly/printing package

def _artwork_objects(context):
    root = context.scene.crf_settings.artwork_collection
    if root and context.scene.crf_settings.output_mode == "NUMBERED_PIECES":
        return [o for o in root.all_objects if o.type == "MESH"]
    names = json.loads(context.scene.get("crf_panel_objects", "[]"))
    if names:
        return [context.scene.objects[name] for name in names if name in context.scene.objects]
    return [o for o in context.scene.objects
            if o.type == "MESH" and o.get("crf_output") and not o.get("crf_piece_id")]


def _manifest(context):
    root = context.scene.crf_settings.artwork_collection
    if not root or not root.get("crf_manifest"):
        raise ValueError("Generate numbered artwork with this version first")
    return json.loads(root["crf_manifest"])


def _svg_map(manifest, column=None, row=None):
    width, height = manifest["width"], manifest["height"]
    x0 = y0 = 0.0
    if column is not None:
        width, height = manifest["panel_width"], manifest["panel_height"]
        x0, y0 = column * width, row * height
    points = lambda outline: " ".join(
        f"{x - x0:.3f},{height - (y - y0):.3f}" for x, y in outline
    )
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" '
        f'height="{height}mm" viewBox="0 0 {width} {height}">',
        '<title>Coral Reef — full scale mounting map; print at 100%</title>',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    colours = ("#eef0df", "#dce8e3", "#d3e0e8", "#e3d9db", "#e8d8c4")
    for p in manifest["pieces"]:
        if column is not None and (p["panel_column"] != column + 1 or p["panel_row"] != row + 1):
            continue
        svg.append(f'<polygon points="{points(p["outline"])}" '
                   f'fill="{colours[p["colour_group"] - 1]}" stroke="#777" stroke-width=".18"/>')
        svg.append(f'<polygon points="{points(p["foot_outline"])}" '
                   'fill="none" stroke="#222" stroke-width=".25" stroke-dasharray="1 .6"/>')
        x, y = p["artwork_x_mm"] - x0, height - (p["artwork_y_mm"] - y0)
        angle = math.radians(p["rotation_degrees"])
        dx, dy = 3.5 * math.cos(angle), -3.5 * math.sin(angle)
        svg.append(f'<path d="M{x-1},{y}h2 M{x},{y-1}v2 M{x},{y}l{dx},{dy}" '
                   'fill="none" stroke="#111" stroke-width=".3"/>')
        svg.append(f'<text x="{x}" y="{y+3}" font-family="sans-serif" '
                   f'font-size="2.4" text-anchor="middle">{escape(p["piece_id"])}</text>')
    if column is None:
        for c in range(1, manifest["columns"]):
            x = c * manifest["panel_width"]
            svg.append(f'<path d="M{x},0V{height}" stroke="#22649c" stroke-width=".3" '
                       'stroke-dasharray="3 2"/>')
        for r in range(1, manifest["rows"]):
            y = r * manifest["panel_height"]
            svg.append(f'<path d="M0,{y}H{width}" stroke="#22649c" stroke-width=".3" '
                       'stroke-dasharray="3 2"/>')
    svg.append(f'<rect x=".2" y=".2" width="{width-.4}" height="{height-.4}" '
               'fill="none" stroke="#111" stroke-width=".3"/>')
    # A physical ruler makes accidental fit-to-page scaling visible.
    svg.append('<path d="M5,5H25 M5,3V7 M25,3V7" stroke="#111" stroke-width=".3"/>')
    svg.append('<text x="15" y="10" font-family="sans-serif" font-size="2.5" '
               'text-anchor="middle">20 mm</text></svg>')
    return "\n".join(svg)


def _pack_plates(records, width, height, gap):
    """Deterministic shelf packing, no rotations; all 3D bounds remain disjoint."""
    plates = []
    for record in sorted(records, key=lambda p: (
        -(p["bounds_max"][1] - p["bounds_min"][1]), p["piece_id"]
    )):
        low, high = record["bounds_min"], record["bounds_max"]
        w, h = high[0] - low[0], high[1] - low[1]
        if w > width + 1e-6 or h > height + 1e-6:
            raise ValueError(f'{record["piece_id"]} exceeds the usable print bed')
        placed = False
        for plate in plates:
            for shelf in plate["shelves"]:
                if h <= shelf["height"] + 1e-6 and shelf["next_x"] + w <= width + 1e-6:
                    plate["pieces"].append((record, shelf["next_x"], shelf["y"]))
                    shelf["next_x"] += w + gap
                    placed = True
                    break
            if placed:
                break
            y = sum(s["height"] + gap for s in plate["shelves"])
            if y + h <= height + 1e-6:
                plate["shelves"].append(dict(height=h, next_x=w + gap, y=y))
                plate["pieces"].append((record, 0.0, y))
                placed = True
                break
        if not placed:
            plates.append(dict(shelves=[dict(height=h, next_x=w + gap, y=0.0)],
                               pieces=[(record, 0.0, 0.0)]))
    return plates


def _write_stl(path, objects_and_offsets):
    """Write numeric millimetres directly; independent of Blender STL extensions."""
    count = 0
    for obj, offset in objects_and_offsets:
        obj.data.calc_loop_triangles()
        count += len(obj.data.loop_triangles)
    with path.open("wb") as handle:
        handle.write(b"Coral Reef: coordinates in millimetres".ljust(80, b"\0"))
        handle.write(struct.pack("<I", count))
        for obj, offset in objects_and_offsets:
            mesh = obj.data
            for triangle in mesh.loop_triangles:
                a, b, c = [mesh.vertices[i].co for i in triangle.vertices]
                normal = (b - a).cross(c - a).normalized()
                xyz = [value + offset[axis]
                       for point in (a, b, c) for axis, value in enumerate(point)]
                handle.write(struct.pack("<12fH", *normal, *xyz, 0))


def _export_print_package(context, directory):
    context.view_layer.update()
    manifest = _manifest(context)
    settings = context.scene.crf_settings
    objects = {o.get("crf_piece_id"): o for o in _artwork_objects(context)}
    usable_x = settings.printer_bed_x - 2 * settings.printer_margin
    usable_y = settings.printer_bed_y - 2 * settings.printer_margin
    if min(usable_x, usable_y) <= 0:
        raise ValueError("Bed margin leaves no usable print area")
    for p in manifest["pieces"]:
        obj = objects.get(p["piece_id"])
        expected_location = (p["artwork_x_mm"] - manifest["width"] / 2,
                             p["artwork_y_mm"] - manifest["height"] / 2, 0)
        if (obj is None or obj.modifiers or obj.parent
                or any(abs(obj.matrix_world[i][j] - (1.0 if i == j else 0.0)) > 1e-5
                       for i in range(3) for j in range(3))
                or any(abs(obj.matrix_world[i][3] - expected_location[i]) > 0.002
                       for i in range(3))
                or obj.get("crf_mesh_signature") != _mesh_fingerprint(obj.data)):
            raise ValueError(f'{p["piece_id"]} was edited; regenerate to synchronize geometry and map')
        if p["bounds_max"][2] - p["bounds_min"][2] > settings.printer_bed_z:
            raise ValueError(f'{p["piece_id"]} exceeds the configured print height')
    plates = _pack_plates(manifest["pieces"], usable_x, usable_y, settings.batch_spacing)
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    # Unique destination on every export; existing print jobs are never replaced.
    package = Path(tempfile.mkdtemp(prefix=f'OrganicCups_seed{manifest["seed"]}_', dir=destination))
    (package / "pieces").mkdir()
    (package / "plates").mkdir()
    (package / "regions").mkdir()
    (package / "assembly.csv").write_text(_assembly_csv(manifest["pieces"]), encoding="utf-8")
    (package / "assembly.svg").write_text(_svg_map(manifest), encoding="utf-8")
    for row in range(manifest["rows"]):
        for column in range(manifest["columns"]):
            number = row * manifest["columns"] + column + 1
            (package / "regions" / f"P{number:02d}.svg").write_text(
                _svg_map(manifest, column, row), encoding="utf-8",
            )
    for p in manifest["pieces"]:
        low, high = p["bounds_min"], p["bounds_max"]
        offset = (-(low[0] + high[0]) / 2, -(low[1] + high[1]) / 2, -low[2])
        _write_stl(package / "pieces" / f'{p["piece_id"]}.stl',
                   [(objects[p["piece_id"]], offset)])
    plate_manifest = []
    margin = settings.printer_margin
    for index, plate in enumerate(plates, 1):
        items, assignments = [], []
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{settings.printer_bed_x}mm" '
               f'height="{settings.printer_bed_y}mm" '
               f'viewBox="0 0 {settings.printer_bed_x} {settings.printer_bed_y}">',
               '<rect width="100%" height="100%" fill="white"/>']
        for p, x, y in plate["pieces"]:
            low, high = p["bounds_min"], p["bounds_max"]
            offset = (x + margin - low[0], y + margin - low[1], -low[2])
            items.append((objects[p["piece_id"]], offset))
            assignments.append(dict(piece_id=p["piece_id"], offset=list(offset)))
            w, h = high[0] - low[0], high[1] - low[1]
            sy = settings.printer_bed_y - (y + margin + h)
            svg.append(f'<rect x="{x+margin}" y="{sy}" width="{w}" height="{h}" '
                       'fill="#eee" stroke="#555" stroke-width=".2"/>')
            svg.append(f'<text x="{x+margin+w/2}" y="{sy+h/2}" font-size="3" '
                       f'text-anchor="middle">{p["piece_id"]}</text>')
        svg.append('</svg>')
        filename = f"plate_{index:03d}"
        _write_stl(package / "plates" / f"{filename}.stl", items)
        (package / "plates" / f"{filename}.svg").write_text("\n".join(svg), encoding="utf-8")
        plate_manifest.append(dict(plate=filename, pieces=assignments))
    manifest["print_plates"] = plate_manifest
    manifest["export_printer"] = dict(x=settings.printer_bed_x, y=settings.printer_bed_y,
                                     z=settings.printer_bed_z, margin=margin,
                                     spacing=settings.batch_spacing)
    (package / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (package / "PRINT_ME_FIRST.md").write_text(
        "# Your Coral Reef print package\n\n"
        "All STL coordinates are millimetres. Import one plates/plate_*.stl at a time "
        "into Bambu Studio, keeping its parts together and their layout unchanged. "
        "Use the matching plate SVG to label pieces as they come off the bed. "
        "The individual pieces/ files are for reprints.\n\n"
        "The SVG mounting maps use true millimetre dimensions: print at 100%, not "
        "fit-to-page, and measure the 20 mm ruler. Convert or tile the master SVG "
        "in a vector editor if it exceeds your paper size. Dashed contours mark "
        "glue feet; faint solid contours mark mouths. Coordinates start at bottom-left. "
        "The small orientation line points along the shape's local X direction; "
        "STL geometry already includes that rotation. Colour groups are suggestions.\n\n"
        "Bed margin and spacing do not include slicer-added brims. Check them in "
        "layer preview. Print a few representative forms before the complete set. "
        "Regions organize assembly; cups can cross seams. Join the backing first. "
        "Do not rescale pieces independently.\n", encoding="utf-8",
    )
    return package, len(plates)


class CRF_OT_frame_artwork(Operator):
    bl_idname = "crf.frame_artwork"
    bl_label = "Frame All Panels"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = _artwork_objects(context)
        if not objects:
            self.report({"ERROR"}, "Generate artwork first")
            return {"CANCELLED"}
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in objects:
            obj.hide_set(False)
            obj.select_set(True)
        context.view_layer.objects.active = objects[0]
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                with context.temp_override(area=area, region=region):
                    bpy.ops.view3d.view_selected(use_all_regions=False)
                area.spaces.active.clip_end = 100000
                break
        return {"FINISHED"}


def _setup_render(context):
    from mathutils import Vector
    objects = _artwork_objects(context)
    if not objects:
        raise ValueError("Generate artwork first")
    context.view_layer.update()
    settings = context.scene.crf_settings
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    low, high = _vertex_bounds(points)
    center = Vector([(low[i] + high[i]) / 2 for i in range(3)])
    span = max(high[i] - low[i] for i in range(3))
    preview = bpy.data.scenes.get(context.scene.get("crf_preview_scene", ""))
    if preview is None or not preview.get("crf_render_scene"):
        preview = bpy.data.scenes.new("CRF Artwork Preview")
        preview["crf_render_scene"] = True
        context.scene["crf_preview_scene"] = preview.name
    for obj in list(preview.objects):
        if obj.get("crf_render_helper"):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
                elif isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
        else:
            preview.collection.objects.unlink(obj)
    for obj in objects:
        preview.collection.objects.link(obj)
    camera_data = bpy.data.cameras.new("CRF Full Artwork Camera")
    camera = bpy.data.objects.new("CRF Full Artwork Camera", camera_data)
    camera["crf_render_helper"] = True
    preview.collection.objects.link(camera)
    direction = Vector((0, 0, 1) if settings.render_view == "TOP" else (0.28, -0.52, 1)).normalized()
    camera.location = center + direction * (span * 3 + 100)
    camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    inverse_rotation = camera.rotation_euler.to_quaternion().inverted()
    projected = [inverse_rotation @ (p - center) for p in points]
    width = max(abs(p.x) for p in projected) * 2
    height = max(abs(p.y) for p in projected) * 2
    width, height = max(width, 1), max(height, 1)
    aspect = width / height
    size = settings.render_pixels
    preview.render.resolution_x = max(64, round(size * min(1, aspect)))
    preview.render.resolution_y = max(64, round(size * min(1, 1 / aspect)))
    preview.render.resolution_percentage = 100
    preview.render.pixel_aspect_x = preview.render.pixel_aspect_y = 1
    camera_data.type = "ORTHO"
    camera_data.sensor_fit = "HORIZONTAL"
    actual_aspect = preview.render.resolution_x / preview.render.resolution_y
    camera_data.ortho_scale = max(width, height * actual_aspect) * 1.12
    camera_data.clip_start = 0.01
    camera_data.clip_end = span * 10 + 1000
    preview.camera = camera
    # A dedicated studio-render scene leaves user camera/lighting/engine intact.
    preview.render.engine = "BLENDER_WORKBENCH"
    preview.display.shading.light = "STUDIO"
    preview.display.shading.color_type = "MATERIAL"
    preview.display.shading.show_shadows = True
    preview.display.shading.show_cavity = False
    preview.display.shading.cavity_type = "BOTH"
    preview.display.shading.background_type = "WORLD"
    preview.world = bpy.data.worlds.get("CRF Preview World") or bpy.data.worlds.new("CRF Preview World")
    preview.world.color = (0.05, 0.05, 0.05)
    preview.render.image_settings.file_format = "PNG"
    preview.unit_settings.system = "METRIC"
    preview.unit_settings.scale_length = 0.001
    if settings.studio_render:
        _reef_studio_lighting(preview, low, high)
    preview.view_layers[0].update()
    return preview


def _reef_studio_lighting(preview, low, high):
    """Physical light and a display-only backing, never included in STL export."""
    from mathutils import Vector
    span = max(high[0]-low[0], high[1]-low[1])
    center = Vector(((low[0]+high[0])/2, (low[1]+high[1])/2, 0))
    preview.render.engine = "CYCLES"
    preview.cycles.samples = 32
    preview.cycles.use_denoising = True
    preview.world.use_nodes = True
    background = preview.world.node_tree.nodes.get('Background')
    background.inputs['Color'].default_value = (0.6, 0.64, 0.7, 1)
    background.inputs['Strength'].default_value = 0.10
    for name, location, power, size in (
        ('Key', (-0.65, 0.15, 0.65), 12, 0.65),
        ('Fill', (0.6, -0.4, 0.8), 2, 1.0),
    ):
        light = bpy.data.lights.new('CRF Studio ' + name, 'AREA')
        light.energy = span * span * power
        light.shape = 'DISK'
        light.size = span * size
        obj = bpy.data.objects.new(light.name, light)
        obj['crf_render_helper'] = True
        preview.collection.objects.link(obj)
        obj.location = center + Vector(location) * span
        obj.rotation_euler = (center-obj.location).to_track_quat('-Z', 'Y').to_euler()
    mesh = bpy.data.meshes.new('CRF Display Backing')
    pad = span * 0.04
    mesh.from_pydata([(low[0]-pad, low[1]-pad, -0.4),
                      (high[0]+pad, low[1]-pad, -0.4),
                      (high[0]+pad, high[1]+pad, -0.4),
                      (low[0]-pad, high[1]+pad, -0.4)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(mesh.name, mesh)
    obj['crf_render_helper'] = True
    preview.collection.objects.link(obj)
    material = bpy.data.materials.get('CRF Dark Backing') or bpy.data.materials.new('CRF Dark Backing')
    material.diffuse_color = (0.085, 0.078, 0.065, 1)
    material.roughness = 0.9
    mesh.materials.append(material)


class CRF_OT_setup_render(Operator):
    bl_idname = "crf.setup_render"
    bl_label = "Set Up Full Artwork Camera"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            scene = _setup_render(context)
            self.report({"INFO"}, f"Camera ready in scene: {scene.name}; use Render All Panels")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class CRF_OT_render_artwork(Operator):
    bl_idname = "crf.render_artwork"
    bl_label = "Render All Panels"
    bl_description = "Fit all generated panels to a separate studio scene and render an image"

    def execute(self, context):
        try:
            scene = _setup_render(context)
            if bpy.app.background:
                bpy.ops.render.render(scene=scene.name)
            else:
                bpy.ops.render.render("INVOKE_DEFAULT", scene=scene.name)
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class CRF_OT_export_package(Operator):
    bl_idname = "crf.export_package"
    bl_label = "Export Print & Assembly Package"
    bl_description = "Save individual STLs, spaced print plates, numbered SVG maps and settings"
    directory: StringProperty(subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            if not self.directory:
                raise ValueError("Choose an output folder")
            package, plates = _export_print_package(context, bpy.path.abspath(self.directory))
            self.report({"INFO"}, f"Exported {plates} plates and maps to {package}")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class CRF_PT_sidebar(Panel):
    bl_label = "Flowing Coral Reef"
    bl_idname = "CRF_PT_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Coral Reef"

    def draw(self, context):
        layout = self.layout
        s = context.scene.crf_settings
        box = layout.box()
        box.label(text="Flowing Coral Reef", icon="FORCE_TURBULENCE")
        box.prop(s, "style_preset")
        box.operator("crf.apply_style_preset", text="Apply Preset")
        box.label(text="Thin shells + individual glue feet", icon="INFO")
        row = box.row(align=True)
        row.prop(s, "finished_width")
        row.prop(s, "finished_height")
        try:
            cols, rows, px, py, ux, uy = _panel_plan(s)
            box.label(text=f"Mounting regions: {cols} x {rows} ({px:.1f} x {py:.1f} mm)")
            count = _estimated_cup_count(s.finished_width*s.finished_height, s)
            box.label(text=f"Target: {count} cups, composed together")
        except ValueError as exc:
            box.label(text=str(exc), icon="ERROR")
        row = box.row()
        row.scale_y = 1.6
        row.operator("crf.generate_modular_artwork", text="Generate Complete Reef", icon="MESH_GRID")
        row = box.row(align=True)
        row.prop(s, "random_seed")
        row.operator("crf.randomize_seed", text="", icon="FILE_REFRESH")

        box = layout.box()
        box.label(text="Current & Cup Hierarchy")
        for name in ("density", "min_cup_scale", "max_cup_scale", "cluster_strength",
                     "orientation_flow_scale", "flow_swirl", "flow_alignment", "wave_direction"):
            box.prop(s, name)
        box = layout.box()
        box.label(text="Shell Shape & Relief")
        for name in ("form_style", "min_height", "max_height", "wall_thickness",
                     "mouth_variation", "mouth_elongation", "throat_size", "throat_offset",
                     "max_lean", "bend_variation", "base_rotation", "rotation_variation",
                     "wave_amplitude", "auto_fit_wave_to_artwork", "wave_cycles_across_artwork"):
            box.prop(s, name)
        if not s.auto_fit_wave_to_artwork:
            box.prop(s, "wave_wavelength")
        box.prop(s, "undercurrent_depth")
        if s.form_style != "ORGANIC_FUNNELS":
            box.prop(s, "block_fraction")
            box.prop(s, "block_bevel")
            box.label(text="Blocks are solid geometry", icon="INFO")

        box = layout.box()
        box.label(text="Print & Assembly", icon="EXPORT")
        for name in ("individual_base_thickness", "foot_flange", "printer_bed_x",
                     "printer_bed_y", "printer_bed_z", "printer_margin", "batch_spacing",
                     "radial_segments", "vertical_segments"):
            box.prop(s, name)
        box.label(text="Default usable bed: 175 x 175 mm")
        box.label(text="No voxel merge needed for individual shells")
        root = s.artwork_collection
        if root:
            try:
                data = json.loads(root["crf_manifest"])
                volume = data["volume_cm3"]
                box.label(text=f"Model material: {volume:.1f} cm3")
                box.label(text=f"About {volume*1.24:.0f} g at 1.24 g/cm3 (no supports)")
            except (KeyError, ValueError):
                pass
        box.operator("crf.export_package", text="Export STLs & Numbered Maps")
        box = layout.box()
        box.label(text="View the Complete Artwork", icon="CAMERA_DATA")
        box.operator("crf.frame_artwork", text="Frame Complete Reef")
        box.prop(s, "render_view")
        box.prop(s, "studio_render")
        box.prop(s, "render_pixels")
        box.operator("crf.render_artwork", text="Render Complete Reef")
        box.label(text="Studio backing is visual only; not exported")


CLASSES = (
    CRFSettings,
    CRF_OT_apply_style_preset,
    CRF_OT_apply_reference_preset,
    CRF_OT_randomize_seed,
    CRF_OT_generate_field,
    CRF_OT_generate_panel_set,
    CRF_OT_generate_modular_artwork,
    CRF_OT_export_assembly_csv,
    CRF_OT_generate_finished_work,
    CRF_OT_frame_artwork,
    CRF_OT_setup_render,
    CRF_OT_render_artwork,
    CRF_OT_export_package,
    CRF_PT_sidebar,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.crf_settings = PointerProperty(type=CRFSettings)


def unregister():
    if hasattr(bpy.types.Scene, "crf_settings"):
        del bpy.types.Scene.crf_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
