# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
import uuid

import frappe
from frappe import _
import requests

from flow.ledger.credits import get_ai_settings

logger = frappe.logger("copilot_crm.qdrant")
logger.setLevel(logging.INFO)


class QdrantStore:
	def __init__(self, url: str | None = None, api_key: str | None = None, collection: str | None = None):
		settings = get_ai_settings()
		self.url = (url or settings.get("qdrant_url") or "http://localhost:6333").rstrip("/")
		self.api_key = api_key or settings.get("qdrant_api_key")
		self.collection = collection or settings.get("qdrant_collection") or "crm_knowledge"
		self.headers = {"Content-Type": "application/json"}
		if self.api_key:
			self.headers["api-key"] = self.api_key

	def is_available(self) -> bool:
		try:
			res = requests.get(f"{self.url}/collections", headers=self.headers, timeout=3)
			return res.status_code == 200
		except Exception:
			return False

	def ensure_collection(self, dimension: int = 1536) -> bool:
		try:
			res = requests.get(f"{self.url}/collections/{self.collection}", headers=self.headers, timeout=5)
			if res.status_code == 200:
				return True

			payload = {
				"vectors": {
					"size": dimension,
					"distance": "Cosine",
				}
			}
			create_res = requests.put(
				f"{self.url}/collections/{self.collection}",
				headers=self.headers,
				json=payload,
				timeout=10,
			)
			return create_res.status_code in (200, 201)
		except Exception as e:
			logger.warning(f"Failed to ensure Qdrant collection {self.collection}: {e}")
			return False

	def upsert_points(self, points: list[dict[str, Any]]) -> bool:
		if not points:
			return True
		try:
			res = requests.put(
				f"{self.url}/collections/{self.collection}/points?wait=true",
				headers=self.headers,
				json={"points": points},
				timeout=15,
			)
			return res.status_code == 200
		except Exception as e:
			logger.warning(f"Failed to upsert points to Qdrant: {e}")
			return False

	def search(
		self,
		vector: list[float],
		limit: int = 5,
		filter_conditions: dict[str, Any] | None = None,
	) -> list[dict[str, Any]]:
		try:
			payload: dict[str, Any] = {
				"vector": vector,
				"limit": limit,
				"with_payload": True,
			}
			if filter_conditions:
				must = []
				for k, v in filter_conditions.items():
					if v:
						must.append({"key": k, "match": {"value": v}})
				if must:
					payload["filter"] = {"must": must}

			res = requests.post(
				f"{self.url}/collections/{self.collection}/points/search",
				headers=self.headers,
				json=payload,
				timeout=10,
			)
			if res.status_code == 200:
				results = res.json().get("result", [])
				formatted = []
				for r in results:
					pl = r.get("payload", {})
					formatted.append(
						{
							"id": r.get("id"),
							"score": r.get("score"),
							"text": pl.get("text", ""),
							"doctype": pl.get("doctype", ""),
							"docname": pl.get("docname", ""),
							"date": pl.get("date", ""),
							"author": pl.get("author", ""),
							"metadata": pl.get("metadata", {}),
						}
					)
				return formatted
		except Exception as e:
			logger.warning(f"Qdrant search error: {e}")

		return []


def get_embedding_vector(text: str) -> list[float]:
	"""Generate embedding using Flow knowledge embedder or a hash fallback."""
	from flow.knowledge.embedder import embed_texts

	try:
		vectors = embed_texts([text])
		if vectors and len(vectors[0]) > 0:
			return vectors[0]
	except Exception:
		pass

	# Stable deterministic vector fallback when no external embedding API is configured
	dim = 1536
	h = hashlib.sha256(text.encode("utf-8")).digest()
	vec = []
	for i in range(dim):
		b = h[i % len(h)]
		vec.append((float(b) / 128.0) - 1.0)
	norm = sum(x * x for x in vec) ** 0.5 or 1.0
	return [x / norm for x in vec]


