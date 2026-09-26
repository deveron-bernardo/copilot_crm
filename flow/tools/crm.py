# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from __future__ import annotations

import json
from typing import Any, Literal

import frappe
from frappe import _

from flow.knowledge.qdrant_store import search_crm_knowledge
from flow.ledger.credits import consume_ai_credits
from flow.lib.tool import Tool, tool


@tool(
	requires_confirmation=True,
	confirm_prompt=lambda args: (
		_("Converter o Lead '{0}' em uma Oportunidade (Deal)?").format(args.get("lead", "?"))
	),
)
def convert_lead(
	lead: str,
	deal_title: str | None = None,
	status: str | None = None,
	existing_contact: str | None = None,
	existing_organization: str | None = None,
) -> dict[str, Any]:
	"""Converte um CRM Lead qualificado em um CRM Deal (Oportunidade).

	Cria ou vincula automaticamente o Contato e a Organização, preservando o histórico de
	e-mails, notas e chamadas.
	"""
	if not frappe.has_permission("CRM Lead", "write", lead):
		raise PermissionError(f"Sem permissão para editar ou converter o Lead {lead}")

	try:
		from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal as crm_convert

		deal_dict = {}
		if deal_title:
			deal_dict["deal_name"] = deal_title
		if status:
			deal_dict["status"] = status

		deal = crm_convert(
			lead=lead,
			deal=deal_dict if deal_dict else None,
			existing_contact=existing_contact,
			existing_organization=existing_organization,
		)
		deal_name = deal.name if hasattr(deal, "name") else str(deal)
		return {
			"status": "success",
			"lead": lead,
			"deal": deal_name,
			"message": f"Lead '{lead}' convertido com sucesso no Deal '{deal_name}'.",
		}
	except Exception as e:
		frappe.log_error(title=f"Falha ao converter lead {lead}", message=frappe.get_traceback())
		raise RuntimeError(f"Erro ao converter lead: {e}")


@tool(
	requires_confirmation=True,
	confirm_prompt=lambda args: (
		_("Atualizar {0} registro(s) em lote do DocType {1} com os valores: {2}").format(
			args.get("limit", 50),
			args.get("doctype", "?"),
			json.dumps(args.get("update_values", {}), ensure_ascii=False),
		)
	),
)
def bulk_update_records(
	doctype: str,
	filters: dict[str, Any],
	update_values: dict[str, Any],
	limit: int = 50,
) -> dict[str, Any]:
	"""Atualiza registros em lote do CRM (ex: mover múltiplos deals parados para o status 'Esfriou').

	Respeita estritamente o RBAC e a hierarquia de vendas do usuário autenticado.
	"""
	allowed_doctypes = {"CRM Lead", "CRM Deal", "CRM Task", "FCRM Note", "Contact", "CRM Organization"}
	if doctype not in allowed_doctypes:
		raise ValueError(f"Edição em lote permitida apenas para: {', '.join(allowed_doctypes)}")

	from flow.tools.builtins import normalize_record_values

	norm_update_values = normalize_record_values(doctype, update_values, is_create=False)
	norm_filters = normalize_record_values(doctype, filters, is_create=False) if isinstance(filters, dict) else filters

	limit = min(max(int(limit), 1), 100)
	records = frappe.get_list(doctype, filters=norm_filters, pluck="name", limit=limit)

	if not records:
		return {"status": "no_records_found", "updated_count": 0, "records": []}

	updated = []
	failures = []

	for name in records:
		if not frappe.has_permission(doctype, "write", name):
			failures.append({"name": name, "error": "Sem permissão de escrita"})
			continue

		try:
			doc = frappe.get_doc(doctype, name)
			for field, val in norm_update_values.items():
				doc.set(field, val)
			doc.save()
			updated.append(name)
		except Exception as err:
			failures.append({"name": name, "error": str(err)[:200]})

	return {
		"status": "completed",
		"total_found": len(records),
		"updated_count": len(updated),
		"updated_records": updated,
		"failures": failures,
	}


