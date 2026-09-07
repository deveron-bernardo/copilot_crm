# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import functools
from typing import Any, Callable

import frappe
from frappe import _


def get_ai_settings() -> dict[str, Any]:
	"""Retrieve or default Copilot AI Settings."""
	if not frappe.db.exists("DocType", "Copilot AI Settings"):
		return {
			"enabled": 1,
			"block_on_zero_credits": 1,
			"default_user_credits": 100.0,
			"cost_per_chat": 1.0,
			"cost_per_tool": 0.5,
			"cost_per_rag": 1.5,
			"cost_per_proposal": 2.0,
			"qdrant_url": "http://localhost:6333",
			"qdrant_collection": "crm_knowledge",
		}

	doc = frappe.get_cached_doc("Copilot AI Settings")
	return {
		"enabled": getattr(doc, "enabled", 1),
		"block_on_zero_credits": getattr(doc, "block_on_zero_credits", 1),
		"default_user_credits": getattr(doc, "default_user_credits", 100.0) or 100.0,
		"cost_per_chat": getattr(doc, "cost_per_chat", 1.0) or 1.0,
		"cost_per_tool": getattr(doc, "cost_per_tool", 0.5) or 0.5,
		"cost_per_rag": getattr(doc, "cost_per_rag", 1.5) or 1.5,
		"cost_per_proposal": getattr(doc, "cost_per_proposal", 2.0) or 2.0,
		"qdrant_url": getattr(doc, "qdrant_url", "http://localhost:6333") or "http://localhost:6333",
		"qdrant_collection": getattr(doc, "qdrant_collection", "crm_knowledge") or "crm_knowledge",
	}


def get_feature_cost(feature: str) -> float:
	settings = get_ai_settings()
	key = f"cost_per_{feature.lower()}"
	return float(settings.get(key, 1.0))


def _create_ledger_entry(
	user: str,
	feature: str,
	credits_delta: float,
	balance_after: float,
	tokens_prompt: int = 0,
	tokens_completion: int = 0,
	session: str | None = None,
	run: str | None = None,
	details: str | None = None,
) -> None:
	if not frappe.db.exists("DocType", "Copilot Credit Ledger"):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Copilot Credit Ledger",
			"user": user,
			"posting_datetime": frappe.utils.now_datetime(),
			"feature": feature,
			"credits": credits_delta,
			"balance_after": balance_after,
			"tokens_prompt": tokens_prompt,
			"tokens_completion": tokens_completion,
			"reference_session": session,
			"reference_run": run,
			"details": details,
		}
	)
	doc.insert(ignore_permissions=True)


def get_user_credit_balance(user: str | None = None, initialize: bool = True) -> float:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return 0.0

	if not frappe.db.exists("DocType", "Copilot Credit Ledger"):
		return 100.0

	# Calculate current balance from ledger
	latest = frappe.db.get_value(
		"Copilot Credit Ledger",
		filters={"user": user},
		fieldname=["balance_after"],
		order_by="creation desc",
		as_dict=True,
	)

	if latest and latest.balance_after is not None:
		return float(latest.balance_after)

	if not initialize:
		return 0.0

	# Initialize new user with default credits
	settings = get_ai_settings()
	initial = float(settings.get("default_user_credits", 100.0))
	if initial > 0:
		_create_ledger_entry(
			user=user,
			feature="Credit Recharge",
			credits_delta=initial,
			balance_after=initial,
			details=_("Initial credit balance"),
		)
		return initial

	return 0.0


def check_user_has_credits(user: str | None, feature: str) -> tuple[bool, float, float]:
	user = user or frappe.session.user
	settings = get_ai_settings()

	if not settings.get("enabled", 1):
		frappe.throw(_("Copilot CRM AI está desativado pelo administrador."), frappe.PermissionError)

	cost = get_feature_cost(feature)
	if not settings.get("block_on_zero_credits", 1) or user == "Administrator":
		return True, 9999.0, cost

	balance = get_user_credit_balance(user)
	if balance < cost:
		return False, balance, cost

	return True, balance, cost


def record_credit_transaction(
	user: str,
	feature: str,
	credits_delta: float,
	tokens_prompt: int = 0,
	tokens_completion: int = 0,
	session: str | None = None,
	run: str | None = None,
	details: str | None = None,
) -> float:
	"""Record a transaction in the Copilot Credit Ledger."""
	if not frappe.db.exists("DocType", "Copilot Credit Ledger"):
		return 0.0

	current_balance = get_user_credit_balance(user, initialize=True)
	new_balance = current_balance + credits_delta

	_create_ledger_entry(
		user=user,
		feature=feature,
		credits_delta=credits_delta,
		balance_after=new_balance,
		tokens_prompt=tokens_prompt,
		tokens_completion=tokens_completion,
		session=session,
		run=run,
		details=details,
	)
	return new_balance


def recharge_user_credits(user: str, amount: float, details: str = "Recarga de créditos") -> float:
	return record_credit_transaction(
		user=user,
		feature="Credit Recharge",
		credits_delta=abs(amount),
		details=details,
	)


def consume_ai_credits(feature: str = "chat"):
	"""Decorator to enforce RBAC credit governance before and after execution."""

	def decorator(func: Callable):
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			user = frappe.session.user
			has_credit, balance, cost = check_user_has_credits(user, feature)

			if not has_credit:
				frappe.throw(
					_(
						"Seus créditos de IA do Deveron CRM acabaram ({0:.2f} disponíveis, {1:.2f} necessários). "
						"Contate o administrador para recarregar sua franquia."
					).format(balance, cost),
					frappe.PermissionError,
				)

			result = func(*args, **kwargs)

			# Deduct after successful invocation
			session_id = kwargs.get("session") or kwargs.get("session_name")
			run_id = kwargs.get("run") or kwargs.get("run_name")
			record_credit_transaction(
				user=user,
				feature=feature.capitalize() if feature != "rag" else "Semantic Search (RAG)",
				credits_delta=-cost,
				session=session_id,
				run=run_id,
				details=f"Execução de {feature}",
			)

			return result

		return wrapper

	return decorator
