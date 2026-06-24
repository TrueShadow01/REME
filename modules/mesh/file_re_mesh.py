# Author: NSA Cloud
# Credit to AsteriskAmpersand for original re mesh addon that I used for reference
# Also credit to AlphaZomega for noesis re mesh plugin and re mesh 010 template

import ctypes
import os
import struct
import time
from io import BytesIO
from itertools import chain

import numpy as np

from ..gen_functions import (
    getBit,
    getPaddedPos,
    getPaddingAmount,
    raiseError,
    raiseWarning,
    read_byte,
    read_float,
    read_int,
    read_int64,
    read_short,
    read_string,
    read_ubyte,
    read_uint,
    read_uint64,
    read_unicode_string,
    read_ushort,
    setBit,
    splitNativesPath,
    textColors,
    write_byte,
    write_float,
    write_int,
    write_int64,
    write_short,
    write_string,
    write_ubyte,
    write_uint,
    write_uint64,
    write_unicode_string,
    write_ushort,
)
from .file_re_mesh_mply import REMeshMPLY

# How mesh import/export works:
# 1. The mesh file is imported in it's original structure and layout in this file (file_re_mesh.py)
# 2. The mesh structure is converted into an intermediary parsed format in re_mesh_parse.py
# 3. The parsed mesh format is passed to blender to be imported by blender_re_mesh.py
# 4. For export in blender, the mesh is checked for errors or things that otherwise wont work in the mesh format
# 5. The parsed mesh format is rebuilt inside blender_re_mesh.py once it has been error checked
# 6. The parsed format is passed back to file_re_mesh.py and rebuilt into a mesh structure (ParsedREMeshToREMesh())

IMPORT_BLEND_SHAPES = False  # Legacy (SF6 and earlier) blend shape import is still broken; keep disabled.

# MH Wilds blend shape EXPORT. The engine reads blend deltas from the streaming buffer, so this only
# works alongside EXPORT_WILDS_STREAMING: convertToStreamedWilds writes the deltas into each LOD's
# streaming entry tail (after the declared geometry), keeping the base file clean. Stage B.
# Isolation test confirmed: geometry-only (no blend) loads fine; the crash is the blend structure.
EXPORT_WILDS_BLEND_SHAPES = True

# Debug: force a specific BlendShapeData.typing value (0 = use captured/meta typing, then the
# nTargets-based rule). The faithful-rebuild path now carries the original typing in its metadata,
# so this is left 0; set non-zero only to experiment.
EXPORT_WILDS_DEBUG_FORCE_TYPING = 0

# Debug: when True, export blend shapes with NO normal-recalc section (normalRecalcOffset=0, no tail
# table). Tests whether the engine simply skips the normal-recalc pass when absent — if blend loads
# without it, custom geometry never needs the (unreversed) adjacency format generated.
EXPORT_WILDS_DEBUG_NO_NORMALRECALC = False

# Debug: when True, the resident base buffer is a small distinct stub (a handful of verts) instead of
# a full copy of the streamed LOD0. The original keeps its lowest LOD (smaller than the blend region)
# resident, so the blend loader targets the streamed entry, not the resident. A full LOD0 copy gets
# pulled into the blend path and crashes. Geometry is rendered from the streamed entry (vbi>=1).
EXPORT_WILDS_DEBUG_SMALL_BASE = True

# Temporary: prints a preview of the per-LOD streaming split during export (no file changes) so the
# split logic can be validated against the original via the Dump button before the write is wired.
DEBUG_STREAMING_BUILD = True

# Debug: when True, export only the FIRST blend target (drop the rest). Used to isolate the in-game
# crash to single-target first; single-target is now confirmed working in-game, so multi-target
# (one target per blend submesh) is enabled by setting this False.
EXPORT_WILDS_DEBUG_FIRST_TARGET_ONLY = False

# Debug: when True, export blend shapes for only the LAST submesh that has them (drop the others).
# Confirmed: the runtime's get_BlendShapeChannelNum reports joint-correction channels (defined
# externally, by the skeleton/motion system), NOT the mesh's blend targets — so editing the mesh's
# blend section never changes that count. The mesh's targets only supply deltas correctives look up
# by name. Keep False so the body submesh's 12 corrective-named targets are all exported (the override
# test below drives them via their existing pose-driven channels).
EXPORT_WILDS_DEBUG_LAST_SUBMESH_ONLY = False

# Debug piggyback test: rename the exported custom morph to exactly match an existing joint-correction
# channel name. Empty string = no rename (keep the real shape-key names so the 12 body correctives stay
# matched to their pose-driven channels for the override test below).
EXPORT_WILDS_DEBUG_PIGGYBACK_NAME = ""

# Debug delta-override test: replace every exported blend shape's deltas with a large uniform offset.
# The 12 body-corrective channels are already pose-driven at runtime (several at weight ~0.9 at rest),
# so if the engine reads its corrective deltas from the mesh, the body submesh will visibly lurch by
# this offset. If the body looks normal, corrective deltas are external and the mesh blend section is
# vestigial for armor. 0 = off; otherwise the per-axis offset in mesh units (meters).
# Result (2026-06-22): body did NOT deform with a forced 0.3 offset on the 12 pose-driven correctives,
# confirming the engine ignores mesh blend deltas for armor entirely. Kept off.
EXPORT_WILDS_DEBUG_OVERRIDE_DELTA_OFFSET = 0

# Stage A: write MH Wilds meshes as the real 2-file streamed layout (geometry moved into a streaming
# companion). Off = the normal single-file INLINE export (all geometry + blend deltas in the base
# file, vbi=0, no streaming companion). Working custom mods are inline single-file and pair with the
# vanilla streaming file, so we go inline and put the blend block + deltas inline too — far simpler
# than the resident-base/streaming apparatus, which is what was crashing.
EXPORT_WILDS_STREAMING = False

# EXPERIMENT (2026-06-23): single-file resident blend. Appends the streamed buffer into the BASE file
# and rebases streamingInfo.bufferStart to in-base offsets, keeping the blend submesh at vbi=N.
# SUPERSEDED by the REFramework recon (2026-06-23): vbi=N is resolved via DirectStorage/pak by hash+offset
# into the PACKAGE, never from the base file — so the engine ignores these in-base bytes (and a changed
# base streaming layout can make the DStorage read grab mismatched package data → crash). The correct
# single-file path is vbi=0 (resident -> in_memory_buffer_ptr -> base buffer); we already know vbi=0
# GEOMETRY renders from the base. The open question is whether the morph delta-fetch accepts a vbi=0 buffer
# and which offset field locates the deltas within it — pending the runtime hook before a correct vbi=0
# build. Leaving this flag (default False) for reference; do NOT rely on it. See [[reme-blendshape-export-fields]].
EXPORT_WILDS_RESIDENT_BLEND = False

# EXPERIMENT Phase 2 (2026-06-23): fixed/resident blendshape buffer. Per the REFramework recon, MH Wilds
# splits blend deltas into a streaming buffer (DStorage/pak, unmoddable) vs a FIXED buffer (resident,
# in_memory_buffer_ptr, in the base file). No shipped mesh uses the fixed buffer, but the API is live
# (get_BlendShapeFixBufferSize). This mode authors a single-LOD base where the blend submesh's geometry
# AND delta tail live in the resident buffer (vbi=0, which the engine reads from the base — proven for
# geometry), described by ONE streaming-buffer-header entry with word11(vbi)=0 and word9=deltaStart, and
# streamingInfo.bufferStart pointing at that resident buffer inside the base. HYPOTHESIS: the engine's
# blend-size pass counts a vbi=0 entry's (vbl-word9) as FIX and reads deltas from the base. Validate by
# loading + reading get_BlendShapeFixBufferSize (should become >0) and force-driving a channel. Requires
# single-LOD input (export with "Export All LODs" OFF). See [[reme-wilds-engine-load-paths]].
EXPORT_WILDS_FIX_BUFFER = False

# MH Wilds-era meshes (by raw file version) use a different, working blend shape decode and are
# always imported regardless of IMPORT_BLEND_SHAPES. Other games stay gated by the flag above.
WILDS_PACKED_BLEND_SHAPE_FILE_VERSIONS = frozenset(
    [
        240820143,  # VERSION_MHWILDS_BETA
        241111606,  # VERSION_MHWILDS
        250604100,  # VERSION_MHS3
    ]
)

# Meshes to test blend shapes with:
# MHR player face "F:\MHR_EXTRACT\extract\re_chunk_000\natives\STM\player\mod\face\pl_face000.mesh.2109148288"
# RE4R leon face "I:\RE4_EXTRACT\re_chunk_000\natives\STM\_Chainsaw\Character\ch\cha0\cha000\10\cha000_10.mesh.221108797"
# SF6 chun li body "J:\SF6_EXTRACT\re_chunk_000\natives\stm\product\model\esf\esf004\001\01\esf004_001_01.mesh.230110883"

IMPORT_MPLY = True
# Not implemented fully yet, need to figure out unkn struct and how meshlets get positioned


timeFormat = "%d"
# Mesh version numbers do not always increase for newer versions of the file format
# Therefore mesh versions have been remapped to new values to allow for conditional import and export changes depending on the mesh version

# Leaving gaps in case the versions in between these need to be parsed
VERSION_DMC5 = 75  # file:1808282334,internal:386270720
VERSION_RE2 = 80  # file:1808312334,internal:386270720
VERSION_RE3 = 85  # file:1902042334,internal:21011200
VERSION_RE8 = 90  # file:2101050001,internal:2020091500
VERSION_RERT = 95  # file:2109108288,internal:21041600
VERSION_RE7RT = 96  # file:220128762,internal:21041600
VERSION_MHRSB = 100  # file:2109148288,internal:21091000
VERSION_SF6 = 105  # file:230110883,internal:220705151
VERSION_RE4 = 110  # file:221108797,internal:220822879
VERSION_DD2 = 115  # file:230517984,internal:230517984
VERSION_KG = 120  # file:240306278,internal:230727984
VERSION_DD2NEW = 124  # file:240423143,internal:230517984
VERSION_DR = 125  # file:240424828,internal:240423829
# VERSION_MHWILDS = 130#file:240820143,internal:240704828# beta
VERSION_ONI2 = 127  # file:240827123,internal:240827123
VERSION_MHWILDS = 130  # file:241111606,internal:240704828
VERSION_PRAGDEMO = 135  # file:250925211,internal:250707828
VERSION_MHS3 = 136  # file:250604100,internal:250203152
VERSION_RE9 = 140  # file:250925211,internal:250707828#RE9 Placeholder

SIX_WEIGHT_GAMES = frozenset(
    [
        VERSION_SF6,
        VERSION_MHWILDS,
        VERSION_MHS3,
        VERSION_PRAGDEMO,
    ]
)

meshFileVersionToNewVersionDict = {
    1808282334: VERSION_DMC5,
    1808312334: VERSION_RE2,
    1902042334: VERSION_RE3,
    2101050001: VERSION_RE8,
    2102020001: VERSION_RE8,  # RE VERSE
    2109108288: VERSION_RERT,
    220128762: VERSION_RE7RT,
    2109148288: VERSION_MHRSB,
    230110883: VERSION_SF6,
    221108797: VERSION_RE4,
    231011879: VERSION_DD2,
    240306278: VERSION_KG,
    240423143: VERSION_DD2NEW,
    240424828: VERSION_DR,
    240820143: VERSION_MHWILDS,
    240827123: VERSION_ONI2,
    241111606: VERSION_MHWILDS,
    250604100: VERSION_MHS3,
    # 250925211:VERSION_PRAGDEMO,
    250925211: VERSION_RE9,
}
newVersionToMeshFileVersion = {
    VERSION_DMC5: 1808282334,
    VERSION_RE2: 1808312334,
    VERSION_RE3: 1902042334,
    VERSION_RE8: 2101050001,
    VERSION_RERT: 2109108288,
    VERSION_RE7RT: 220128762,
    VERSION_MHRSB: 2109148288,
    VERSION_SF6: 230110883,
    VERSION_RE4: 221108797,
    VERSION_DD2: 231011879,
    VERSION_KG: 240306278,
    VERSION_DD2NEW: 240423143,
    VERSION_DR: 240424828,
    VERSION_ONI2: 240820143,
    VERSION_MHWILDS: 241111606,
    VERSION_MHS3: 250604100,
    # VERSION_PRAGDEMO:250925211,
    VERSION_RE9: 250925211,
}
meshFileVersionToInternalVersionDict = {
    1808282334: 386270720,  # VERSION_DMC5
    1808312334: 386270720,  # VERSION_RE2
    1902042334: 21011200,  # VERSION_RE3
    2101050001: 2020091500,  # VERSION_RE8
    2109108288: 21041600,  # VERSION_RERT
    2109148288: 21091000,  # VERSION_MHRSB
    230110883: 220705151,  # VERSION_SF6
    221108797: 220822879,  # VERSION_RE4
    231011879: 230517984,  # VERSION_DD2
    240306278: 230727984,  # VERSION_KG
    240423143: 230517984,  # VERSION_DD2NEW
    240424828: 240423829,  # VERSION_DR
    240820143: 240704828,  # VERSION_MHWILDS
    240827123: 240704828,  # VERSION_ONI2
    241111606: 240704828,  # VERSION_MHWILDS
    250604100: 250203152,  # VERSION_MHS3
    # 250925211:250707828,#VERSION_PRAGDEMO
    250925211: 250904410,  # VERSION_RE9
}
internalVersionToMeshFileVersionDict = {
    386270720: 1808282334,  # VERSION_DMC5
    # 386270720:1808312334,#VERSION_RE2
    21011200: 1902042334,  # VERSION_RE3
    2020091500: 2101050001,  # VERSION_RE8
    21041600: 2109108288,  # VERSION_RERT
    21091000: 2109148288,  # VERSION_MHRSB
    220705151: 230110883,  # VERSION_SF6
    220822879: 221108797,  # VERSION_RE4
    # 230517984:231011879,#VERSION_DD2
    230727984: 240306278,  # VERSION_KG
    230517984: 240423143,  # VERSION_DD2NEW
    240423829: 240424828,  # VERSION_DR
    # 240704828:240820143,#VERSION_MHWILDSBETA
    240704828: 240820143,  # VERSION_ONI2
    240704828: 241111606,  # VERSION_MHWILDS
    250203152: 250604100,  # VERSION_MHS3
    250707828: 250925211,  # VERSION_PRAGDEMO
    250904410: 250925211,  # VERSION_RE9
}
meshFileVersionToGameNameDict = {
    1808282334: "DMC5",  # VERSION_DMC5
    1808312334: "RE2",  # VERSION_RE2
    1902042334: "RE3",  # VERSION_RE3
    2101050001: "RE8",  # VERSION_RE8
    2102020001: "RE8",  # RE VERSE
    2109108288: "RE2RT",  # VERSION_RERT
    220128762: "RE7RT",  # VERSION_RE7RT
    2109148288: "MHRSB",  # VERSION_MHRSB
    230110883: "SF6",  # VERSION_SF6
    221108797: "RE4",  # VERSION_RE4
    231011879: "DD2",  # VERSION_DD2
    240306278: "KG",  # VERSION_KG
    240423143: "DD2",  # VERSION_DD2NEW
    240424828: "DR",  # VERSION_DR
    240820143: "MHWILDS",  # VERSION_MHWILDSBETA
    240827123: "ONI2",  # VERSION_ONI2
    241111606: "MHWILDS",  # VERSION_MHWILDS
    250604100: "MHS3",  # VERSION_MHS3
    # 250925211:"PRAG",#VERSION_PRAGDEMO
    250925211: "RE9",  # VERSION_RE9
}


# Used for unmapped mesh versions, potentially allows for importing
def getNearestRemapVersion(
    meshVersion,
):  # Returns the remapped version number of the closest mesh version
    return meshFileVersionToNewVersionDict[
        min(meshFileVersionToNewVersionDict.keys(), key=lambda x: abs(x - meshVersion))
    ]


c_uint64 = ctypes.c_uint64


class CompressedSixWeightIndices_bits(ctypes.LittleEndianStructure):
    _fields_ = [
        ("w0", c_uint64, 10),
        ("w1", c_uint64, 10),
        ("w2", c_uint64, 10),
        ("pad0", c_uint64, 2),
        ("w3", c_uint64, 10),
        ("w4", c_uint64, 10),
        ("w5", c_uint64, 10),
        ("pad1", c_uint64, 2),
    ]


class CompressedSixWeightIndices(ctypes.Union):
    _anonymous_ = ("weights",)
    _fields_ = [("weights", CompressedSixWeightIndices_bits), ("asUInt64", c_uint64)]


c_uint32 = ctypes.c_uint32


class CompressedBlendShapeVertexInt_bits(ctypes.LittleEndianStructure):
    _fields_ = [
        ("x", c_uint32, 11),
        ("y", c_uint32, 10),
        ("z", c_uint32, 11),
    ]


class CompressedBlendShapeVertexInt(ctypes.Union):
    _anonymous_ = ("pos",)
    _fields_ = [("pos", CompressedBlendShapeVertexInt_bits), ("asUInt32", c_uint32)]


class Vec3:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0

    def read(self, file):
        self.x = read_float(file)
        self.y = read_float(file)
        self.z = read_float(file)

    def write(self, file):
        write_float(file, self.x)
        write_float(file, self.y)
        write_float(file, self.z)


class Vec4:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.w = 0.0

    def read(self, file):
        self.x = read_float(file)
        self.y = read_float(file)
        self.z = read_float(file)
        self.w = read_float(file)

    def write(self, file):
        write_float(file, self.x)
        write_float(file, self.y)
        write_float(file, self.z)
        write_float(file, self.w)


class Sphere:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.r = 0.0

    def read(self, file):
        self.x = read_float(file)
        self.y = read_float(file)
        self.z = read_float(file)
        self.r = read_float(file)

    def write(self, file):
        write_float(file, self.x)
        write_float(file, self.y)
        write_float(file, self.z)
        write_float(file, self.r)


class Matrix4x4:
    def __init__(self):
        self.matrix = [
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ]

    def read(self, file):
        self.matrix = np.frombuffer(file.read(64), dtype="<4f").tolist()

    def write(self, file):
        for row in self.matrix:
            for val in row:
                write_float(file, val)


class AABB:
    def __init__(self):
        self.min = Vec4()
        self.max = Vec4()

    def read(self, file):
        self.min.read(file)
        self.max.read(file)

    def write(self, file):
        self.min.write(file)
        self.max.write(file)


class MaterialSubdivision:
    def __init__(self):
        self.materialIndex = 0
        self.isQuad = 0
        self.vertexBufferIndex = 0
        self.padding = 0
        self.dr_unkn0 = 0
        self.faceCount = 0
        self.faceStartIndex = 0
        self.vertexStartIndex = 0
        self.streamingOffsetBytes = 0
        self.streamingPlatormSpecificOffsetBytes = 0
        self.dr_unkn1 = 0

    def read(self, file, version):
        self.materialIndex = read_ubyte(file)
        self.isQuad = read_ubyte(file)
        self.vertexBufferIndex = read_ubyte(file)
        self.padding = read_ubyte(file)
        if version >= VERSION_DR:
            self.dr_unkn0 = read_uint(file)
        self.faceCount = read_uint(file)
        self.faceStartIndex = read_uint(file)
        self.vertexStartIndex = read_uint(file)
        if version >= VERSION_RE8:
            self.streamingOffsetBytes = read_uint(file)
            self.streamingPlatormSpecificOffsetBytes = read_uint(file)
        if version >= VERSION_DD2NEW:
            self.dr_unkn1 = read_uint(file)

    def write(self, file, version):
        write_ubyte(file, self.materialIndex)
        write_ubyte(file, self.isQuad)
        write_ubyte(file, self.vertexBufferIndex)
        write_ubyte(file, self.padding)
        if version >= VERSION_DR:
            write_uint(file, self.dr_unkn0)
        write_uint(file, self.faceCount)
        write_uint(file, self.faceStartIndex)
        write_uint(file, self.vertexStartIndex)
        if version >= VERSION_RE8:
            write_uint(file, self.streamingOffsetBytes)
            write_uint(file, self.streamingPlatormSpecificOffsetBytes)
        if version >= VERSION_DD2NEW:
            write_uint(file, self.dr_unkn1)


class MeshGroup:
    def __init__(self):
        self.visconGroupID = 0
        self.meshCount = 0
        self.null0 = 0
        self.null1 = 0
        self.null2 = 0
        self.vertexCount = 0
        self.faceCount = 0
        self.vertexInfoList = []

    def read(self, file, version):
        self.visconGroupID = read_ubyte(file)
        self.meshCount = read_ubyte(file)
        self.null0 = read_ushort(file)
        self.null1 = read_ushort(file)
        self.null2 = read_ushort(file)
        self.vertexCount = read_uint(file)
        self.faceCount = read_uint(file)
        for i in range(0, self.meshCount):
            entry = MaterialSubdivision()
            entry.read(file, version)
            self.vertexInfoList.append(entry)

    def write(self, file, version):
        write_ubyte(file, self.visconGroupID)
        write_ubyte(file, self.meshCount)
        write_ushort(file, self.null0)
        write_ushort(file, self.null1)
        write_ushort(file, self.null2)
        write_uint(file, self.vertexCount)
        write_uint(file, self.faceCount)
        for entry in self.vertexInfoList:
            entry.write(file, version)


