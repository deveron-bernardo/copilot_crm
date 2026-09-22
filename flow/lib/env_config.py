# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import frappe


def load_env_file() -> None:
	"""Load .env file from bench root, sites dir, or app dir into os.environ."""
	candidate_paths: list[Path] = []
	try:
		if hasattr(frappe, "get_site_path"):
			candidate_paths.append(Path(frappe.get_site_path(".env")))
			candidate_paths.append(Path(frappe.get_site_path("..", ".env")))
	except Exception:
		pass

	try:
		if hasattr(frappe, "get_bench_path"):
			bench_dir = frappe.get_bench_path()
			if bench_dir:
				candidate_paths.append(Path(bench_dir) / ".env")
	except Exception:
		pass

	# Standard locations
	candidate_paths.append(Path(__file__).resolve().parents[2] / ".env")
	candidate_paths.append(Path("/home/bernardo/frappe/my-bench/.env"))
	candidate_paths.append(Path("/home/bernardo/frappe/my-bench/sites/.env"))
	candidate_paths.append(Path("/home/bernardo/frappe/my-bench/apps/flow/.env"))
	candidate_paths.append(Path("/home/bernardo/repos/copilot_crm/.env"))

	for path in candidate_paths:
		try:
			if path.is_file():
				with open(path, "r", encoding="utf-8") as f:
					for line in f:
						line = line.strip()
						if not line or line.startswith("#") or "=" not in line:
							continue
						key, val = line.split("=", 1)
						key = key.strip()
						val = val.strip().strip("'").strip('"')
						if key and key not in os.environ:
							os.environ[key] = val
		except Exception:
			pass


def get_ai_env_config() -> dict[str, Any]:
	"""Extract AI model, provider, and API key from .env, os.environ, or site_config.json."""
	load_env_file()

	conf = getattr(frappe, "conf", {}) or {}

	# 1. Specific Copilot/Flow keys
	api_key = (
		os.getenv("COPILOT_AI_API_KEY")
		or os.getenv("FLOW_AI_API_KEY")
		or conf.get("copilot_ai_api_key")
		or conf.get("flow_ai_api_key")
	)
	model_id = (
		os.getenv("COPILOT_AI_MODEL")
		or os.getenv("FLOW_AI_MODEL")
		or conf.get("copilot_ai_model")
		or conf.get("flow_ai_model")
	)
	base_url = (
		os.getenv("COPILOT_AI_BASE_URL")
		or os.getenv("FLOW_AI_BASE_URL")
		or conf.get("copilot_ai_base_url")
		or conf.get("flow_ai_base_url")
	)

	# 2. Standard provider keys fallback
	if not api_key:
		if os.getenv("OPENAI_API_KEY"):
			api_key = os.getenv("OPENAI_API_KEY")
			model_id = model_id or "openai/gpt-4o-mini"
		elif os.getenv("OPENROUTER_API_KEY"):
			api_key = os.getenv("OPENROUTER_API_KEY")
			model_id = model_id or "openrouter/openai/gpt-4o-mini"
		elif os.getenv("ANTHROPIC_API_KEY"):
			api_key = os.getenv("ANTHROPIC_API_KEY")
			model_id = model_id or "anthropic/claude-3-5-sonnet-20241022"
		elif os.getenv("GROQ_API_KEY"):
			api_key = os.getenv("GROQ_API_KEY")
			model_id = model_id or "groq/llama-3.3-70b-versatile"
		elif os.getenv("GEMINI_API_KEY"):
			api_key = os.getenv("GEMINI_API_KEY")
			model_id = model_id or "gemini/gemini-2.0-flash"

	if api_key and not model_id:
		model_id = "openai/gpt-4o-mini"

	return {
		"api_key": api_key,
		"model_id": model_id,
		"base_url": base_url,
	}


def auto_provision_from_env() -> str | None:
	"""Bootstrap Flow Model and Copilot CRM agent automatically from .env without Desk UI setup."""
	conf = get_ai_env_config()
	model_id = conf.get("model_id")
	api_key = conf.get("api_key")
	base_url = conf.get("base_url")

	if not model_id or not api_key:
		return None

	title = "Default Copilot Model"

	try:
		if not frappe.db.exists("Flow Model", title):
			doc = frappe.get_doc(
				{
					"doctype": "Flow Model",
					"title": title,
					"model_id": model_id,
					"api_key": api_key,
					"base_url": base_url,
					"enabled": 1,
				}
			)
			doc.insert(ignore_permissions=True)
		else:
			doc = frappe.get_doc("Flow Model", title)
			updated = False
			if doc.model_id != model_id:
				doc.model_id = model_id
				updated = True
			if api_key and doc.get_password("api_key", raise_exception=False) != api_key:
				doc.api_key = api_key
				updated = True
			if base_url and doc.base_url != base_url:
				doc.base_url = base_url
				updated = True
			if not doc.enabled:
				doc.enabled = 1
				updated = True
			if updated:
				doc.save(ignore_permissions=True)

		from flow.assistant.assistant import sync_builtin_assistant
		sync_builtin_assistant(model=title)

		if not getattr(frappe.flags, "in_test", False):
			frappe.db.commit()

		return title
	except Exception as e:
		frappe.log_error(title="Erro auto-provisioning Flow Model do .env", message=frappe.get_traceback())
		return None
