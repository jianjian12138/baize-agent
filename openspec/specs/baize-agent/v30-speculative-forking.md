# OpenSpec: V30 Speculative Time-Travel Forking Engine

## 1. Context & Motivation
Traditional agents attempt solutions by directly modifying the active workspace. When complex refactoring or bug fixing fails midway, the workspace becomes corrupted with broken intermediate state.

V30 introduces **Speculative Time-Travel Forking**:
- The agent spawns $N$ isolated candidate timelines in memory/ephemeral virtual workspaces;
- Each timeline explores a distinct strategy (`minimal_patch`, `modular_refactor`, `contract_driven`);
- A multi-dimensional evaluator ranks the results based on verification checks, AST complexity, code churn, and execution time;
- The highest-scoring timeline's atomic diff is merged into the real workspace; rejected timelines are discarded with zero footprint.

## 2. Data Structures & Schema

### 2.1 TimelineStrategy Enum
- `minimal_patch`: Targets immediate, localized fix with smallest line diff.
- `modular_refactor`: Restructures functions/classes for high maintainability.
- `contract_driven`: Generates property/boundary tests first, then satisfies them.

### 2.2 SpeculativeTimeline Dataclass
```python
@dataclass
class SpeculativeTimeline:
    timeline_id: str
    strategy: str  # minimal_patch | modular_refactor | contract_driven
    status: str    # pending | running | verified | failed
    score: float   # 0.0 to 1.0
    modified_files: dict[str, str]  # rel_path -> new_content
    checks_passed: int
    total_checks: int
    churn_lines: int
    duration_ms: int
    error_message: str | None = None
```

### 2.3 Evaluation Function
$$\text{Score} = 0.4 \times \left(\frac{\text{checks\_passed}}{\text{total\_checks}}\right) + 0.3 \times \text{Simplicity} + 0.2 \times \text{TestCoverage} - 0.1 \times \text{NormalizedChurn}$$

## 3. Guarantees & Constraints
- **Zero Real Workspace Pollution**: Real files on disk are never touched during timeline evaluation.
- **Fail-Closed on Equal Scores**: In case of a tie, the timeline with the lowest `churn_lines` wins.
- **Pure Python Standard Library**: Implemented strictly using `tempfile`, `pathlib`, `shutil`, `difflib`, and `dataclasses`.