class LODGroupHeader:
    def __init__(self):
        self.count = 0
        self.vertexFormat = 0
        self.reserved = 0
        self.distance = 0
        self.offsetOffset = 0
        self.meshGroupOffsetList = []
        # padding align 16
        self.meshGroupList = []

    def read(self, file, version):
        self.count = read_ubyte(file)
        self.vertexFormat = read_ubyte(file)
        self.reserved = read_ushort(file)
        self.distance = read_float(file)
        self.offsetOffset = read_uint64(file)
        for i in range(0, self.count):
            self.meshGroupOffsetList.append(read_uint64(file))
        file.seek(getPaddedPos(file.tell(), 16))
        for i in range(0, self.count):
            entry = MeshGroup()
            entry.read(file, version)
            self.meshGroupList.append(entry)

    def write(self, file, version):
        write_ubyte(file, self.count)
        write_ubyte(file, self.vertexFormat)
        write_ushort(file, self.reserved)
        write_float(file, self.distance)
        write_uint64(file, self.offsetOffset)
        for entry in self.meshGroupOffsetList:
            write_uint64(file, entry)
        file.seek(getPaddedPos(file.tell(), 16))
        for entry in self.meshGroupList:
            entry.write(file, version)


class MainMeshHeader:
    def __init__(self):
        self.lodGroupCount = 0
        self.materialCount = 0
        self.uvCount = 0
        self.skinWeightCount = 18
        self.totalMeshCount = 0
        self.has32BitIndexBuffer = 0
        self.sharedLodBits = 0
        self.nullPadding = 0  # PRE RE8
        self.sphere = Sphere()
        self.bbox = AABB()
        self.offsetOffset = 0
        self.lodGroupOffsetList = []
        self.lodGroupList = []
        # padding align 16

    def read(self, file, version, lodTarget=None):
        self.lodGroupCount = read_byte(file)
        self.materialCount = read_byte(file)
        self.uvCount = read_byte(file)
        self.skinWeightCount = read_byte(file)
        self.totalMeshCount = read_ushort(file)
        self.has32BitIndexBuffer = read_byte(file)
        self.sharedLodBits = read_ubyte(file)
        if version < VERSION_RE8:
            self.nullPadding = read_uint64(file)
        self.sphere.read(file)
        self.bbox.read(file)
        self.offsetOffset = read_uint64(file)
        self.lodGroupOffsetList = []
        for i in range(0, self.lodGroupCount):
            self.lodGroupOffsetList.append(read_uint64(file))
        self.lodGroupList = []
        startPos = file.tell()

        if lodTarget is not None:
            lodTarget = abs(lodTarget)
            if (
                lodTarget >= self.lodGroupCount
            ):  # If the chosen LOD target isn't on the mesh, use the lowest quality LOD possible
                lodTarget = self.lodGroupCount - 1
        for lodIndex, offset in enumerate(self.lodGroupOffsetList):
            if (
                lodTarget is None or lodTarget == lodIndex
            ):  # Read only the target lod if specified
                file.seek(offset)
                entry = LODGroupHeader()
                entry.read(file, version)
                self.lodGroupList.append(entry)
        file.seek(startPos)
        file.seek(getPaddedPos(file.tell(), 16))

    def write(self, file, version):
        write_byte(file, self.lodGroupCount)
        write_byte(file, self.materialCount)
        write_byte(file, self.uvCount)
        write_byte(file, self.skinWeightCount)
        write_ushort(file, self.totalMeshCount)
        write_byte(file, self.has32BitIndexBuffer)
        write_ubyte(file, self.sharedLodBits)
        if version < VERSION_RE8:
            write_uint64(file, self.nullPadding)
        self.sphere.write(file)
        self.bbox.write(file)
        write_uint64(file, self.offsetOffset)
        for entry in self.lodGroupOffsetList:
            write_uint64(file, entry)
        file.seek(getPaddedPos(file.tell(), 16))
        for entry in self.lodGroupList:
            entry.write(file, version)


class ShadowHeader:
    def __init__(self):
        self.lodGroupCount = 0
        self.materialCount = 0
        self.uvCount = 0
        self.skinWeightCount = 18
        self.totalMeshCount = 0
        self.nullPadding = 0
        self.offsetOffset = 0
        self.null0 = 0
        self.null1 = 0
        self.null2 = 0
        self.null3 = 0
        self.null4 = 0
        self.null5 = 0
        self.lodGroupOffsetList = []
        self.lodGroupList = []

    def read(self, file, version):
        self.lodGroupCount = read_byte(file)
        self.materialCount = read_byte(file)
        self.uvCount = read_byte(file)
        self.skinWeightCount = read_byte(file)
        self.totalMeshCount = read_uint(file)
        if version < VERSION_RE8:
            self.nullPadding = read_uint64(file)
        self.offsetOffset = read_uint64(file)
        self.null0 = read_uint64(file)
        self.null1 = read_uint64(file)
        self.null2 = read_uint64(file)
        self.null3 = read_uint64(file)
        self.null4 = read_uint64(file)
        self.null5 = read_uint64(file)

        self.lodGroupOffsetList = []
        for i in range(0, self.lodGroupCount):
            self.lodGroupOffsetList.append(read_uint64(file))
        self.lodGroupList = []

        # Commented out because there's no reason to read it, shadow meshes can only use main mesh lods
        """
		startPos = file.tell()
		for offset in self.lodGroupOffsetList:
			file.seek(offset)
			entry = LODGroupHeader()
			entry.read(file)
			self.lodGroupList.append(entry)
		file.seek(startPos)
		"""
        file.seek(getPaddedPos(file.tell(), 16))

    def write(self, file, version):
        # print(file.tell())
        write_byte(file, self.lodGroupCount)
        write_byte(file, self.materialCount)
        write_byte(file, self.uvCount)
        write_byte(file, self.skinWeightCount)
        write_uint(file, self.totalMeshCount)
        if version < VERSION_RE8:
            write_uint64(file, self.nullPadding)
        write_uint64(file, self.offsetOffset)
        write_uint64(file, self.null0)
        write_uint64(file, self.null1)
        write_uint64(file, self.null2)
        write_uint64(file, self.null3)
        write_uint64(file, self.null4)
        write_uint64(file, self.null5)
        for entry in self.lodGroupOffsetList:
            write_uint64(file, entry)
        file.seek(getPaddedPos(file.tell(), 16))

        # Shadow meshes can't have unique lods, the game will crash
        """
		#Halfway through writing the exporter I realised lod group offsets can be shared, this is a workaround so that the lod group doesn't get written again if it shouldn't be
		currentPos = file.tell()
		#print(file.tell())
		for index,entry in enumerate(self.lodGroupList):
			if self.lodGroupOffsetList[index] >= currentPos:#If less than current pos, it's a reused offset, do not write
				#print("wrote shadow lod structure")
				entry.write(file)
		"""


# WILDS
class StreamingInfoEntry:
    def __init__(self):
        self.bufferStart = 0
        self.bufferLength = 0

    def read(self, file):
        self.bufferStart = read_uint(file)
        self.bufferLength = read_uint(file)

    def write(self, file):
        write_uint(file, self.bufferStart)
        write_uint(file, self.bufferLength)


class StreamingInfo:
    def __init__(self):
        self.entryCount = 0
        self.unkn1 = 0
        self.entryOffset = 0
        self.streamingInfoEntryList = []

    def read(self, file):
        self.entryCount = read_uint(file)
        self.unkn1 = read_uint(file)
        self.entryOffset = read_uint64(file)

        currentPos = file.tell()
        file.seek(self.entryOffset)
        for i in range(0, self.entryCount):
            entry = StreamingInfoEntry()
            entry.read(file)
            self.streamingInfoEntryList.append(entry)
        file.seek(currentPos)

    def write(self, file):
        write_uint(file, self.entryCount)
        write_uint(file, self.unkn1)
        write_uint64(file, self.entryOffset)


class StreamingBufferHeaderEntry:
    def __init__(self):
        self.unkn0 = 0
        self.totalBufferSize = 0
        self.vertexBufferLength = 0
        self.mainVertexElementCount = 0
        self.vertexElementCount = 0
        self.unpaddedBufferSize = 0
        self.unpaddedBufferSize2 = 0
        self.prag_unknOffset0 = 0
        self.prag_unknOffset1 = 0
        self.unkn7 = 0
        self.unkn8 = 0
        self.unkn9 = 0
        self.unkn10 = 0
        self.unkn11 = 0
        self.unkn12 = 0
        self.unkn13 = 0
        self.nextBufferOffset = 0
        self.unkn15 = 0
        self.vertexBuffer = None
        self.faceBuffer = None
        self.vertexElementList = []

    def read(self, file, version):
        self.unkn0 = read_uint64(file)
        self.totalBufferSize = read_uint(file)
        self.vertexBufferLength = read_uint(file)
        self.mainVertexElementCount = read_ushort(file)
        self.vertexElementCount = read_ushort(file)
        if version >= VERSION_PRAGDEMO:
            self.prag_unknOffset0 = read_uint64(file)
            self.prag_unknOffset1 = read_uint64(file)
        self.unpaddedBufferSize = read_uint(file)
        self.unpaddedBufferSize2 = read_uint(file)
        self.unkn7 = read_uint(file)
        self.unkn8 = read_uint(file)
        self.unkn9 = read_uint(file)
        self.unkn10 = read_uint(file)
        self.unkn11 = read_uint(file)
        self.unkn12 = read_uint(file)
        self.unkn13 = read_uint(file)
        self.nextBufferOffset = read_uint(file)
        self.unkn15 = read_uint(file)

    def write(self, file, version):
        write_uint64(file, self.unkn0)
        write_uint(file, self.totalBufferSize)
        write_uint(file, self.vertexBufferLength)
        write_ushort(file, self.mainVertexElementCount)
        write_ushort(file, self.vertexElementCount)
        if version >= VERSION_PRAGDEMO:
            write_uint64(file, self.prag_unknOffset0)
            write_uint64(file, self.prag_unknOffset1)
        write_uint(file, self.unpaddedBufferSize)
        write_uint(file, self.unpaddedBufferSize2)
        write_uint(file, self.unkn7)
        write_uint(file, self.unkn8)
        write_uint(file, self.unkn9)
        write_uint(file, self.unkn10)
        write_uint(file, self.unkn11)
        write_uint(file, self.unkn12)
        write_uint(file, self.unkn13)
        write_uint(file, self.nextBufferOffset)
        write_uint(file, self.unkn15)


#


class VertexElementStruct:
    def __init__(self):
        self.typing = 0
        self.stride = 0
        self.posStartOffset = 0

    def read(self, file):
        self.typing = read_ushort(file)
        self.stride = read_ushort(file)
        self.posStartOffset = read_uint(file)

    def write(self, file):
        write_ushort(file, self.typing)
        write_ushort(file, self.stride)
        write_uint(file, self.posStartOffset)


class MeshBufferHeader:
    def __init__(self):
        self.vertexElementOffset = 0
        self.vertexBufferOffset = 0
        self.faceBufferOffset = 0
        self.sunbreakOffset = 0
        self.vertexBufferSize = 0
        self.faceBufferSize = 0
        self.mainVertexElementCount = 0
        self.vertexElementCount = 0
        self.prag_unknOffset0 = 0
        self.prag_unknOffset1 = 0
        self.block2FaceBufferOffset = 0
        self.NULL = 0
        self.vertexElementSize = 0  # TODO this field name is not correct
        self.unkn1 = -1
        self.sunbreakSecondUnknown = 0
        self.vertexElementList = []
        self.streamingBufferHeaderList = []  # WILDS
        self.vertexBuffer = bytearray()
        self.faceBuffer = (
            bytearray()
        )  # NOTE: Face buffer is padded to 4 byte alignment per sub mesh
        self.secondaryWeightBuffer = None  # DD2 shape keys
        # SF6
        self.totalBufferSize = 0
        self.sf6unkn0 = 0
        self.streamingVertexElementOffset = 0  # vectorStructSize
        self.sf6unkn2 = 0  # vectorStructOffset #TODO FIX - sf6unkn2 is vertexElementStreamInfoOffset

    def read(self, file, version, streamingHeader=None, streamingBuffer=None):
        self.vertexElementOffset = read_uint64(file)
        self.vertexBufferOffset = read_uint64(file)
        if version < VERSION_SF6:
            self.faceBufferOffset = read_uint64(file)
            if version > VERSION_RE8:
                self.sunbreakOffset = read_uint64(file)
            self.vertexBufferSize = read_uint(file)
            self.faceBufferSize = read_uint(file)
            self.mainVertexElementCount = read_ushort(file)
            self.vertexElementCount = read_ushort(file)
            self.block2FaceBufferOffset = read_uint(file)
            self.NULL = read_uint(file)
            self.vertexElementSize = read_short(file)
            self.unkn1 = read_short(file)
            if version > VERSION_RE8:
                self.sunbreakSecondUnknown = read_uint64(file)
        elif version >= VERSION_SF6:
            self.sunbreakOffset = read_uint64(file)
            self.totalBufferSize = read_uint(file)
            self.vertexBufferSize = read_uint(file)
            self.faceBufferOffset = self.vertexBufferOffset + self.vertexBufferSize
            self.mainVertexElementCount = read_ushort(file)
            self.vertexElementCount = read_ushort(file)
            if version >= VERSION_PRAGDEMO:
                self.prag_unknOffset0 = read_uint64(file)
                self.prag_unknOffset1 = read_uint64(file)
            self.block2FaceBufferOffset = read_uint(file)
            self.faceBufferSize = self.block2FaceBufferOffset - self.vertexBufferSize
            self.NULL = read_uint(file)
            self.vertexElementSize = read_short(file)
            self.unkn1 = read_short(file)
            self.sunbreakSecondUnknown = read_uint64(file)
            self.sf6unkn0 = read_uint64(file)
            self.streamingVertexElementOffset = read_uint64(file)
            self.sf6unkn2 = read_uint64(file)

        if (
            streamingHeader is not None
            and streamingHeader.entryCount != 0
            and streamingBuffer is not None
        ):
            # Made a bit of a miscalculation, this doesn't account for the fact that the vertex buffers can't just be stacked since the elements won't be grouped together correctly
            # Moved into re_mesh_parse

            # print("Merging streamed face buffers...")
            # print(f"Streamed buffer size {len(streamingBuffer)}")
            # elementArrayList = []

            for i in range(0, streamingHeader.entryCount):
                entry = StreamingBufferHeaderEntry()
                entry.read(file, version)
                # print(entry.__dict__)
                streamInfo = streamingHeader.streamingInfoEntryList[i]
                # vertexBytes = streamingBuffer[streamInfo.bufferStart:streamInfo.bufferStart+entry.vertexBufferLength]
                # faceBytes = streamingBuffer[streamInfo.bufferStart+entry.vertexBufferLength:streamInfo.bufferStart+entry.unpaddedBufferSize]
                entry.vertexBuffer = streamingBuffer[
                    streamInfo.bufferStart : streamInfo.bufferStart
                    + entry.vertexBufferLength
                ]
                entry.faceBuffer = streamingBuffer[
                    streamInfo.bufferStart
                    + entry.vertexBufferLength : streamInfo.bufferStart
                    + entry.unpaddedBufferSize
                ]
                # print(f"stream header {i} vertex buffer size: {len(entry.vertexBuffer)}")
                # print(f"stream header {i} face buffer size: {len(entry.faceBuffer)}")
                # entry.faceBuffer = streamingBuffer[streamInfo.bufferStart+entry.vertexBufferLength:entry.nextBufferOffset]

                currentPos = file.tell()
                file.seek(
                    self.streamingVertexElementOffset
                    + (i * getPaddedPos(8 * self.mainVertexElementCount, 16))
                )  # 8 is vertex element size

                # print(f"vertex element {i} start {file.tell()}")
                for j in range(0, self.mainVertexElementCount):
                    element = VertexElementStruct()
                    element.read(file)
                    entry.vertexElementList.append(element)
                file.seek(currentPos)
                # self.vertexBuffer.extend(vertexBytes)
                # self.faceBuffer.extend(faceBytes)

                self.streamingBufferHeaderList.append(entry)

                # print(f"vertex range {i} {streamInfo.bufferStart}:{streamInfo.bufferStart+entry.vertexBufferLength}")
                # print(f"face range {i} {streamInfo.bufferStart+entry.vertexBufferLength}:{streamInfo.bufferStart+entry.unpaddedBufferSize}")

                # print(f"current vertex buffer size {i} {len(self.vertexBuffer)}")
                # print(f"current face buffer size {i} {len(self.faceBuffer)}")

        self.vertexElementList = []
        file.seek(self.vertexElementOffset)
        for i in range(0, self.vertexElementCount):
            entry = VertexElementStruct()
            # print(f"element {i} {file.tell()}")
            entry.read(file)
            self.vertexElementList.append(entry)

        file.seek(self.vertexBufferOffset)
        # print(f"Vertex buffer start {str(file.tell())}")
        self.vertexBuffer.extend(file.read(self.vertexBufferSize))
        # print(f"Vertex buffer end {str(file.tell())}")
        file.seek(self.faceBufferOffset)
        # print(f"Face buffer start {str(file.tell())}")
        self.faceBuffer.extend(file.read(self.faceBufferSize))

        if self.sunbreakOffset != 0:
            if version == VERSION_DD2 or version == VERSION_DD2NEW:
                # Limit this DD2 for now in case it happens to be used in other games for other things
                file.seek(self.sunbreakOffset)
                vertexCount = (
                    self.vertexElementList[1].posStartOffset // 12
                )  # Get amount of vertices from length of position buffer,pos data is 12 bytes
                self.secondaryWeightBuffer = file.read(
                    vertexCount * 16
                )  # Weight data is 16 bytes
                print("Read DD2 secondary weight data")
        # print(f"full face buffer size {len(self.faceBuffer)}")
        # print(f"Face buffer end {str(file.tell())}")

    def write(self, file, version):
        write_uint64(file, self.vertexElementOffset)
        write_uint64(file, self.vertexBufferOffset)
        if version < VERSION_SF6:
            write_uint64(file, self.faceBufferOffset)
            if version > VERSION_RE8:
                write_uint64(file, self.sunbreakOffset)
            write_uint(file, self.vertexBufferSize)
            write_uint(file, self.faceBufferSize)
            write_ushort(file, self.mainVertexElementCount)
            write_ushort(file, self.vertexElementCount)
            write_uint(file, self.block2FaceBufferOffset)
            write_uint(file, self.NULL)
            write_short(file, self.vertexElementSize)
            write_short(file, self.unkn1)
            if version > VERSION_RE8:
                write_uint64(file, self.sunbreakSecondUnknown)
        elif version >= VERSION_SF6:
            write_uint64(file, self.sunbreakOffset)
            write_uint(file, self.totalBufferSize)
            write_uint(file, self.vertexBufferSize)
            write_ushort(file, self.mainVertexElementCount)
            write_ushort(file, self.vertexElementCount)
            if version >= VERSION_PRAGDEMO:
                write_uint64(file, self.prag_unknOffset0)
                write_uint64(file, self.prag_unknOffset1)
            write_uint(file, self.block2FaceBufferOffset)
            write_uint(file, self.NULL)
            write_short(file, self.vertexElementSize)
            write_short(file, self.unkn1)
            write_uint64(file, self.sunbreakSecondUnknown)
            write_uint64(file, self.sf6unkn0)
            write_uint64(file, self.streamingVertexElementOffset)
            write_uint64(file, self.sf6unkn2)

        # TODO WILDS STREAMING INFO WRITE
        for entry in self.vertexElementList:
            entry.write(file)
        file.seek(getPaddedPos(file.tell(), 16))
        file.write(self.vertexBuffer)
        file.seek(getPaddedPos(file.tell(), 16))
        file.write(self.faceBuffer)
        if self.secondaryWeightBuffer is not None:
            file.seek(getPaddedPos(file.tell(), 16))
            file.write(self.secondaryWeightBuffer)


class ContentFlag:  # Short bitflag in header that determines what content the mesh has Ex: Blend shapes, skeleton, etc.
    def __init__(self):
        self.bitFlag = 0
        self.hasUnknFlag16 = False
        self.hasUnknFlag10 = False
        self.hasUnknFlag8 = False  # Always true on MHR
        self.hasGroupPivot = False
        self.hasBlendShape = False
        self.hasSkeleton = False
        self.hasAABB = False

    def parseBitFlag(self):
        self.hasAABB = bool(getBit(self.bitFlag, 0))
        self.hasSkeleton = bool(getBit(self.bitFlag, 1))
        self.hasBlendShape = bool(getBit(self.bitFlag, 2))
        self.hasGroupPivot = bool(getBit(self.bitFlag, 3))
        self.hasUnknFlag8 = bool(getBit(self.bitFlag, 7))
        self.hasUnknFlag10 = bool(getBit(self.bitFlag, 9))
        self.hasUnknFlag16 = bool(getBit(self.bitFlag, 15))

        # print(f"aabb:{self.hasAABB}")
        # print(f"skeleton:{self.hasSkeleton}")
        # print(f"blendshape:{self.hasBlendShape}")
        # print(f"grouppivot:{self.hasGroupPivot}")

    def setBitFlag(
        self,
        hasUnknFlag16,
        hasUnknFlag10,
        hasUnknFlag8,
        hasGroupPivot,
        hasBlendShape,
        hasSkeleton,
        hasAABB,
    ):
        self.bitFlag = 0
        if hasAABB:
            self.bitFlag = setBit(self.bitFlag, 0)
        if hasSkeleton:
            self.bitFlag = setBit(self.bitFlag, 1)
        if hasBlendShape:
            self.bitFlag = setBit(self.bitFlag, 2)
        if hasGroupPivot:
            self.bitFlag = setBit(self.bitFlag, 3)
        if hasUnknFlag8:
            self.bitFlag = setBit(self.bitFlag, 7)
        if hasUnknFlag10:
            self.bitFlag = setBit(self.bitFlag, 9)
        if hasUnknFlag16:
            self.bitFlag = setBit(self.bitFlag, 15)
        self.parseBitFlag()

    def read(self, file):
        self.bitFlag = read_ushort(file)
        self.parseBitFlag()

    def write(self, file):
        write_ushort(file, self.bitFlag)


