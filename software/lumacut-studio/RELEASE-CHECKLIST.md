# Release acceptance gate

A green CI installer build is **not** proof of usable machine control.

## Windows package
- [ ] GitHub Actions completes on windows-latest
- [ ] Installer artifact can be downloaded and NSIS setup runs on clean Windows 11
- [ ] App opens with correct icon and no missing local scripts
- [ ] Real SVG import, drawing, project save/reopen and material profiles smoke-tested
- [ ] Program does not silently start the laser or move any motors

## Laser output gate (not yet complete)
- [ ] Freeze machine configuration: travel, axis orientation, homing switches, reserved zone and offsets
- [ ] Machine handshake implemented and simulated with controller transcripts
- [ ] Vector and raster planner deterministic tests, clipping, bounds and M4/M5 semantics
- [ ] Tested Z probe lifecycle, focus lift, and pass offsets with defined coordinate systems
- [ ] Hardware interlocks and E-stop proven by real test
- [ ] Dry-run and supervised first physical engraving

## Camera acceptance (not yet complete)
- [ ] Camera intrinsic calibration / lens distortion model
- [ ] Four-or-more observable fiducials, outlier rejection and accuracy report
- [ ] Homography coordinate convention and independent ground-truth fiducials
- [ ] Moving camera scan stage registration and image stitching
- [ ] No motion before homed machine + bounded scan path validation

## Updates
- [ ] Generate and preserve updater private signing key outside repository
- [ ] Configure corresponding updater public key and trusted HTTPS manifest endpoint
- [ ] Signed stable release, signature verification and rollback strategy
