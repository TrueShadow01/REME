# RE Mesh Editor Community Fork

A Blender addon for importing/exporting RE Engine mesh, material, texture-adjacent data, maintained as a community fork of NSACloud's original plugin.

## Status
- Actively maintained
- Blender 4.3.2+ supported
- Blender 5.1 not supported currently
- Some newer-game support is experimental
- Monster Hunter Wilds mesh import is experimental
- Blend-shape import is supported for some legacy and newer formats but needs broader testing

# Requirements
- Blender 4.3.2 or higher

## Installation
1. Download the latest addon version zip file from Releases
2. In Blender, go to Edit > Preferences > Add-ons
3. Install from zip
4. Enable RE Mesh Editor (Community Maintained)

## Features
- Import/export RE Engine `.mesh` files for supported titles
- Import materials and texture bindings
- Import blend shapes as Blender shape keys for supported mesh formats
- Experimental Monster Hunter Wilds mesh import support and Legacy (pre SF6)
- Experimental Street Fighter 6 material reconstruction
- SF6 CMD costume-color parsing, including fixed and variable-length color clusters
- SF6 CMASK/CMASK2 colors, cloth shading, body details, hair tinting and shared-head material support
- SF6 StitchMap reconstruction with material-controlled tiling, color variation, AO contrast, normal strength and roughness
- Batch export tools
- Presets for multiple RE Engine games
- Texture/material helper tools

## Game And Format Support

The following versions are explicitly recognized by the addon. Support can vary by asset type, shader and game update.

| Game | Internal Name | MESH Version | MDF Version | TEX Version | Status |
|---|---|---:|---:|---:|---|
| Devil May Cry 5 | `DMC5` | `1808282334` | `10` | `11` | Supported |
| Resident Evil 2 | `RE2` | `1808312334` | `10` | `10` | Supported |
| Resident Evil 3 | `RE3` | `1902042334` | `13` | `190820018` | Supported |
| Resident Evil Village / RE:Verse | `RE8` | `2101050001` / `2102020001` | `19` / `20` | `30` | Supported |
| Resident Evil 2/3 Ray Tracing | `RE2RT` / `RE3RT` | `2109108288` | `21` | `34` | Supported |
| Resident Evil 7 Ray Tracing | `RE7RT` | `220128762` | `21` | `35` | Supported |
| Monster Hunter Rise / Sunbreak | `MHRSB` | `2109148288` | `23` | `28` | Supported |
| Resident Evil 4 | `RE4` | `221108797` | `32` | `143221013` | Supported |
| Street Fighter 6 | `SF6` | `230110883` | `31` | `241101895` | Experimental enhanced support |
| Dragon's Dogma 2 | `DD2` | `231011879` / `240423143` | `40` | `760230703` | Supported |
| Kunitsu-Gami | `KG` | `240306278` | `40` | `231106777` | Limited validation |
| Dead Rising Deluxe Remaster | `DR` | `240424828` | `40` | `240606151` | Limited validation |
| Onimusha 2 | `ONI2` | `240827123` | `46` | `240701001` | Limited validation |
| Monster Hunter Wilds | `MHWILDS` | `241111606` | `45` | `241106027` | Experimental |
| Monster Hunter Stories 3 | `MHS3` | `250604100` | `49` | `251111100` | Preliminary |
| Pragmata | `PRAG` | Not enabled | `51` | `250813143` | Preliminary |
| Resident Evil 9 / Requiem | `RE9` | `250925211` | `51` | `250813143` | Preliminary |

“Supported” means the corresponding format versions have importer mappings. It does not guarantee perfect reconstruction of every material, effect, animation or blend shape.

## Street Fighter 6 Support

Street Fighter 6 material import is experimental. The addon can reconstruct costume colors from extracted CMD `.user.2` files and apply them to supported MDF materials.

### Import Options

- **SF6 Costume Index** selects the costume folder containing the CMD files. For example, `1` selects folder `001`.
- **SF6 Color Index** selects the CMD color file. For example, `1` selects `cmd_001.user.2`.

Shared character meshes stored under costume folder `000` can use CMD data from the selected costume folder.

Example for Costume 2, Color 1:

```text
SF6 Costume Index: 2
SF6 Color Index: 1
```

## Known Limitations
- Blender 5.1 is not currently supported
- Monster Hunter Wilds support remains experimental
- Blend-shape support varies by game and mesh format
- SF6 blend shapes are kept at zero by default
- Automatic SF6 JCNS pose-corrective drivers are disabled while their vertex mapping remains experimental
- Extreme FK poses may not match the game's deformation without pose-corrective shapes
- The imported skeleton does not include custom IK or animator-facing controls
- Blend-shape export is not guaranteed for every supported import path
- Damage, sweat, animated muscle, cloth-wave and some auxiliary SF6 effects are not reconstructed
- Blender materials cannot reproduce every RE Engine lighting and shader effect exactly

## Roadmap

### Near Term
- Validate Street Fighter 6 materials across more fighters, costumes, color variants and shader types
- Investigate SF6 blend-shape vertex mapping and safely restore JCNS pose-corrective drivers
- Add automated regression tests for CMD parsing and material matching
- Improve remaining SF6 effects such as damage, sweat, animated deformation and specialized transparency
- Improve texture import reliability and support for newer compression formats
- Validate compatibility with RE2, RE3, RE4R, RE7RT and newer RE Engine titles

### Mesh And Format Support
- Validate Monster Hunter Wilds mesh import across more character, armor, weapon and environment assets
- Regression test legacy mesh and blend-shape import paths
- Continue investigating blend-shape / shape-key export support
- Improve support for newer mesh/material variations used by SF6, PRAGMATA, MH Wilds and future RE Engine games
- Reduce hardcoded format assumptions where possible

### Code Quality
- Refactor shader and material generation for easier maintenance
- Improve import/export performance
- Expand documentation for contributors and testers

---

**Contributing**: If you're interested in tackling any of these areas, feel free to open an issue or PR.

# Credits
- [Ando](https://github.com/Andoryuuta) - Solving the compression format for MH Wilds textures.
- [AsteriskAmpersand](https://github.com/AsteriskAmpersand) - Mesh format research and tex conversion code
- [AlphaZomega](https://github.com/alphazolam/) - RE Mesh 010 Template and Noesis plugin
- [CG Cookie](https://github.com/CGCookie) - Addon updater module
- [matyalatte](https://github.com/matyalatte/Texconv-Custom-DLL) - DirectX Texconv DLL library
- [PittRBM](https://x.com/wDnrbm) - NRRT texture node setup
- Ridog - NRRT normal conversion code used as reference
- [NSACloud](https://github.com/NSACloud) - Original RE-Mesh-Editor Plugin Author
