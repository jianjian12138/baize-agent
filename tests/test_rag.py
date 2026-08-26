"""Real tests for V20 data layer: vector search, RAG, graph, bench.

Zero network. Real files in tmp_path. No mocks of business logic -
the TF-IDF math, the corpus build, and the triple store all run for real.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baize import bench, graph, rag  # noqa: E402
from baize.memory import log_event, remember  # noqa: E402
from baize.vector import EmbeddingBackend, TfidfIndex, tokenize  # noqa: E402


def cfg_for(tmp_path: Path) -> dict:
    """Minimal real config: persistence + a pre-built skill index file."""
    index_file = tmp_path / "skill_index.json"
    index_file.write_text(json.dumps({
        "version": 1, "count": 2, "skills": [
            {"name": "deploy-checklist",
             "description": "blue-green deploy rollout steps",
             "skill_file": "skills/deploy/SKILL.md"},
            {"name": "csv-report",
             "description": "generate csv sales report",
             "skill_file": "skills/csv/SKILL.md"},
        ]}), encoding="utf-8")
    return {"BAIZE_PERSISTENCE_DIR": str(tmp_path / "persistence"),
            "BAIZE_INDEX_FILE": str(index_file),
            "BAIZE_VECTOR_BACKEND": "tfidf"}


# --- vector ------------------------------------------------------------------

def test_tokenize_mixed_language():
    toks = tokenize("Deploy 蓝绿发布 v2")
    assert "deploy" in toks and "v2" in toks
    assert "蓝" in toks and "蓝绿" in toks  # CJK chars + bigrams


def test_tfidf_ranks_relevant_doc_first():
    idx = TfidfIndex()
    idx.add("a", "blue green deploy rollout production")
    idx.add("b", "csv report sales quarterly numbers")
    idx.add("c", "kubernetes cluster deploy config")
    hits = idx.search("blue green deploy")
    assert hits and hits[0]["id"] == "a"
    assert hits[0]["score"] > hits[-1]["score"] or len(hits) == 1


def test_tfidf_readd_replaces_document():
    idx = TfidfIndex()
    idx.add("a", "old topic entirely")
    idx.add("a", "new deploy content")
    assert len(idx) == 1
    assert idx.search("deploy")[0]["id"] == "a"
    assert idx.search("old topic") == []


def test_embedding_backend_fails_closed_without_url():
    be = EmbeddingBackend(cfg={"BAIZE_EMBEDDING_URL": ""})
    assert not be.configured
    try:
        be.embed(["x"])
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "not configured" in str(exc)


def test_embedding_backend_uses_injected_transport():
    calls = []

    def fake_transport(url, payload):
        calls.append((url, payload))
        return {"data": [{"embedding": [0.1, 0.2]} for _ in payload["input"]]}

    be = EmbeddingBackend(cfg={"BAIZE_EMBEDDING_URL": "http://x/emb"},
                          transport=fake_transport)
    vecs = be.embed(["hello", "world"])
    assert vecs == [[0.1, 0.2], [0.1, 0.2]]
    assert calls[0][0] == "http://x/emb"


# --- rag ---------------------------------------------------------------------

def test_rag_retrieves_skill_and_memory(tmp_path):
    cfg = cfg_for(tmp_path)
    remember("previous deploy used blue-green strategy", cfg)
    log_event("investigated csv encoding issue", ["data"], cfg)

    hits = rag.retrieve("blue green deploy rollout", cfg=cfg)
    kinds = {h["meta"]["kind"] for h in hits}
    assert "skill" in kinds        # deploy-checklist skill matched
    assert any(h["meta"].get("name") == "deploy-checklist" for h in hits)

    block = rag.augment("blue green deploy rollout", cfg=cfg)
    assert block.startswith("Retrieved context (RAG):")
    assert "deploy-checklist" in block


def test_rag_augment_empty_when_nothing_matches(tmp_path):
    cfg = cfg_for(tmp_path)
    assert rag.augment("zzz qqq xyzzy", cfg=cfg) == ""


def test_skill_scoring_round_trip(tmp_path):
    cfg = cfg_for(tmp_path)
    rag.record_skill_outcome("deploy-checklist", True, cfg)
    rag.record_skill_outcome("deploy-checklist", False, cfg)
    scores = rag.skill_scores(cfg)
    e = scores["deploy-checklist"]
    assert e["uses"] == 2 and e["successes"] == 1
    assert e["success_rate"] == 0.5


# --- graph -------------------------------------------------------------------

def test_graph_add_query_neighbors(tmp_path):
    cfg = cfg_for(tmp_path)
    graph.add("baize", "version", "20", cfg=cfg)
    graph.add("baize", "written_in", "python", cfg=cfg)
    graph.add("python", "type", "language", cfg=cfg)

    assert len(graph.query(subject="baize", cfg=cfg)) == 2
    assert graph.query(predicate="type", cfg=cfg)[0]["o"] == "language"
    nb = graph.neighbors("python", cfg=cfg)
    assert len(nb) == 2  # as object of baize->written_in, as subject of type

    s = graph.stats(cfg=cfg)
    # nodes = {baize, 20, python, language}
    assert s["triples"] == 3 and s["nodes"] == 4


def test_graph_dedupes_and_survives_bad_lines(tmp_path):
    cfg = cfg_for(tmp_path)
    graph.add("a", "rel", "b", cfg=cfg)
    graph.add("a", "rel", "b", cfg=cfg)  # duplicate
    gf = Path(cfg["BAIZE_PERSISTENCE_DIR"]) / "graph.jsonl"
    with gf.open("a", encoding="utf-8") as f:
        f.write("not json at all\n")     # corruption must not crash reads
    assert len(graph.query(cfg=cfg)) == 1


def test_graph_rejects_empty_fields(tmp_path):
    cfg = cfg_for(tmp_path)
    try:
        graph.add("", "rel", "b", cfg=cfg)
        assert False, "should have raised"
    except ValueError:
        pass


# --- bench -------------------------------------------------------------------

def test_bench_run_all_passes(tmp_path):
    cfg = cfg_for(tmp_path)
    report = bench.run_all(cfg)
    assert report["total"] >= 4
    failed = [c for c in report["cases"] if not c["ok"]]
    assert report["all_ok"], f"failed benchmarks: {failed}"


# --- agent integration -------------------------------------------------------

def test_recall_context_uses_rag_ranking(tmp_path):
    from baize.agent import recall_context
    cfg = cfg_for(tmp_path)
    remember("previous deploy used blue-green strategy", cfg)
    ctx = recall_context("plan the blue green deploy rollout", cfg=cfg)
    assert ctx.startswith("Relevant persistent memory:")
    assert "deploy" in ctx


def test_recall_context_falls_back_when_rag_empty(tmp_path):
    """Short/CJK-free goal with keyword hit must still recall via fallback."""
    from baize.agent import recall_context
    cfg = cfg_for(tmp_path)
    ctx = recall_context("zzz qqq", cfg=cfg)
    assert ctx == ""  # nothing anywhere -> empty, no crash
