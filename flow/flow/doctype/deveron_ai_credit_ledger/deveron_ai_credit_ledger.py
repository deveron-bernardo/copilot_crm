# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class DeveronAICreditLedger(Document):
	def validate(self):
		# 1. Fallback for user if empty
		if not self.user:
			session_user = getattr(frappe.session, "user", None)
			if session_user and session_user != "Guest":
				self.user = session_user
			else:
				self.user = "Administrator"

		# 2. Default workspace
		if not self.workspace:
			self.workspace = "default"

		# 3. Default feature and operation_type
		if self.operation_type == "Voice SDR Minute" and (not self.feature or self.feature in ("Chat", "Custom")):
			self.feature = "Voice SDR"
		elif not self.feature:
			self.feature = "Custom"

		if not self.operation_type:
			self.operation_type = self.feature

		# 4. Synchronize credits, credits_debited, credits_credited
		debited = float(getattr(self, "credits_debited", 0.0) or 0.0)
		credited = float(getattr(self, "credits_credited", 0.0) or 0.0)

		if debited > 0 and not getattr(self, "credits", None):
			self.credits = -abs(debited)
		elif credited > 0 and not getattr(self, "credits", None):
			self.credits = abs(credited)
		elif getattr(self, "credits", None) is not None:
			c = float(self.credits)
			if c < 0 and debited == 0:
				self.credits_debited = abs(c)
			elif c > 0 and credited == 0:
				self.credits_credited = abs(c)
		else:
			self.credits = 0.0

		# 5. Calculate and persist workspace balances if not supplied
		if self.workspace_balance_after is None or self.balance_after is None:
			if frappe.db.exists("DocType", "Deveron AI Workspace Balance"):
				from flow.ledger.credits import ensure_workspace_balance_record

				ensure_workspace_balance_record(self.workspace)
				current_balance = (
					frappe.db.get_value("Deveron AI Workspace Balance", self.workspace, "credit_balance") or 0.0
				)
				new_bal = float(current_balance) + float(self.credits)

				if self.workspace_balance_after is None:
					self.workspace_balance_after = new_bal
				if self.balance_after is None:
					self.balance_after = new_bal

				# Update workspace balance
				update_values = {
					"credit_balance": new_bal,
					"last_recharge" if self.credits > 0 else "last_deduction": frappe.utils.now_datetime(),
				}
				if self.credits < 0:
					total_consumed = (
						frappe.db.get_value("Deveron AI Workspace Balance", self.workspace, "total_consumed") or 0.0
					)
					update_values["total_consumed"] = float(total_consumed) + abs(float(self.credits))

				frappe.db.set_value("Deveron AI Workspace Balance", self.workspace, update_values)

