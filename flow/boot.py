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
