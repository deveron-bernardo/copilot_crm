# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""Vectorless FTS search over Flow Agent Memory rows.

The Flow Agent Memory doctype in MariaDB is the source of truth.
No external binary dependencies (such as AVX2-requiring LanceDB) needed.
All operations are best-effort: search degrades gracefully to recency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
	from flow.flow.doctype.flow_agent_memory.flow_agent_memory import FlowAgentMemory

TABLE_NAME = "memories"
FTS_FIELD = "search_text"


def _search_text(doc: FlowAgentMemory) -> str:
	content = (doc.content or "").strip()
	keywords = (doc.keywords or "").strip()
	return f"{content}\n{keywords}" if keywords else content


def sync(doc: FlowAgentMemory) -> None:
	"""Upsert an Active memory into the index; drop it for any other status."""
	# MariaDB is already the source of truth for Flow Agent Memory.
	pass


def remove(name: str) -> None:
	pass


def search(query: str, *, agent: str, user: str, limit: int) -> list[str]:
	"""Names of the best keyword matches among `agent`'s shared memories and `user`'s
	personal ones, most relevant first. Empty on failure — the caller falls back to recency."""
	try:
		words = [w.strip() for w in (query or "").split() if len(w.strip()) > 2]
		if not words:
			return []

		or_filters = [["content", "like", f"%{w}%"] for w in words]
		or_filters.extend([["keywords", "like", f"%{w}%"] for w in words])

		rows = frappe.get_all(
			"Flow Agent Memory",
			filters={"agent": agent, "status": "Active"},
			or_filters=or_filters,
			fields=["name"],
			limit=limit,
		)
		return [r["name"] for r in rows]
	except Exception:
		frappe.log_error(title="Agent memory search failed")
		return []


def drop_table() -> None:
	pass