class FileHeader:
    def __init__(self):
        self.magic = 1213416781
        self.version = 0
        self.fileSize = 0
        self.lodGroupNameHash = 0  # This determines what LOD distance scaling to use based on category of object
        self.contentFlag = (
            ContentFlag()
        )  # Bitflag 1000 XXXX-[GroupPivot/Floats][Blendshape][Skeleton][AABB]
        self.nameCount = 0
        self.unkn = 0
        self.meshGroupOffset = 0
        self.shadowMeshGroupOffset = 0
        self.occlusionMeshGroupOffset = 0
        self.skeletonOffset = 0
        self.normalRecalcOffset = 0
        self.blendShapesOffset = 0
        self.aabbOffset = 0
        self.meshOffset = 0
        self.floatsOffset = 0
        self.materialNameRemapOffset = 0
        self.boneNameRemapOffset = 0
        self.blendShapeNameOffset = 0
        self.nameOffsetsOffset = 0

        # SF6
        self.sf6UnknCount = 0
        self.sf6unkn0 = 0
        self.sf6unkn1 = 0
        self.streamingInfoOffset = 0
        self.sf6unkn3 = 0
        self.sf6unkn4 = 0

        # DD2
        self.dd2HashOffset = 0
        self.verticesOffset = 0

        # MHWilds
        # TODO Update offset calculation for wilds meshes
        # TODO Fix write for wilds changes
        self.wilds_unkn1 = 0  # TODO Clean these variables up and figure out if they're not actually new, just shifted
        self.wilds_unkn2 = 0
        self.wilds_unkn3 = 0
        self.wilds_unkn4 = 0
        self.wilds_unkn5 = 0
        self.streamingInfoOffset = 0

    def read(self, file, version):
        self.magic = read_uint(file)
        if self.magic != 1213416781:
            if self.magic == 1498173517:  # MPLY
                raise Exception(
                    "MPLY formatted mesh files (stage meshes mostly) are not supported yet."
                )
            else:
                raise Exception("File is not an RE mesh file.")
        self.version = read_uint(file)
        self.fileSize = read_uint(file)
        self.lodGroupNameHash = read_uint(file)

        if version < VERSION_SF6:
            self.contentFlag.read(file)
            self.nameCount = read_short(file)
            self.unkn = read_uint(file)
            self.meshGroupOffset = read_uint64(file)
            self.shadowMeshGroupOffset = read_uint64(file)
            self.occlusionMeshGroupOffset = read_uint64(file)
            self.skeletonOffset = read_uint64(file)
            self.normalRecalcOffset = read_uint64(file)
            self.blendShapesOffset = read_uint64(file)
            self.aabbOffset = read_uint64(file)
            self.meshOffset = read_uint64(file)
            self.floatsOffset = read_uint64(file)
            self.materialNameRemapOffset = read_uint64(file)
            self.boneNameRemapOffset = read_uint64(file)
            self.blendShapeNameOffset = read_uint64(file)
            self.nameOffsetsOffset = read_uint64(file)
        elif version >= VERSION_SF6 and version < VERSION_ONI2:
            self.contentFlag.read(file)
            self.sf6UnknCount = read_short(file)
            self.nameCount = read_short(file)

            self.sf6unkn3 = read_short(file)  # new

            self.unkn = read_uint(file)
            self.sf6unkn0 = read_uint(file)  # new
            self.meshGroupOffset = read_uint64(file)
            self.shadowMeshGroupOffset = read_uint64(file)
            self.occlusionMeshGroupOffset = read_uint64(file)
            self.normalRecalcOffset = read_uint64(file)
            self.blendShapesOffset = read_uint64(file)
            self.meshOffset = read_uint64(file)
            self.sf6unkn1 = read_uint64(file)  # new

            self.floatsOffset = read_uint64(file)
            self.aabbOffset = read_uint64(file)
            self.skeletonOffset = read_uint64(file)
            self.materialNameRemapOffset = read_uint64(file)
            self.boneNameRemapOffset = read_uint64(file)
            self.blendShapeNameOffset = read_uint64(file)

            if version < VERSION_DD2:
                self.streamingInfoOffset = read_uint64(
                    file
                )  # vertex ElementOffset New with sf6
                self.nameOffsetsOffset = read_uint64(file)
            else:
                self.nameOffsetsOffset = read_uint64(file)
                self.dd2HashOffset = read_uint64(file)
                self.streamingInfoOffset = read_uint64(
                    file
                )  # vertex ElementOffset New with sf6
            self.verticesOffset = read_uint64(file)  # new
            self.sf6unkn4 = read_uint64(file)  # new

        elif version >= VERSION_ONI2:
            self.wilds_unkn1 = read_uint(file)
            self.nameCount = read_short(file)
            self.contentFlag.read(file)
            self.sf6UnknCount = read_short(file)

            self.wilds_unkn2 = read_uint(file)
            self.wilds_unkn3 = read_uint(file)
            self.wilds_unkn4 = read_uint(file)
            self.wilds_unkn5 = read_short(file)

            self.verticesOffset = read_uint64(file)
            self.meshGroupOffset = read_uint64(file)
            self.shadowMeshGroupOffset = read_uint64(file)
            self.occlusionMeshGroupOffset = read_uint64(file)
            self.normalRecalcOffset = read_uint64(file)
            self.blendShapesOffset = read_uint64(file)
            self.meshOffset = read_uint64(file)
            self.sf6unkn1 = read_uint64(file)  # new

            self.floatsOffset = read_uint64(file)
            self.aabbOffset = read_uint64(file)
            self.skeletonOffset = read_uint64(file)
            self.materialNameRemapOffset = read_uint64(file)
            self.boneNameRemapOffset = read_uint64(file)
            self.blendShapeNameOffset = read_uint64(file)
            self.nameOffsetsOffset = read_uint64(file)
            self.streamingInfoOffset = read_uint64(file)  # new with wilds
            self.sf6unkn4 = read_uint64(file)  # new

    def write(self, file, version):
        write_uint(file, self.magic)
        write_uint(file, self.version)
        write_uint(file, self.fileSize)
        write_uint(file, self.lodGroupNameHash)

        if version < VERSION_SF6:
            self.contentFlag.write(file)
            write_short(file, self.nameCount)
            write_uint(file, self.unkn)
            write_uint64(file, self.meshGroupOffset)
            write_uint64(file, self.shadowMeshGroupOffset)
            write_uint64(file, self.occlusionMeshGroupOffset)
            write_uint64(file, self.skeletonOffset)
            write_uint64(file, self.normalRecalcOffset)
            write_uint64(file, self.blendShapesOffset)
            write_uint64(file, self.aabbOffset)
            write_uint64(file, self.meshOffset)
            write_uint64(file, self.floatsOffset)
            write_uint64(file, self.materialNameRemapOffset)
            write_uint64(file, self.boneNameRemapOffset)
            write_uint64(file, self.blendShapeNameOffset)
            write_uint64(file, self.nameOffsetsOffset)
        elif version >= VERSION_SF6 and version < VERSION_ONI2:
            self.contentFlag.write(file)
            write_short(file, self.sf6UnknCount)
            write_short(file, self.nameCount)
            write_short(file, self.sf6unkn3)  # new
            write_uint(file, self.unkn)
            write_uint(file, self.sf6unkn0)  # new
            write_uint64(file, self.meshGroupOffset)
            write_uint64(file, self.shadowMeshGroupOffset)
            write_uint64(file, self.occlusionMeshGroupOffset)
            write_uint64(file, self.normalRecalcOffset)
            write_uint64(file, self.blendShapesOffset)
            write_uint64(file, self.meshOffset)
            write_uint64(file, self.sf6unkn1)  # new

            write_uint64(file, self.floatsOffset)
            write_uint64(file, self.aabbOffset)
            write_uint64(file, self.skeletonOffset)
            write_uint64(file, self.materialNameRemapOffset)
            write_uint64(file, self.boneNameRemapOffset)
            write_uint64(file, self.blendShapeNameOffset)
            if version < VERSION_DD2:
                write_uint64(file, self.streamingInfoOffset)  # new
                write_uint64(file, self.nameOffsetsOffset)
            else:
                write_uint64(file, self.nameOffsetsOffset)
                write_uint64(file, self.dd2HashOffset)
                write_uint64(file, self.streamingInfoOffset)  # new

            write_uint64(file, self.verticesOffset)  # new
            write_uint64(file, self.sf6unkn4)  # new
        elif version >= VERSION_ONI2:
            write_uint(file, self.wilds_unkn1)
            write_short(file, self.nameCount)
            self.contentFlag.write(file)
            write_short(file, self.sf6UnknCount)
            write_uint(file, self.wilds_unkn2)
            write_uint(file, self.wilds_unkn3)
            write_uint(file, self.wilds_unkn4)
            write_short(file, self.wilds_unkn5)
            write_uint64(file, self.verticesOffset)
            write_uint64(file, self.meshGroupOffset)
            write_uint64(file, self.shadowMeshGroupOffset)
            write_uint64(file, self.occlusionMeshGroupOffset)
            write_uint64(file, self.normalRecalcOffset)
            write_uint64(file, self.blendShapesOffset)
            write_uint64(file, self.meshOffset)
            write_uint64(file, self.sf6unkn1)
            write_uint64(file, self.floatsOffset)
            write_uint64(file, self.aabbOffset)
            write_uint64(file, self.skeletonOffset)
            write_uint64(file, self.materialNameRemapOffset)
            write_uint64(file, self.boneNameRemapOffset)
            write_uint64(file, self.blendShapeNameOffset)
            write_uint64(file, self.nameOffsetsOffset)
            write_uint64(file, self.streamingInfoOffset)
            write_uint64(file, self.sf6unkn4)


class IndexNormalRecalc:
    def __init__(self):
        self.index = 0
        self.left = 0
        self.right = 0

    def read(self, file):
        self.index = read_ushort(file)
        self.left = read_ubyte(file)
        self.right = read_ubyte(file)

    def write(self, file):
        write_ushort(file, self.index)
        write_ubyte(file, self.left)
        write_ubyte(file, self.right)


class NormalRecalc:
    def __init__(self):
        self.blockCount = 0
        self.dataOffset = 0
        self.nextOffset = 0
        self.null = 0
        self.vertexOffset = 0
        self.faceOffset = 0
        # padding align 16
        self.vertexDataList = []
        # padding align 16
        self.faceDataList = []

    def read(self, file, vertexCount, faceCount):
        self.blockCount = read_uint(file)
        self.dataOffset = read_uint64(file)
        self.nextOffset = read_short(file)
        self.null = read_short(file)
        self.vertexOffset = read_uint(file)
        self.faceOffset = read_uint64(file)
        file.seek(getPaddedPos(file.tell(), 16))
        for i in range(0, vertexCount):
            entry = IndexNormalRecalc()
            entry.read(file)
            self.vertexDataList.append(entry)
        file.seek(getPaddedPos(file.tell(), 16))
        for i in range(0, faceCount):
            entry = IndexNormalRecalc()
            entry.read(file)
            self.faceDataList.append(entry)

    def write(self, file):
        write_uint(file, self.blockCount)
        write_uint64(file, self.dataOffset)
        write_short(file, self.nextOffset)
        write_short(file, self.null)
        write_uint(file, self.vertexOffset)
        write_uint64(file, self.faceOffset)
        file.seek(getPaddedPos(file.tell(), 16))  # TODO FIX WRITE
        for entry in self.vertexDataList:
            entry.write(file)
        file.seek(getPaddedPos(file.tell(), 16))  # TODO FIX WRITE
        for entry in self.faceDataList:
            entry.write(file)


class BlendSubMesh:
    def __init__(self):
        self.subMeshVertexStartIndex = 0
        self.vertOffset = 0
        self.vertCount = 0
        self.paramUnkn3 = 0

    def read(self, file):
        self.subMeshVertexStartIndex = read_uint(file)
        self.vertOffset = read_uint(file)
        self.vertCount = read_uint(file)
        self.paramUnkn3 = read_uint(file)

    def write(self, file):
        write_uint(file, self.subMeshVertexStartIndex)
        write_uint(file, self.vertOffset)
        write_uint(file, self.vertCount)
        write_uint(file, self.paramUnkn3)


class BlendTarget:
    def __init__(self):
        self.subMeshVertexStartIndex = 0
        self.vertCount = 0
        self.blendSSIndex = 0
        self.blendShapeNum = 0
        self.deltaOffset = 0

        # sf6 changes
        self.unkn0 = 0
        self.subMeshEntryCount = 0
        self.unkn2 = 0
        self.subMeshEntryOffset = 0
        self.subMeshEntryList = []

    def read(self, file, version):
        if version < VERSION_SF6:
            self.subMeshVertexStartIndex = read_uint(file)
            self.vertCount = read_uint(file)
            self.blendSSIndex = read_ushort(file)
            self.blendShapeNum = read_ushort(file)
            self.deltaOffset = read_uint(file)
        else:
            self.blendSSIndex = read_ushort(file)
            self.blendShapeNum = read_ushort(file)
            self.unkn0 = read_ushort(file)
            self.subMeshEntryCount = read_ubyte(file)
            self.unkn2 = read_ubyte(file)
            self.subMeshEntryOffset = read_uint64(file)
            currentPos = file.tell()
            file.seek(self.subMeshEntryOffset)
            for i in range(0, self.subMeshEntryCount):
                subMeshEntry = BlendSubMesh()
                subMeshEntry.read(file)
                self.subMeshEntryList.append(subMeshEntry)

            file.seek(currentPos)

    def write(self, file, version):  # TODO FIX WRITE
        write_uint64(file, self.count)
        write_uint64(file, self.mainOffset)
        write_uint64(file, self.zero)
        write_uint64(file, self.hash)
        for entry in self.blendShapeOffsetList:
            write_uint64(file, entry)

        for entry in self.blendShapeList:  # TODO FIX WRITE
            entry.write(file)


class BlendShapeData:
    def __init__(self):
        self.targetCount = 1
        self.typing = 0
        self.unknFlag = 0
        self.padding1 = 0
        self.padding2 = 0
        self.dataOffset = 0  # [Target count]
        self.aabbOffset = 0
        self.blendSOffset = 0
        self.blendSSOffset = 0
        self.blendTargetList = []
        self.aabbList = [AABB()]
        self.blendS = [0, 0, 0, 0]
        self.blendSSList = []

    def read(self, file, version):
        self.targetCount = read_ushort(file)
        self.typing = read_ushort(file)
        self.unknFlag = read_uint(file)
        self.padding1 = read_uint(file)
        self.padding2 = read_uint(file)
        self.dataOffset = read_uint64(file)  # [Target count]
        self.aabbOffset = read_uint64(file)
        self.blendSOffset = read_uint64(file)
        self.blendSSOffset = read_uint64(file)
        file.seek(self.dataOffset)
        for i in range(0, self.targetCount):
            blendTargetEntry = BlendTarget()
            blendTargetEntry.read(file, version)
            self.blendTargetList.append(blendTargetEntry)
        file.seek(self.aabbOffset)  # TODO FIX WRITE
        self.aabbList.clear()
        for i in range(0, self.targetCount):
            aabbEntry = AABB()
            aabbEntry.read(file)
            self.aabbList.append(aabbEntry)
        self.blendS = [read_int(file), read_int(file), read_int(file)]
        self.blendSSList = []
        for blendTarget in self.blendTargetList:
            for i in range(0, blendTarget.blendShapeNum):
                self.blendSSList.append(read_int(file))

    def write(self, file):  # TODO FIX WRITE
        write_ushort(file, self.targetCount)
        write_ushort(file, self.typing)
        write_uint(file, self.unknFlag)
        write_uint(file, self.padding1)
        write_uint(file, self.padding2)
        write_uint64(file, self.dataOffset)
        write_uint64(file, self.aabbOffset)
        write_uint64(file, self.blendSOffset)
        write_uint64(file, self.blendSSOffset)
        write_uint(file, self.vertOffset)
        write_uint(file, self.vertCount)
        write_ushort(file, self.visconTarget)
        write_ushort(file, self.blendShapeCount)
        self.aabb.write(file)
        for entry in self.blendS:
            write_int(file, entry)
        for entry in self.blendSSList:
            write_int(file, entry)


class BlendShapeHeader:
    def __init__(self):
        self.count = 0
        self.mainOffset = 0
        self.zero = 0
        self.hash = 0
        self.blendShapeOffsetList = []
        self.blendShapeList = []
        # TODO Blend shapes are different in wilds, fix

    def read(self, file, version):
        self.count = read_uint64(file)
        if version < VERSION_ONI2:
            self.mainOffset = read_uint64(file)
            self.zero = read_uint64(file)
        else:
            self.zero = read_uint64(file)
            self.mainOffset = read_uint64(file)
        self.hash = read_uint64(file)
        self.blendShapeOffsetList = []
        for i in range(0, self.count):
            self.blendShapeOffsetList.append(read_uint64(file))
        self.blendShapeList = []
        currentPos = file.tell()
        for i in range(0, self.count):
            file.seek(self.blendShapeOffsetList[i])
            entry = BlendShapeData()
            entry.read(file, version)
            self.blendShapeList.append(entry)
        file.seek(currentPos)

    def write(self, file, version):
        write_uint64(file, self.count)
        write_uint64(file, self.mainOffset)
        write_uint64(file, self.zero)
        write_uint64(file, self.hash)
        for entry in self.blendShapeOffsetList:
            write_uint64(file, entry)

        for entry in self.blendShapeList:  # TODO FIX WRITE
            entry.write(file, version)


class BoneAABBGroup:
    def __init__(self):
        self.count = 0
        self.offset = 0
        self.bboxList = []
        # padding align 16

    def read(self, file):
        self.count = read_uint64(file)
        self.offset = read_uint64(file)
        self.bboxList = []
        for i in range(0, self.count):
            entry = AABB()
            entry.read(file)
            self.bboxList.append(entry)
        file.seek(getPaddedPos(file.tell(), 16))

    def write(self, file):
        write_uint64(file, self.count)
        write_uint64(file, self.offset)
        for entry in self.bboxList:  # TODO FIX WRITE
            entry.write(file)
        file.seek(getPaddedPos(file.tell(), 16))


class Bone:
    def __init__(self):
        self.boneIndex = 0
        self.boneParent = 0
        self.boneSibling = 0
        self.boneChild = 0
        self.boneSymmetric = 0
        self.useSecondaryWeight = 0
        self.padding0 = 0
        self.padding1 = 0

    def read(self, file):
        self.boneIndex = read_ushort(file)
        self.boneParent = read_short(file)
        self.boneSibling = read_short(file)
        self.boneChild = read_short(file)
        self.boneSymmetric = read_short(file)
        self.useSecondaryWeight = read_short(file)
        self.padding0 = read_short(file)
        self.padding1 = read_short(file)

    def write(self, file):
        write_ushort(file, self.boneIndex)
        write_short(file, self.boneParent)
        write_short(file, self.boneSibling)
        write_short(file, self.boneChild)
        write_short(file, self.boneSymmetric)
        write_short(file, self.useSecondaryWeight)
        write_short(file, self.padding0)
        write_short(file, self.padding1)


class Skeleton:
    def __init__(self):
        self.boneCount = 0
        self.remapCount = 0
        self.NULL = 0
        self.boneHeaderOffset = 0
        self.boneLocalMatrixOffset = 0
        self.boneWorldMatrixOffset = 0
        self.boneInverseMatrixOffset = 0
        self.boneRemapList = []
        # padding align 16
        self.boneInfoList = []
        # padding align 16
        self.localMatList = []
        self.worldMatList = []
        self.inverseMatList = []

    def read(self, file):
        self.boneCount = read_uint(file)
        self.remapCount = read_uint(file)
        self.NULL = read_uint64(file)
        self.boneHeaderOffset = read_uint64(file)
        self.boneLocalMatrixOffset = read_uint64(file)
        self.boneWorldMatrixOffset = read_uint64(file)
        self.boneInverseMatrixOffset = read_uint64(file)
        self.boneRemapList = []
        for i in range(0, self.remapCount):
            self.boneRemapList.append(read_ushort((file)))
        file.seek(getPaddedPos(file.tell(), 16))
        self.boneInfoList = []
        for i in range(0, self.boneCount):
            entry = Bone()
            entry.read(file)
            self.boneInfoList.append(entry)
        file.seek(getPaddedPos(file.tell(), 16))
        localMatList = []
        for i in range(0, self.boneCount):
            entry = Matrix4x4()
            entry.read(file)
            self.localMatList.append(entry)
        worldMatList = []
        for i in range(0, self.boneCount):
            entry = Matrix4x4()
            entry.read(file)
            self.worldMatList.append(entry)
        inverseMatList = []
        for i in range(0, self.boneCount):
            entry = Matrix4x4()
            entry.read(file)
            self.inverseMatList.append(entry)

    def write(self, file):
        write_uint(file, self.boneCount)
        write_uint(file, self.remapCount)
        write_uint64(file, self.NULL)
        write_uint64(file, self.boneHeaderOffset)
        write_uint64(file, self.boneLocalMatrixOffset)
        write_uint64(file, self.boneWorldMatrixOffset)
        write_uint64(file, self.boneInverseMatrixOffset)
        for entry in self.boneRemapList:
            write_ushort(file, entry)
        file.seek(getPaddedPos(file.tell(), 16))
        for entry in self.boneInfoList:
            entry.write(file)
        for entry in self.localMatList:
            entry.write(file)
        for entry in self.worldMatList:
            entry.write(file)
        for entry in self.inverseMatList:
            entry.write(file)


