# RE Mesh Editor (Community Maintained Fork)

This is a maintained fork of the [original RE Mesh Editor Plugin by NSACloud.](https://github.com/NSACloud/RE-Mesh-Editor)

The original projects is no longer being updated, so this fork continues development, fixes bugs and improves the combatibility with newer RE Engine titles. 
# I am currently only working on PRAGMATA Support.

---

## Changes in this fork
- Fixed alpha clipping causing holes in solid materials
- Improved compatiblity with newer games (e.g. PRAGMATA)
- Better handling of alpha maps (prevents unintended transparency) (NOT TESTED ON ALL GAMES)

More updates coming soon.

# Roadmap
### Short-Term
- Fix material accuracy issues
  - Improve alpha handling (transparency vs data maps like ATOS / BaseAlphaMap)
  - Correct UV mapping for special materials (e.g. hair, eyebrows, decals)
- Resolve texture misalignment in complex shaders (HairOverMap, detail maps)
- Ensure consistency between original addon and forked version behaviour

### Mid-Term
- Implement smarter shader detection
  - Automatically detect when materials require UV1 instead of UV0
  - Improve handling of hair, skin and eye materials
- Refactor material pipelines
  - Reduce hardcoded cases
  - Make node generation more modular and predictable
- Improve compatibility with newer RE Engine titles (RE9, MHWILDS, etc.)

### Long-Term
- Achieve near 1:1 visual parity with in-game materials
- Support more advanced shader features:
  - Proper transluceny handling
  - Better subsurface scattering (SSS)
  - Accurate hair shading
- Optimize import performance and reduce redundant texture processing
- Clean up and document the codebase for easier contributions

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
