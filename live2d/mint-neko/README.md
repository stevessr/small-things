# mint_neko_oc Live2D

High-precision Live2D production workspace for the mint-haired cat-eared OC.

## Quick preview

```bash
python tools/serve_preview.py
```

Open `http://127.0.0.1:8000/preview.html`.

The preview includes:

- Head / Body / Face / Physics parameter sliders
- Expressions
- Idle / TapHead / Wave / LookAround / TailWag
- Motion timeline + playback speed
- Auto blink
- Pointer-driven head/eye tracking
- Preset JSON import/export
- Layer debug outlines

## Runtime status

`runtime/` is a Cubism-compatible **runtime scaffold**. The model descriptor,
motions, expressions, physics, display info, and texture placeholder are present.

`runtime/mint_neko_oc.moc3` is deliberately only an 8-byte placeholder and is
**not** a usable Live2D model. A real `.moc3` must be exported from Live2D Cubism
Editor after true PSD separation, ArtMesh generation, deformers, keyforms, and
physics binding.

Run:

```bash
python tools/validate.py
```

The dependency check should pass; strict `.moc3` readiness will remain blocked
until a real Editor export replaces the placeholder.

## Production path

See:

- `docs/PRODUCTION_TODO.md`
- `docs/parameter_bindings.csv`
- `docs/draw_order_plan.csv`
- `docs/clipping_mask_plan.csv`
- `docs/physics_tuning_plan.csv`
- `docs/deformer_hierarchy.json`

## Skill-driven workflow

The project structure follows the supplied Live2D Cubism Web skills and the
`cli-anything-live2d` validate/lint/runtime workflow. The project intentionally
keeps a hard boundary between a design/runtime scaffold and a genuine compiled
Cubism model.
