# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import functools
from typing import Any, Callable

import frappe
from frappe import _


def get_ai_settings() -> dict[str, Any]:
	"""Retrieve or default Copilot / Deveron AI Settings."""
	if not frappe.db.exists("DocType", "Copilot AI Settings"):
		return {
			"enabled": 1,
			"block_on_zero_credits": 1,
			"default_user_credits": 100.0,
			"default_workspace_credits": 1000.0,
			"workspace_credit_balance": 1000.0,
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
		"default_workspace_credits": getattr(doc, "default_workspace_credits", 1000.0) or 1000.0,
		"workspace_credit_balance": getattr(doc, "workspace_credit_balance", 1000.0) or 1000.0,
		"cost_per_chat": getattr(doc, "cost_per_chat", 1.0) or 1.0,
		"cost_per_tool": getattr(doc, "cost_per_tool", 0.5) or 0.5,
		"cost_per_rag": getattr(doc, "cost_per_rag", 1.5) or 1.5,
		"cost_per_proposal": getattr(doc, "cost_per_proposal", 2.0) or 2.0,
		"qdrant_url": getattr(doc, "qdrant_url", "http://localhost:6333") or "http://localhost:6333",
		"qdrant_collection": getattr(doc, "qdrant_collection", "crm_knowledge") or "crm_knowledge",
	}


def get_feature_cost(feature: str) -> float:
	"""Return the configured cost for a given feature."""
	settings = get_ai_settings()
	key = f"cost_per_{feature.lower()}"
	return float(settings.get(key, 1.0))


