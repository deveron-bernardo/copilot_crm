# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

from flow.knowledge.extract import FILE_EXTENSIONS
from flow.lib.env_config import auto_provision_from_env


def boot_session(bootinfo):
	# Single source of truth for file types the ingest pipeline can extract
	bootinfo.flow_supported_file_types = sorted(FILE_EXTENSIONS)

	# Auto-bootstrap AI Model and Copilot CRM Agent from .env if present
	try:
		auto_provision_from_env()
	except Exception:
		pass


def inject_flow_panel_into_crm(request=None, response=None, **kwargs):
	"""Inject Copilot CRM / Flow panel assets into Frappe CRM SPA responses."""
	if not response or not request:
		return
	if getattr(response, "status_code", 0) != 200:
		return
	path = getattr(request, "path", "") or ""
	content_type = response.headers.get("Content-Type", "")
	if (path.startswith("/crm") or path == "/crm") and "text/html" in content_type:
		try:
			data = response.get_data()
			if b"flow_panel.js" not in data and b"</body>" in data:
				from flow.hooks import _flow_panel_asset

				css_url = _flow_panel_asset("flow_panel.css")
				js_url = _flow_panel_asset("flow_panel.js")
				snippet = (
					f'\n\t<!-- Copilot CRM (Flow) AI Panel -->\n'
					f'\t<link rel="stylesheet" href="{css_url}">\n'
					f'\t<script src="{js_url}"></script>\n</body>'
				).encode("utf-8")
				response.set_data(data.replace(b"</body>", snippet, 1))
		except Exception:
			pass

