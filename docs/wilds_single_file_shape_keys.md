# MH Wilds — Single-File Custom Shape Keys

This branch adds authoring of **brand-new custom shape keys (blend shapes) for Monster Hunter Wilds
armor in a single, self-contained base `.mesh` file** — no streaming companion required. Shapes
authored in Blender export to one base file, load and deform correctly in-game (geometry, deltas and
normals), and round-trip back into Blender.

Format version: `241111606` (`VERSION_MHWILDS`). Single-LOD export only (export with *Export All LODs*
off). Multiple shape keys and multiple submeshes are supported.

Blend export is **automatic**: any submesh that carries shape keys is exported as blend shapes; meshes
without shape keys export exactly as before. There is no toggle.

---

## 1. Files changed

| File | Contribution |
|---|---|
| `modules/mesh/file_re_mesh.py` | Export/serialize/build pipeline + in-base import detection. |
| `modules/mesh/re_mesh_parse.py` | Wilds blend-delta import decoder + single-file (resident) read path. |
| `modules/mesh/blender_re_mesh.py` | Blender shape-key → per-vertex game-space delta capture on export. |
| `modules/mesh/re_mesh_propertyGroups.py`, `__init__.py` | Removed the old **Export Blend Shapes** option; export is now driven purely by shape-key presence. |

---

## 2. Functions

### Export (`file_re_mesh.py`)

- **`buildWildsBlendShapeExport(parsedMesh, parsedSubMeshToSubMeshDataDict)`**
  Gathers Blender shape keys per LOD. Builds **one blend target per morph submesh**, each covering a
  **merged region spanning every submesh in the LOD** (non-morph submeshes contribute zero deltas).
  Attaches a per-shape deformed normal to every vertex. Returns `(deltaBytes, perLodList, blendNames)`.
- **`serializeWildsBlendShapeRegion(perLodList, baseOffset)`**
  Serializes the blend block (header + per-LOD `BlendShapeData` + targets + sub-entries + AABBs +
  `blendS`/`blendSSList`). Pads each target list to `targetCount + typing` slots.
- **`buildWildsSingleFileBlend(reMesh, blendDeltaBytes, blendPerLodList)`**
  Rebuilds the mesh region as the resident (vbi=0) layout: deltas at the buffer base, geometry shifted
  after them, described by one streaming-buffer-header entry + a `streamingInfo` that points at the
  buffer in-base.
- **`packBlendShapeDeltas(deltaArray, aabb)`**
  11/10/11 position-delta encoder (x=11 @ 2047, y=10 @ 1023, z=11 @ 2047) against a symmetric AABB.
- **`packBlendShapeDeltasStride8(deltaArray, aabb, normals=None)`**
  8 bytes per vertex: low u32 = 11/10/11 position delta; high u32 = int8 normal (`floor(n*127)` packed
  `[nx][ny][nz][0]`, the same format the geometry `norTan` buffer uses).
- **`computeVertexNormals(positions, faceList)`**
  Area-weighted per-vertex normals; used to derive each shape's deformed normal as
  `base_normal + (recompute(base+delta) − recompute(base))`, renormalized.
- **`computeBlendShapeAABB(deltaArrayList)`**
  Symmetric (min = −max) bounding box of the deltas; the box the 11/10/11 packing quantizes against.
  In the single-file path this is computed **once per LOD over every morph submesh's deltas** (a shared
  union box) because the engine dequantizes all targets in the resident buffer with a single AABB.
- **`ParsedREMeshToREMesh(...)`** *(modified)*
  Places the blend block before the mesh region, sets `contentFlag.hasBlendShape`, and dispatches to
  `buildWildsSingleFileBlend` for Wilds blend meshes.
- **`REMesh.read(...)`** *(modified)*
  When the mesh declares streaming entries but no companion is present, detects an **in-base buffer**
  (all `streamingInfo` `bufferStart + length ≤ file size`) and reads the buffer from the base file
  itself, so single-file meshes load without a streaming companion.
- Flag **`EXPORT_WILDS_BLEND_SHAPES`** (master enable). `DEBUG_STREAMING_BUILD` (verbose export logging,
  off by default).