@tool
def add_crm_comment(
	content: str,
	reference_doctype: str,
	reference_docname: str,
) -> dict[str, Any]:
	"""Adiciona um comentário diretamente na linha do tempo / histórico (Atividade e Comentários) de um Lead, Deal ou outro registro do CRM.

	Use esta ferramenta SEMPRE que o usuário pedir para comentar, adicionar observação ou registrar uma mensagem no histórico do lead ou deal:
	- 'adicione um comentário...'
	- 'crie um comentário: ...'
	- 'comente no lead...'
	- 'registre esse recado no documento...'
	NÃO use manage_crm_task para comentários! Tarefas criam pendências com prazos (due_date) e responsáveis, enquanto comentários registram anotações no histórico do documento.
	"""
	if not reference_doctype or not reference_docname:
		raise ValueError("reference_doctype e reference_docname são obrigatórios para adicionar comentário.")
	if not content:
		raise ValueError("Conteúdo do comentário não pode ser vazio.")

	if not frappe.has_permission(reference_doctype, "read", reference_docname):
		raise PermissionError(f"Sem permissão para acessar o {reference_doctype} {reference_docname}")

	try:
		from crm.api.comment import add_comment

		comment = add_comment(
			reference_doctype=reference_doctype,
			reference_name=reference_docname,
			content=content,
		)
		comment_name = getattr(comment, "name", str(comment))
	except Exception:
		from frappe.desk.form.utils import add_comment as frappe_add_comment
		from frappe.utils import get_fullname

		comment = frappe_add_comment(
			reference_doctype,
			reference_docname,
			content,
			comment_email=frappe.session.user,
			comment_by=get_fullname(frappe.session.user),
		)
		comment_name = getattr(comment, "name", str(comment))

	return {
		"status": "created",
		"comment_id": comment_name,
		"reference_doctype": reference_doctype,
		"reference_docname": reference_docname,
		"content": content,
		"message": f"Comentário registrado com sucesso no {reference_doctype} '{reference_docname}'.",
	}


@tool
def add_crm_note(
	title: str,
	content: str | None = None,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
) -> dict[str, Any]:
	"""Cria uma anotação estruturada na aba 'Anotações' (FCRM Note) vinculada a um Lead, Deal ou Organização."""
	if not title:
		raise ValueError("Título da anotação é obrigatório.")

	doc = frappe.new_doc("FCRM Note")
	doc.title = title
	doc.content = content or ""
	doc.reference_doctype = reference_doctype
	doc.reference_docname = reference_docname
	doc.insert()

	return {
		"status": "created",
		"note_id": doc.name,
		"title": doc.title,
		"reference_doctype": reference_doctype,
		"reference_docname": reference_docname,
		"message": f"Anotação '{title}' criada com sucesso.",
	}


@tool
def manage_crm_task(
	action: Literal["create", "update", "list", "complete"],
	title: str | None = None,
	task_id: str | None = None,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
	due_date: str | None = None,
	priority: Literal["Low", "Medium", "High"] = "Medium",
	status: Literal["Backlog", "Todo", "In Progress", "Done", "Cancelled"] = "Todo",
	assigned_to: str | None = None,
	description: str | None = None,
) -> dict[str, Any]:
	"""Gerencia tarefas operacionais (CRM Task) com status (Todo, In Progress, Done) e prazos (due_date).

	ATENÇÃO: NUNCA USE ESTA FERRAMENTA PARA COMENTÁRIOS OU ANOTAÇÕES!
	- Para comentários na linha do tempo / atividade, use `add_crm_comment`.
	- Para anotações na aba Anotações, use `add_crm_note`.
	Use `manage_crm_task` exclusivamente para pendências e compromissos operacionais (ex: 'agendar ligação', 'marcar reunião', 'criar tarefa de follow-up').
	"""
	if action == "create":
		if not title:
			raise ValueError("Título é obrigatório para criar tarefa.")

		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": title,
				"description": description or "",
				"priority": priority,
				"status": status,
				"due_date": due_date or str(frappe.utils.nowdate()),
				"assigned_to": assigned_to or frappe.session.user,
				"reference_doctype": reference_doctype,
				"reference_docname": reference_docname,
			}
		)
		task.insert()
		return {
			"status": "created",
			"task_id": task.name,
			"title": task.title,
			"due_date": str(task.due_date),
			"assigned_to": task.assigned_to,
		}

	if action == "complete":
		if not task_id:
			raise ValueError("task_id é obrigatório para concluir tarefa.")
		doc = frappe.get_doc("CRM Task", task_id)
		doc.status = "Done"
		doc.save()
		return {"status": "completed", "task_id": doc.name, "title": doc.title}

	if action == "update":
		if not task_id:
			raise ValueError("task_id é obrigatório para atualizar.")
		doc = frappe.get_doc("CRM Task", task_id)
		if title:
			doc.title = title
		if description is not None:
			doc.description = description
		if due_date:
			doc.due_date = due_date
		if priority:
			doc.priority = priority
		if status:
			doc.status = status
		if assigned_to:
			doc.assigned_to = assigned_to
		doc.save()
		return {"status": "updated", "task_id": doc.name}

	if action == "list":
		filters = {}
		if reference_doctype and reference_docname:
			filters["reference_doctype"] = reference_doctype
			filters["reference_docname"] = reference_docname
		if status:
			filters["status"] = status
		tasks = frappe.get_list(
			"CRM Task",
			filters=filters,
			fields=["name", "title", "due_date", "priority", "status", "assigned_to"],
			order_by="due_date asc",
			limit=20,
		)
		return {"status": "listed", "tasks": tasks}

	raise ValueError(f"Ação inválida: {action}")


