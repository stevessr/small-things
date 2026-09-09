# Production QA Checklist

## Art separation
- [ ] All hidden facial regions repainted under bangs
- [ ] Ear roots complete under hair/accessories
- [ ] Torso/shoulders complete under clothes
- [ ] Back skirt and upper-leg coverage complete
- [ ] Tail root complete behind skirt
- [ ] Every long hair lock has overlap margin

## ArtMesh / deformers
- [ ] Dense mesh at silhouette, eyes, mouth and curls
- [ ] Warp deformers nested consistently
- [ ] Rotation deformers only where joint-like motion is intended
- [ ] No unnecessary parent-child double transforms

## Face
- [ ] Angle X/Y 3x3 corner test
- [ ] Angle Z ±30
- [ ] Blink preserves lash contour
- [ ] Iris cannot escape sclera clipping mask
- [ ] MouthForm x MouthOpenY combinations checked

## Physics
- [ ] Front hair stable at rapid head movement
- [ ] Rear hair L/R independent
- [ ] Cat ears spring subtly, not rubbery
- [ ] Tail has delayed multi-segment motion
- [ ] Skirt/accessories do not oscillate indefinitely

## Runtime
- [ ] Real `.moc3` replaces placeholder
- [ ] `python tools/validate.py` dependency check passes
- [ ] CLI-Anything strict validate passes
- [ ] Web SDK rendering has no black alpha seams
- [ ] Motion V2 loops smoothly
- [ ] Expressions do not fight Blink/LipSync
