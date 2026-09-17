# Architecture Foundation

## Dependency direction

External systems are adapters around application/domain logic. Provider-specific code, Check-Host
protocol details, SSH commands, master API details, and Telegram transport behavior must not leak into
the replacement orchestration core.

Conceptual dependency direction:

```text
API / Telegram / Workers
          |
          v
Application Services / Orchestrator
          |
          v
Abstract contracts / domain policy
          ^
          |
Provider / Check-Host / SSH / Master adapters
```

## Phase boundaries

Phase 1 contains only foundation concerns: package layout, configuration, secret handling, development
containers, logging, common exceptions, health API, tests, and documentation. Later-phase packages are
present only as empty namespace placeholders so the target structure is stable; their business logic is
not implemented prematurely.