### Import (`re_mesh_parse.py`)

- **`_decodeWildsBlendShapes(reMesh)`**
  Decodes blend deltas. Auto-detects the single-file format (first vertex element `posStartOffset > 0`)
  and reads the deltas from the buffer base; otherwise uses the streamed-companion path.
- **`decodeTarget(tail, cur, bt, aabb, lodDict, stride=4, splitBySubmesh=False)`** *(modified)*
  `stride=8` for the resident single-file format (reads the low u32 of each 8-byte vertex).
  `splitBySubmesh=True` assigns each shape to the submesh whose slice actually carries deltas, so shapes
  land on their correct Blender meshes.

### Blender export (`blender_re_mesh.py`)

- Shape-key capture: `blendShapeEntry.deltas = (shapeCo − basisCo) · worldMatrix3x3`, in the exported
  vertex order.

---

## 3. File structure and exact data locations

The base `.mesh` is self-contained. The blend block precedes the mesh region; the mesh region carries
the deltas, geometry and faces in one resident (vbi=0) buffer.

```
FileHeader → … → AABB → BLEND BLOCK (blendShapesOffset) → MESH REGION (meshOffset = M) → names/strings
```

### Blend block (`serializeWildsBlendShapeRegion`, at `blendShapesOffset`)

```
+0   BlendShapeHeader (32B): count(u64)  0(u64)  mainOffset(u64)=baseOffset+32  hash(u64)
+32  blendShapeOffsetList[count] (u64 each) → per-LOD BlendShapeData

     BlendShapeData (48B):
        targetCount (u16 +0)   typing (u16 +2)
        unknFlag    (u32 +4) = (totalShapes << 16) | firstSSIndex
        dataOffset  (u64 +16) → targetList        aabbOffset  (u64 +24) → aabbList
        blendSOffset(u64 +32)                     blendSSOffset(u64 +40)

     targetList: (targetCount + typing) × 16B   ← the engine iterates targetCount+typing records;
                 real targets first, then `typing` ZEROED padding slots
        BlendTarget (16B):
           blendSSIndex(u16 +0)  blendShapeNum(u16 +2)  unkn0(u16 +4)
           subMeshEntryCount(u8 +6)  unkn2(u8 +7)=1  subMeshEntryOffset(u64 +8)
        BlendSubMesh (16B each):    ← ONE sub-entry per submesh in the LOD (non-morph present, zero-delta)
           subMeshVertexStartIndex(u32 +0)  vertOffset(u32 +4)  vertCount(u32 +8)  paramUnkn3(u32 +12)

     aabbList: targetCount × 32B  (min.xyz + pad, max.xyz + pad), symmetric; in the single-file path
                 every entry is the SAME shared box (the engine dequantizes all targets with one AABB)
     blendS (12B, 3 ints) + blendSSList (totalShapes × 4B, running 0..N-1)
```

### Mesh region (`buildWildsSingleFileBlend`, at `meshOffset = M`)

```
M+0    80B MeshBufferHeader (SF6+):
          vertexElementOffset (+0) = M+baseElemOff     vertexBufferOffset (+8) = M+baseVtxOff
          sunbreakOffset (+16) = 0
          totalBufferSize (+24)    vertexBufferSize (+28) = baseVtxSize
          mainVertexElementCount (+32) / vertexElementCount (+34)
          block2FaceBufferOffset (+36)   NULL (+40)
          vertexElementSize (+44) = 27104   unkn1 (+46) = -1
          streamingVertexElementOffset (+64) = M+streamVEOff

M+80   StreamingBufferHeaderEntry (64B), vbi=0 (in-base):
          vertexBufferLength (+12) = vbl
          word7 = geomEnd (+28)   word8 = nrVertStart (+32)   word9 = deltaStart (+36)
          vbi = 0 (+44)   word12 (+48) = M+streamVEOff   nextBufferOffset (+56)

M+144  StreamingInfo entry (8B): bufferStart = M+baseVtxOff, bufferLength = total
       StreamingInfo struct (16B, at fileHeader.streamingInfoOffset): entryCount = 1, 0, entryOffset

baseElemOff   vertex element table (mainVEC × 8B): typing, stride, posStartOffset + deltaPad
streamVEOff   duplicate element table (streaming copy)
baseVtxOff    ── RESIDENT VERTEX BUFFER (vbl bytes) ──►  fileHeader.verticesOffset
baseFaceOff   FACE BUFFER (verbatim)
regionEnd     →  fileHeader.fileSize
```

