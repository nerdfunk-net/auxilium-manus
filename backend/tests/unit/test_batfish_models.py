"""Result-size cap on BatfishQueryResponse (B3)."""

from __future__ import annotations

from models.batfish import MAX_PREVIEW_NODES, MAX_PREVIEW_ROWS, BatfishQueryResponse


def _response(**overrides) -> BatfishQueryResponse:
    base = {"success": True, "question": "q", "network": "n", "snapshot": "s", "rows": []}
    base.update(overrides)
    return BatfishQueryResponse(**base)


def test_response_rows_capped_and_flagged() -> None:
    response = _response(rows=[{"i": i} for i in range(MAX_PREVIEW_ROWS + 10)])
    assert len(response.rows) == MAX_PREVIEW_ROWS
    assert response.rows[0] == {"i": 0}
    assert response.truncated is True


def test_response_under_cap_not_flagged() -> None:
    response = _response(rows=[{"i": i} for i in range(MAX_PREVIEW_ROWS)])
    assert len(response.rows) == MAX_PREVIEW_ROWS
    assert response.truncated is False


def test_facts_by_node_capped() -> None:
    nodes = {f"n{i}": {"x": i} for i in range(MAX_PREVIEW_NODES + 5)}
    response = _response(facts_by_node=nodes)
    assert len(response.facts_by_node) == MAX_PREVIEW_NODES
    assert response.truncated is True
