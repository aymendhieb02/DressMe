"""Build a small, non-personal rigged mannequin fixture using only Python stdlib."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path


OUT = Path(__file__).with_name("synthetic_rigged_avatar.glb")
binary = bytearray()
buffer_views = []
accessors = []
positions: list[tuple[float, float, float]] = []
joints: list[tuple[int, int, int, int]] = []
weights: list[tuple[float, float, float, float]] = []
indices: list[int] = []


def align4() -> None:
    binary.extend(b"\x00" * ((-len(binary)) % 4))


def accessor(data: bytes, component_type: int, shape: str, count: int, *, target=None, minimum=None, maximum=None) -> int:
    align4()
    offset = len(binary)
    binary.extend(data)
    view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
    if target is not None:
        view["target"] = target
    buffer_views.append(view)
    result = {
        "bufferView": len(buffer_views) - 1,
        "componentType": component_type,
        "count": count,
        "type": shape,
    }
    if minimum is not None:
        result["min"] = minimum
    if maximum is not None:
        result["max"] = maximum
    accessors.append(result)
    return len(accessors) - 1


def add_vertex(x: float, y: float, z: float, joint: int) -> int:
    positions.append((x, y, z))
    joints.append((joint, 0, 0, 0))
    weights.append((1.0, 0.0, 0.0, 0.0))
    return len(positions) - 1


def box(center, size, joint: int) -> None:
    cx, cy, cz = center
    sx, sy, sz = (part / 2 for part in size)
    first = len(positions)
    for x, y, z in (
        (-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
        (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz),
    ):
        add_vertex(cx + x, cy + y, cz + z, joint)
    faces = (
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    )
    indices.extend(first + index for face in faces for index in face)


def tube(start, end, radius_start: float, radius_end: float, joint: int, segments: int = 12) -> None:
    direction = tuple(end[i] - start[i] for i in range(3))
    length = math.sqrt(sum(value * value for value in direction))
    axis = tuple(value / length for value in direction)
    helper = (0.0, 0.0, 1.0) if abs(axis[2]) < 0.9 else (0.0, 1.0, 0.0)
    u = (axis[1] * helper[2] - axis[2] * helper[1], axis[2] * helper[0] - axis[0] * helper[2], axis[0] * helper[1] - axis[1] * helper[0])
    u_len = math.sqrt(sum(value * value for value in u))
    u = tuple(value / u_len for value in u)
    v = (axis[1] * u[2] - axis[2] * u[1], axis[2] * u[0] - axis[0] * u[2], axis[0] * u[1] - axis[1] * u[0])
    first = len(positions)
    for center, radius in ((start, radius_start), (end, radius_end)):
        for segment in range(segments):
            angle = 2 * math.pi * segment / segments
            x = center[0] + radius * (math.cos(angle) * u[0] + math.sin(angle) * v[0])
            y = center[1] + radius * (math.cos(angle) * u[1] + math.sin(angle) * v[1])
            z = center[2] + radius * (math.cos(angle) * u[2] + math.sin(angle) * v[2])
            add_vertex(x, y, z, joint)
    for segment in range(segments):
        next_segment = (segment + 1) % segments
        a, b = first + segment, first + next_segment
        c, d = first + segments + segment, first + segments + next_segment
        indices.extend((a, c, b, b, c, d))
    indices.extend((first + segment for segment in range(segments)))
    indices.extend((first + segments + segment for segment in reversed(range(segments))))


def sphere(center, radius: float, joint: int, rings: int = 8, segments: int = 12) -> None:
    first = len(positions)
    for ring in range(rings + 1):
        phi = math.pi * ring / rings
        for segment in range(segments):
            theta = 2 * math.pi * segment / segments
            add_vertex(
                center[0] + radius * math.sin(phi) * math.cos(theta),
                center[1] + radius * math.cos(phi),
                center[2] + radius * math.sin(phi) * math.sin(theta),
                joint,
            )
    for ring in range(rings):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            a = first + ring * segments + segment
            b = first + ring * segments + next_segment
            c = first + (ring + 1) * segments + segment
            d = first + (ring + 1) * segments + next_segment
            indices.extend((a, c, b, b, c, d))


# Joint positions are parent-relative. Inverse bind matrices below preserve this
# visible neutral pose while keeping the test GLB's mesh genuinely skinned.
bone_specs = [
    ("pelvis", None, (0, 0.90, 0)),
    ("spine", 0, (0, 0.20, 0)),
    ("chest", 1, (0, 0.28, 0)),
    ("neck", 2, (0, 0.12, 0)),
    ("head", 3, (0, 0.12, 0)),
    ("left_shoulder", 2, (-0.20, 0.02, 0)),
    ("left_elbow", 5, (-0.28, -0.04, 0)),
    ("left_hand", 6, (-0.27, -0.04, 0)),
    ("right_shoulder", 2, (0.20, 0.02, 0)),
    ("right_elbow", 8, (0.28, -0.04, 0)),
    ("right_hand", 9, (0.27, -0.04, 0)),
    ("left_hip", 0, (-0.12, -0.08, 0)),
    ("left_knee", 11, (0, -0.43, 0)),
    ("left_ankle", 12, (0, -0.39, 0)),
    ("right_hip", 0, (0.12, -0.08, 0)),
    ("right_knee", 14, (0, -0.43, 0)),
    ("right_ankle", 15, (0, -0.39, 0)),
]
world_positions = []
for name, parent, translation in bone_specs:
    if parent is None:
        world_positions.append(translation)
    else:
        world_positions.append(tuple(world_positions[parent][axis] + translation[axis] for axis in range(3)))

box((0, 0.88, 0), (0.34, 0.22, 0.20), 0)
tube((0, 0.94, 0), (0, 1.15, 0), 0.16, 0.17, 1)
tube((0, 1.13, 0), (0, 1.42, 0), 0.17, 0.24, 2)
tube((0, 1.42, 0), (0, 1.57, 0), 0.06, 0.06, 3)
sphere((0, 1.68, 0), 0.13, 4)
for sign, shoulder_joint, elbow_joint, hand_joint in ((-1, 5, 6, 7), (1, 8, 9, 10)):
    shoulder = (sign * 0.20, 1.44, 0)
    elbow = (sign * 0.48, 1.38, 0)
    wrist = (sign * 0.73, 1.31, 0)
    tube(shoulder, elbow, 0.085, 0.065, shoulder_joint)
    tube(elbow, wrist, 0.065, 0.045, elbow_joint)
    sphere((sign * 0.80, 1.29, 0), 0.06, hand_joint, rings=6, segments=10)
for sign, hip_joint, knee_joint, ankle_joint in ((-1, 11, 12, 13), (1, 14, 15, 16)):
    hip = (sign * 0.12, 0.82, 0)
    knee = (sign * 0.12, 0.41, 0)
    ankle = (sign * 0.12, 0.08, 0)
    tube(hip, knee, 0.12, 0.085, hip_joint)
    tube(knee, ankle, 0.085, 0.055, knee_joint)
    box((sign * 0.12, 0.045, 0.06), (0.14, 0.09, 0.28), ankle_joint)

position_min = [min(position[axis] for position in positions) for axis in range(3)]
position_max = [max(position[axis] for position in positions) for axis in range(3)]
position_accessor = accessor(b"".join(struct.pack("<3f", *position) for position in positions), 5126, "VEC3", len(positions), target=34962, minimum=position_min, maximum=position_max)
joints_accessor = accessor(b"".join(struct.pack("<4B", *joint) for joint in joints), 5121, "VEC4", len(joints), target=34962)
weights_accessor = accessor(b"".join(struct.pack("<4f", *weight) for weight in weights), 5126, "VEC4", len(weights), target=34962)
indices_accessor = accessor(b"".join(struct.pack("<H", index) for index in indices), 5123, "SCALAR", len(indices), target=34963, minimum=[min(indices)], maximum=[max(indices)])

inverse_bind = []
for x, y, z in world_positions:
    inverse_bind.extend((1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1))
inverse_bind_accessor = accessor(struct.pack(f"<{len(inverse_bind)}f", *inverse_bind), 5126, "MAT4", len(bone_specs))

nodes = [{"name": "MannequinMesh", "mesh": 0, "skin": 0}]
for index, (name, parent, translation) in enumerate(bone_specs):
    children = [child + 1 for child, spec in enumerate(bone_specs) if spec[1] == index]
    node = {"name": name, "translation": list(translation)}
    if children:
        node["children"] = children
    nodes.append(node)

document = {
    "asset": {"version": "2.0", "generator": "DressMe synthetic rig fixture"},
    "scene": 0,
    "scenes": [{"nodes": [0, 1]}],
    "nodes": nodes,
    "meshes": [{"name": "Neutral synthetic mannequin", "primitives": [{
        "attributes": {"POSITION": position_accessor, "JOINTS_0": joints_accessor, "WEIGHTS_0": weights_accessor},
        "indices": indices_accessor,
        "material": 0,
    }]}],
    "skins": [{"name": "Synthetic test skeleton", "inverseBindMatrices": inverse_bind_accessor, "skeleton": 1, "joints": list(range(1, len(bone_specs) + 1))}],
    "materials": [{"name": "Neutral test material", "pbrMetallicRoughness": {"baseColorFactor": [0.42, 0.53, 0.46, 1], "metallicFactor": 0, "roughnessFactor": 0.9}}],
    "buffers": [{"byteLength": len(binary)}],
    "bufferViews": buffer_views,
    "accessors": accessors,
}
json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
json_chunk += b" " * ((-len(json_chunk)) % 4)
binary.extend(b"\x00" * ((-len(binary)) % 4))
total = 12 + 8 + len(json_chunk) + 8 + len(binary)
OUT.write_bytes(
    struct.pack("<4sII", b"glTF", 2, total)
    + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
    + struct.pack("<I4s", len(binary), b"BIN\x00") + binary
)
print(f"Wrote {OUT} ({total} bytes, {len(bone_specs)} joints, {len(positions)} vertices)")
