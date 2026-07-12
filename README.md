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
- Batch export tools
- Presets for multiple RE Engine games
- Texture/material helper tools

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
- Blender 5.1 is not supported
- Monster Hunter Wilds support is experimental and needs broader testing
- Blend-shape / shape-key import support varies by game and mesh format
- Legacy blend-shape import has been improved but regression testing across older titles is still needed
- Blend-shape export is not guaranteed for all supported import paths
- Some newer game formats may import but not export correctly
- Street Fighter 6 material support remains experimental and may vary by fighter, costume and shader
- Damage, sweat, animated muscle, cloth-wave and some auxiliary SF6 material effects are not reconstructed
- Blender materials may not reproduce every RE Engine lighting and shader effect exactly
- Material reconstruction may differ from in-game rendering

## Roadmap

### Near Term
- Validate Street Fighter 6 materials across more fighters, costumes, color variants and shader types
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