def _create_ledger_entry(
	user: str,
	feature: str,
	credits_delta: float,
	balance_after: float,
	workspace: str = "default",
	workspace_balance_after: float | None = None,
	tokens_prompt: int = 0,
	tokens_completion: int = 0,
	session: str | None = None,
	run: str | None = None,
	details: str | None = None,
	operation_type: str | None = None,
) -> None:
	"""Insert an audit record into Deveron AI Credit Ledger and legacy Copilot Credit Ledger."""
	now_dt = frappe.utils.now_datetime()

	# 1. Primary: Deveron AI Credit Ledger
	if frappe.db.exists("DocType", "Deveron AI Credit Ledger"):
		try:
			ledger_dict = {
				"doctype": "Deveron AI Credit Ledger",
				"user": user,
				"workspace": workspace or "default",
				"posting_datetime": now_dt,
				"feature": feature,
				"operation_type": operation_type or feature,
				"credits": credits_delta,
				"balance_after": balance_after,
				"workspace_balance_after": workspace_balance_after if workspace_balance_after is not None else balance_after,
				"tokens_prompt": tokens_prompt,
				"tokens_completion": tokens_completion,
				"reference_session": session,
				"reference_run": run,
				"details": details,
			}
			doc = frappe.get_doc(ledger_dict)
			doc.insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(title="Erro inserção Deveron AI Credit Ledger", message=str(e))

	# 2. Legacy fallback / compatibility: Copilot Credit Ledger
	if frappe.db.exists("DocType", "Copilot Credit Ledger"):
		try:
			legacy_doc = frappe.get_doc(
				{
					"doctype": "Copilot Credit Ledger",
					"user": user,
					"posting_datetime": now_dt,
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
			legacy_doc.insert(ignore_permissions=True)
		except Exception:
			pass


def ensure_workspace_balance_record(workspace: str = "default") -> float:
	"""Ensure a workspace balance record exists and return its current balance."""
	workspace = workspace or "default"
	settings = get_ai_settings()
	default_initial = float(settings.get("default_workspace_credits", 1000.0))

	if frappe.db.exists("DocType", "Deveron AI Workspace Balance"):
		if not frappe.db.exists("Deveron AI Workspace Balance", workspace):
			doc = frappe.get_doc(
				{
					"doctype": "Deveron AI Workspace Balance",
					"workspace": workspace,
					"credit_balance": default_initial,
					"total_consumed": 0.0,
					"status": "Active",
					"last_recharge": frappe.utils.now_datetime(),
				}
			)
			doc.insert(ignore_permissions=True)
			# Audit initial balance in ledger
			_create_ledger_entry(
				user="Administrator",
				feature="Credit Recharge",
				credits_delta=default_initial,
				balance_after=default_initial,
				workspace=workspace,
				workspace_balance_after=default_initial,
				details=_("Saldo inicial compartilhado do workspace"),
			)
			return default_initial
		current = frappe.db.get_value("Deveron AI Workspace Balance", workspace, "credit_balance")
		return float(current) if current is not None else 0.0

	return default_initial


def get_workspace_credit_balance(workspace: str = "default", initialize: bool = True) -> float:
	"""Return the current shared credit balance for the given workspace."""
	workspace = workspace or "default"

	if frappe.db.exists("DocType", "Deveron AI Workspace Balance"):
		if frappe.db.exists("Deveron AI Workspace Balance", workspace):
			val = frappe.db.get_value("Deveron AI Workspace Balance", workspace, "credit_balance")
			if val is not None:
				return float(val)
		if initialize:
			return ensure_workspace_balance_record(workspace)
		return 0.0

	# Fallback: check latest ledger entry for this workspace
	if frappe.db.exists("DocType", "Deveron AI Credit Ledger"):
		latest = frappe.db.get_value(
			"Deveron AI Credit Ledger",
			filters={"workspace": workspace},
			fieldname=["workspace_balance_after"],
			order_by="creation desc",
			as_dict=True,
		)
		if latest and latest.workspace_balance_after is not None:
			return float(latest.workspace_balance_after)

	settings = get_ai_settings()
	return float(settings.get("default_workspace_credits", 1000.0))


def get_user_credit_balance(user: str | None = None, initialize: bool = True) -> float:
	"""Return the credit balance for an individual seat/user."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return 0.0

	# Check Deveron AI Credit Ledger first
	if frappe.db.exists("DocType", "Deveron AI Credit Ledger"):
		latest = frappe.db.get_value(
			"Deveron AI Credit Ledger",
			filters={"user": user},
			fieldname=["balance_after"],
			order_by="creation desc",
			as_dict=True,
		)
		if latest and latest.balance_after is not None:
			return float(latest.balance_after)

	# Fallback to Copilot Credit Ledger
	if frappe.db.exists("DocType", "Copilot Credit Ledger"):
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

	# Initialize new user seat with default credits
	settings = get_ai_settings()
	initial = float(settings.get("default_user_credits", 100.0))
	if initial > 0:
		_create_ledger_entry(
			user=user,
			feature="Credit Recharge",
			credits_delta=initial,
			balance_after=initial,
			workspace="default",
			workspace_balance_after=get_workspace_credit_balance("default", initialize=True),
			details=_("Initial credit balance (seat)"),
		)
		return initial

	return 0.0


def check_user_has_credits(user: str | None, feature: str = "chat", cost: float | None = None, workspace: str = "default") -> tuple[bool, float, float]:
	"""Check if both the workspace shared pool and user seat have enough credits."""
	user = user or frappe.session.user
	settings = get_ai_settings()

	if not settings.get("enabled", 1):
		frappe.throw(_("Copilot CRM AI está desativado pelo administrador."), frappe.PermissionError)

	call_cost = float(cost) if cost is not None else get_feature_cost(feature)
	workspace_balance = get_workspace_credit_balance(workspace)

	# Block if workspace balance has reached zero or is less than the required cost
	if settings.get("block_on_zero_credits", 1):
		if workspace_balance <= 0 or workspace_balance < call_cost:
			return False, workspace_balance, call_cost

	user_balance = get_user_credit_balance(user)
	return True, user_balance, call_cost


def deduct_credits_atomically(
	user: str,
	cost: float,
	feature: str = "Chat",
	workspace: str = "default",
	session: str | None = None,
	run: str | None = None,
	details: str | None = None,
	tokens_prompt: int = 0,
	tokens_completion: int = 0,
	operation_type: str | None = None,
) -> tuple[float, float]:
	"""Atomically check and deduct credits from the workspace pool and user balance in the DB.

	Uses row-level database locking (SELECT ... FOR UPDATE) to prevent race conditions and overdrafts.
	Immediately commits after deduction to avoid holding locks during long external LLM operations.
	"""
	workspace = workspace or "default"
	user = user or frappe.session.user
	cost = float(cost)

	settings = get_ai_settings()
	if not settings.get("enabled", 1):
		frappe.throw(_("Copilot CRM AI está desativado pelo administrador."), frappe.PermissionError)

	block_on_zero = bool(settings.get("block_on_zero_credits", 1))

	# Ensure workspace balance record exists
	ensure_workspace_balance_record(workspace)

	# Execute atomic deduction under row lock
	if frappe.db.exists("DocType", "Deveron AI Workspace Balance"):
		# Lock workspace row
		ws_row = frappe.db.sql(
			"""
			SELECT credit_balance, total_consumed
			FROM `tabDeveron AI Workspace Balance`
			WHERE workspace = %s
			FOR UPDATE
			""",
			(workspace,),
			as_dict=True,
		)

		if not ws_row:
			ensure_workspace_balance_record(workspace)
			ws_row = frappe.db.sql(
				"""
				SELECT credit_balance, total_consumed
				FROM `tabDeveron AI Workspace Balance`
				WHERE workspace = %s
				FOR UPDATE
				""",
				(workspace,),
				as_dict=True,
			)

		current_ws_balance = float(ws_row[0].credit_balance) if ws_row else 0.0

		if block_on_zero and (current_ws_balance <= 0 or current_ws_balance < cost):
			frappe.throw(
				_(
					"Saldo de créditos de IA do workspace esgotado ({0:.2f} disponíveis, {1:.2f} necessários). "
					"Contate o administrador para recarregar."
				).format(current_ws_balance, cost),
				frappe.PermissionError,
			)

		new_ws_balance = max(0.0, current_ws_balance - cost)
		current_consumed = float(ws_row[0].total_consumed or 0.0) if ws_row else 0.0
		new_status = "Exhausted" if new_ws_balance <= 0 else "Active"
		now_dt = frappe.utils.now_datetime()

		frappe.db.sql(
			"""
			UPDATE `tabDeveron AI Workspace Balance`
			SET credit_balance = %s,
				total_consumed = %s,
				last_deduction = %s,
				status = %s
			WHERE workspace = %s
			""",
			(new_ws_balance, current_consumed + cost, now_dt, new_status, workspace),
		)
	else:
		# Fallback if table doesn't exist yet
		current_ws_balance = get_workspace_credit_balance(workspace)
		if block_on_zero and (current_ws_balance <= 0 or current_ws_balance < cost):
			frappe.throw(
				_(
					"Saldo de créditos de IA do workspace esgotado ({0:.2f} disponíveis, {1:.2f} necessários). "
					"Contate o administrador para recarregar."
				).format(current_ws_balance, cost),
				frappe.PermissionError,
			)
		new_ws_balance = max(0.0, current_ws_balance - cost)

	# Calculate user balance
	user_bal = get_user_credit_balance(user, initialize=True)
	new_user_bal = max(0.0, user_bal - cost)

	# Insert audit entry into Deveron AI Credit Ledger
	_create_ledger_entry(
		user=user,
		feature=feature,
		credits_delta=-cost,
		balance_after=new_user_bal,
		workspace=workspace,
		workspace_balance_after=new_ws_balance,
		tokens_prompt=tokens_prompt,
		tokens_completion=tokens_completion,
		session=session,
		run=run,
		details=details or f"Dedução de serviço {feature}",
		operation_type=operation_type,
	)

	# Commit immediately so locks are released before invoking external LLM APIs
	frappe.db.commit()

	return new_user_bal, new_ws_balance


def refund_credits_atomically(
	user: str,
	cost: float,
	feature: str = "Chat",
	workspace: str = "default",
	session: str | None = None,
	run: str | None = None,
	reason: str = "Falha no serviço de IA",
	operation_type: str | None = None,
) -> tuple[float, float]:
	"""Atomically refund deducted credits back to workspace and user balances upon service failure."""
	workspace = workspace or "default"
	user = user or frappe.session.user
	cost = float(cost)

	if frappe.db.exists("DocType", "Deveron AI Workspace Balance"):
		ws_row = frappe.db.sql(
			"""
			SELECT credit_balance, total_consumed
			FROM `tabDeveron AI Workspace Balance`
			WHERE workspace = %s
			FOR UPDATE
			""",
			(workspace,),
			as_dict=True,
		)
		current_ws_balance = float(ws_row[0].credit_balance) if ws_row else 0.0
		new_ws_balance = current_ws_balance + cost
		current_consumed = max(0.0, float(ws_row[0].total_consumed or 0.0) - cost) if ws_row else 0.0
		new_status = "Active"

		frappe.db.sql(
			"""
			UPDATE `tabDeveron AI Workspace Balance`
			SET credit_balance = %s,
				total_consumed = %s,
				status = %s
			WHERE workspace = %s
			""",
			(new_ws_balance, current_consumed, new_status, workspace),
		)
	else:
		new_ws_balance = get_workspace_credit_balance(workspace) + cost

	user_bal = get_user_credit_balance(user, initialize=False)
	new_user_bal = user_bal + cost

	_create_ledger_entry(
		user=user,
		feature=feature if feature in ("Chat", "Tool Execution", "Semantic Search (RAG)", "Proposal Generation", "Lead Enrichment") else "Custom",
		credits_delta=cost,
		balance_after=new_user_bal,
		workspace=workspace,
		workspace_balance_after=new_ws_balance,
		session=session,
		run=run,
		details=f"Estorno de créditos: {reason}",
		operation_type=operation_type,
	)

	frappe.db.commit()
	return new_user_bal, new_ws_balance


def recharge_workspace_credits(
	workspace: str = "default",
	amount: float = 100.0,
	user: str = "Administrator",
	details: str = "Recarga de créditos do workspace",
) -> float:
	"""Add credits to the shared workspace pool and record in Deveron AI Credit Ledger."""
	workspace = workspace or "default"
	amount = abs(float(amount))
	ensure_workspace_balance_record(workspace)

	if frappe.db.exists("DocType", "Deveron AI Workspace Balance"):
		ws_row = frappe.db.sql(
			"""
			SELECT credit_balance
			FROM `tabDeveron AI Workspace Balance`
			WHERE workspace = %s
			FOR UPDATE
			""",
			(workspace,),
			as_dict=True,
		)
		current_ws = float(ws_row[0].credit_balance) if ws_row else 0.0
		new_ws = current_ws + amount
		now_dt = frappe.utils.now_datetime()

		frappe.db.sql(
			"""
			UPDATE `tabDeveron AI Workspace Balance`
			SET credit_balance = %s,
				last_recharge = %s,
				status = 'Active'
			WHERE workspace = %s
			""",
			(new_ws, now_dt, workspace),
		)
	else:
		new_ws = get_workspace_credit_balance(workspace) + amount

	user_bal = get_user_credit_balance(user, initialize=False) + amount

	_create_ledger_entry(
		user=user,
		feature="Credit Recharge",
		credits_delta=amount,
		balance_after=user_bal,
		workspace=workspace,
		workspace_balance_after=new_ws,
		details=details,
	)

	frappe.db.commit()
	return new_ws


def recharge_user_credits(user: str, amount: float, details: str = "Recarga de créditos") -> float:
	"""Add credits to an individual user seat."""
	amount = abs(float(amount))
	current = get_user_credit_balance(user, initialize=True)
	new_balance = current + amount
	ws_balance = get_workspace_credit_balance("default")

	_create_ledger_entry(
		user=user,
		feature="Credit Recharge",
		credits_delta=amount,
		balance_after=new_balance,
		workspace="default",
		workspace_balance_after=ws_balance,
		details=details,
	)
	frappe.db.commit()
	return new_balance


def consume_ai_credits(
	cost: float | Callable | None = None,
	feature: str = "chat",
	workspace: str | None = None,
	operation_type: str | None = None,
	**kwargs,
):
	"""Decorator to enforce RBAC credit governance with atomic database deduction.

	Usage:
	    @consume_ai_credits(cost=2.0)
	    @consume_ai_credits(cost=1.5, feature="rag")
	    @consume_ai_credits(cost=1, operation_type="Lead Enrichment")
	    @consume_ai_credits(feature="chat")
	    @consume_ai_credits
	"""
	# Handle bare decorator: @consume_ai_credits
	if callable(cost) and feature == "chat" and workspace is None and operation_type is None and not isinstance(cost, (int, float)):
		target_func = cost
		return _build_consume_wrapper(target_func, cost=None, feature="chat", workspace=None, operation_type=None)

	def decorator(func: Callable):
		return _build_consume_wrapper(func, cost=cost, feature=feature, workspace=workspace, operation_type=operation_type)

	return decorator


def _build_consume_wrapper(
	func: Callable,
	cost: float | Callable | None = None,
	feature: str = "chat",
	workspace: str | None = None,
	operation_type: str | None = None,
) -> Callable:
	"""Construct wrapper with atomic DB deduction and blocking on zero workspace balance."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		# Resolve workspace
		actual_workspace = (
			workspace
			or kwargs.get("workspace")
			or getattr(frappe.local, "workspace", None)
			or "default"
		)
		user = getattr(frappe.session, "user", "Administrator")

		# If operation_type is provided and feature is default, align feature
		effective_feature = feature
		if operation_type and (feature == "chat" or not feature):
			effective_feature = operation_type

		# Resolve cost
		if callable(cost):
			call_cost = float(cost(*args, **kwargs))
		elif cost is not None:
			call_cost = float(cost)
		else:
			call_cost = get_feature_cost(effective_feature)

		session_id = kwargs.get("session") or kwargs.get("session_name")
		run_id = kwargs.get("run") or kwargs.get("run_name")

		# Format feature label
		if effective_feature in ("Lead Enrichment", "Lead enrichment", "lead_enrichment"):
			feature_label = "Lead Enrichment"
		elif effective_feature == "rag":
			feature_label = "Semantic Search (RAG)"
		else:
			feature_label = effective_feature.capitalize()

		if feature_label not in ("Chat", "Tool Execution", "Semantic Search (RAG)", "Proposal Generation", "Lead Enrichment", "Credit Recharge"):
			feature_label = "Custom"

		# Atomic check & deduction in database (throws PermissionError if workspace balance is zero)
		deduct_credits_atomically(
			user=user,
			cost=call_cost,
			feature=feature_label,
			workspace=actual_workspace,
			session=session_id,
			run=run_id,
			details=f"Execução de {effective_feature} ({call_cost:.2f} créditos)",
			operation_type=operation_type or feature_label,
		)

		try:
			result = func(*args, **kwargs)
			return result
		except Exception as exc:
			# If the AI execution fails, refund the atomically deducted credits
			try:
				refund_credits_atomically(
					user=user,
					cost=call_cost,
					feature=feature_label,
					workspace=actual_workspace,
					session=session_id,
					run=run_id,
					reason=f"Erro durante execução: {exc}",
					operation_type=operation_type or feature_label,
				)
			except Exception:
				pass
			raise

	return wrapper
