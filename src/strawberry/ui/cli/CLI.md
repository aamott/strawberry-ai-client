---
description: CLI UI overview for the Spoke and todo items. 
---

# CLI UI (Spoke)

This document tracks the CLI implementation in the Spoke and links to the
planning/design doc.

## Implementation location

- Source: `ai-pc-spoke/src/strawberry/ui/cli/`
- Entrypoint: `strawberry-cli` → `strawberry.ui.cli.main:main`

## Design reference

- Plan: [`docs/plans/CLI-UI-Design.md`](../../../../../docs/plans/CLI-UI-Design.md)

## Notes
- There are two versions of the CLI UI: 
- The CLI is wired for a future `SpokeCore` entrypoint and currently falls back
  to a minimal echo core when the core is not available.
- Tool call expansion uses `Shift+Tab` with `/last` as a fallback.


## TODO
- [ ] Detect hub coming online/offline