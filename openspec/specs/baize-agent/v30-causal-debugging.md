# OpenSpec: V30 AST-Level Causal Debugging & Mutation Fuzzing

## 1. Context & Motivation
When an error occurs, naive LLM agents blindly append raw tracebacks to their prompt, frequently hallucinating root causes or deleting unit tests to fake success.

V30 introduces **AST Causal Debugging**:
- Slices the Python AST of the failing function and tracks variables involved in the fault;
- Automatically generates 3 adversarial mutation fuzzing inputs (e.g. `None`, empty string, boundary limits, invalid types);
- Requires the fix to prove both historical test pass and mutation fuzzing immunity.

## 2. Core Entities

### 2.1 CausalSlice
```python
@dataclass
class CausalSlice:
    target_file: str
    target_function: str
    line_range: tuple[int, int]
    culprit_variables: list[str]
    ast_node_type: str
    error_summary: str
```

### 2.2 MutationTest
```python
@dataclass
class MutationTest:
    name: str
    input_payload: dict
    expected_behavior: str  # e.g., 'raise_value_error' | 'graceful_fallback'
    mutation_type: str      # null_pointer | boundary_overflow | type_mismatch
```

### 2.3 CausalProof
```python
@dataclass
class CausalProof:
    hypothesis: str
    causal_slice: CausalSlice
    mutation_tests: list[MutationTest]
    verified: bool
    proof_patch: str
```

## 3. Workflow
1. **Trace Analysis**: AST parser extracts the failing function node and culprit variables.
2. **Adversarial Synthesis**: Fuzzer produces 3 boundary mutation tests.
3. **Dual Verification Gate**:
   - Condition 1: Original test suite passes;
   - Condition 2: All 3 mutation tests pass;
   - Condition 3: AST complexity does not increase by more than 2x.