@tool(
	requires_confirmation=True,
	confirm_prompt=lambda args: (
		_("Enviar e-mail para '{0}' com o assunto '{1}'?").format(
			args.get("recipient", "?"),
			args.get("subject", "?"),
		)
	),
)
def send_crm_email(
	recipient: str,
	subject: str,
	content: str,
	reference_doctype: str,
	reference_docname: str,
	cc: str | None = None,
	bcc: str | None = None,
) -> dict[str, Any]:
	"""Envia um e-mail formal diretamente vinculado a um Lead ou Deal no Frappe CRM.

	Registra a troca de mensagens na timeline (Communication) do documento.
	"""
	if not frappe.has_permission(reference_doctype, "write", reference_docname):
		raise PermissionError(f"Sem permissão para enviar comunicação neste {reference_doctype}")

	cc_list = [c.strip() for c in cc.split(",")] if cc else None
	bcc_list = [b.strip() for b in bcc.split(",")] if bcc else None

	frappe.sendmail(
		recipients=[recipient],
		subject=subject,
		message=content,
		reference_doctype=reference_doctype,
		reference_name=reference_docname,
		cc=cc_list,
		bcc=bcc_list,
		now=True,
	)

	return {
		"status": "sent",
		"recipient": recipient,
		"subject": subject,
		"reference_doctype": reference_doctype,
		"reference_docname": reference_docname,
		"message": f"E-mail enviado com sucesso para {recipient}.",
	}


@tool(
	requires_confirmation=True,
	confirm_prompt=lambda args: (
		_("Enviar mensagem de WhatsApp para o número '{0}'?").format(args.get("to_number", "?"))
	),
)
def send_crm_whatsapp(
	to_number: str,
	message: str,
	reference_doctype: str,
	reference_name: str,
	template: str | None = None,
) -> dict[str, Any]:
	"""Dispara uma mensagem ou template oficial de WhatsApp pelo Frappe CRM."""
	try:
		from crm.api.whatsapp import create_whatsapp_message, send_whatsapp_template

		if template:
			doc_name = send_whatsapp_template(
				reference_doctype=reference_doctype,
				reference_name=reference_name,
				template=template,
				to=to_number,
			)
		else:
			doc_name = create_whatsapp_message(
				reference_doctype=reference_doctype,
				reference_name=reference_name,
				message=message,
				to=to_number,
				attach="",
				reply_to="",
			)

		return {
			"status": "dispatched",
			"whatsapp_doc": doc_name,
			"to": to_number,
			"message": f"Mensagem de WhatsApp enviada para {to_number}.",
		}
	except Exception as e:
		frappe.log_error(title="Erro envio WhatsApp Copilot", message=frappe.get_traceback())
		return {
			"status": "error",
			"error": str(e),
			"fallback_tip": "Certifique-se de que a integração WhatsApp está ativada nas configurações do CRM.",
		}


@tool
def generate_deal_proposal(deal_name: str, print_format: str | None = None) -> dict[str, Any]:
	"""Compila uma proposta comercial ou cotação em PDF baseada no Deal e seus produtos.

	Utiliza a renderização de impressão do Frappe / Print Designer, anexa o PDF gerado diretamente
	ao Deal e retorna o link para download ou envio ao cliente.
	"""
	if not frappe.has_permission("CRM Deal", "read", deal_name):
		raise PermissionError(f"Sem permissão para acessar o Deal {deal_name}")

	deal = frappe.get_doc("CRM Deal", deal_name)
	products = getattr(deal, "products", [])
	if not products:
		# Não impede a criação, mas avisa o usuário
		pass

	try:
		pdf_content = frappe.get_print(
			doctype="CRM Deal",
			name=deal_name,
			print_format=print_format,
			as_pdf=True,
		)

		clean_deal = deal_name.replace("/", "_").replace(" ", "_")
		file_name = f"Proposta_{clean_deal}.pdf"

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"attached_to_doctype": "CRM Deal",
				"attached_to_name": deal_name,
				"content": pdf_content,
				"is_private": 0,
			}
		)
		file_doc.insert(ignore_permissions=True)

		return {
			"status": "generated",
			"deal": deal_name,
			"file_name": file_name,
			"file_url": file_doc.file_url,
			"products_count": len(products),
			"deal_value": getattr(deal, "deal_value", getattr(deal, "annual_revenue", 0)),
			"message": f"Proposta comercial em PDF compilada e anexada ao Deal '{deal_name}'.",
		}
	except Exception as e:
		frappe.log_error(title="Erro geração PDF Proposta", message=frappe.get_traceback())
		raise RuntimeError(f"Falha ao compilar PDF da proposta: {e}")


