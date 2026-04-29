# PyScript Documentation And Obsidian Updates

When these references say "the documentation", "the vault", or "Obsidian", they all mean the Obsidian MCP server — the single source of truth for project documentation. Use the `obsidian_*` MCP tools to read and write notes. See `.opencode/references/obsidian-vault.md` for full terminology and workflow rules.

## When To Read

- Updating PyScript architecture docs, runbooks, or implementation notes
- Capturing behavior changes after a PyScript modification
- Deciding which Obsidian notes need targeted updates

## Critical Rules

- Use the Obsidian MCP server for vault updates.
- Prefer surgical updates such as `obsidian_patch_note` over large rewrites when only part of a note changed.
- Update only notes relevant to the change you actually made.
- For general vault workflow guidance, read `.opencode/references/obsidian-vault.md`.

## Target Notes

- `_context.md` at `Areas/Home/Homeassistant/_context.md` when new concepts, services, or config keys were added
- Per-class docs in `Areas/Home/Homeassistant/Automation/Documentation/<ClassName>.md` when a class interface or behavior changed
- `Core Engine (area_tree.py).md` when services, class summaries, or config loading changed
- `Drivers and Device State Model` notes when driver behavior or state guardrails changed
- `Configuration Reference` when PyScript YAML schema changed
- `Services, Testing, and Diagnostics` when startup, services, or runbook steps changed

## Workflow Rules

- Update documentation after the change is implemented and validated.
- Keep documentation aligned with the real runtime behavior, not intended behavior.
- Link to the nearest authoritative note instead of duplicating the same explanation in multiple places.
- For new PyScript-related Obsidian notes that should stay discoverable, add a durable link in `Projects/Hub/Dashboard.md` in the most appropriate manual section.
- When replacing older planning or documentation notes for the same PyScript topic, update the dashboard link to the new note instead of leaving both active.

## References

- `.opencode/references/docs-and-obsidian.md`
- `.opencode/references/obsidian-vault.md`
- `pyscript/references/operations-and-verification.md`
