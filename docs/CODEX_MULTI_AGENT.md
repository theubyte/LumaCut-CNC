# Codex multi-agent setup for LumaCut CNC on Windows

This guide configures the **ChatGPT desktop app in Codex mode** with multiple parallel local Worktree chats. It does not install software on your PC remotely or start autonomous agents by merely being committed to GitHub.

## 1. Windows prerequisites

Open PowerShell:

    winget install --id 9PLM9XGG6VKS -s msstore
    winget install --id Git.Git -e
    winget install --id GitHub.cli -e
    winget install --id Microsoft.VisualStudioCode -e
    winget install --id Python.Python.3.14 -e
    winget install --id OpenJS.NodeJS.LTS -e

Restart PowerShell. Authenticate GitHub interactively:

    gh auth login
    gh auth status

Sign in to the ChatGPT desktop app with your existing ChatGPT account and select Codex. The app uses Git and GitHub CLI installed on Windows.

## 2. Local repository

    New-Item -ItemType Directory -Force -Path "C:\Dev" | Out-Null
    Set-Location "C:\Dev"
    git clone https://github.com/theubyte/LumaCut-CNC.git
    Set-Location "C:\Dev\LumaCut-CNC"
    git status

If the repository is already cloned, do not clone over it. Preserve local uncommitted work; inspect git status before pulling.

## 3. Open in Codex and isolate work

- In the desktop app select Codex, Add new project, and C:\Dev\LumaCut-CNC.
- Use Windows native agent environment and PowerShell.
- Use Ask for approval rather than Full access. Restrict filesystem access to the repo/worktree where possible.
- Start each independent coding task using **Worktree** with main as its base.
- Each Codex chat gets a managed worktree. To publish results, choose Create branch here, commit, push, and create a PR. Review changes before merging.
- Always open new threads after merging AGENTS.md so the instructions are loaded.

## 4. Four parallel starter chats (start each as a Worktree)

### Agent A - Windows Studio
Read AGENTS.md and software/lumacut-studio. Audit vector drawing, multilayer cut/engrave settings, import, camera overlays, UI layout, and unit tests. First report a prioritized implementation plan tied to real files. Then implement the highest-priority self-contained Studio improvement with tests, without editing firmware or Pi code.

### Agent B - Raspberry Pi 400 UI/API
Read AGENTS.md, docs/PI400_CONTROL_STUDIO.md and pi400/. Audit settings persistence, machine state, Web UI, authentication boundaries, and USB ownership. Fix a reproducible, localized issue with tests. Do not alter SKR firmware or automatically deploy to the Pi.

### Agent C - Firmware and hardware contract
Read AGENTS.md, docs/PI400_MARLIN_MIGRATION.md, docs/FAN1_LASER_PI400_RELEASE.md and firmware/. Compare experimental Marlin vs existing grblHAL build contracts and map protocol incompatibilities. Add automated verification or documentation only at first. Do not flash hardware, run motors, drive PWM, or change electrical assumptions.

### Agent D - Integration and regression
Read AGENTS.md and tests/. Audit LightBurn to Pi to SKR boundaries, transport acknowledgments, homing state, disconnection/reconnection and safety checks. Add isolated regression tests for a confirmed bug. Do not change active production transport without a coordinated interface plan.

## 5. Integration/checklist

1. Ask each agent for its changed file list, diff summary, tests run, limitations, and hardware validation status.
2. Prefer separate PRs. Do not push or merge directly to main.
3. Run Python tests and Studio unit tests as applicable:

       python -m unittest discover -s tests -v
       npm --prefix software/lumacut-studio install
       npm --prefix software/lumacut-studio run test:unit

4. Review contracts before merging cross-cutting changes.
5. The production Raspberry Pi reads main for updates. Never merge and deploy casually.
6. For Windows Tauri packaging, install Rust, Microsoft C++ Build Tools with the Desktop development with C++ workload, and WebView2, then validate the Studio package/build workflow.
7. Never treat a successful software build as hardware authorization.

## 6. Optional advanced orchestration

The desktop app's **parallel Worktree chats** are the reliable baseline, independently started by a user. Do not confuse them with a single chat automatically spawning subordinate agents. If your Codex version supports subagents, you may separately ask a coordinator chat to delegate independent read-only research and compare findings, but shared-file writers still need separated Git worktrees and review.

References:
- https://learn.chatgpt.com/docs/app/windows
- https://learn.chatgpt.com/docs/environments/git-worktrees
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://v2.tauri.app/start/prerequisites/
