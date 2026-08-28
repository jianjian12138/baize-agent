# OpenSpec: V30 Neuro-Symbolic Snapshot & Time-Travel Replay

## 1. Context & Motivation
Traditional debugging tools only capture stack traces. Complex multi-agent systems require capturing the unified neuro-symbolic state: symbolic assumptions, decisions, facts, active roles, neural token stats, and filesystem state deltas.

## 2. Core Entities

### 2.1 ExecutionSnapshot Dataclass
```python
@dataclass
class ExecutionSnapshot:
    snapshot_id: str
    run_id: str
    timestamp: str
    step_index: int
    active_role: str
    assumptions: list[str]
    decisions: list[str]
    facts: list[str]
    file_deltas: dict[str, str]  # rel_path -> content
    token_usage: dict[str, int]
```

### 2.2 TimeTravelReplayer
Supports:
- `step_forward()`: Advance to next execution frame.
- `step_backward()`: Revert to previous execution frame.
- `jump_to_step(index)`: Seek to arbitrary step.
- `fork_at_step(index)`: Spawns a new exploratory session from that point in time.

## 3. Storage & Guarantees
- Snapshots are stored in `persistence/snapshots/<snapshot_id>.json`.
- 100% Pure Python standard library implementation.
