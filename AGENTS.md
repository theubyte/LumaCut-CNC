# LumaCut CNC - Codex Agent Instructions

## Source of truth
- Read README.md, docs/PROJECT_STATE.md, and the documentation for the component you edit before changing code.
- Work from the actual repository state. Distinguish implemented, unit-tested, built, hardware-tested, and deployed. Never claim hardware verification from CI.
- Active components: software/lumacut-studio/ (Windows Tauri studio), pi400/ (Raspberry Pi 400 host), firmware/ (SKR Mini MZ V1.0), tests/, and .github/workflows/.
- The older ESP32 HMI is archived; do not make it a new architectural dependency.
- grblHAL and experimental Marlin are **separate firmware and host stacks**. The Marlin gateway must use native Marlin responses; do not masquerade as GRBL. Do not migrate between them implicitly.

## Parallel-agent coordination
- Use one independent Codex Worktree per development thread; create a dedicated feature branch when publishing.
- The older note in docs/PROJECT_STATE.md saying no development branches are needed predates this new multi-agent workflow. For concurrent development, use feature branches and pull requests.
- One owner per changed area. A change affecting shared protocol/API contracts requires documenting that contract and coordinating consumer updates before integration.
- Keep unrelated edits out of each agent's branch. Do not overwrite, reset, or discard other agents' work.
- Prefer small PRs. Review diffs, report tests and limitations, then merge deliberately.
- Do not push directly to main or deploy/flash machine firmware unless the user explicitly requests it.

## Machine-control and safety constraints
- Never infer actual pin behavior, motor directions, limit polarity, PWM voltage, hardware isolation, or fail-off from code alone.
- No real laser activation, firmware flashing, automatic homing, or live motion tests without explicit authorization and a verified physical test plan.
- Treat physical E-stop, door/laser interlocks, laser power isolation, and unexpected PWM emission as hardware concerns, not software promises.
- Preserve the proven fallback while working on the experimental Marlin stack.
- Never commit secrets, tokens, access keys, service passwords, machine-specific credentials, or private configuration.

## Verification expectations
- For Python/Pi/transport changes: python -m unittest discover -s tests -v
- For Windows studio changes, when dependencies are installed: npm --prefix software/lumacut-studio run test:unit
- For relevant UI changes, inspect and run the available smoke tests; report browser/runtime limitations.
- For firmware changes, use the matching build script/CI workflow only after checking the variant and prerequisites.
- Treat any failed, skipped, or unrun test honestly. CI workflows in this repository may be manual-only.
- Every final report: scope, files changed, tests actually run, known issues, hardware-verification status, and merge/deployment instructions.
