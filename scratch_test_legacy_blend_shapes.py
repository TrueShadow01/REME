r"""Synthetic checks for legacy RE Engine blend-shape import.

Run from the parent folder of this repo or from inside D:\REME:

    python scratch_test_legacy_blend_shapes.py
"""

from __future__ import annotations

import io
import os
import struct
import sys
import types

import numpy as np


def _ensure_package_import():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(repo_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    if "REME" not in sys.modules:
        pkg = types.ModuleType("REME")
        pkg.__path__ = [repo_dir]
        sys.modules["REME"] = pkg


_ensure_package_import()

from REME.modules.mesh import file_re_mesh as mesh_file  # noqa: E402
from REME.modules.mesh import re_mesh_parse as mesh_parse  # noqa: E402


def test_legacy_blend_header_uses_compact_layout():
    stream = io.BytesIO(bytearray(160))
    stream.seek(0)
    stream.write(bytes([1]))
    stream.write((0x123456789ABC).to_bytes(7, byteorder="little"))
    stream.write(struct.pack("<Q", 16))
    stream.seek(16)
    stream.write(struct.pack("<Q", 32))
    stream.seek(32)
    stream.write(struct.pack("<HHIIIQQ", 1, 0, 0, 0, 0, 64, 80))
    stream.seek(64)
    stream.write(struct.pack("<IIHHI", 3, 5, 0, 2, 0))
    stream.seek(80)
    # AABB min/max.
    stream.write(struct.pack("<4f4f", -1.0, -2.0, -3.0, 0.0, 1.0, 2.0, 3.0, 0.0))
    stream.write(struct.pack("<3i", 5, 6, 7))
    stream.write(struct.pack("<2i", 10, 11))

    stream.seek(0)
    header = mesh_file.BlendShapeHeader()
    header.read(stream, mesh_file.VERSION_RE8)

    assert header.count == 1
    data = header.blendShapeList[0]
    assert data.targetCount == 1
    assert data.blendS == [5, 6, 7]
    assert data.blendSSList == [10, 11]
    target = data.blendTargetList[0]
    assert target.subMeshVertexStartIndex == 3
    assert target.vertCount == 5
    assert target.blendShapeNum == 2


def test_legacy_delta_unpack_and_aabb_remap():
    packed = np.array([2047 | (511 << 11) | (0 << 21)], dtype="<u4").tobytes()
    normalized = mesh_parse.ReadBlendShapeByteBuffer(packed, set())

    box = mesh_file.AABB()
    box.min.x = -1.0
    box.min.y = -2.0
    box.min.z = -3.0
    box.max.x = 1.0
    box.max.y = 2.0
    box.max.z = 3.0

    remapped = mesh_parse.remapBlendShapeDeltas(normalized, box)
    expected = np.array([[1.0, -0.001955, -3.0]], dtype=np.float32)
    assert np.allclose(remapped, expected, atol=1e-5), remapped


def main():
    tests = [
        test_legacy_blend_header_uses_compact_layout,
        test_legacy_delta_unpack_and_aabb_remap,
    ]
    for test in tests:
        test()
        print(f"[PASS] {test.__name__}")
    print("\nAll legacy blend-shape checks passed.")


if __name__ == "__main__":
    main()
