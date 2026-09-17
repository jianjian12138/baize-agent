# OpenSpec: V30 Darwinian Meta-Tool Synthesizer

## 1. Context & Motivation
Fixed toolsets constrain autonomous agents. When an agent requires domain-specific data parsing, AST mutations, or specialized text manipulation, it should dynamically compile and verify custom Python micro-tools using the standard library.

## 2. Core Entities

### 2.1 SynthesizedTool
```python
@dataclass
class SynthesizedTool:
    name: str
    description: str
    code_source: str
    inline_test_code: str
    gene_signature: str
    certified: bool = False
    usage_count: int = 0
    success_count: int = 0
```

### 2.2 GeneStore
Tracks usage statistics and evolutionary status (`candidate`, `promoted`, `deprecated`).
A synthesized tool is automatically promoted when:
- `usage_count >= 3`
- `success_rate >= 0.8`

## 3. Guarantees
- **Pure Standard Library**: Synthesized code can only import Python built-ins.
- **Mandatory Self-Certification**: Code without passing inline tests cannot be registered or executed.
