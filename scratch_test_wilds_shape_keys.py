r"""Synthetic checks for PR #24 Wilds shape-key coordinate handling.

Run from the parent folder of this repo or from inside D:\REME:

    python scratch_test_wilds_shape_keys.py

These tests do not need Blender or MH Wilds files. They only check whether the
new shape-key code mixes global RE mesh indices with Blender object-local
shape-key arrays.
"""

from __future__ import annotations

import os
import sys
import types
from types import SimpleNamespace

import numpy as np


def _ensure_package_import():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(repo_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    # Avoid executing REME/__init__.py, which imports Blender's bpy. The mesh
    # modules only need package context for their relative imports.
    if "REME" not in sys.modules:
        pkg = types.ModuleType("REME")
        pkg.__path__ = [repo_dir]
        sys.modules["REME"] = pkg


_ensure_package_import()

from REME.modules.mesh import file_re_mesh as mesh_file  # noqa: E402
from REME.modules.mesh import re_mesh_parse as mesh_parse  # noqa: E402


def _aabb():
    box = mesh_file.AABB()
    box.min.x = -1.0
    box.min.y = -1.0
    box.min.z = -1.0
    box.max.x = 1.0
    box.max.y = 1.0
    box.max.z = 1.0
    return box


def test_export_reexport_uses_global_start_for_local_deltas():
    """Current PR behavior should fail this check.

    A Blender object's shape-key deltas are local to that object, so a 3-vertex
    object has delta indices 0..2. The imported Wilds metadata can still record
    subMeshVertexStartIndex=100 because that is where this submesh starts in the
    full RE mesh buffer. The faithful re-export path currently slices
    deltas[100:103], which returns an empty segment and then zero-pads it.
    """

    captured_segments = []
    original_pack = mesh_file.packBlendShapeDeltasStride8

    def capture_pack(delta_array, aabb, normals=None):
        captured_segments.append(np.asarray(delta_array, dtype=np.float32).copy())
        return np.zeros((len(delta_array), 2), dtype="<u4")

    mesh_file.packBlendShapeDeltasStride8 = capture_pack
    try:
        shape = mesh_parse.BlendShape()
        shape.blendShapeName = "Smile"
        shape.deltas = np.array(
            [
                [0.25, 0.0, 0.0],
                [0.50, 0.0, 0.0],
                [0.75, 0.0, 0.0],
            ],
            dtype=np.float32,
        )

        submesh = mesh_parse.SubMesh()
        submesh.vertexPosList = [(0.0, 0.0, 0.0)] * 3
        submesh.blendShapeList = [shape]
        submesh.wildsBlendMeta = {
            "typing": 7,
            "blendS": [0, 0, 0],
            "targets": [
                {
                    "blendShapeNum": 1,
                    "names": ["Smile"],
                    "aabbMin": [-1.0, -1.0, -1.0],
                    "aabbMax": [1.0, 1.0, 1.0],
                    # start=100 simulates a nonzero global RE vertex-buffer start.
                    # vertOffset=0 is the local/target-region offset.
                    "subEntries": [[100, 0, 3]],
                }
            ],
        }

        viscon = mesh_parse.VisconGroup()
        viscon.subMeshList = [submesh]
        lod = mesh_parse.LODLevel()
        lod.visconGroupList = [viscon]
        parsed = mesh_parse.ParsedREMesh()
        parsed.mainMeshLODList = [lod]

        sub_data = SimpleNamespace(vertexStartIndex=100)
        mesh_file.buildWildsBlendShapeExport(parsed, {submesh: sub_data})
    finally:
        mesh_file.packBlendShapeDeltasStride8 = original_pack

    expected = shape.deltas
    actual = captured_segments[0]
    if np.allclose(actual, expected):
        return True, "export re-export slice kept the local shape-key deltas"
    return (
        False,
        "export re-export slice did not keep local deltas; likely used global "
        f"subMeshVertexStartIndex. Captured segment:\n{actual}",
    )


def test_streamed_decode_multi_submesh_target_chooses_nonzero_submesh():
    """Current PR behavior should fail this check.

    The original streamed Wilds path calls decodeTarget(..., splitBySubmesh=False).
    For a target whose first subentry is zero padding and whose later subentry
    carries the actual morph, that stores the combined shape under only baseStart.
    The resident path uses splitBySubmesh=True to attach the shape to the submesh
    whose slice carries the real deltas.
    """

    sm_a = SimpleNamespace(subMeshVertexStartIndex=0, vertCount=2)
    sm_b = SimpleNamespace(subMeshVertexStartIndex=2, vertCount=2)

    target = SimpleNamespace(
        blendShapeNum=1,
        blendSSIndex=0,
        subMeshEntryList=[sm_a, sm_b],
    )
    bs_data = SimpleNamespace(
        typing=7,
        blendTargetList=[target],
        aabbList=[_aabb()],
        blendS=[0, 0, 0],
    )
    blend_header = SimpleNamespace(blendShapeList=[bs_data])

    pos_elem = SimpleNamespace(posStartOffset=0, stride=12)
    normal_elem = SimpleNamespace(posStartOffset=48, stride=8)
    last_elem = normal_elem

    # Four vertices. Element layout makes endOfElements = 48 + 4*8 = 80.
    geometry = b"\x00" * 80

    def pack_delta(x):
        # For AABB [-1, 1], x=0.5 maps to normalized 0.75.
        xi = int(round(((x + 1.0) / 2.0) * 2047.0))
        yi = int(round(0.5 * 1023.0))
        zi = int(round(0.5 * 2047.0))
        return xi | (yi << 11) | (zi << 21)

    # First submesh is zero padding, second submesh carries the actual morph.
    packed = np.array(
        [pack_delta(0.0), pack_delta(0.0), pack_delta(0.75), pack_delta(1.0)],
        dtype="<u4",
    ).tobytes()

    stream_entry = SimpleNamespace(
        vertexBuffer=geometry + packed,
        vertexElementList=[pos_elem, normal_elem, last_elem],
        unkn9=80,
    )
    mbh = SimpleNamespace(
        streamingBufferHeaderList=[stream_entry],
        vertexElementList=[SimpleNamespace(posStartOffset=0)],
        vertexBuffer=b"",
    )
    re_mesh = SimpleNamespace(
        blendShapeHeader=blend_header,
        meshBufferHeader=mbh,
        blendShapeNameRemapList=[0],
        rawNameList=["Smile"],
    )

    decoded = mesh_parse._decodeWildsBlendShapes(re_mesh)
    lod0 = decoded.get(0, {})
    if sorted(lod0.keys()) == [2]:
        return True, "streamed decode attached the target to the nonzero submesh"
    return (
        False,
        "streamed decode did not attach the target to the nonzero submesh. "
        f"Decoded keys were {sorted(lod0.keys())}; expected [2].",
    )


def main():
    tests = [
        (
            "export faithful re-export should use object-local delta indices",
            test_export_reexport_uses_global_start_for_local_deltas,
        ),
        (
            "streamed multi-submesh decode should choose the nonzero submesh",
            test_streamed_decode_multi_submesh_target_chooses_nonzero_submesh,
        ),
    ]

    failures = 0
    for name, test_func in tests:
        ok, detail = test_func()
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        print(f"       {detail}")
        if not ok:
            failures += 1

    if failures:
        print(f"\n{failures} synthetic check(s) failed.")
        raise SystemExit(1)
    print("\nAll synthetic checks passed.")


if __name__ == "__main__":
    main()
