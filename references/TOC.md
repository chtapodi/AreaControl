# PyScript Subject Guidance TOC

Use this file only when the current PyScript task needs more detail than `pyscript/AGENTS.md` provides.

## Mandatory Topics

- Topic: Operations, reload safety, and verification
  Match: reload behavior, runtime safety, debugging triggers, deployment checks, service lifecycle, production recovery
  Read: `pyscript/references/operations-and-verification.md`
  Requirement: read when changing runtime behavior or validating any PyScript code change

## Topic References

- Topic: Architecture and mental model
  Match: `area_tree.py`, event flow, areas, devices, drivers, trackers, merge behavior, runtime model
  Read: `pyscript/references/architecture.md`
  Requirement: read when relevant

- Topic: Configuration and extension playbooks
  Match: `layout.yml`, `devices.yml`, `rules.yml`, `connections.yml`, `sun_config.yml`, adding rules, drivers, helpers, trackers, or sun/blind behavior
  Read: `pyscript/references/config-and-extension.md`
  Requirement: read when relevant

- Topic: PyScript documentation and Obsidian updates
  Match: architecture docs, the documentation, the vault, Obsidian, operational docs, implementation notes, PyScript-related documentation maintenance
  Read: `pyscript/references/docs-and-obsidian.md`
  Requirement: read when relevant

- Topic: Log debugging and behavior investigation
  Match: why did, light turned off, lights not responding, sensor events, debugging, motion not working, log investigation, unexpected state change
  Read: `pyscript/references/log-debugging.md`
  Requirement: read when relevant
