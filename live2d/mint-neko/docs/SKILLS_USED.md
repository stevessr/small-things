# Skills used

## arjunindia/live2d-skills

Applied:
- `live2d-cubism-web-quickstart`: runtime asset layout and `CubismUserModel` loading architecture.
- `live2d-cubism-web-rendering`: WebGL state and premultiplied-alpha texture upload.
- `live2d-cubism-web-motion`: motion groups, expressions, blink/breath/physics planning and V2 looping.

## HKUDS/CLI-Anything — cli-anything-live2d

Applied workflow:
- `init` semantics: create a complete runtime descriptor scaffold with a deliberate placeholder `.moc3`.
- `validate`: verify every referenced texture / motion / expression / physics / display-info file exists.
- `validate --strict`: reject the 8-byte placeholder `.moc3`, exactly as a production safety gate should.
- `lint`: use power-of-two PNG texture, conventional Idle/TapHead groups and clean names.
- `runtime-check`: explicitly report Web SDK rendering blocked until a real `.moc3` is exported.
- `snapshot`: generate HTML preview metadata.
- `pack`: package the complete handoff as a ZIP.

## Important boundary

Neither skill creates a production `.moc3` from a flat illustration.
`.moc3` contains compiled Cubism mesh/deformer/model data and must come from a real Cubism model source/export.
The CLI-Anything implementation itself intentionally creates only an 8-byte `MOC3` placeholder during `init`.