def index_crm_document(
	doctype: str,
	docname: str,
	text: str,
	author: str | None = None,
	date: str | None = None,
	metadata: dict[str, Any] | None = None,
) -> bool:
	"""Index a CRM text asset (Note, Call Log transcription, Email) into Qdrant."""
	text = (text or "").strip()
	if not text or len(text) < 10:
		return False

	store = QdrantStore()
	if not store.is_available():
		return False

	vector = get_embedding_vector(text)
	store.ensure_collection(dimension=len(vector))

	point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doctype}:{docname}"))
	point = {
		"id": point_id,
		"vector": vector,
		"payload": {
			"text": text[:4000],
			"doctype": doctype,
			"docname": docname,
			"author": author or frappe.session.user,
			"date": date or str(frappe.utils.now_datetime()),
			"metadata": metadata or {},
		},
	}
	return store.upsert_points([point])


def search_crm_knowledge(
	query: str,
	doctype: str | None = None,
	docname: str | None = None,
	limit: int = 5,
) -> list[dict[str, Any]]:
	"""Semantic search over CRM company memory (Qdrant) with graceful database fallback."""
	store = QdrantStore()
	query_vector = get_embedding_vector(query)

	filter_conditions = {}
	if doctype:
		filter_conditions["doctype"] = doctype
	if docname:
		filter_conditions["docname"] = docname

	if store.is_available():
		hits = store.search(query_vector, limit=limit, filter_conditions=filter_conditions)
		if hits:
			return hits

	# Graceful fallback: Frappe DB query on notes and communications
	fallback_results = []
	like_query = f"%{query}%"

	# 1. Search Notes
	if not doctype or doctype == "FCRM Note":
		notes = frappe.get_list(
			"FCRM Note",
			filters={"content": ["like", like_query]},
			fields=["name", "title", "content", "reference_doctype", "reference_docname", "creation"],
			limit=limit,
		)
		for n in notes:
			fallback_results.append(
				{
					"score": 0.85,
					"text": f"Nota '{n.title}': {n.content}",
					"doctype": n.reference_doctype or "FCRM Note",
					"docname": n.reference_docname or n.name,
					"date": str(n.creation),
					"author": "",
				}
			)

	# 2. Search Call Logs
	if not doctype or doctype == "CRM Call Log":
		logs = frappe.get_list(
			"CRM Call Log",
			filters={"summary": ["like", like_query]} if frappe.db.has_column("CRM Call Log", "summary") else {},
			fields=["name", "creation"],
			limit=limit,
		)
		for l in logs:
			fallback_results.append(
				{
					"score": 0.80,
					"text": f"Chamada {l.name}",
					"doctype": "CRM Call Log",
					"docname": l.name,
					"date": str(l.creation),
					"author": "",
				}
			)

	return fallback_results[:limit]


def on_note_update(doc, method=None):
	"""Auto-index updated note in Qdrant."""
	try:
		content = f"{doc.title or ''}\n{doc.content or ''}".strip()
		index_crm_document(
			doctype="FCRM Note",
			docname=doc.name,
			text=content,
			author=doc.owner,
			date=str(doc.creation),
			metadata={
				"title": doc.title,
				"reference_doctype": getattr(doc, "reference_doctype", None),
				"reference_docname": getattr(doc, "reference_docname", None),
			},
		)
	except Exception:
		pass


def on_call_log_update(doc, method=None):
	"""Auto-index updated call transcript/summary in Qdrant."""
	try:
		transcript = getattr(doc, "summary", None) or getattr(doc, "notes", None) or getattr(doc, "transcript", None)
		if transcript:
			index_crm_document(
				doctype="CRM Call Log",
				docname=doc.name,
				text=str(transcript),
				author=doc.owner,
				date=str(doc.creation),
				metadata={
					"from": getattr(doc, "from", ""),
					"to": getattr(doc, "to", ""),
					"reference_doctype": getattr(doc, "reference_doctype", None),
					"reference_docname": getattr(doc, "reference_docname", None),
				},
			)
	except Exception:
		pass


def on_communication_update(doc, method=None):
	"""Auto-index email communications in Qdrant."""
	try:
		if getattr(doc, "communication_medium", "") == "Email" and getattr(doc, "content", None):
			text = f"Assunto: {doc.subject or ''}\nDe: {doc.sender or ''}\nPara: {doc.recipients or ''}\n\n{doc.content}"
			index_crm_document(
				doctype="Communication",
				docname=doc.name,
				text=text,
				author=doc.sender,
				date=str(doc.creation),
				metadata={
					"subject": doc.subject,
					"reference_doctype": getattr(doc, "reference_doctype", None),
					"reference_name": getattr(doc, "reference_name", None),
				},
			)
	except Exception:
		pass
