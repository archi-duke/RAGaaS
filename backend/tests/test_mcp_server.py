"""MCP 서버 도구 등록 확인 (docs/design/agent/design-mcp-agent-query.md §5)."""
import asyncio

import pytest

pytest.importorskip("mcp")


def test_tools_registered():
    from app.mcp_server import mcp
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert {"list_kbs", "describe_kb", "lookup_values", "resolve_entities", "query_plan", "get_chunks", "search", "describe_entity"} <= names
    qp = next(t for t in tools if t.name == "query_plan")
    props = (getattr(qp, "input_schema", None) or qp.inputSchema)["properties"]
    assert {"kb_id", "kind", "where", "return_paths", "aggregate"} <= set(props)
    assert "sparql" not in names          # 원문 SPARQL 은 MCP 에 노출하지 않음 (관리자 REST 전용)
