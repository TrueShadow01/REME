# RE Mesh Editor (Community Maintained Fork)

This is a maintained fork of the [original RE Mesh Editor Plugin by NSACloud.](https://github.com/NSACloud/RE-Mesh-Editor)

The original projects is no longer being updated, so this fork continues development, fixes bugs and improves the combatibility with newer RE Engine titles. 

Note: This project is not affiliated with any third-party forums or communities reposting it.

---

## Changes in this fork
- Fixed alpha clipping causing holes in solid materials
- Improved compatiblity with newer games (e.g. PRAGMATA)
- Better handling of alpha maps (prevents unintended transparency)

**More updates coming soon. See the Roadmap below for a rough overview of future updates.**

## Roadmap

### Current Priority: PRAGMATA Support
- [IN-PROGRESS] Validate and improve material node accuracy for PRAGMATA assets
- [IN-PROGRESS] Test texture format handling with PRAGMATA-specific compression

### Material and Shader Fixes
- **[IN-PROGRESS] Material Accuracy**
  - Improve alpha map handling (distinguish transparency vs data maps like ATOS/BaseAlphaMap)
  - Fix UV mapping for specialized materials (hair, eyebrows, decals)
  - Resolve texture misalignment in complex shaders (HairOverMap, detail maps)

- **[IN-PROGRESS] Shader Detection & Generation**
  - Automatically detect when materials require UV1 vs UV0
  - Reduce hardcoded shader cases
  - Make node generation more modular and predictable

- **[IN-PROGRESS] Material Consistency**
  - Ensure forked version matches original addon behavior
  - Improve hair, skin, and eye material handling

### Code Quality & Maintainability
- [IN-PROGRESS] Refactor material pipelines for better modularity
- [IN-PROGRESS] Clean up and document codebase for community contributions
- [IN-PROGRESS] Reduce redundant texture processing and optimize import performance

### Game Compatibility
- [IN-PROGRESS] Improve support for RE9 and MHWILDS
- [IN-PROGRESS] Validate against RE2, RE3, RE4, RE7RT presets
- [IN-PROGRESS] Test with newly discovered RE Engine asset variations

### Advanced Features (Future)
- [IN-PROGRESS] Advanced shader support (proper translucency, subsurface scattering)
- [IN-PROGRESS] Accurate hair shading
- [IN-PROGRESS] Near 1:1 visual parity with in-game materials

---

**Contributing**: If you're interested in tackling any of these areas, open an issue or PR.

# Requirements
- Blender 4.3.2 or higher

# Credits
- [Ando](https://github.com/Andoryuuta) - Solving the compression format for MH Wilds textures.
- [AsteriskAmpersand](https://github.com/AsteriskAmpersand) - Mesh format research and tex conversion code
- [AlphaZomega](https://github.com/alphazolam/) - RE Mesh 010 Template and Noesis plugin
- [CG Cookie](https://github.com/CGCookie) - Addon updater module
- [matyalatte](https://github.com/matyalatte/Texconv-Custom-DLL) - DirectX Texconv DLL library
- [PittRBM](https://x.com/wDnrbm) - NRRT texture node setup
- Ridog - NRRT normal conversion code used as reference
- [NSACloud](https://github.com/NSACloud) - Original RE-Mesh-Editor Plugin Author
