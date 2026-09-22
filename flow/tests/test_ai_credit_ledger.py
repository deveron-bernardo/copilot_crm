# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from flow.ledger import (
	check_user_has_credits,
	consume_ai_credits,
	deduct_credits_atomically,
	get_user_credit_balance,
	get_workspace_credit_balance,
	recharge_user_credits,
	recharge_workspace_credits,
	refund_credits_atomically,
)


class TestDeveronAICreditLedger(IntegrationTestCase):
	"""Test suite for Deveron AI Credit Ledger, shared workspace balances, and atomic deduction."""

	def setUp(self):
		super().setUp()
		self.test_workspace = f"test_ws_{frappe.generate_hash(length=8)}"
		self.test_user = "test_seat_user@example.com"

	def tearDown(self):
		frappe.db.rollback()

	def test_workspace_credit_initialization(self):
		"""Workspace balance should be auto-initialized with default credits."""
		initial_bal = get_workspace_credit_balance(self.test_workspace, initialize=True)
		self.assertGreaterEqual(initial_bal, 0.0)

	def test_deduct_credits_atomically_success(self):
		"""Atomic deduction should decrease workspace balance and record audit ledger entry."""
		# Ensure workspace starts with known balance
		recharge_workspace_credits(self.test_workspace, amount=50.0)
		start_ws_bal = get_workspace_credit_balance(self.test_workspace)

		user_bal, ws_bal = deduct_credits_atomically(
			user=self.test_user,
			cost=5.0,
			feature="Chat",
			workspace=self.test_workspace,
			details="Test atomic deduction",
		)

		self.assertEqual(ws_bal, start_ws_bal - 5.0)

	def test_block_when_workspace_balance_zero(self):
		"""AI calls should be blocked when workspace credit balance is zero or insufficient."""
		# Set workspace balance to zero
		if frappe.db.exists("DocType", "Deveron AI Workspace Balance"):
			if frappe.db.exists("Deveron AI Workspace Balance", self.test_workspace):
				frappe.db.set_value("Deveron AI Workspace Balance", self.test_workspace, "credit_balance", 0.0)
			else:
				frappe.get_doc({
					"doctype": "Deveron AI Workspace Balance",
					"workspace": self.test_workspace,
					"credit_balance": 0.0,
					"status": "Exhausted",
				}).insert(ignore_permissions=True)

		@consume_ai_credits(cost=5.0, workspace=self.test_workspace)
		def dummy_ai_call():
			return "success"

		with self.assertRaises(frappe.PermissionError):
			dummy_ai_call()

	def test_decorator_with_cost_and_feature(self):
		"""@consume_ai_credits(cost=X) should deduct cost and execute target function."""
		recharge_workspace_credits(self.test_workspace, amount=100.0)
		initial_bal = get_workspace_credit_balance(self.test_workspace)

		@consume_ai_credits(cost=12.5, feature="rag", workspace=self.test_workspace)
		def rag_search_call(query: str):
			return f"Results for {query}"

		output = rag_search_call("Frappe CRM")
		self.assertEqual(output, "Results for Frappe CRM")

		new_bal = get_workspace_credit_balance(self.test_workspace)
		self.assertEqual(new_bal, initial_bal - 12.5)

	def test_refund_on_failure(self):
		"""If AI service execution raises an unhandled error, credits should be refunded."""
		recharge_workspace_credits(self.test_workspace, amount=100.0)
		bal_before = get_workspace_credit_balance(self.test_workspace)

		@consume_ai_credits(cost=10.0, workspace=self.test_workspace)
		def failing_ai_service():
			raise RuntimeError("External LLM Provider 503 Service Unavailable")

		with self.assertRaises(RuntimeError):
			failing_ai_service()

		bal_after = get_workspace_credit_balance(self.test_workspace)
		self.assertEqual(bal_after, bal_before)

	def test_recharge_workspace_credits(self):
		"""Recharge should increment workspace balance and return the new balance."""
		bal_initial = get_workspace_credit_balance(self.test_workspace)
		new_bal = recharge_workspace_credits(self.test_workspace, amount=250.0)
		self.assertEqual(new_bal, bal_initial + 250.0)

	def test_backward_compatibility_decorator(self):
		"""Existing @consume_ai_credits(feature="chat") usage should continue to work."""
		recharge_workspace_credits(self.test_workspace, amount=50.0)

		@consume_ai_credits(feature="chat", workspace=self.test_workspace)
		def standard_chat():
			return "chat ok"

		result = standard_chat()
		self.assertEqual(result, "chat ok")