class FloatData:
    def __init__(self):
        self.bufferSize = 0
        self.offset = 0
        self.unknDataList = []

    def read(self, file):
        self.count = read_uint64(file)
        self.offset = read_uint64(file)
        self.unknDataList = []
        startPos = file.tell()
        file.seek(self.offset)
        for i in range(0, self.bufferSize // 12):
            entry = Vec3()
            entry.read(file)
            self.unknDataList.append(entry)
        file.seek(startPos)

    def write(self, file):
        write_uint64(file, self.count)
        write_uint64(file, self.offset)
        startPos = file.tell()
        file.seek(self.offset)
        for entry in self.unknDataList:  # TODO FIX WRITE
            entry.write(file)
        file.seek(startPos)


class REMesh:
    def __init__(self):
        self.meshVersion = 0
        self.isMPLY = False
        self.fileHeader = FileHeader()
        self.lodHeader = None
        self.shadowHeader = None
        self.occlusionHeader = None
        self.skeletonHeader = None
        self.normalRecalcHeader = None
        self.blendShapeHeader = None
        self.boneBoundingBoxHeader = None
        self.streamingInfoHeader = None  # WILDS
        self.streamingBuffer = None  # WILDS
        self.meshBufferHeader = None
        self.floatsHeader = None
        self.rawNameOffsetList = []
        self.rawNameList = []
        self.materialNameRemapList = []
        self.boneNameRemapList = []
        self.blendShapeNameRemapList = []
        self.blendShapeRegionBytes = b""  # MH Wilds: pre-serialized blend shape struct region
        self.normalRecalcRegionBytes = b""  # MH Wilds: pre-serialized 16-byte normal-recalc header
        self.streamingBytes = b""  # MH Wilds: bytes for the parallel streaming companion file
        self.isStreamed = False  # MH Wilds: True when the mesh region is written as the streamed layout
        self.streamInBase = False  # MH Wilds: True = append streamingBytes to the base file (single-file experiment)
        self.meshRegionBytes = b""  # MH Wilds: pre-serialized mesh region (streamed layout)

    def read(
        self, file, version, lodTarget=None, streamingBuffer=None
    ):  # LOD target is an int that determines what lod level to import, the rest get ignored
        self.streamingBuffer = streamingBuffer
        if streamingBuffer is not None:
            lodTarget = (
                None  # Disable lod target optimization since all lods are needed
            )
        self.fileHeader.read(file, version)

        if self.fileHeader.meshGroupOffset:
            file.seek(self.fileHeader.meshGroupOffset)
            self.lodHeader = MainMeshHeader()
            self.lodHeader.read(file, version, lodTarget)

        if self.fileHeader.shadowMeshGroupOffset and lodTarget is None:
            file.seek(self.fileHeader.shadowMeshGroupOffset)
            self.shadowHeader = ShadowHeader()
            self.shadowHeader.read(file, version)

        if self.fileHeader.occlusionMeshGroupOffset and lodTarget is None:
            file.seek(self.fileHeader.occlusionMeshGroupOffset)
            self.occlusionHeader = LODGroupHeader()
            self.occlusionHeader.read(file, version)

        if self.fileHeader.skeletonOffset:
            file.seek(self.fileHeader.skeletonOffset)
            self.skeletonHeader = Skeleton()
            self.skeletonHeader.read(file)
        # TODO - Normal recalc is changed or offset is different in mhwilds
        """
		if self.fileHeader.normalRecalcOffset:
			file.seek(self.fileHeader.normalRecalcOffset)
			self.normalRecalcHeader = NormalRecalc()
			self.normalRecalcHeader.read(file,sum([i.vertexCount for i in self.lodHeader.lodGroupList[0].meshGroupList]),sum([i.faceCount for i in self.lodHeader.lodGroupList[0].meshGroupList]))
		"""
        if self.fileHeader.blendShapesOffset and (
            IMPORT_BLEND_SHAPES
            or self.meshVersion in WILDS_PACKED_BLEND_SHAPE_FILE_VERSIONS
        ):
            file.seek(self.fileHeader.blendShapesOffset)
            self.blendShapeHeader = BlendShapeHeader()
            self.blendShapeHeader.read(file, version)

        if self.fileHeader.aabbOffset:
            file.seek(self.fileHeader.aabbOffset)
            self.boneBoundingBoxHeader = BoneAABBGroup()
            self.boneBoundingBoxHeader.read(file)

        if version >= VERSION_SF6:
            if self.fileHeader.streamingInfoOffset:
                file.seek(self.fileHeader.streamingInfoOffset)
                self.streamingInfoHeader = StreamingInfo()
                self.streamingInfoHeader.read(file)
                if self.streamingInfoHeader.entryCount != 0 and streamingBuffer is None:
                    raiseError(
                        "Streaming mesh file is missing. Both mesh files are required. Extract the corresponding mesh file from inside the streaming directory.\n\nExample Mesh Path: natives\\STM\\Art\\Model\\Character\\ch02\\007\\000\\1\\ch02_007_0001.mesh.241111606\nExample Streaming Mesh Path: natives\\STM\\streaming\\Art\\Model\\Character\\ch02\\007\\000\\1\\ch02_007_0001.mesh.241111606"
                    )
                    raise Exception(
                        "Streaming mesh file is missing. Both mesh files are required. Extract the corresponding mesh file from inside the streaming directory."
                    )
        if self.fileHeader.meshOffset:
            file.seek(self.fileHeader.meshOffset)
            self.meshBufferHeader = MeshBufferHeader()
            self.meshBufferHeader.read(
                file, version, self.streamingInfoHeader, streamingBuffer
            )

        if self.fileHeader.floatsOffset:
            file.seek(self.fileHeader.floatsOffset)
            self.floatsHeader = FloatData()
            self.floatsHeader.read(file)

        if self.fileHeader.nameOffsetsOffset:
            file.seek(self.fileHeader.nameOffsetsOffset)
            for i in range(0, self.fileHeader.nameCount):
                self.rawNameOffsetList.append(read_uint64(file))

            for offset in self.rawNameOffsetList:
                file.seek(offset)
                self.rawNameList.append(read_string(file))

        if self.fileHeader.materialNameRemapOffset and self.lodHeader is not None:
            file.seek(self.fileHeader.materialNameRemapOffset)
            for i in range(0, self.lodHeader.materialCount):
                self.materialNameRemapList.append(read_ushort(file))

        if self.fileHeader.boneNameRemapOffset and self.skeletonHeader is not None:
            file.seek(self.fileHeader.boneNameRemapOffset)
            for i in range(0, self.skeletonHeader.boneCount):
                self.boneNameRemapList.append(read_ushort(file))

        if self.fileHeader.blendShapeNameOffset and self.blendShapeHeader is not None:
            file.seek(self.fileHeader.blendShapeNameOffset)
            blendNameCount = (
                self.fileHeader.nameCount
                - len(self.materialNameRemapList)
                - len(self.boneNameRemapList)
            )
            # for i in range(0,sum([blendShape.blendShapeCount for blendShape in self.blendShapeHeader.blendShapeList])):
            for i in range(0, blendNameCount):
                self.blendShapeNameRemapList.append(read_ushort(file))

    def write(self, file, version):
        self.fileHeader.write(file, version)

        if self.fileHeader.meshGroupOffset:
            if self.fileHeader.meshGroupOffset != file.tell():
                print(
                    f"ERROR IN OFFSET CALCULATION - meshGroupOffset - expected {self.fileHeader.meshGroupOffset}, actual {file.tell()}"
                )
            self.lodHeader.write(file, version)

        if self.fileHeader.shadowMeshGroupOffset:
            if self.fileHeader.shadowMeshGroupOffset != file.tell():
                print(
                    f"ERROR IN OFFSET CALCULATION - shadowMeshGroupOffset - expected {self.fileHeader.shadowMeshGroupOffset}, actual {file.tell()}"
                )
            self.shadowHeader.write(file, version)

        if self.fileHeader.skeletonOffset:
            if self.fileHeader.skeletonOffset != file.tell():
                print(
                    f"ERROR IN OFFSET CALCULATION - skeletonOffset - expected {self.fileHeader.skeletonOffset}, actual {file.tell()}"
                )
            self.skeletonHeader.write(file)

        if (
            self.fileHeader.materialNameRemapOffset
            and self.fileHeader.materialNameRemapOffset != file.tell()
        ):
            print(
                f"ERROR IN OFFSET CALCULATION - materialNameRemapOffset - expected {self.fileHeader.materialNameRemapOffset}, actual {file.tell()}"
            )
        for entry in self.materialNameRemapList:
            write_ushort(file, entry)

        file.seek(getPaddedPos(file.tell(), 16))
        if (
            self.fileHeader.boneNameRemapOffset
            and self.fileHeader.boneNameRemapOffset != file.tell()
        ):
            print(
                f"ERROR IN OFFSET CALCULATION - boneNameRemapOffset - expected {self.fileHeader.boneNameRemapOffset}, actual {file.tell()}"
            )
        for entry in self.boneNameRemapList:
            write_ushort(file, entry)

        file.seek(getPaddedPos(file.tell(), 16))
        if (
            self.fileHeader.blendShapeNameOffset
            and self.fileHeader.blendShapeNameOffset != file.tell()
        ):
            print(
                f"ERROR IN OFFSET CALCULATION - boneNameRemapOffset - expected {self.fileHeader.blendShapeNameOffset}, actual {file.tell()}"
            )
        for entry in self.blendShapeNameRemapList:
            write_ushort(file, entry)

        file.seek(getPaddedPos(file.tell(), 16))

        if (
            self.fileHeader.nameOffsetsOffset
            and self.fileHeader.nameOffsetsOffset != file.tell()
        ):
            print(
                f"ERROR IN OFFSET CALCULATION - nameOffsetsOffset - expected {self.fileHeader.nameOffsetsOffset}, actual {file.tell()}"
            )

        for offset in self.rawNameOffsetList:
            write_uint64(file, offset)
        file.seek(getPaddedPos(file.tell(), 16))

        for name in self.rawNameList:
            write_string(file, name)

        file.seek(getPaddedPos(file.tell(), 16))

        if self.fileHeader.aabbOffset:
            if self.fileHeader.aabbOffset != file.tell():
                print(
                    f"ERROR IN OFFSET CALCULATION - aabbOffset - expected {self.fileHeader.aabbOffset}, actual {file.tell()}"
                )
            self.boneBoundingBoxHeader.write(file)

        # MH Wilds normal-recalc header (pre-serialized in ParsedREMeshToREMesh).
        if self.fileHeader.normalRecalcOffset and self.normalRecalcRegionBytes:
            if self.fileHeader.normalRecalcOffset != file.tell():
                print(
                    f"ERROR IN OFFSET CALCULATION - normalRecalcOffset - expected {self.fileHeader.normalRecalcOffset}, actual {file.tell()}"
                )
            file.write(self.normalRecalcRegionBytes)
            file.write(b"\x00" * getPaddingAmount(file.tell(), 16))

        # MH Wilds blend shape struct region (pre-serialized in ParsedREMeshToREMesh).
        if self.fileHeader.blendShapesOffset and self.blendShapeRegionBytes:
            if self.fileHeader.blendShapesOffset != file.tell():
                print(
                    f"ERROR IN OFFSET CALCULATION - blendShapesOffset - expected {self.fileHeader.blendShapesOffset}, actual {file.tell()}"
                )
            file.write(self.blendShapeRegionBytes)
            file.write(b"\x00" * getPaddingAmount(file.tell(), 16))

        if self.fileHeader.meshOffset:
            if self.fileHeader.meshOffset != file.tell():
                print(
                    f"ERROR IN OFFSET CALCULATION - meshOffset - expected {self.fileHeader.meshOffset}, actual {file.tell()}"
                )
            if self.isStreamed and self.meshRegionBytes:
                # MH Wilds streamed layout: the whole mesh region was pre-serialized.
                file.write(self.meshRegionBytes)
                if self.streamInBase and self.streamingBytes:
                    # Single-file resident-blend experiment: the streamed buffer lives in the base, 16-aligned
                    # right after the mesh region (matches baseStreamOffset / the rebased bufferStarts).
                    file.write(b"\x00" * getPaddingAmount(file.tell(), 16))
                    file.write(self.streamingBytes)
            else:
                self.meshBufferHeader.write(file, version)

        file.write(
            b"\x00" * getPaddingAmount(file.tell(), 16)
        )  # Write end of file padding
        if self.fileHeader.fileSize != file.tell():
            print(
                f"ERROR IN OFFSET CALCULATION - fileSize - expected {self.fileHeader.fileSize}, actual {file.tell()}"
            )


# List to buffer conversions


def WriteToVertexPosBuffer(bufferStream, vertexPosList):
    data = struct.pack(
        f"{len(vertexPosList) * 3}f", *chain.from_iterable(vertexPosList)
    )
    bufferStream.write(data)


def WriteToNorTanBuffer(bufferStream, normalArray, tangentArray):
    vertexCount = len(normalArray)
    normalArray = np.floor(np.multiply(normalArray, 127))
    normalArray = np.insert(
        normalArray, 3, np.zeros(vertexCount, np.dtype("<b")), axis=1
    )
    norTanArray = np.empty((vertexCount * 2, 4), dtype=np.dtype("<b"))
    norTanArray[::2] = normalArray
    norTanArray[1::2] = tangentArray
    # print(norTanArray)

    bufferStream.write(norTanArray.tobytes())


# Old method of calculating tangents, slow


def WriteToNorTanBufferOld(bufferStream, normalList, vertexPosList, uvList, faceList):

    vertexCount = len(vertexPosList)
    faceCount = len(faceList)
    normalArray = np.array(normalList)
    tangentArray = np.zeros((vertexCount, 4), dtype="int8")
    # print(tangentArray)
    tan1Array = np.zeros((vertexCount * 2, 3), dtype="float")
    # print(tan1Array)
    tan2Array = np.zeros((vertexCount * 2, 3), dtype="float")
    for face in faceList:
        v1 = vertexPosList[face[0]]
        v2 = vertexPosList[face[1]]
        v3 = vertexPosList[face[2]]

        w1 = uvList[face[0]]
        w2 = uvList[face[1]]
        w3 = uvList[face[2]]

        x1 = v2[0] - v1[0]
        x2 = v3[0] - v1[0]
        y1 = v2[1] - v1[1]
        y2 = v3[1] - v1[1]
        z1 = v2[2] - v1[2]
        z2 = v3[2] - v1[2]

        s1 = w2[0] - w1[0]
        s2 = w3[0] - w1[0]
        t1 = w2[1] - w1[1]
        t2 = w3[1] - w1[1]

        div = s1 * t2 - s2 * t1
        r = 1.0
        if div != 0.0:
            r = 1.0 / div
        sdir = [
            (t2 * x1 - t1 * x2) * r,
            (t2 * y1 - t1 * y2) * r,
            (t2 * z1 - t1 * z2) * r,
        ]
        tdir = [
            (s1 * x2 - s2 * x1) * r,
            (s1 * y2 - s2 * y1) * r,
            (s1 * z2 - s2 * z1) * r,
        ]
        tan1Array[face[0]] += sdir
        tan1Array[face[1]] += sdir
        tan1Array[face[2]] += sdir

        tan2Array[face[0]] += tdir
        tan2Array[face[1]] += tdir
        tan2Array[face[2]] += tdir

    for i in range(vertexCount):
        n = normalArray[i]
        t = tan1Array[i]
        TN = t - n * (np.dot(n, t))
        norm = np.linalg.norm(TN)
        # print(norm)
        if norm != 0.0:
            TN /= norm
        # print(f"TN : {TN}")
        TNW = np.dot(np.cross(n, t), tan2Array[i])
        if TNW < 0.0:
            TNW = -128
        else:
            TNW = 127

        tangentArray[i][0] = TN[0] * 127
        tangentArray[i][1] = TN[1] * 127
        tangentArray[i][2] = TN[2] * 127
        tangentArray[i][3] = TNW
    normalArray = np.multiply(normalArray, 127)
    normalArray = np.floor(normalArray)
    normalArray = np.insert(
        normalArray, 3, np.zeros(vertexCount, np.dtype("<b")), axis=1
    )
    norTanArray = np.empty((vertexCount * 2, 4), dtype=np.dtype("<b"))
    norTanArray[::2] = normalArray
    norTanArray[1::2] = tangentArray
    # print(norTanArray)

    bufferStream.write(norTanArray.tobytes())


def WriteToUVBuffer(bufferStream, uvList):
    uvArray = np.array(uvList, dtype=np.dtype("<e"))
    uvArray = uvArray.flatten()
    uvArray[1::2] *= -1
    uvArray[1::2] += 1
    # print(uvArray)
    bufferStream.write(uvArray.tobytes())


def WriteToWeightBuffer(bufferStream, boneWeightsList, boneIndicesList, isSixWeight):

    if isSixWeight:
        # TODO Do bitfield work in numpy
        bf = CompressedSixWeightIndices()
        uint64Array = np.empty((len(boneWeightsList), 1), dtype=np.dtype("<Q"))
        for index in range(len(boneIndicesList)):
            # print(f"boneIndicesList: {boneIndicesList[index]}")
            bf.weights.w0 = boneIndicesList[index][0]
            bf.weights.w1 = boneIndicesList[index][1]
            bf.weights.w2 = boneIndicesList[index][2]
            bf.weights.pad0 = 0
            bf.weights.w3 = boneIndicesList[index][3]
            bf.weights.w4 = boneIndicesList[index][4]
            bf.weights.w5 = boneIndicesList[index][5]
            bf.weights.pad1 = 0
            uint64Array[index] = bf.asUInt64
            # print(f"bitfield: {[bf.weights.w0,bf.weights.w1,bf.weights.w2,bf.weights.w3,bf.weights.w4,bf.weights.w5]}")
            # print(f"uint64: {uint64Array[index]}\n")
        boneIndicesArray = uint64Array.view(dtype="<B")  # .byteswap(inplace=True)
        # print(boneIndicesArray)
    else:
        boneIndicesArray = boneIndicesList.astype("<B")

    boneWeightsArray = np.array(boneWeightsList)

    # Clean Weights
    # boneWeightsArray = np.round(boneWeightsArray,decimals=4)
    # MIN_FLOAT_VALUE = 0.01
    # boneWeightsArray = np.where(((boneWeightsArray != 0) & (boneWeightsArray < MIN_FLOAT_VALUE)),0.0,boneWeightsArray)

    # boneWeightsArray = np.round(boneWeightsArray,decimals = 2)
    weightSums = np.sum(boneWeightsArray, axis=1, dtype=np.float32)
    # print(weightSums)
    # Normalize weights to 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        boneWeightsArray = boneWeightsArray / weightSums[:, None]
        boneWeightsArray[weightSums == 0] = 0
    boneWeightsArray = np.multiply(boneWeightsArray, 255)
    boneWeightsArray = np.round(boneWeightsArray)
    diffSums = 255.0 - np.sum(boneWeightsArray, axis=1, dtype=np.float32)
    # print(diffSums)
    # for i in range(len(boneWeightsArray)):
    # print(f"{boneWeightsArray[i]}, difference: {diffSums[i]}")

    # Add difference of 255 to the largest value of each row in weight array
    boneWeightsArray[
        np.arange(boneWeightsArray.shape[0]), np.argmax(boneWeightsArray, axis=1)
    ] += diffSums
    # boneWeightsArray[:, 0] += diffSums
    boneWeightsArray = boneWeightsArray.astype("<B")

    if (255 - np.sum(boneWeightsArray, axis=1, dtype=np.int32) != 0).any():
        raiseWarning(
            "Non normalized weights detected on sub mesh! Weights may not behave as expected in game!"
        )

    # Set zero weight bone indices to 0
    # boneIndicesArray = np.where(boneWeightsArray == 0,0,boneIndicesArray)

    weightArray = np.empty((len(boneWeightsList) * 2, 8), dtype=np.dtype("<B"))
    weightArray[::2] = boneIndicesArray
    weightArray[1::2] = boneWeightsArray
    # print(weightArray)
    bufferStream.write(weightArray.tobytes())


def WriteToWeightBufferExtended(
    bufferStream,
    boneWeightsList,
    boneIndicesList,
    extraBufferStream,
    extraBoneWeightsList,
    extraBoneIndicesList,
    isSixWeight,
):

    if isSixWeight:
        # TODO Do bitfield work in numpy
        bf = CompressedSixWeightIndices()
        uint64Array = np.empty((len(boneWeightsList), 1), dtype=np.dtype("<Q"))
        for index in range(len(boneIndicesList)):
            # print(f"boneIndicesList: {boneIndicesList[index]}")
            bf.weights.w0 = boneIndicesList[index][0]
            bf.weights.w1 = boneIndicesList[index][1]
            bf.weights.w2 = boneIndicesList[index][2]
            bf.weights.pad0 = 0
            bf.weights.w3 = boneIndicesList[index][3]
            bf.weights.w4 = boneIndicesList[index][4]
            bf.weights.w5 = boneIndicesList[index][5]
            bf.weights.pad1 = 0
            uint64Array[index] = bf.asUInt64
            # print(f"bitfield: {[bf.weights.w0,bf.weights.w1,bf.weights.w2,bf.weights.w3,bf.weights.w4,bf.weights.w5]}")
            # print(f"uint64: {uint64Array[index]}\n")
        boneIndicesArray = uint64Array.view(dtype="<B")  # .byteswap(inplace=True)

        uint64Array2 = np.empty(
            (len(extraBoneIndicesList), 1), dtype=np.dtype("<Q")
        )  # Extra weights
        for index in range(len(extraBoneIndicesList)):
            # print(f"boneIndicesList: {boneIndicesList[index]}")
            bf.weights.w0 = extraBoneIndicesList[index][0]
            bf.weights.w1 = extraBoneIndicesList[index][1]
            bf.weights.w2 = extraBoneIndicesList[index][2]
            bf.weights.pad0 = 0
            bf.weights.w3 = extraBoneIndicesList[index][3]
            bf.weights.w4 = extraBoneIndicesList[index][4]
            bf.weights.w5 = extraBoneIndicesList[index][5]
            bf.weights.pad1 = 0
            uint64Array2[index] = bf.asUInt64
            # print(f"bitfield: {[bf.weights.w0,bf.weights.w1,bf.weights.w2,bf.weights.w3,bf.weights.w4,bf.weights.w5]}")
            # print(f"uint64: {uint64Array[index]}\n")
        extraBoneIndicesArray = uint64Array2.view(dtype="<B")  # .byteswap(inplace=True)
        # print(boneIndicesArray)
    else:
        boneIndicesArray = boneIndicesList.astype("<B")
        extraBoneIndicesArray = extraBoneIndicesList.astype("<B")

    boneWeightsArray = np.array(boneWeightsList)
    # Combine extra weights with first set so that they're normalized together
    boneWeightsArray = np.hstack((boneWeightsArray, np.array(extraBoneWeightsList)))
    # print(boneWeightsArray)
    # Clean Weights
    # boneWeightsArray = np.round(boneWeightsArray,decimals=4)
    # MIN_FLOAT_VALUE = 0.01
    # boneWeightsArray = np.where(((boneWeightsArray != 0) & (boneWeightsArray < MIN_FLOAT_VALUE)),0.0,boneWeightsArray)

    # boneWeightsArray = np.round(boneWeightsArray,decimals = 2)
    weightSums = np.sum(boneWeightsArray, axis=1, dtype=np.float32)
    # print(weightSums)
    # Normalize weights to 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        boneWeightsArray = boneWeightsArray / weightSums[:, None]
        boneWeightsArray[weightSums == 0] = 0
    boneWeightsArray = np.multiply(boneWeightsArray, 255)
    boneWeightsArray = np.round(boneWeightsArray)
    diffSums = 255.0 - np.sum(boneWeightsArray, axis=1, dtype=np.float32)
    # print(diffSums)
    # for i in range(len(boneWeightsArray)):
    # print(f"{boneWeightsArray[i]}, difference: {diffSums[i]}")

    # Add difference of 255 to the largest value of each row in weight array
    boneWeightsArray[
        np.arange(boneWeightsArray.shape[0]), np.argmax(boneWeightsArray, axis=1)
    ] += diffSums
    # boneWeightsArray[:, 0] += diffSums
    boneWeightsArray = boneWeightsArray.astype("<B")

    if (255 - np.sum(boneWeightsArray, axis=1, dtype=np.int32) != 0).any():
        raiseWarning(
            "Non normalized weights detected on sub mesh! Weights may not behave as expected in game!"
        )

    # Set zero weight bone indices to 0
    # boneIndicesArray = np.where(boneWeightsArray == 0,0,boneIndicesArray)

    weightArray = np.empty((len(boneWeightsList) * 2, 8), dtype=np.dtype("<B"))
    weightArray[::2] = boneIndicesArray
    weightArray[1::2] = boneWeightsArray[:, :8]
    # print(weightArray)
    bufferStream.write(weightArray.tobytes())

    extraWeightArray = np.empty(
        (len(extraBoneWeightsList) * 2, 8), dtype=np.dtype("<B")
    )
    extraWeightArray[::2] = extraBoneIndicesArray
    extraWeightArray[1::2] = boneWeightsArray[:, 8:]
    extraBufferStream.write(extraWeightArray.tobytes())


def WriteToColorBuffer(bufferStream, colorList):
    colorArray = np.array(colorList, dtype=np.float32)
    colorArray = np.multiply(colorArray, 255)
    colorArray = colorArray.astype(dtype=">B")
    # print(colorArray)
    bufferStream.write(colorArray.tobytes())


def computeBlendShapeAABB(deltaArrayList):
    # Symmetric (min = -max) AABB covering the per-axis extent of all the given delta arrays.
    # This is the box the Wilds 11/10/11 packing quantizes against (one per blend target).
    aabb = AABB()
    if not deltaArrayList:
        return aabb
    allDeltas = np.concatenate(
        [np.asarray(d, dtype=np.float64).reshape(-1, 3) for d in deltaArrayList], axis=0
    )
    if len(allDeltas) == 0:
        return aabb
    # Keep the range non-zero so the quantization step never divides by zero.
    maxAbs = np.maximum(np.max(np.abs(allDeltas), axis=0), 1e-6)
    aabb.min.x, aabb.min.y, aabb.min.z = (-maxAbs[0], -maxAbs[1], -maxAbs[2])
    aabb.max.x, aabb.max.y, aabb.max.z = (maxAbs[0], maxAbs[1], maxAbs[2])
    return aabb


def packBlendShapeDeltas(deltaArray, aabb):
    # Inverse of the Wilds blend shape decode: dequant is delta = aabb.min + n*(aabb.max-aabb.min),
    # so n = (delta - aabb.min) / (aabb.max - aabb.min); pack as 11/10/11 (x=11, y=10, z=11 bits).
    deltas = np.asarray(deltaArray, dtype=np.float64).reshape(-1, 3)
    rangeVec = np.array(
        [aabb.max.x - aabb.min.x, aabb.max.y - aabb.min.y, aabb.max.z - aabb.min.z]
    )
    rangeVec[rangeVec == 0] = 1.0
    minVec = np.array([aabb.min.x, aabb.min.y, aabb.min.z])
    norm = (deltas - minVec) / rangeVec
    xi = np.clip(np.round(norm[:, 0] * 2047), 0, 2047).astype(np.uint32)
    yi = np.clip(np.round(norm[:, 1] * 1023), 0, 1023).astype(np.uint32)
    zi = np.clip(np.round(norm[:, 2] * 2047), 0, 2047).astype(np.uint32)
    return (xi | (yi << 11) | (zi << 21)).astype("<u4")


def buildWildsBlendShapeExport(parsedMesh, parsedSubMeshToSubMeshDataDict):
    # Gather Blender-side blend shapes into per-LOD blend targets. Each submesh that has shape keys
    # becomes its own blend target (its own blendShapeNum / AABB / name range), so submeshes with
    # different shape key sets are handled. Returns (deltaBytes, perLodList, blendNames) where
    # blendNames is the flat per-occurrence name list (target.blendSSIndex offsets into it), or
    # (None, None, None) if there are no shape keys anywhere. perLodList has one entry per main LOD
    # (possibly with an empty target list) so the BlendShapeData list stays index-aligned with LODs.
    if not EXPORT_WILDS_BLEND_SHAPES:
        # Disabled until the streaming-file write path exists (see the flag's definition).
        return None, None, None
    perLodList = []
    deltaChunks = []
    blendNames = []
    anyBlend = False
    for lod in parsedMesh.mainMeshLODList:
        # Collect every submesh in this LOD that has shape keys (keep the submesh for its blend meta).
        blendSubs = []  # (startIdx, vertCount, shapes, sm)
        for viscon in lod.visconGroupList:
            for sm in viscon.subMeshList:
                shapes = getattr(sm, "blendShapeList", None)
                if not shapes:
                    continue
                anyBlend = True
                subData = parsedSubMeshToSubMeshDataDict.get(sm)
                startIdx = subData.vertexStartIndex if subData is not None else 0
                blendSubs.append((startIdx, len(sm.vertexPosList), shapes, sm))
        if EXPORT_WILDS_DEBUG_LAST_SUBMESH_ONLY and len(blendSubs) > 1:
            blendSubs = blendSubs[-1:]  # keep only the last blend submesh (the custom morph)
        targets = []
        blockTyping = None
        blockBlendS = None
        metaSubs = [bs for bs in blendSubs if getattr(bs[3], "wildsBlendMeta", None)]
        if metaSubs:
            # FAITHFUL PATH: rebuild the original block layout exactly from the metadata captured at
            # import (target grouping, fragmented subEntries with their cumulative vertOffsets, typing,
            # per-target AABB, blendS). Each shape's deltas are pulled from its shape key by name and
            # sliced into the recorded sub-ranges, so the delta buffer matches the original byte layout.
            for startIdx, vertCount, shapes, sm in metaSubs:
                meta = sm.wildsBlendMeta
                blockTyping = meta.get("typing")
                blockBlendS = meta.get("blendS")
                shapeByName = {bs.blendShapeName: bs for bs in shapes}
                for mt in meta["targets"]:
                    aabb = AABB()
                    aabb.min.x, aabb.min.y, aabb.min.z = mt["aabbMin"]
                    aabb.max.x, aabb.max.y, aabb.max.z = mt["aabbMax"]
                    subs3 = [tuple(se) for se in mt["subEntries"]]  # (startIdx, vertOffset, vertCount)
                    ssIndex = len(blendNames)
                    shapeArrays = []
                    for nm in mt["names"]:
                        blendNames.append(nm)
                        bs = shapeByName.get(nm)
                        deltas = (
                            np.asarray(bs.deltas, dtype=np.float64).reshape(-1, 3)
                            if bs is not None
                            else np.zeros((vertCount, 3))
                        )
                        for sStart, _sVOff, sCnt in subs3:
                            seg = deltas[sStart : sStart + sCnt]
                            if len(seg) < sCnt:  # shape key shorter than the recorded range: zero-pad
                                seg = np.vstack([seg, np.zeros((sCnt - len(seg), 3))])
                            shapeArrays.append(packBlendShapeDeltas(seg, aabb))
                    deltaChunks.append(np.concatenate(shapeArrays).astype("<u4").tobytes())
                    targets.append(
                        {
                            "blendShapeNum": mt["blendShapeNum"],
                            "subEntries3": subs3,
                            "aabb": aabb,
                            "blendSSIndex": ssIndex,
                        }
                    )
            perLodList.append({"targets": targets, "typing": blockTyping, "blendS": blockBlendS})
            continue
        if blendSubs:
            # The engine allocates blend channels for ONE shared vertex region, so every target must
            # cover the same merged region (one range per blend submesh, all starting from the region's
            # base). Each shape's deltas span the whole region; the shape's real deltas land in its own
            # submesh's portion and the rest are zero (which, with the symmetric AABB, means no movement).
            # This matches how Capcom meshes lay out multi-target blends (face: 1 target; armor: 5 targets,
            # all sharing the same subMeshEntries). Per-submesh disjoint targets are dropped by the engine.
            mergedRegion = [(s, c) for (s, c, _sh, _sm) in blendSubs]
            totalRegionVerts = sum(c for (_s, c, _sh, _sm) in blendSubs)
            portionOffset = 0
            for startIdx, vertCount, shapes, sm in blendSubs:
                if EXPORT_WILDS_DEBUG_OVERRIDE_DELTA_OFFSET:
                    # AABB must cover the forced offset or the packer clamps it back to ~zero.
                    aabb = computeBlendShapeAABB(
                        [np.full((1, 3), EXPORT_WILDS_DEBUG_OVERRIDE_DELTA_OFFSET)]
                    )
                else:
                    aabb = computeBlendShapeAABB([bs.deltas for bs in shapes])
                ssIndex = len(blendNames)
                for bs in shapes:
                    blendNames.append(
                        EXPORT_WILDS_DEBUG_PIGGYBACK_NAME or bs.blendShapeName
                    )
                shapeArrays = []
                for bs in shapes:
                    full = np.zeros((totalRegionVerts, 3), dtype=np.float64)
                    if EXPORT_WILDS_DEBUG_OVERRIDE_DELTA_OFFSET:
                        # Force a large, obvious uniform delta on this submesh's portion.
                        real = np.full((vertCount, 3), EXPORT_WILDS_DEBUG_OVERRIDE_DELTA_OFFSET)
                    else:
                        real = np.asarray(bs.deltas, dtype=np.float64).reshape(-1, 3)
                    full[portionOffset : portionOffset + vertCount] = real
                    shapeArrays.append(packBlendShapeDeltas(full, aabb))
                chunk = np.concatenate(shapeArrays).astype("<u4").tobytes()
                if DEBUG_STREAMING_BUILD:
                    print(
                        f"[BSEXP] target shapes={len(shapes)} regionVerts={totalRegionVerts} "
                        f"portionOffset={portionOffset} portionVerts={vertCount} chunkBytes={len(chunk)} "
                        f"names={[bs.blendShapeName for bs in shapes]}"
                    )
                deltaChunks.append(chunk)
                targets.append(
                    {
                        "blendShapeNum": len(shapes),
                        "subEntries": list(mergedRegion),
                        "aabb": aabb,
                        "blendSSIndex": ssIndex,
                    }
                )
                portionOffset += vertCount
        if EXPORT_WILDS_DEBUG_FIRST_TARGET_ONLY and len(targets) > 1:
            # Keep only the first target; trim its names and deltas from the shared lists too.
            dropped = targets[1:]
            targets = targets[:1]
            droppedNames = sum(t["blendShapeNum"] for t in dropped)
            del blendNames[len(blendNames) - droppedNames :]
            del deltaChunks[len(deltaChunks) - len(dropped) :]
        perLodList.append({"targets": targets, "typing": blockTyping, "blendS": blockBlendS})
    if not anyBlend:
        return None, None, None
    return b"".join(deltaChunks), perLodList, blendNames


def serializeWildsBlendShapeRegion(perLodList, baseOffset):
    # Serialize BlendShapeHeader + per-LOD BlendShapeData (+ BlendTarget/BlendSubMesh/AABB/blendS/
    # blendSSList sub-blocks) into one contiguous byte block at absolute file offset baseOffset,
    # computing every internal absolute offset. Mirrors the import struct layout, with one or more
    # blend targets per LOD. The importer reads blendS/blendSSList immediately after the AABB list,
    # so those must be contiguous with it.
    def subsOf(t):
        # Normalize to (startIdx, vertOffset|None, vertCount). subEntries3 carries the original's exact
        # cumulative vertOffsets; plain subEntries (custom path) leaves vertOffset None to be computed.
        if "subEntries3" in t:
            return [tuple(se) for se in t["subEntries3"]]
        return [(s, None, c) for (s, c) in t["subEntries"]]

    count = len(perLodList)
    headerSize = getPaddedPos(32 + count * 8, 16)
    layout = []
    cur = headerSize
    for lod in perLodList:
        targets = lod["targets"]
        nTargets = len(targets)
        dataStructOff = cur
        cur += 48
        targetListOff = cur
        cur += 16 * nTargets
        subOffsets = []
        for t in targets:
            subOffsets.append(cur)
            cur += 16 * len(subsOf(t))
        aabbOff = cur
        cur += 32 * nTargets
        blendSOff = cur  # blendS + blendSSList must follow the AABB list (read sequentially)
        cur += 12
        blendSSOff = cur
        cur += sum(t["blendShapeNum"] for t in targets) * 4
        cur = getPaddedPos(cur, 16)
        layout.append(
            {
                "dataStructOff": dataStructOff,
                "targetListOff": targetListOff,
                "subOffsets": subOffsets,
                "aabbOff": aabbOff,
                "blendSOff": blendSOff,
                "blendSSOff": blendSSOff,
            }
        )
    buf = bytearray(cur)
    struct.pack_into("<Q", buf, 0, count)
    struct.pack_into("<Q", buf, 8, 0)  # zero
    # mainOffset: the engine's load-time relocation reads this field (blendShapes+0x10) and uses it as the
    # pointer to the per-block offset array (blendShapeOffsetList), which sits right after the 32-byte
    # header. It MUST point at baseOffset+0x20 (matches vanilla = baseOffset+32). Pointing it at
    # baseOffset+headerSize (the first data block) makes the engine read the block's targetCount/typing
    # bytes as block-offset pointers -> rebases garbage -> deref -> access violation on hover. The import
    # decoder ignores this field (reads the list at +0x20 directly), which hid the bug. (Found via the
    # MonsterHunterWilds.exe+0xA9A7BCC crash disasm: the mesh is a self-relocating blob, base+offset.)
    struct.pack_into("<Q", buf, 16, baseOffset + 32)  # mainOffset -> blendShapeOffsetList
    struct.pack_into("<Q", buf, 24, 0)  # hash
    for i, lay in enumerate(layout):
        struct.pack_into("<Q", buf, 32 + i * 8, baseOffset + lay["dataStructOff"])
    for lod, lay in zip(perLodList, layout):
        targets = lod["targets"]
        nTargets = len(targets)
        d = lay["dataStructOff"]
        # unknFlag = (total blend shapes in this block << 16) | first target's blendSSIndex.
        # Verified against the original face: e.g. (41<<16)|41 = 2687017. The engine uses this to
        # size/index the block's blend shapes; writing 0 here is what crashed the GPU at load.
        totalShapes = sum(t["blendShapeNum"] for t in targets)
        firstSSIndex = targets[0]["blendSSIndex"] if targets else 0
        # typing: the engine reads only the first target unless this signals multi-target. Originals:
        # single-target face = 7, multi-target corrective armor (ch03_090_0012) = 3. With 7 on a
        # multi-target block the runtime allocated channels for target[0] only (12 of 13). Use 3 when
        # there's more than one target so every target's shapes get channels.
        struct.pack_into("<H", buf, d + 0, nTargets)  # targetCount
        # Faithful typing from the captured block wins; else the debug force; else the nTargets rule.
        typingVal = lod.get("typing") or EXPORT_WILDS_DEBUG_FORCE_TYPING or (3 if nTargets > 1 else 7)
        struct.pack_into("<H", buf, d + 2, typingVal)  # typing
        struct.pack_into("<I", buf, d + 4, (totalShapes << 16) | (firstSSIndex & 0xFFFF))  # unknFlag
        struct.pack_into("<I", buf, d + 8, 0)  # padding1
        struct.pack_into("<I", buf, d + 12, 0)  # padding2
        struct.pack_into("<Q", buf, d + 16, baseOffset + lay["targetListOff"])  # dataOffset
        struct.pack_into("<Q", buf, d + 24, baseOffset + lay["aabbOff"])  # aabbOffset
        struct.pack_into("<Q", buf, d + 32, baseOffset + lay["blendSOff"])  # blendSOffset
        struct.pack_into("<Q", buf, d + 40, baseOffset + lay["blendSSOff"])  # blendSSOffset
        for ti, t in enumerate(targets):
            tOff = lay["targetListOff"] + ti * 16
            sOff = lay["subOffsets"][ti]
            struct.pack_into("<H", buf, tOff + 0, t["blendSSIndex"])
            struct.pack_into("<H", buf, tOff + 2, t["blendShapeNum"])
            struct.pack_into("<H", buf, tOff + 4, 0)  # unkn0
            subs = subsOf(t)
            struct.pack_into("<B", buf, tOff + 6, len(subs))  # subMeshEntryCount
            struct.pack_into("<B", buf, tOff + 7, 1)  # unkn2
            struct.pack_into("<Q", buf, tOff + 8, baseOffset + sOff)  # subMeshEntryOffset
            cumOff = 0
            for j, (startIdx, vertOffset, vertCount) in enumerate(subs):
                o = sOff + j * 16
                struct.pack_into("<I", buf, o + 0, startIdx)  # subMeshVertexStartIndex
                # Use the recorded vertOffset (cumulative across the block in the original) when present;
                # otherwise compute it per-target for the simplified/custom path.
                struct.pack_into("<I", buf, o + 4, cumOff if vertOffset is None else vertOffset)
                struct.pack_into("<I", buf, o + 8, vertCount)
                struct.pack_into("<I", buf, o + 12, 0)  # paramUnkn3
                cumOff += vertCount
            aabb = t["aabb"]
            ao = lay["aabbOff"] + ti * 32
            struct.pack_into("<4f", buf, ao + 0, aabb.min.x, aabb.min.y, aabb.min.z, 0.0)
            struct.pack_into("<4f", buf, ao + 16, aabb.max.x, aabb.max.y, aabb.max.z, 0.0)
        # blendSSList holds one int per shape, running continuously 0..(totalShapes-1) across ALL
        # targets in the block (verified against the original ch03_090_0012: 5 targets of 1,1,1,1,8
        # shapes give [0..11], not a per-target restart). The face's single target made both readings
        # identical; the multi-target armor disambiguates. blendS (3 ints) stays zero (face uses that).
        blendSVals = (lod.get("blendS") or [0, 0, 0])[:3]
        for k, v in enumerate(blendSVals):
            struct.pack_into("<i", buf, lay["blendSOff"] + k * 4, int(v))
        ssCursor = lay["blendSSOff"]
        ssVal = 0
        for t in targets:
            for _i in range(t["blendShapeNum"]):
                struct.pack_into("<i", buf, ssCursor, ssVal)
                ssCursor += 4
                ssVal += 1
    return bytes(buf)


def WriteToFaceBuffer(bufferStream, faceList):
    data = struct.pack(f"{len(faceList) * 3}H", *chain.from_iterable(faceList))

    if (len(data)) % 4 != 0:  # Align face buffer to 4 bytes per submesh
        data += b"\x00\x00"
    bufferStream.write(data)


def WriteToIntFaceBuffer(bufferStream, faceList):
    data = struct.pack(f"{len(faceList) * 3}I", *chain.from_iterable(faceList))

    # if (len(data))%4 != 0:#Align face buffer to 4 bytes per submesh
    # data += b'\x00\x00\x00\x00'
    bufferStream.write(data)


class sizeData:
    def __init__(self, version):
        self.MESH_HEADER_SIZE = 128
        if version >= VERSION_SF6:
            self.MESH_HEADER_SIZE = 168
        if version >= VERSION_DD2:
            self.MESH_HEADER_SIZE = 176
        self.LOD_HEADER_OFFSET_LIST_OFFSET = (
            64  # Offset from start of lod header to offset list
        )
        self.LOD_GROUP_HEADER_OFFSET_LIST_OFFSET = (
            16  # Offset from start of lod group to offset list
        )
        self.MESH_GROUP_SIZE = 16
        self.MATERIAL_SUBDIVISION_SIZE = 24
        self.SKELETON_REMAP_TABLE_OFFSET = 48
        self.BONE_INFO_ENTRY_SIZE = 16
        self.MATRIX_SIZE = 64
        self.AABB_OFFSET = 16
        self.AABB_SIZE = 32
        self.VERTEX_ELEMENT_OFFSET = 64
        self.STREAMING_HEADER_SIZE = 16  # WILDS
        if version < VERSION_RE8:
            self.LOD_HEADER_OFFSET_LIST_OFFSET = 72
            self.MATERIAL_SUBDIVISION_SIZE = 16

        if version <= VERSION_RE8:
            self.VERTEX_ELEMENT_OFFSET = 48
        if version >= VERSION_SF6:
            self.VERTEX_ELEMENT_OFFSET = 80

        if version >= VERSION_DD2NEW:
            self.MATERIAL_SUBDIVISION_SIZE = 28

        if version >= VERSION_DR:
            self.MATERIAL_SUBDIVISION_SIZE = 32

        if version >= VERSION_PRAGDEMO:
            self.VERTEX_ELEMENT_OFFSET = 96

        self.VERTEX_ELEMENT_SIZE = 8


def buildWildsNormalRecalcTail(vertexCount, faceBytes, indexSize):
    # MH Wilds blend-shaped meshes run a GPU normal-recalculation pass over the deformed vertices, and
    # it reads two index arrays from the front of the streaming entry's undeclared tail (before the
    # blend deltas): one IndexNormalRecalc (u16 index, u8, u8) per FACE index, then one per vertex
    # (this face-then-vertex order is what the original files use; the streamingBufferHeader offsets
    # word8/word9 mark the boundaries). Without this section the engine allocates a zero-size buffer
    # for the pass and crashes with D3D E_INVALIDARG the moment the mesh loads. The adjacency bytes
    # (left/right) only affect normal quality during deformation, so we emit a correctly-sized section
    # with valid in-range indices (real corner vertex for faces, self for verts) and zero adjacency.
    # Returns (faceArrayBytes, vertArrayBytes), each padded to 16.
    indexCount = len(faceBytes) // indexSize
    fmt = "<I" if indexSize == 4 else "<H"
    fbuf = bytearray()
    for k in range(indexCount):
        vi = struct.unpack_from(fmt, faceBytes, k * indexSize)[0]
        fbuf += struct.pack("<HBB", vi & 0xFFFF, 0, 0)
    fbuf += b"\x00" * (-len(fbuf) % 16)
    vbuf = bytearray()
    for k in range(vertexCount):
        vbuf += struct.pack("<HBB", k & 0xFFFF, 0, 0)
    vbuf += b"\x00" * (-len(vbuf) % 16)
    return bytes(fbuf), bytes(vbuf)


def convertToStreamedWilds(reMesh, blendDeltaBytes=b"", blendPerLodList=None):
    # Post-process the inline-built mesh into the MH Wilds 2-file streamed layout: each LOD's geometry
    # (+ blend deltas + faces) becomes a streaming entry in the companion file, the base file holds the
    # streaming bookkeeping (streamingInfo + streamingBufferHeaderList + per-entry vertex elements), and
    # every submesh's vertexBufferIndex points at its LOD's entry. The base vertex buffer holds a
    # resident copy of the inline geometry (a zero-size GPU buffer crashes the engine).
    mbh = reMesh.meshBufferHeader
    if mbh is None or reMesh.lodHeader is None or not mbh.vertexElementList:
        return False
    elements = mbh.vertexElementList
    inlineVtx = bytes(mbh.vertexBuffer)
    inlineFace = bytes(mbh.faceBuffer)
    indexSize = 4 if reMesh.lodHeader.has32BitIndexBuffer else 2
    mainVEC = len(elements)

    # Blend deltas (Stage B): the importer/engine reads them from the undeclared tail of each streaming
    # entry's vertex buffer, after the declared geometry. Slice the flat delta blob per LOD (the blob
    # is concatenated in the same LOD -> target order as blendPerLodList).
    perLodDeltas = []
    if blendDeltaBytes and blendPerLodList is not None:
        cur = 0
        for lod in blendPerLodList:
            sz = 0
            for t in lod["targets"]:
                if "subEntries3" in t:
                    verts = sum(vc for (_si, _vo, vc) in t["subEntries3"])
                else:
                    verts = sum(vc for (_si, vc) in t["subEntries"])
                sz += t["blendShapeNum"] * verts * 4
            perLodDeltas.append(blendDeltaBytes[cur : cur + sz])
            cur += sz
            if DEBUG_STREAMING_BUILD:
                def _tgtVerts(t):
                    if "subEntries3" in t:
                        return sum(vc for (_s, _vo, vc) in t["subEntries3"])
                    return sum(vc for (_s, vc) in t["subEntries"])
                print(
                    f"[BSCONV] lod expectedDeltaBytes={sz} sliceBytes={len(perLodDeltas[-1])} "
                    f"totalBlendDeltaBytes={len(blendDeltaBytes)} "
                    f"targets={[(t['blendShapeNum'], _tgtVerts(t)) for t in lod['targets']]}"
                )

    streamingBytes = bytearray()
    streamInfo = []  # (bufferStart, bufferLength)
    streamEntries = []  # dicts: total, vbl, unpadded, vCount, elemOffsets
    for li, lodGroup in enumerate(reMesh.lodHeader.lodGroupList):
        if not lodGroup.meshGroupList or not lodGroup.meshGroupList[0].vertexInfoList:
            continue
        firstSub = lodGroup.meshGroupList[0].vertexInfoList[0]
        vStart = firstSub.vertexStartIndex
        fStart = firstSub.faceStartIndex
        vCount = sum(mg.vertexCount for mg in lodGroup.meshGroupList)
        fCount = sum(mg.faceCount for mg in lodGroup.meshGroupList)
        geom = bytearray()
        elemOffsets = []
        for ve in elements:
            elemOffsets.append(len(geom))
            s = ve.stride
            geom += inlineVtx[
                ve.posStartOffset + vStart * s : ve.posStartOffset + (vStart + vCount) * s
            ]
        faces = inlineFace[fStart * indexSize : (fStart + fCount) * indexSize]
        blendTail = perLodDeltas[li] if li < len(perLodDeltas) else b""
        # When this LOD carries blend deltas it also needs the normal-recalc section in front of them
        # (the engine runs the normal-recalc pass whenever a mesh has blend shapes). Order in the tail:
        # geometry, pad16, [normal-recalc face array][normal-recalc vert array], blend deltas, faces.
        # The originals pad the geometry up to 16 before the tail so every sub-buffer (normal-recalc
        # arrays, deltas) starts 16-aligned — required or the GPU buffer view fails with E_INVALIDARG.
        geomEnd = getPaddedPos(len(geom), 16)
        geomPad = geomEnd - len(geom)
        if blendTail and not EXPORT_WILDS_DEBUG_NO_NORMALRECALC:
            nrFace, nrVert = buildWildsNormalRecalcTail(vCount, faces, indexSize)
        else:
            nrFace, nrVert = (b"", b"")
        deltaStart = geomEnd + len(nrFace) + len(nrVert)
        vbl = deltaStart + len(blendTail)
        unpadded = vbl + len(faces)
        total = getPaddedPos(unpadded, 16)
        bufStart = len(streamingBytes)
        entryData = bytearray(geom)
        entryData += b"\x00" * geomPad
        entryData += nrFace
        entryData += nrVert
        entryData += blendTail
        entryData += faces
        entryData += b"\x00" * (total - unpadded)
        streamingBytes += entryData
        streamInfo.append((bufStart, total))
        streamEntries.append(
            {
                "total": total, "vbl": vbl, "unpadded": unpadded, "vCount": vCount,
                "elemOffsets": elemOffsets, "geomEnd": geomEnd,
                "nrVertStart": geomEnd + len(nrFace), "deltaStart": deltaStart, "vbi": li + 1,
            }
        )
        # Submeshes now read from this entry, with per-LOD-relative start indices.
        for mg in lodGroup.meshGroupList:
            for sub in mg.vertexInfoList:
                sub.vertexBufferIndex = li + 1
                sub.vertexStartIndex -= vStart
                sub.faceStartIndex -= fStart
    entryCount = len(streamEntries)
    if entryCount == 0:
        return False
    reMesh.streamingBytes = bytes(streamingBytes)

    # Mesh region byte layout (relative to meshOffset), matching the original streamed mesh.
    M = reMesh.fileHeader.meshOffset
    headerSize = 80
    elemBlock = getPaddedPos(mainVEC * 8, 16)
    sbhlOff = headerSize
    siEntriesOff = sbhlOff + entryCount * 64
    siStructOff = getPaddedPos(siEntriesOff + entryCount * 8, 16)
    baseElemOff = siStructOff + 16
    streamVEOff = getPaddedPos(baseElemOff + mainVEC * 8, 16)
    baseVtxOff = getPaddedPos(streamVEOff + entryCount * elemBlock, 16)
    # The base buffer must be non-empty (a zero-size GPU buffer crashes the engine with E_INVALIDARG),
    # but it must NOT be a full copy of the streamed blend-target LOD or the blend loader treats the
    # resident as a blend target and crashes. Emit a small distinct resident (first N verts re-laid-out)
    # mirroring how the original keeps a tiny low LOD resident; everything is rendered from vbi>=1.
    if EXPORT_WILDS_DEBUG_SMALL_BASE:
        inlineVertTotal = (
            (elements[1].posStartOffset - elements[0].posStartOffset) // elements[0].stride
            if len(elements) >= 2 and elements[0].stride
            else (len(inlineVtx) // elements[0].stride if elements[0].stride else 0)
        )
        baseN = max(3, min(128, inlineVertTotal))
        baseElements = []  # (typing, stride, offset) into the small base buffer
        baseVtxBuf = bytearray()
        for ve in elements:
            baseElements.append((ve.typing, ve.stride, len(baseVtxBuf)))
            baseVtxBuf += inlineVtx[ve.posStartOffset : ve.posStartOffset + baseN * ve.stride]
        nTris = max(1, min(8, baseN // 3))
        idxList = []
        for t in range(nTris):
            a = (t * 3) % baseN
            idxList += [a, (a + 1) % baseN, (a + 2) % baseN]
        baseFaceBuf = struct.pack(
            f"<{len(idxList)}{'I' if indexSize == 4 else 'H'}", *idxList
        )
    else:
        baseElements = [(ve.typing, ve.stride, ve.posStartOffset) for ve in elements]
        baseVtxBuf = bytearray(inlineVtx)
        baseFaceBuf = inlineFace
    baseVtxSize = getPaddedPos(len(baseVtxBuf), 16)
    baseFaceOff = baseVtxOff + baseVtxSize
    baseFaceSize = len(baseFaceBuf)
    block2 = baseVtxSize + baseFaceSize
    regionEnd = getPaddedPos(baseFaceOff + baseFaceSize, 16)

    reMesh.fileHeader.streamingInfoOffset = M + siStructOff
    reMesh.fileHeader.verticesOffset = M + baseVtxOff
    # Resident-blend (single-file) experiment: append the streamed buffer to the BASE file and make every
    # streamingInfo.bufferStart an in-base absolute offset, so deltaAddr = bufferStart + word9 lands on the
    # bytes we wrote. Otherwise the streamed buffer goes to a separate companion (bufferStart 0-based).
    residentBlend = EXPORT_WILDS_RESIDENT_BLEND
    baseStreamOffset = getPaddedPos(M + regionEnd, 16)
    if residentBlend:
        reMesh.fileHeader.fileSize = baseStreamOffset + len(streamingBytes)
    else:
        reMesh.fileHeader.fileSize = M + regionEnd

    buf = bytearray(regionEnd)
    sp = struct.pack_into
    # meshBufferHeader header (SF6+)
    sp("<Q", buf, 0, M + baseElemOff)  # vertexElementOffset
    sp("<Q", buf, 8, M + baseVtxOff)  # vertexBufferOffset
    sp("<Q", buf, 16, 0)  # sunbreakOffset
    sp("<I", buf, 24, getPaddedPos(block2, 16))  # totalBufferSize
    sp("<I", buf, 28, baseVtxSize)  # vertexBufferSize
    sp("<H", buf, 32, mainVEC)  # mainVertexElementCount
    sp("<H", buf, 34, mainVEC)  # vertexElementCount (base declarations)
    sp("<I", buf, 36, block2)  # block2FaceBufferOffset
    sp("<I", buf, 40, block2)  # NULL
    sp("<h", buf, 44, 27104)  # vertexElementSize
    sp("<h", buf, 46, -1)  # unkn1
    sp("<Q", buf, 48, 0)  # sunbreakSecondUnknown
    sp("<Q", buf, 56, 0)  # sf6unkn0
    sp("<Q", buf, 64, M + streamVEOff)  # streamingVertexElementOffset
    sp("<Q", buf, 72, 0)  # sf6unkn2
    # streamingBufferHeaderList
    for i, e in enumerate(streamEntries):
        b = sbhlOff + i * 64
        sp("<I", buf, b + 8, e["total"])
        sp("<I", buf, b + 12, e["vbl"])
        sp("<H", buf, b + 16, mainVEC)
        sp("<H", buf, b + 18, mainVEC)
        sp("<I", buf, b + 20, e["unpadded"])
        sp("<I", buf, b + 24, e["unpadded"])
        # Tail sub-region offsets the engine uses to locate the normal-recalc arrays and blend deltas.
        # geometry ends at geomEnd; normal-recalc face array [geomEnd, nrVertStart); vert array
        # [nrVertStart, deltaStart); deltas at deltaStart. All three collapse to geomEnd when no tail.
        sp("<I", buf, b + 28, e["geomEnd"])  # word7: end of declared geometry
        sp("<I", buf, b + 32, e["nrVertStart"])  # word8: normal-recalc vertex array start
        sp("<I", buf, b + 36, e["deltaStart"])  # word9: blend delta start
        sp("<I", buf, b + 44, e["vbi"])  # word11: vertexBufferIndex that reads this entry
        sp("<Q", buf, b + 48, M + streamVEOff + i * elemBlock)  # word12: this entry's vertex elements
        sp("<I", buf, b + 56, (baseStreamOffset if residentBlend else 0) + streamInfo[i][0] + e["total"])  # nextBufferOffset
    # streamingInfo entries
    for i, (bs, bl) in enumerate(streamInfo):
        o = siEntriesOff + i * 8
        sp("<I", buf, o + 0, (baseStreamOffset + bs) if residentBlend else bs)
        sp("<I", buf, o + 4, bl)
    # streamingInfo struct
    sp("<I", buf, siStructOff + 0, entryCount)
    sp("<I", buf, siStructOff + 4, 0)
    sp("<Q", buf, siStructOff + 8, M + siEntriesOff)
    # base vertex elements (declarations for the resident base buffer)
    for j, (typing, stride, off) in enumerate(baseElements):
        eo = baseElemOff + j * 8
        sp("<H", buf, eo + 0, typing)
        sp("<H", buf, eo + 2, stride)
        sp("<I", buf, eo + 4, off)
    # per-entry vertex elements (offsets relative to each entry's geometry)
    for i, e in enumerate(streamEntries):
        base = streamVEOff + i * elemBlock
        for j, ve in enumerate(elements):
            eo = base + j * 8
            sp("<H", buf, eo + 0, ve.typing)
            sp("<H", buf, eo + 2, ve.stride)
            sp("<I", buf, eo + 4, e["elemOffsets"][j])
    # base vertex buffer + face buffer (small resident stub or full copy, per the flag)
    buf[baseVtxOff : baseVtxOff + len(baseVtxBuf)] = baseVtxBuf
    buf[baseFaceOff : baseFaceOff + len(baseFaceBuf)] = baseFaceBuf
    reMesh.meshRegionBytes = bytes(buf)
    reMesh.isStreamed = True
    reMesh.streamInBase = residentBlend
    if DEBUG_STREAMING_BUILD:
        if residentBlend:
            print(
                f"[STRM] RESIDENT-BLEND single-file: streamingBytes={len(streamingBytes)} appended to base "
                f"at offset {baseStreamOffset}; bufferStarts rebased; fileSize={reMesh.fileHeader.fileSize}"
            )
        print(
            f"[STRM] BUILT streamed: entries={entryCount} streamingBytes={len(streamingBytes)} "
            f"regionSize={regionEnd} meshOffset={M} streamingInfoOffset={M + siStructOff} "
            f"vertexElementOffset={M + baseElemOff} streamingVEO={M + streamVEOff} fileSize={M + regionEnd}"
        )
        for i, e in enumerate(streamEntries):
            print(
                f"[STRM]  entry[{i}] total={e['total']} vbl={e['vbl']} unpadded={e['unpadded']} "
                f"vCount={e['vCount']} bufStart={streamInfo[i][0]}"
            )
    return True


def convertToFixedBlendWilds(reMesh, blendDeltaBytes=b"", blendPerLodList=None):
    # Phase 2 fixed/resident blend experiment. Single LOD only (export with "Export All LODs" OFF). Lays
    # the blend submesh's geometry + normal-recalc + deltas into the RESIDENT buffer (the 80-byte mesh
    # header's buffer, read via vbi=0 from the base) and describes the delta tail with ONE streaming-
    # buffer-header entry whose vbi(word11)=0 and word9=deltaStart, with streamingInfo.bufferStart pointing
    # at that resident buffer in-base. Goal: make the engine compute get_BlendShapeFixBufferSize > 0.
    mbh = reMesh.meshBufferHeader
    if mbh is None or reMesh.lodHeader is None or not mbh.vertexElementList:
        return False
    elements = mbh.vertexElementList
    inlineVtx = bytes(mbh.vertexBuffer)
    inlineFace = bytes(mbh.faceBuffer)
    indexSize = 4 if reMesh.lodHeader.has32BitIndexBuffer else 2
    mainVEC = len(elements)
    lodGroups = reMesh.lodHeader.lodGroupList
    if not lodGroups:
        return False
    if len(lodGroups) > 1 and DEBUG_STREAMING_BUILD:
        print(f"[FIXBLEND] WARNING: {len(lodGroups)} LODs present; fixed-buffer mode uses LOD0 only. Export with 'Export All LODs' OFF.")
    lodGroup = lodGroups[0]
    if not lodGroup.meshGroupList or not lodGroup.meshGroupList[0].vertexInfoList:
        return False

    firstSub = lodGroup.meshGroupList[0].vertexInfoList[0]
    vStart = firstSub.vertexStartIndex
    fStart = firstSub.faceStartIndex
    vCount = sum(mg.vertexCount for mg in lodGroup.meshGroupList)
    fCount = sum(mg.faceCount for mg in lodGroup.meshGroupList)

    geom = bytearray()
    elemOffsets = []
    for ve in elements:
        elemOffsets.append(len(geom))
        s = ve.stride
        geom += inlineVtx[ve.posStartOffset + vStart * s : ve.posStartOffset + (vStart + vCount) * s]
    faces = inlineFace[fStart * indexSize : (fStart + fCount) * indexSize]
    deltas = blendDeltaBytes or b""  # single LOD: all the delta bytes belong here

    geomEnd = getPaddedPos(len(geom), 16)
    geomPad = geomEnd - len(geom)
    if deltas and not EXPORT_WILDS_DEBUG_NO_NORMALRECALC:
        nrFace, nrVert = buildWildsNormalRecalcTail(vCount, faces, indexSize)
    else:
        nrFace, nrVert = (b"", b"")
    nrVertStart = geomEnd + len(nrFace)
    deltaStart = nrVertStart + len(nrVert)
    residentBuf = bytearray(geom)
    residentBuf += b"\x00" * geomPad
    residentBuf += nrFace
    residentBuf += nrVert
    residentBuf += deltas
    vbl = len(residentBuf)  # vertex buffer length = geometry + tail (== deltaStart + len(deltas))

    M = reMesh.fileHeader.meshOffset
    elemBlock = getPaddedPos(mainVEC * 8, 16)
    sbhlOff = 80
    entryCount = 1
    siEntriesOff = sbhlOff + entryCount * 64
    siStructOff = getPaddedPos(siEntriesOff + entryCount * 8, 16)
    baseElemOff = siStructOff + 16
    streamVEOff = getPaddedPos(baseElemOff + mainVEC * 8, 16)
    baseVtxOff = getPaddedPos(streamVEOff + entryCount * elemBlock, 16)
    baseVtxSize = getPaddedPos(vbl, 16)
    baseFaceOff = baseVtxOff + baseVtxSize
    baseFaceSize = len(faces)
    block2 = baseVtxSize + baseFaceSize
    total = getPaddedPos(block2, 16)
    unpadded = vbl + baseFaceSize
    regionEnd = getPaddedPos(baseFaceOff + baseFaceSize, 16)

    reMesh.fileHeader.streamingInfoOffset = M + siStructOff
    reMesh.fileHeader.verticesOffset = M + baseVtxOff
    reMesh.fileHeader.fileSize = M + regionEnd

    buf = bytearray(regionEnd)
    sp = struct.pack_into
    # 80-byte mesh buffer header (SF6+)
    sp("<Q", buf, 0, M + baseElemOff)   # vertexElementOffset
    sp("<Q", buf, 8, M + baseVtxOff)    # vertexBufferOffset
    sp("<Q", buf, 16, 0)               # sunbreakOffset
    sp("<I", buf, 24, total)           # totalBufferSize
    sp("<I", buf, 28, baseVtxSize)     # vertexBufferSize
    sp("<H", buf, 32, mainVEC)
    sp("<H", buf, 34, mainVEC)
    sp("<I", buf, 36, block2)          # block2FaceBufferOffset
    sp("<I", buf, 40, block2)          # NULL
    sp("<h", buf, 44, 27104)           # vertexElementSize
    sp("<h", buf, 46, -1)
    sp("<Q", buf, 48, 0)
    sp("<Q", buf, 56, 0)
    sp("<Q", buf, 64, M + streamVEOff)  # streamingVertexElementOffset
    sp("<Q", buf, 72, 0)
    # ONE streaming buffer header entry describing the resident blend tail, vbi=0 (fixed/resident)
    b = sbhlOff
    sp("<I", buf, b + 8, total)
    sp("<I", buf, b + 12, vbl)
    sp("<H", buf, b + 16, mainVEC)
    sp("<H", buf, b + 18, mainVEC)
    sp("<I", buf, b + 20, unpadded)
    sp("<I", buf, b + 24, unpadded)
    sp("<I", buf, b + 28, geomEnd)      # word7: end of declared geometry
    sp("<I", buf, b + 32, nrVertStart)  # word8: normal-recalc vertex array start
    sp("<I", buf, b + 36, deltaStart)   # word9: blend delta start
    sp("<I", buf, b + 44, 0)            # word11: vbi = 0 (resident -> fixed buffer)
    sp("<Q", buf, b + 48, M + streamVEOff)        # word12: this entry's vertex elements
    sp("<I", buf, b + 56, (M + baseVtxOff) + total)  # nextBufferOffset
    # streamingInfo entry: buffer is the resident buffer, in the base
    sp("<I", buf, siEntriesOff + 0, M + baseVtxOff)
    sp("<I", buf, siEntriesOff + 4, total)
    # streamingInfo struct
    sp("<I", buf, siStructOff + 0, entryCount)
    sp("<I", buf, siStructOff + 4, 0)
    sp("<Q", buf, siStructOff + 8, M + siEntriesOff)
    # base + per-entry vertex element declarations (geometry offsets within the resident buffer)
    for tableOff in (baseElemOff, streamVEOff):
        for j, ve in enumerate(elements):
            eo = tableOff + j * 8
            sp("<H", buf, eo + 0, ve.typing)
            sp("<H", buf, eo + 2, ve.stride)
            sp("<I", buf, eo + 4, elemOffsets[j])
    # resident vertex buffer (geometry + tail) + face buffer
    buf[baseVtxOff : baseVtxOff + len(residentBuf)] = residentBuf
    buf[baseFaceOff : baseFaceOff + len(faces)] = faces

    reMesh.meshRegionBytes = bytes(buf)
    reMesh.isStreamed = True
    reMesh.streamInBase = False  # all data is inside the mesh region; no separate companion append
    reMesh.streamingBytes = b""
    # submeshes read from the resident buffer (vbi=0), with LOD-relative indices
    for mg in lodGroup.meshGroupList:
        for sub in mg.vertexInfoList:
            sub.vertexBufferIndex = 0
            sub.vertexStartIndex -= vStart
            sub.faceStartIndex -= fStart
    if DEBUG_STREAMING_BUILD:
        print(
            f"[FIXBLEND] resident vbi=0 buffer: geom={len(geom)} nrFace={len(nrFace)} nrVert={len(nrVert)} "
            f"deltas={len(deltas)} vbl={vbl} faces={baseFaceSize}"
        )
        print(
            f"[FIXBLEND] authored FIX delta size (vbl-deltaStart)={vbl - deltaStart}  bufferStart(in-base)="
            f"{M + baseVtxOff}  word9(deltaStart)={deltaStart}  fileSize={reMesh.fileHeader.fileSize}"
        )
    return True


def _debugStreamingSplit(reMesh):
    # Preview of the per-LOD streaming split: which LOD goes to the base buffer vs a streaming entry,
    # and each entry's geometry/face byte sizes. Compared against the original face via the Dump
    # button to validate the split before the streaming write is wired in. No file changes.
    if not DEBUG_STREAMING_BUILD or reMesh.lodHeader is None:
        return
    mbh = reMesh.meshBufferHeader
    if mbh is None or not mbh.vertexElementList:
        return
    vbytesPerVert = sum(ve.stride for ve in mbh.vertexElementList)
    indexSize = 4 if reMesh.lodHeader.has32BitIndexBuffer else 2
    lodGroups = reMesh.lodHeader.lodGroupList
    nLod = len(lodGroups)
    print("[STRM] ===== STREAMING SPLIT PREVIEW =====")
    print(
        f"[STRM] numLODs={nLod} vertexBytesPerVertex={vbytesPerVert} indexSize={indexSize} "
        f"elements={[(ve.typing, ve.stride) for ve in mbh.vertexElementList]}"
    )
    for li, lodGroup in enumerate(lodGroups):
        if not lodGroup.meshGroupList or not lodGroup.meshGroupList[0].vertexInfoList:
            continue
        firstSub = lodGroup.meshGroupList[0].vertexInfoList[0]
        vStart = firstSub.vertexStartIndex
        fStart = firstSub.faceStartIndex
        vCount = sum(mg.vertexCount for mg in lodGroup.meshGroupList)
        fCount = sum(mg.faceCount for mg in lodGroup.meshGroupList)
        geomBytes = vCount * vbytesPerVert
        faceBytes = fCount * indexSize
        isBase = li == nLod - 1
        vbi = 0 if isBase else li + 1
        print(
            f"[STRM] LOD{li} {'BASE(vbi=0)' if isBase else f'STREAM entry{li}(vbi={vbi})'}: "
            f"globalVertStart={vStart} vCount={vCount} geomBytes={geomBytes} globalFaceStart={fStart} "
            f"fCount={fCount} faceBytes={faceBytes} entryTotal~={getPaddedPos(geomBytes + faceBytes, 16)}"
        )
    print("[STRM] ===================================")


def ParsedREMeshToREMesh(parsedMesh, meshVersion):
    print(f"Mesh Version:{meshVersion}")
    version = meshFileVersionToNewVersionDict.get(
        meshVersion, getNearestRemapVersion(meshVersion)
    )
    print(f"Remapped Version:{version}")
    sd = sizeData(version)
    currentOffset = 0
    currentVertexIndex = 0
    currentFaceIndex = 0

    # totalTangentGenerationTime = 0.0#For benchmarking the time it takes tangents to calculate

    # Buffers
    vertexPosBuffer = BytesIO()
    norTanBuffer = BytesIO()
    UVBuffer = BytesIO()
    UV2Buffer = BytesIO()
    weightBuffer = BytesIO()
    colorBuffer = BytesIO()
    faceBuffer = BytesIO()
    extraWeightBuffer = BytesIO()  # MH Wilds extended weight buffer
    secondaryWeightBuffer = BytesIO()  # DD2 shapekey

    parsedSubMeshToSubMeshDataDict = dict()

    reMesh = REMesh()

    reMesh.fileHeader.version = meshFileVersionToInternalVersionDict.get(
        meshVersion, getNearestRemapVersion(meshVersion)
    )
    # TODO Fix shadow mesh export, causes game to crash. It seems shadow meshes can't have unique lods, even if the sub mesh offsets are still shared. They might only be able to use the existing full lods from the main mesh
    # parsedMesh.shadowMeshLODList.clear()

    # Main Meshes
    if parsedMesh.mainMeshLODList != []:
        reMesh.fileHeader.meshGroupOffset = sd.MESH_HEADER_SIZE
        reMesh.lodHeader = MainMeshHeader()
        reMesh.lodHeader.lodGroupCount = len(parsedMesh.mainMeshLODList)
        reMesh.lodHeader.materialCount = len(parsedMesh.materialNameList)
        reMesh.lodHeader.bbox = parsedMesh.boundingBox
        reMesh.lodHeader.sphere = parsedMesh.boundingSphere
        for viscon in parsedMesh.mainMeshLODList[0].visconGroupList:
            reMesh.lodHeader.totalMeshCount += len(viscon.subMeshList)
        reMesh.lodHeader.skinWeightCount = 18
        if version == VERSION_SF6:
            reMesh.lodHeader.skinWeightCount = 9
        elif version == VERSION_MHWILDS:
            reMesh.lodHeader.skinWeightCount = 25  # Not sure why but this fixes monsters causing crashes and dead hitbox issues
        elif version == VERSION_PRAGDEMO:
            reMesh.lodHeader.skinWeightCount = 27  #
        elif version == VERSION_RE9:
            reMesh.lodHeader.skinWeightCount = 18  #
        if parsedMesh.bufferHasUV2:  # This is wrong, uv count is determined by something else. However uv count is unused by the game so it doesn't really matter
            reMesh.lodHeader.uvCount = 2
        else:
            reMesh.lodHeader.uvCount = 1
        if parsedMesh.bufferHasIntFaces:
            reMesh.lodHeader.has32BitIndexBuffer = 1
        reMesh.lodHeader.offsetOffset = (
            sd.MESH_HEADER_SIZE + sd.LOD_HEADER_OFFSET_LIST_OFFSET
        )

        # currentOffset = LOD Group 0 offset
        currentOffset = (
            reMesh.lodHeader.offsetOffset
            + 8 * reMesh.lodHeader.lodGroupCount
            + getPaddingAmount(
                reMesh.lodHeader.offsetOffset + (8 * reMesh.lodHeader.lodGroupCount), 16
            )
        )

        # SF6 uses six weights with higher possible bone index values
        isSixWeight = version in SIX_WEIGHT_GAMES

        # Main Meshes
        # TODO Move lod parsing into a function and call it for both main and shadow mesh
        for lod in parsedMesh.mainMeshLODList:
            reMesh.lodHeader.lodGroupOffsetList.append(currentOffset)
            lodGroupHeader = LODGroupHeader()
            lodGroupHeader.count = len(lod.visconGroupList)
            lodGroupHeader.distance = lod.lodDistance
            currentOffset += sd.LOD_GROUP_HEADER_OFFSET_LIST_OFFSET
            lodGroupHeader.offsetOffset = currentOffset
            # Viscon 0 Offset
            currentOffset = (
                lodGroupHeader.offsetOffset
                + 8 * lodGroupHeader.count
                + getPaddingAmount(
                    lodGroupHeader.offsetOffset + (8 * lodGroupHeader.count), 16
                )
            )
            for viscon in lod.visconGroupList:
                lodGroupHeader.meshGroupOffsetList.append(currentOffset)
                # print(f"viscon {viscon.visconGroupNum} offset: {str(currentOffset)}")
                meshGroup = MeshGroup()
                meshGroup.visconGroupID = viscon.visconGroupNum
                meshGroup.meshCount = len(viscon.subMeshList)
                for parsedSubMesh in viscon.subMeshList:
                    subMesh = MaterialSubdivision()
                    subMesh.materialIndex = parsedSubMesh.materialIndex
                    subMesh.faceCount = len(parsedSubMesh.faceList) * 3
                    if parsedMesh.bufferHasIntFaces:
                        paddedFaceCount = subMesh.faceCount
                    else:
                        paddedFaceCount = getPaddedPos(subMesh.faceCount, 2)
                    meshGroup.faceCount += paddedFaceCount

                    vertCount = len(parsedSubMesh.vertexPosList)
                    meshGroup.vertexCount += vertCount
                    parsedSubMeshToSubMeshDataDict[parsedSubMesh] = subMesh
                    if not parsedSubMesh.isReusedMesh:
                        subMesh.faceStartIndex = currentFaceIndex
                        subMesh.vertexStartIndex = currentVertexIndex
                        currentVertexIndex += vertCount
                        currentFaceIndex += paddedFaceCount
                        # TODO Add vertices and faces to buffers
                        WriteToVertexPosBuffer(
                            vertexPosBuffer, parsedSubMesh.vertexPosList
                        )

                        # tangentGenerationStartTime = time.time()
                        WriteToNorTanBuffer(
                            norTanBuffer,
                            parsedSubMesh.normalList,
                            parsedSubMesh.tangentList,
                        )
                        # WriteToNorTanBufferOld(norTanBuffer, parsedSubMesh.normalList,parsedSubMesh.vertexPosList,parsedSubMesh.uvList,parsedSubMesh.faceList)
                        # totalTangentGenerationTime +=  (time.time() - tangentGenerationStartTime)

                        # Copy uv1 to uv2 if buffer has uv2, but the mesh only has 1 uv
                        if parsedMesh.bufferHasUV2 and parsedSubMesh.uv2List is None:
                            parsedSubMesh.uv2List = parsedSubMesh.uvList

                        WriteToUVBuffer(UVBuffer, parsedSubMesh.uvList)
                        if parsedSubMesh.uv2List is not None:
                            WriteToUVBuffer(UV2Buffer, parsedSubMesh.uv2List)

                        if len(parsedSubMesh.weightIndicesList) != 0 and len(
                            parsedSubMesh.weightIndicesList
                        ) == len(parsedSubMesh.weightList):
                            if (
                                parsedMesh.bufferHasExtraWeight
                                and len(parsedSubMesh.extraWeightIndicesList) != 0
                                and len(parsedSubMesh.extraWeightIndicesList)
                                == len(parsedSubMesh.extraWeightList)
                            ):
                                WriteToWeightBufferExtended(
                                    weightBuffer,
                                    parsedSubMesh.weightList,
                                    parsedSubMesh.weightIndicesList,
                                    extraWeightBuffer,
                                    parsedSubMesh.extraWeightList,
                                    parsedSubMesh.extraWeightIndicesList,
                                    isSixWeight,
                                )
                            else:
                                WriteToWeightBuffer(
                                    weightBuffer,
                                    parsedSubMesh.weightList,
                                    parsedSubMesh.weightIndicesList,
                                    isSixWeight,
                                )

                        # DD2 shapekeys
                        if len(parsedSubMesh.secondaryWeightIndicesList) != 0 and len(
                            parsedSubMesh.secondaryWeightIndicesList
                        ) == len(parsedSubMesh.secondaryWeightList):
                            WriteToWeightBuffer(
                                secondaryWeightBuffer,
                                parsedSubMesh.secondaryWeightList,
                                parsedSubMesh.secondaryWeightIndicesList,
                                isSixWeight,
                            )

                        # Add vertex color if it's missing and other meshes have it
                        if (
                            parsedMesh.bufferHasColor
                            and parsedSubMesh.colorList is None
                        ):
                            parsedSubMesh.colorList = [(255, 255, 255, 255)] * len(
                                parsedSubMesh.vertexPosList
                            )

                        if parsedSubMesh.colorList is not None:
                            WriteToColorBuffer(colorBuffer, parsedSubMesh.colorList)
                        if parsedMesh.bufferHasIntFaces:
                            WriteToIntFaceBuffer(faceBuffer, parsedSubMesh.faceList)
                        else:
                            WriteToFaceBuffer(faceBuffer, parsedSubMesh.faceList)
                    else:
                        linkedMeshData = parsedSubMeshToSubMeshDataDict[
                            parsedSubMesh.linkedSubMesh
                        ]
                        subMesh.faceStartIndex = linkedMeshData.faceStartIndex
                        subMesh.vertexStartIndex = linkedMeshData.vertexStartIndex
                        # TODO Get linked mesh offset for reused meshes
                        # Make dict of offset key to tuple of vertexstartindex and facestartindex
                        # meshOffsetDict[parsedSubMesh.linkedMesh][0]
                    meshGroup.vertexInfoList.append(subMesh)
                currentOffset += (
                    sd.MESH_GROUP_SIZE
                    + meshGroup.meshCount * sd.MATERIAL_SUBDIVISION_SIZE
                )

                lodGroupHeader.meshGroupList.append(meshGroup)
            reMesh.lodHeader.lodGroupList.append(lodGroupHeader)
    # print(f"Tangent calculation took {timeFormat%(totalTangentGenerationTime * 1000)} ms.")
    # Shadow Meshes

    if parsedMesh.shadowMeshLinkedLODList != []:
        reMesh.fileHeader.shadowMeshGroupOffset = currentOffset
        reMesh.shadowHeader = ShadowHeader()
        reMesh.shadowHeader.skinWeightCount = 18
        reMesh.shadowHeader.lodGroupCount = len(parsedMesh.shadowMeshLinkedLODList)
        reMesh.shadowHeader.materialCount = reMesh.lodHeader.materialCount
        reMesh.shadowHeader.totalMeshCount = reMesh.lodHeader.totalMeshCount

        if parsedMesh.bufferHasUV2:
            reMesh.shadowHeader.uvCount = 2
        else:
            reMesh.shadowHeader.uvCount = 1
        reMesh.shadowHeader.offsetOffset = (
            reMesh.fileHeader.shadowMeshGroupOffset + sd.LOD_HEADER_OFFSET_LIST_OFFSET
        )

        for linkedLOD in parsedMesh.shadowMeshLinkedLODList:
            mainMeshLODIndex = parsedMesh.mainMeshLODList.index(linkedLOD)
            reMesh.shadowHeader.lodGroupOffsetList.append(
                reMesh.lodHeader.lodGroupOffsetList[mainMeshLODIndex]
            )

        # currentOffset = LOD Group 0 offset
        currentOffset = getPaddedPos(
            reMesh.shadowHeader.offsetOffset + 8 * reMesh.shadowHeader.lodGroupCount, 16
        )
    # It turns out shadow meshes can only use existing lods from the main mesh so this was pointless
    """
	if parsedMesh.shadowMeshLODList != []:
		reMesh.fileHeader.shadowMeshGroupOffset = currentOffset
		reMesh.shadowHeader = ShadowHeader()
		reMesh.shadowHeader.skinWeightCount = 18
		reMesh.shadowHeader.lodGroupCount = len(parsedMesh.shadowMeshLODList)
		reMesh.shadowHeader.materialCount = len(parsedMesh.materialNameList)
		for viscon in parsedMesh.shadowMeshLODList[0].visconGroupList:
			reMesh.shadowHeader.totalMeshCount += len(viscon.subMeshList)
		if parsedMesh.bufferHasUV2:
			reMesh.shadowHeader.uvCount = 2
		else:
			reMesh.shadowHeader.uvCount = 1
		reMesh.shadowHeader.offsetOffset = reMesh.fileHeader.shadowMeshGroupOffset+sd.LOD_HEADER_OFFSET_LIST_OFFSET

		#currentOffset = LOD Group 0 offset
		currentOffset = getPaddedPos(reMesh.shadowHeader.offsetOffset + 8*reMesh.shadowHeader.lodGroupCount,16)

		for lod in parsedMesh.shadowMeshLODList:
			reMesh.shadowHeader.lodGroupOffsetList.append(currentOffset)
			lodGroupHeader = LODGroupHeader()
			lodGroupHeader.count = len(lod.visconGroupList)
			lodGroupHeader.distance = lod.lodDistance
			currentOffset += sd.LOD_GROUP_HEADER_OFFSET_LIST_OFFSET
			lodGroupHeader.offsetOffset = currentOffset
			#Viscon 0 Offset
			currentOffset = lodGroupHeader.offsetOffset + 8*lodGroupHeader.count + getPaddingAmount(lodGroupHeader.offsetOffset+(8*lodGroupHeader.count),16)

			for viscon in lod.visconGroupList:
				lodGroupHeader.meshGroupOffsetList.append(currentOffset)
				#print(f"viscon {viscon.visconGroupNum} offset: {str(currentOffset)}")
				meshGroup = MeshGroup()
				meshGroup.visconGroupID = viscon.visconGroupNum
				meshGroup.meshCount = len(viscon.subMeshList)
				for parsedSubMesh in viscon.subMeshList:
					subMesh = MaterialSubdivision()
					parsedSubMeshToSubMeshDataDict[parsedSubMesh] = subMesh
					subMesh.materialIndex = parsedSubMesh.materialIndex
					subMesh.faceCount = len(parsedSubMesh.faceList) * 3
					paddedFaceCount = getPaddedPos(subMesh.faceCount, 2)
					meshGroup.faceCount += paddedFaceCount

					vertCount = len(parsedSubMesh.vertexPosList)
					meshGroup.vertexCount += vertCount
					if not parsedSubMesh.isReusedMesh:
						subMesh.faceStartIndex = currentFaceIndex
						subMesh.vertexStartIndex = currentVertexIndex
						currentVertexIndex += vertCount
						currentFaceIndex += paddedFaceCount
						#TODO Add vertices and faces to buffers
						WriteToVertexPosBuffer(vertexPosBuffer,parsedSubMesh.vertexPosList)
						WriteToNorTanBuffer(norTanBuffer, parsedSubMesh.normalList,parsedSubMesh.vertexPosList,parsedSubMesh.uvList,parsedSubMesh.faceList)
						WriteToUVBuffer(UVBuffer,parsedSubMesh.uvList)
						if parsedSubMesh.uv2List != []:
							WriteToUVBuffer(UV2Buffer,parsedSubMesh.uv2List)
						if parsedSubMesh.weightIndicesList != [] and parsedSubMesh.weightList != []:
							WriteToWeightBuffer(weightBuffer,parsedSubMesh.weightList,parsedSubMesh.weightIndicesList)
						if parsedSubMesh.colorList != []:
							WriteToColorBuffer(colorBuffer,parsedSubMesh.colorList)

						WriteToFaceBuffer(faceBuffer,parsedSubMesh.faceList)
					else:
						linkedMeshData = parsedSubMeshToSubMeshDataDict[parsedSubMesh.linkedSubMesh]
						subMesh.faceStartIndex = linkedMeshData.faceStartIndex
						subMesh.vertexStartIndex = linkedMeshData.vertexStartIndex
						#TODO Get linked mesh offset for reused meshes
						#Make dict of offset key to tuple of vertexstartindex and facestartindex
						#meshOffsetDict[parsedSubMesh.linkedMesh][0]
					meshGroup.vertexInfoList.append(subMesh)
				currentOffset += sd.MESH_GROUP_SIZE + meshGroup.meshCount*sd.MATERIAL_SUBDIVISION_SIZE

				lodGroupHeader.meshGroupList.append(meshGroup)
			reMesh.shadowHeader.lodGroupList.append(lodGroupHeader)
	"""
    # Skeleton / AABB
    if parsedMesh.skeleton is not None:
        reMesh.fileHeader.skeletonOffset = currentOffset
        reMesh.skeletonHeader = Skeleton()
        reMesh.skeletonHeader.boneCount = len(parsedMesh.skeleton.boneList)
        reMesh.skeletonHeader.remapCount = len(parsedMesh.skeleton.weightedBones)

        # Do AABB struct while looping through bones
        if reMesh.skeletonHeader.remapCount > 0:
            reMesh.boneBoundingBoxHeader = BoneAABBGroup()
            reMesh.boneBoundingBoxHeader.count = reMesh.skeletonHeader.remapCount
        for boneIndex, parsedBone in enumerate(parsedMesh.skeleton.boneList):
            if parsedBone.boneName in parsedMesh.skeleton.weightedBones:
                reMesh.skeletonHeader.boneRemapList.append(boneIndex)
                if (
                    parsedBone.boundingBox is not None
                    and reMesh.boneBoundingBoxHeader is not None
                ):
                    reMesh.boneBoundingBoxHeader.bboxList.append(parsedBone.boundingBox)
            reMesh.skeletonHeader.localMatList.append(parsedBone.localMatrix)
            reMesh.skeletonHeader.worldMatList.append(parsedBone.worldMatrix)
            reMesh.skeletonHeader.inverseMatList.append(parsedBone.inverseMatrix)

            bone = Bone()
            bone.boneIndex = boneIndex
            bone.boneParent = parsedBone.parentIndex
            bone.boneSibling = parsedBone.nextSiblingIndex
            bone.boneChild = parsedBone.nextChildIndex
            bone.boneSymmetric = parsedBone.symmetryBoneIndex
            bone.useSecondaryWeight = parsedBone.useSecondaryWeight
            reMesh.skeletonHeader.boneInfoList.append(bone)

        reMesh.skeletonHeader.boneHeaderOffset = getPaddedPos(
            reMesh.fileHeader.skeletonOffset
            + sd.SKELETON_REMAP_TABLE_OFFSET
            + 2 * reMesh.skeletonHeader.remapCount,
            16,
        )
        reMesh.skeletonHeader.boneLocalMatrixOffset = (
            reMesh.skeletonHeader.boneHeaderOffset
            + reMesh.skeletonHeader.boneCount * sd.BONE_INFO_ENTRY_SIZE
        )
        reMesh.skeletonHeader.boneWorldMatrixOffset = (
            reMesh.skeletonHeader.boneLocalMatrixOffset
            + reMesh.skeletonHeader.boneCount * sd.MATRIX_SIZE
        )
        reMesh.skeletonHeader.boneInverseMatrixOffset = (
            reMesh.skeletonHeader.boneWorldMatrixOffset
            + reMesh.skeletonHeader.boneCount * sd.MATRIX_SIZE
        )

        currentOffset = (
            reMesh.skeletonHeader.boneInverseMatrixOffset
            + reMesh.skeletonHeader.boneCount * sd.MATRIX_SIZE
        )
    # Name lists and remaps
    currentNameIndex = 0
    for index, materialName in enumerate(parsedMesh.materialNameList):
        reMesh.rawNameList.append(materialName)
        reMesh.materialNameRemapList.append(index)
    currentNameIndex += len(reMesh.rawNameList)
    if parsedMesh.skeleton is not None:
        for bone in parsedMesh.skeleton.boneList:
            reMesh.rawNameList.append(bone.boneName)
            reMesh.boneNameRemapList.append(currentNameIndex)
            currentNameIndex += 1

    # MH Wilds blend shape (shape key) export: gather packed deltas and register morph names.
    # Blend shape names are appended after material/bone names; the remap maps each to its
    # rawNameList index (the import reads them back as the trailing name entries).
    # Returns (None, None, None) while EXPORT_WILDS_BLEND_SHAPES is off (the default).
    blendDeltaBytes, blendPerLodList, blendNames = buildWildsBlendShapeExport(
        parsedMesh, parsedSubMeshToSubMeshDataDict
    )
    if blendNames is not None:
        for name in blendNames:
            reMesh.blendShapeNameRemapList.append(len(reMesh.rawNameList))
            reMesh.rawNameList.append(name)
            currentNameIndex += 1

    reMesh.fileHeader.materialNameRemapOffset = currentOffset
    currentOffset = getPaddedPos(
        currentOffset + (len(reMesh.materialNameRemapList) * 2), 16
    )
    if parsedMesh.skeleton is not None:
        reMesh.fileHeader.boneNameRemapOffset = currentOffset
        currentOffset = getPaddedPos(
            currentOffset + (len(reMesh.boneNameRemapList) * 2), 16
        )
    if blendNames is not None:
        reMesh.fileHeader.blendShapeNameOffset = currentOffset
        currentOffset = getPaddedPos(
            currentOffset + (len(reMesh.blendShapeNameRemapList) * 2), 16
        )

    reMesh.fileHeader.nameOffsetsOffset = currentOffset
    currentOffset = getPaddedPos(
        currentOffset + (len(reMesh.rawNameList) * 8), 16
    )  # Get the position after all string offsets
    for name in reMesh.rawNameList:
        reMesh.rawNameOffsetList.append(currentOffset)
        currentOffset += len(name.encode("utf-8")) + 1
    reMesh.fileHeader.nameCount = len(reMesh.rawNameList)
    currentOffset = getPaddedPos(currentOffset, 16)
    # AABB
    if reMesh.boneBoundingBoxHeader is not None:
        reMesh.fileHeader.aabbOffset = currentOffset
        reMesh.boneBoundingBoxHeader.offset = currentOffset + sd.AABB_OFFSET
        currentOffset += (
            sd.AABB_OFFSET + reMesh.boneBoundingBoxHeader.count * sd.AABB_SIZE
        )

    # MH Wilds normal-recalc header (16 bytes) — present whenever the streamed mesh has blend shapes.
    # The engine reads the per-vertex/per-face index arrays from the streaming entry tails (written in
    # convertToStreamedWilds); this base header just marks the section as present (normalRecalcOffset).
    if (
        blendPerLodList is not None
        and (EXPORT_WILDS_STREAMING or EXPORT_WILDS_FIX_BUFFER)
        and not EXPORT_WILDS_DEBUG_NO_NORMALRECALC
    ):
        reMesh.fileHeader.normalRecalcOffset = currentOffset
        reMesh.normalRecalcRegionBytes = struct.pack("<IQhh", 1, 0, 0, 0)  # blockCount=1, dataOffset=0
        currentOffset = getPaddedPos(
            currentOffset + len(reMesh.normalRecalcRegionBytes), 16
        )

    # MH Wilds blend shape struct region (header + per-LOD data), placed before the mesh buffer.
    if blendPerLodList is not None:
        reMesh.fileHeader.blendShapesOffset = currentOffset
        reMesh.blendShapeRegionBytes = serializeWildsBlendShapeRegion(
            blendPerLodList, currentOffset
        )
        currentOffset = getPaddedPos(
            currentOffset + len(reMesh.blendShapeRegionBytes), 16
        )

    # Mesh Buffer
    reMesh.fileHeader.meshOffset = currentOffset

    reMesh.meshBufferHeader = MeshBufferHeader()
    reMesh.meshBufferHeader.vertexBuffer = bytearray()
    currentBufferOffset = 0
    if vertexPosBuffer.tell() != 0:
        vertexElement = VertexElementStruct()
        vertexElement.posStartOffset = currentBufferOffset
        vertexElement.typing = 0
        vertexElement.stride = 12
        currentBufferOffset += vertexPosBuffer.tell()
        reMesh.meshBufferHeader.vertexElementList.append(vertexElement)
        reMesh.meshBufferHeader.vertexBuffer.extend(vertexPosBuffer.getvalue())

    if norTanBuffer.tell() != 0:
        vertexElement = VertexElementStruct()
        vertexElement.posStartOffset = currentBufferOffset
        vertexElement.typing = 1
        vertexElement.stride = 8
        currentBufferOffset += norTanBuffer.tell()
        reMesh.meshBufferHeader.vertexElementList.append(vertexElement)
        reMesh.meshBufferHeader.vertexBuffer.extend(norTanBuffer.getvalue())

    if UVBuffer.tell() != 0:
        vertexElement = VertexElementStruct()
        vertexElement.posStartOffset = currentBufferOffset
        vertexElement.typing = 2
        vertexElement.stride = 4
        currentBufferOffset += UVBuffer.tell()
        reMesh.meshBufferHeader.vertexElementList.append(vertexElement)
        reMesh.meshBufferHeader.vertexBuffer.extend(UVBuffer.getvalue())

    if UV2Buffer.tell() != 0:
        vertexElement = VertexElementStruct()
        vertexElement.posStartOffset = currentBufferOffset
        vertexElement.typing = 3
        vertexElement.stride = 4
        currentBufferOffset += UV2Buffer.tell()
        reMesh.meshBufferHeader.vertexElementList.append(vertexElement)
        reMesh.meshBufferHeader.vertexBuffer.extend(UV2Buffer.getvalue())

    if weightBuffer.tell() != 0:
        vertexElement = VertexElementStruct()
        vertexElement.posStartOffset = currentBufferOffset
        vertexElement.typing = 4
        vertexElement.stride = 16
        currentBufferOffset += weightBuffer.tell()
        reMesh.meshBufferHeader.vertexElementList.append(vertexElement)
        reMesh.meshBufferHeader.vertexBuffer.extend(weightBuffer.getvalue())

    if colorBuffer.tell() != 0:
        # print("Added color buffer")
        vertexElement = VertexElementStruct()
        vertexElement.posStartOffset = currentBufferOffset
        vertexElement.typing = 5
        vertexElement.stride = 4
        currentBufferOffset += colorBuffer.tell()
        reMesh.meshBufferHeader.vertexElementList.append(vertexElement)
        reMesh.meshBufferHeader.vertexBuffer.extend(colorBuffer.getvalue())

    if extraWeightBuffer.tell() != 0:
        vertexElement = VertexElementStruct()
        vertexElement.posStartOffset = currentBufferOffset
        vertexElement.typing = 7
        vertexElement.stride = 16
        currentBufferOffset += extraWeightBuffer.tell()
        reMesh.meshBufferHeader.vertexElementList.append(vertexElement)
        reMesh.meshBufferHeader.vertexBuffer.extend(extraWeightBuffer.getvalue())

    # MH Wilds blend shape deltas live in the undeclared tail of the vertex buffer, immediately
    # after the last declared vertex element (no padding before, matching the import math).
    # When streaming, the deltas go into the streaming entry tails instead (convertToStreamedWilds),
    # so the base buffer stays clean.
    if (
        blendDeltaBytes
        and not EXPORT_WILDS_STREAMING
        and not EXPORT_WILDS_RESIDENT_BLEND
        and not EXPORT_WILDS_FIX_BUFFER
    ):
        reMesh.meshBufferHeader.vertexBuffer.extend(blendDeltaBytes)
        currentBufferOffset += len(blendDeltaBytes)

    reMesh.meshBufferHeader.faceBuffer = faceBuffer.getvalue()
    # print(len(reMesh.meshBufferHeader.faceBuffer))
    reMesh.meshBufferHeader.vertexElementCount = len(
        reMesh.meshBufferHeader.vertexElementList
    )
    reMesh.meshBufferHeader.mainVertexElementCount = (
        reMesh.meshBufferHeader.vertexElementCount
    )
    reMesh.meshBufferHeader.vertexElementOffset = (
        reMesh.fileHeader.meshOffset + sd.VERTEX_ELEMENT_OFFSET
    )
    reMesh.meshBufferHeader.vertexBufferOffset = getPaddedPos(
        reMesh.meshBufferHeader.vertexElementOffset
        + reMesh.meshBufferHeader.vertexElementCount * sd.VERTEX_ELEMENT_SIZE,
        16,
    )

    # TODO check on this, padding vertex buffer size might cause issues in some games
    reMesh.meshBufferHeader.vertexBufferSize = getPaddedPos(currentBufferOffset, 16)
    reMesh.meshBufferHeader.faceBufferOffset = getPaddedPos(
        reMesh.meshBufferHeader.vertexBufferOffset
        + reMesh.meshBufferHeader.vertexBufferSize,
        16,
    )
    reMesh.meshBufferHeader.faceBufferSize = faceBuffer.tell()

    # Content Flags
    unknFlag16 = False  # Bit index 15
    unknFlag10 = False  # Bit index 9

    if version < VERSION_SF6:
        reMesh.meshBufferHeader.vertexElementSize = 31872
        reMesh.meshBufferHeader.block2FaceBufferOffset = (
            reMesh.meshBufferHeader.faceBufferSize
        )

    if version >= VERSION_SF6:
        # reMesh.fileHeader.sf6UnknCount = 84
        reMesh.fileHeader.sf6UnknCount = 6 if version == VERSION_SF6 else 84
        reMesh.meshBufferHeader.vertexElementSize = 27104
        reMesh.fileHeader.verticesOffset = reMesh.meshBufferHeader.vertexBufferOffset
        reMesh.fileHeader.streamingInfoOffset = (
            reMesh.fileHeader.meshOffset + sd.VERTEX_ELEMENT_OFFSET - 16
        )
        reMesh.meshBufferHeader.block2FaceBufferOffset = (
            reMesh.meshBufferHeader.vertexBufferSize
            + reMesh.meshBufferHeader.faceBufferSize
        )
        reMesh.meshBufferHeader.NULL = reMesh.meshBufferHeader.block2FaceBufferOffset
        reMesh.meshBufferHeader.totalBufferSize = getPaddedPos(
            reMesh.meshBufferHeader.block2FaceBufferOffset, 16
        )
        unknFlag16 = True
        unknFlag10 = True

    currentOffset = getPaddedPos(
        reMesh.meshBufferHeader.faceBufferOffset
        + reMesh.meshBufferHeader.faceBufferSize,
        16,
    )
    if version >= VERSION_DD2:
        if parsedMesh.bufferHasSecondaryWeight:
            reMesh.meshBufferHeader.sunbreakOffset = (
                reMesh.meshBufferHeader.vertexBufferOffset
                + reMesh.meshBufferHeader.totalBufferSize
            )

            reMesh.meshBufferHeader.secondaryWeightBuffer = (
                secondaryWeightBuffer.getvalue()
            )
            reMesh.meshBufferHeader.sunbreakSecondUnknown = len(
                reMesh.meshBufferHeader.secondaryWeightBuffer
            )
            currentOffset = reMesh.meshBufferHeader.sunbreakOffset + len(
                reMesh.meshBufferHeader.secondaryWeightBuffer
            )
    reMesh.fileHeader.fileSize = currentOffset

    reMesh.fileHeader.contentFlag.setBitFlag(
        unknFlag16,
        unknFlag10,
        hasUnknFlag8=True,
        hasGroupPivot=reMesh.floatsHeader is not None,
        hasBlendShape=blendPerLodList is not None,
        hasSkeleton=reMesh.skeletonHeader is not None,
        hasAABB=reMesh.boneBoundingBoxHeader is not None,
    )
    vertexPosBuffer.close()
    norTanBuffer.close()
    UVBuffer.close()
    UV2Buffer.close()
    weightBuffer.close()
    colorBuffer.close()
    extraWeightBuffer.close()
    faceBuffer.close()
    secondaryWeightBuffer.close()

    if version == VERSION_MHWILDS:
        if EXPORT_WILDS_FIX_BUFFER and blendPerLodList is not None:
            convertToFixedBlendWilds(reMesh, blendDeltaBytes, blendPerLodList)
        elif EXPORT_WILDS_STREAMING or (
            EXPORT_WILDS_RESIDENT_BLEND and blendPerLodList is not None
        ):
            convertToStreamedWilds(reMesh, blendDeltaBytes, blendPerLodList)
        else:
            _debugStreamingSplit(reMesh)

    return reMesh


# ---RE MESH IO FUNCTIONS---#


def readREMesh(filepath, lodTarget=None):
    print("Opening " + filepath)
    try:
        file = open(filepath, "rb", buffering=8192)
    except:
        raiseError("Failed to open " + filepath)
    try:
        meshVersion = int(os.path.splitext(filepath)[1].replace(".", ""))
    except:
        print("Unable to read mesh version from file path, assuming MHRSB")
        meshVersion = 2109148288  # MHRSB
    version = meshFileVersionToNewVersionDict.get(
        meshVersion, getNearestRemapVersion(meshVersion)
    )
    if meshVersion not in meshFileVersionToNewVersionDict:
        raiseWarning(
            f"Mesh Version ({str(meshVersion)}) not supported! Attempting import..."
        )
        print(
            f"Nearest Remap Version: {str(version)} ({meshFileVersionToGameNameDict[newVersionToMeshFileVersion[version]]})"
        )

    streamingBuffer = None  # WILDS
    # if version >= VERSION_MHWILDS:

    # Precheck to see if user imported a headerless streaming mesh
    magic = read_uint(file)
    if magic != 1213416781 and "streaming" in filepath:
        raiseError(
            "Attempted to import a streaming mesh file. Streaming mesh files cannot be imported directly.\nImport the mesh file that has same path and name that's not in the streaming folder."
        )
        raise Exception(
            "Streaming meshes can't be imported directly. Import the non streaming mesh instead."
        )
    file.seek(0)

    if version >= VERSION_SF6:
        paths = splitNativesPath(filepath)
        if paths is not None:  # Returns none if path does not contain a natives folder
            rootPath = paths[0]  # The path to the natives\STM folder from the root
            nativesPath = paths[1]  # The path to the file inside the natives\STM folder
            streamingMeshPath = os.path.join(rootPath, "streaming", nativesPath)
            if os.path.isfile(streamingMeshPath):
                try:
                    streamFile = open(streamingMeshPath, "rb")
                    streamingBuffer = streamFile.read()
                    streamFile.close()
                    print(
                        f"Loaded {len(streamingBuffer)} bytes from streaming mesh at {streamingMeshPath}"
                    )
                except:
                    raiseError("Failed to open " + filepath)
        else:
            # Fallback for loose folders: check for a sibling 'streaming' directory
            folder, name = os.path.split(filepath)
            streamingMeshPath = os.path.join(folder, "streaming", name)
            if os.path.isfile(streamingMeshPath):
                try:
                    with open(streamingMeshPath, "rb") as streamFile:
                        streamingBuffer = streamFile.read()
                        print(
                            f"Loaded {len(streamingBuffer)} bytes from loose streaming mesh at {streamingMeshPath}"
                        )
                except:
                    raiseError("Failed to open streaming file: " + streamingMeshPath)
    if magic == 1498173517 and IMPORT_MPLY:  # MPLY Mesh
        reMeshFile = REMeshMPLY()
        print("Loading MPLY mesh.")
    else:
        reMeshFile = REMesh()
    reMeshFile.meshVersion = meshVersion
    reMeshFile.read(file, version, lodTarget, streamingBuffer)
    file.close()
    return reMeshFile


def writeREMesh(reMeshFile, filepath):
    print("Writing to " + filepath)
    try:
        file = open(filepath, "wb", buffering=8192)
    except:
        raiseError("Failed to open " + filepath)
    try:
        meshVersion = int(os.path.splitext(filepath)[1].replace(".", ""))
    except:
        print("Unable to read mesh version from file path, assuming MHRSB")
        meshVersion = 2109148288  # MHRSB
    version = newVersionToMeshFileVersion.get(
        meshVersion, getNearestRemapVersion(meshVersion)
    )
    reMeshFile.meshVersion = meshVersion
    reMeshFile.write(file, version)
    file.close()

    # MH Wilds: write the parallel streaming companion file when there is streamed data — UNLESS the
    # resident-blend single-file experiment embedded it in the base file already.
    streamingBytes = getattr(reMeshFile, "streamingBytes", b"")
    if streamingBytes and not getattr(reMeshFile, "streamInBase", False):
        paths = splitNativesPath(filepath)
        if paths is not None:
            streamingPath = os.path.join(paths[0], "streaming", paths[1])
        else:
            folder, name = os.path.split(filepath)
            streamingPath = os.path.join(folder, "streaming", name)
        os.makedirs(os.path.dirname(streamingPath), exist_ok=True)
        with open(streamingPath, "wb") as streamFile:
            streamFile.write(streamingBytes)
        print(f"Wrote {len(streamingBytes)} bytes to streaming companion {streamingPath}")