@tool
def search_company_memory(
	query: str,
	doctype: str | None = None,
	docname: str | None = None,
	limit: int = 5,
) -> list[dict[str, Any]]:
	"""Busca semântica no banco vetorial Qdrant (transcrições de reuniões do Meetily/Whisper, e-mails, notas e WhatsApp).

	Use para localizar acordos verbais, objeções recorrentes, histórico de negociações e referências à concorrência.
	"""
	return search_crm_knowledge(query, doctype=doctype, docname=docname, limit=limit)


@tool
def search_customer_history(
	query: str,
	context_deal_id: str | None = None,
	limit: int = 5,
) -> dict[str, Any]:
	"""Busca semântica e híbrida (RAG) no histórico de relacionamentos (E-mails, Notas, Transcrições e WhatsApps) no Qdrant.

	Permite ao Copilot responder dúvidas complexas como 'Qual foi a principal objeção financeira levantada pelo cliente na última reunião?'.
	Se context_deal_id for fornecido, restringe a busca estritamente à negociação indicada.
	"""
	from crm.crm.copilot.tools.rag_tools import search_customer_history as crm_rag_search

	return crm_rag_search(query=query, context_deal_id=context_deal_id, limit=limit)


@tool
def summarize_call_log(call_log_name: str, auto_create_tasks: bool = False) -> dict[str, Any]:
	"""Lê um registro de chamada (CRM Call Log) e sua transcrição/gravação, sintetizando pontos-chave e próximos passos."""
	if not frappe.has_permission("CRM Call Log", "read", call_log_name):
		raise PermissionError(f"Sem permissão para acessar o Call Log {call_log_name}")

	call = frappe.get_doc("CRM Call Log", call_log_name)
	transcript = getattr(call, "summary", None) or getattr(call, "notes", None) or getattr(call, "transcript", "")
	duration = getattr(call, "duration", 0)
	status = getattr(call, "status", "")

	created_tasks = []
	if auto_create_tasks and getattr(call, "reference_doctype", None) and getattr(call, "reference_docname", None):
		task = manage_crm_task(
			action="create",
			title=f"Follow-up de ligação: {call_log_name}",
			reference_doctype=call.reference_doctype,
			reference_docname=call.reference_docname,
			priority="High",
			description=f"Follow-up agendado com base na ligação {call_log_name}.",
		)
		created_tasks.append(task.get("task_id"))

	return {
		"call_log": call_log_name,
		"duration_seconds": duration,
		"call_status": status,
		"transcript_preview": transcript[:500] if transcript else "Sem transcrição de áudio anexada.",
		"tasks_created": created_tasks,
	}


@tool
def enrich_lead_tool(lead_name: str | None = None) -> dict[str, Any]:
	"""Enriquece os dados cadastrais de um CRM Lead via Receita Federal (CNPJ, CNAE, sócios) e Crawl4AI (web).

	Pode ser chamado informando o nome ou ID do Lead (ex: 'Ambario Corp', 'LEAD-2026-00042') ou sem parâmetros
	quando o usuário estiver com a tela do Lead aberta no CRM (resolução contextual automática).
	"""
	from crm.crm.copilot.tools.lead_tools import enrich_lead_from_copilot

	return enrich_lead_from_copilot(lead_name=lead_name)


def build_crm_tools() -> list[Tool]:
	"""Return the suite of specialized Frappe CRM tools."""
	return [
		add_crm_comment,
		add_crm_note,
		convert_lead,
		bulk_update_records,
		manage_crm_task,
		send_crm_email,
		send_crm_whatsapp,
		generate_deal_proposal,
		search_company_memory,
		search_customer_history,
		summarize_call_log,
		enrich_lead_tool,
	]
