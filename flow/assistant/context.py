# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import frappe
from frappe import _


def build_active_record_summary(doctype: str | None, docname: str | None) -> str:
	"""Generate a rich, high-signal summary of the record currently open on the user's screen."""
	if not doctype or not docname:
		return ""

	if not frappe.db.exists(doctype, docname):
		return ""

	if not frappe.has_permission(doctype, "read", docname):
		return f"[ACTIVE RECORD: {doctype} {docname} - Permissão de leitura negada para o usuário]"

	try:
		doc = frappe.get_doc(doctype, docname)
	except Exception:
		return ""

	lines = [
		"=== CONTEXTO DA TELA ATIVA (ACTIVE RECORD CONTEXT) ===",
		f"Documento Ativo: {doctype} {docname}",
	]

	if doctype == "CRM Deal":
		lines.append(f"Título da Oportunidade: {getattr(doc, 'deal_name', docname)}")
		lines.append(f"Status no Funil: {getattr(doc, 'status', 'N/A')}")
		lines.append(f"Responsável (Deal Owner): {getattr(doc, 'deal_owner', 'Não atribuído')}")
		val = getattr(doc, 'deal_value', None) or getattr(doc, 'annual_revenue', 0)
		lines.append(f"Valor Estimado: R$ {val:,.2f}" if isinstance(val, (int, float)) else f"Valor: {val}")
		if getattr(doc, 'expected_closure_date', None):
			lines.append(f"Data Prevista de Fechamento: {doc.expected_closure_date}")
		if getattr(doc, 'probability', None):
			lines.append(f"Probabilidade: {doc.probability}%")

		# Organização
		if getattr(doc, 'organization', None):
			lines.append(f"Organização / Conta: {doc.organization}")

		# Contatos vinculados
		contacts = frappe.get_list(
			"Contact",
			filters={"crm_deal": docname} if frappe.db.has_column("Contact", "crm_deal") else {},
			fields=["name", "first_name", "last_name", "email_id", "mobile_no"],
			limit=3,
		)
		if contacts:
			c_strs = [f"{c.get('first_name', '')} {c.get('last_name', '')} ({c.get('email_id') or c.get('mobile_no') or c.name})".strip() for c in contacts]
			lines.append(f"Contatos Vinculados: {'; '.join(c_strs)}")

		# Tabela de Produtos
		products = getattr(doc, "products", [])
		if products:
			lines.append("Produtos / Itens Negociados:")
			for p in products[:10]:
				item = getattr(p, "product", getattr(p, "product_name", "Item"))
				qty = getattr(p, "qty", 1)
				rate = getattr(p, "rate", 0)
				amount = getattr(p, "amount", qty * rate)
				lines.append(f"  - {qty}x {item} @ R$ {rate:,.2f} = R$ {amount:,.2f}")

	elif doctype == "CRM Lead":
		lines.append(f"Nome do Prospect: {getattr(doc, 'lead_name', getattr(doc, 'first_name', docname))}")
		lines.append(f"Status do Lead: {getattr(doc, 'status', 'N/A')}")
		lines.append(f"Responsável: {getattr(doc, 'lead_owner', 'Não atribuído')}")
		lines.append(f"E-mail: {getattr(doc, 'email', 'N/A')} | Telefone/WhatsApp: {getattr(doc, 'mobile_no', getattr(doc, 'phone', 'N/A'))}")
		lines.append(f"Empresa / Organização: {getattr(doc, 'organization', 'N/A')}")
		lines.append(f"Origem (Source): {getattr(doc, 'source', 'N/A')}")

	elif doctype == "Contact":
		full_name = f"{getattr(doc, 'first_name', '')} {getattr(doc, 'last_name', '')}".strip() or docname
		lines.append(f"Contato: {full_name}")
		lines.append(f"E-mail: {getattr(doc, 'email_id', 'N/A')} | Celular: {getattr(doc, 'mobile_no', getattr(doc, 'phone', 'N/A'))}")
		lines.append(f"Organização: {getattr(doc, 'company_name', 'N/A')}")
		lines.append(f"Cargo: {getattr(doc, 'designation', 'N/A')}")

	elif doctype == "CRM Organization":
		lines.append(f"Organização: {getattr(doc, 'organization_name', docname)}")
		lines.append(f"Website: {getattr(doc, 'website', 'N/A')} | Setor: {getattr(doc, 'industry', 'N/A')}")
		lines.append(f"Território: {getattr(doc, 'territory', 'N/A')}")

	elif doctype == "CRM Task":
		lines.append(f"Tarefa: {getattr(doc, 'title', docname)}")
		lines.append(f"Status: {getattr(doc, 'status', 'N/A')} | Prioridade: {getattr(doc, 'priority', 'Medium')}")
		lines.append(f"Prazo (Due Date): {getattr(doc, 'due_date', 'N/A')}")
		lines.append(f"Atribuído a: {getattr(doc, 'assigned_to', 'N/A')}")
		if getattr(doc, 'reference_doctype', None) and getattr(doc, 'reference_docname', None):
			lines.append(f"Vinculado a: {doc.reference_doctype} {doc.reference_docname}")

	elif doctype == "CRM Call Log":
		lines.append(f"Registro de Chamada: {docname}")
		lines.append(f"Telefone: {getattr(doc, 'from', '')} -> {getattr(doc, 'to', '')}")
		lines.append(f"Status da Chamada: {getattr(doc, 'status', 'N/A')} | Duração: {getattr(doc, 'duration', 0)}s")
		summary = getattr(doc, 'summary', None) or getattr(doc, 'notes', '')
		if summary:
			lines.append(f"Anotação/Resumo da Chamada: {summary[:300]}")

	# Anexar pendências / tarefas abertas vinculadas
	open_tasks = frappe.get_list(
		"CRM Task",
		filters={"reference_doctype": doctype, "reference_docname": docname, "status": ["in", ["Todo", "In Progress", "Backlog"]]},
		fields=["name", "title", "due_date", "priority"],
		limit=3,
	)
	if open_tasks:
		lines.append("Tarefas Pendentes:")
		for t in open_tasks:
			lines.append(f"  - [{t.priority}] {t.title} (Prazo: {t.due_date or 'Sem prazo'})")

	# Anexar últimas anotações (FCRM Note)
	notes = frappe.get_list(
		"FCRM Note",
		filters={"reference_doctype": doctype, "reference_docname": docname},
		fields=["title", "content", "creation"],
		order_by="creation desc",
		limit=2,
	)
	if notes:
		lines.append("Notas Recentes:")
		for n in notes:
			lines.append(f"  - ({n.creation.strftime('%d/%m')}) {n.title or 'Nota'}: {n.content[:200]}")

	lines.append("======================================================")
	lines.append(
		"INSTRUÇÃO DE CONTEXTO: O vendedor está visualizando este documento na tela agora. "
		"Interprete referências relativas ('este deal', 'esse lead', 'esta oportunidade', 'ele', 'ela', 'resuma') "
		"como se referindo diretamente a este registro."
	)
	return "\n".join(lines)
