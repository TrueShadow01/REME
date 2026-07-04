# RE Mesh Editor Community Fork

A Blender addon for importing/exporting RE Engine mesh, material, texture-adjacent data, maintained as a community fork of NSACloud's original plugin.

## Status
- Actively maintained
- Blender 4.3.2+ supported
- Blender 5.1 not supported currently
- Some newer-game support is experimental


# Requirements
- Blender 4.3.2 or higher

## Installation
1. Download the latest addon version zip file from Releases
2. In Blender, go to Edit > Preferences > Add-ons
3. Install from zip
4. Enable RE Mesh Editor (Community Maintained)

## Features
- Import/export RE Engine `.mesh` files
- Import materials and texture bindings
- Batch export tools
- Presets for multiple RE Engine games
- Texture/material helper tools

## Known Limitations
- Blender 5.1 is not supported
- Legacy blend-shape import/export is incomplete
- Some newer game formats may import but not export correctly
- Material reconstruction may differ from in-game rendering

## Roadmap

### Near Term
- Improve Street Fighter 6 material and shader reconstruction, including alpha maps, UV usage, hair, decals and layered materials
- Improve texture import reliability and support for newer compression formats
- Validate compatibility with RE2, RE3, RE4R, RE7RT and newer RE Engine titles

### Mesh And Format Support
- Improve support for newer mesh/material variations used by SF6, PRAGMATA, MH Wilds and future RE Engine games
- Continue investigating blend-shape / shape-key import and export support
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