### Resident vertex buffer — deltas first, geometry after

```
offset 0         DELTAS (16-aligned)     ← the engine reads the resident delta resource from HERE (base)
                   per target, per shape, dense:
                     [target0: shape0 (regionVerts × 8B), shape1, …][target1: …]
                   each vertex = 8 BYTES:
                     low  u32 = 11/10/11 position delta (x11 y10 z11; symmetric-AABB dequant)
                     high u32 = int8 normal floor(n*127) → [nx][ny][nz][0]
                   every shape spans the WHOLE merged region; non-morph submesh slices are zero-packed
                   (midpoint position → ~0 delta, base int8 normal → shading unchanged)

offset deltaPad  GEOMETRY (verbatim mbh.vertexBuffer, struct-of-arrays):
                   position(t0, 12) · normal+tangent(t1, 8) · uv(t2, 4) · uv2(t3, 4) ·
                   weights(t4, 16) · color(t5, 4) · [extended weights(t7, 16)]
                   → every element's posStartOffset is bumped by deltaPad, so the engine reads
                     geometry via vertexBufferOffset + posStartOffset while the delta resource reads
                     from the buffer base (offset 0)
```

---

## 4. The rules that make it work in-game

These were established by in-game testing + runtime reverse-engineering; each addresses a specific
failure mode:

1. **Target list padded to `targetCount + typing` slots.** The engine iterates that many target
   records; a shorter list makes it walk past the data into garbage and crash (access violation).
   The extra `typing` slots are zeroed (`flag=0`, `subMeshEntryCount=0`) so they are inert.
2. **Every submesh is a sub-entry of the target** (non-morph submeshes with zero deltas). A submesh
   left out of the blend gets no blend-group entry and is flung off-screen when the blend is active.
3. **Deltas at the buffer base (offset 0).** The resident delta resource is read from the vertex
   buffer's base; the sbh `word9`/delta offset is ignored for the resident path. The geometry is
   shifted after the deltas and its element offsets bumped accordingly.
4. **8 bytes per vertex** (position delta + normal). The streamed format is 4 bytes; using it here
   makes the engine (reading at `vertex * 8`) pull each region's upper half from the next region.
5. **High u32 is an int8 normal** (`floor(n*127)`, the geometry's own normal format). It is an
   *absolute* normal the engine blends `base → slot` by the shape weight; any other encoding (a zero
   slot, 11/10/11, or a mismatched grid) darkens the surface as the shape is driven.
6. **One shared AABB for all targets in a LOD.** The engine dequantizes every target's deltas in the
   resident buffer with a *single* AABB (it does not switch box per target). So the exporter packs and
   stores every target against the union of all morph submeshes' deltas. Per-target boxes made a
   small-scale shape blow up (~7×/~98×) when a larger target's box was applied to it — a shape moving
   "too far, and sideways" is this bug.

Additional constraints: no GPU normal-recalc section or `normalRecalcOffset` header (it zeroed normals →
black); single-LOD export only; a symmetric AABB (shared across the LOD's targets) for the position
dequant.

---

## 5. Import round-trip

- `REMesh.read` detects the in-base buffer and reads it from the base file (no streaming companion
  needed, no "streaming file missing" error for single-file meshes).
- `_decodeWildsBlendShapes` detects the resident format (first vertex element offset > 0), reads the
  deltas from the buffer base at stride 8, and **splits each shape onto the submesh whose slice carries
  it**, so re-imported shapes attach to their correct meshes. No blend metadata is stored, so a
  re-export rebuilds the region fresh through the standard export path.
