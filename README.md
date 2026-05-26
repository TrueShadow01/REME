# RE Mesh Editor (Community Maintained Fork)

This is a maintained fork of the [original RE Mesh Editor Plugin by NSACloud.](https://github.com/NSACloud/RE-Mesh-Editor)

The original projects is no longer being updated, so this fork continues development, fixes bugs and improves the combatibility with newer RE Engine titles. 

Note: This project is not affiliated with any third-party forums or communities reposting it.

---

Blender 5.1 is not supported currently.

## Changes in this fork
- Fixed alpha clipping issues that caused holes in solid materials
- Improved handling of alpha maps to prevent unintended transparency
- Ongoing work focused on improving Street Fighter 6 material and shader support

**This fork is actively developed with a strong focus on accurate SF6 material importing, shader handling and overall RE Engine compatibility.**

## Roadmap

### Street Fighter 6 Support
- Improve SF6 material reconstruction accuracy
- Refine alpha map interpretation (ATOS/BaseAlphaMap handling)
- Fix UV mapping issues for hair, eyebrows, decals and layered materials
- Resolve texture misalignment in shaders
- Improve HairOverMap and detail map handling
### Shader System
- Automatically detect UV1 vs UV0 requirements
- Reduce hardcoded shader logic
- Refactor shader node generation for better modularity
- Improve shader matching for SF6 specific materials
### Texture & Compression Handling
- Improve texture import reliability
- Validate newer texture compression formats used in SF6 and PRAGMATA
- Reduce incorrect texture assignments and missing textures
### Material Consistency
- Ensure behavior remains consistent with the original addon where appropriate
- Increase visual parity with in-game rendering
### Code Quality and Performance
- Refactor material pipelines for cleaner architecture
- Optimize redundant texture processing
- Improve import performance
- Clean up and document the codebase for contributors
### Additional Game Compatibility
- Improve support for PRAGMATA
- Validate compatibility with RE2, RE3, RE4, and RE7RT presets
- Test newly discovered RE Engine material variations
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
