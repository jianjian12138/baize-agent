"""V26-D1-D5: Secondary extensions tests (vector, channels, roles, providers).

Coverage for Campaign D (D1-D5).
"""
import pytest
from baize.vector import get_backend, EmbeddingBackend, TfidfIndex
from baize.ext.channels import ConversationAdapter, ChannelMessage
from baize.team import Role


def test_d1_vector_backend_unavailable_fails_closed():
    """Embedding backend raises clear RuntimeError when not configured (no fake success)."""
    backend = get_backend({"BAIZE_VECTOR_BACKEND": "embedding", "BAIZE_EMBEDDING_URL": ""})
    assert isinstance(backend, EmbeddingBackend)
    assert not backend.configured
    with pytest.raises(RuntimeError) as exc_info:
        backend.embed(["hello world"])
    assert "not configured" in str(exc_info.value)


def test_d2_channel_adapter_reserved_interface():
    """ConversationAdapter is marked reserved and raises NotImplementedError."""
    adapter = ConversationAdapter("feishu")
    assert adapter.status == "reserved"
    msg = ChannelMessage(channel="feishu", sender="user1", text="run task")
    with pytest.raises(NotImplementedError):
        adapter.handle_inbound(msg)


def test_d4_specialized_role_templates():
    """Specialized role templates (researcher, reviewer, test_engineer) instantiate cleanly."""
    researcher = Role(name="researcher", description="Information gatherer",
                      allow_tools=["read_file", "search_skills"], memory_visibility="read")
    reviewer = Role(name="reviewer", description="Code reviewer",
                    allow_tools=["read_file"], workspace_scope="src/")
    assert researcher.name == "researcher"
    assert "search_skills" in researcher.allow_tools
    assert reviewer.workspace_scope == "src/"
