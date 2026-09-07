function getTitleFromDOM() {
	if (typeof document === "undefined") return null;
	try {
		// Look for CRM breadcrumbs or page headers
		const breadcrumbs = document.querySelectorAll("nav ol li, .breadcrumbs li, [class*='breadcrumb'] li");
		if (breadcrumbs.length > 0) {
			const last = breadcrumbs[breadcrumbs.length - 1];
			const text = last.textContent?.trim();
			if (text && text.length > 1 && !text.includes("...")) return text;
		}
		const titleEl = document.querySelector("header h1, header h2, [class*='title']");
		if (titleEl) {
			const text = titleEl.textContent?.trim();
			if (text && text.length > 1) return text;
		}
	} catch (e) {}
	return null;
}

export function detectActiveCRMContext() {
	// 1. Check Frappe Desk cur_frm
	if (typeof window !== "undefined" && window.cur_frm && window.cur_frm.doctype && window.cur_frm.docname) {
		const doc = window.cur_frm.doc || {};
		const title = doc.lead_name || doc.title || doc.organization_name || doc.customer_name || window.cur_frm.docname;
		return {
			doctype: window.cur_frm.doctype,
			docname: window.cur_frm.docname,
			label: `${window.cur_frm.doctype}: ${title}`,
		};
	}

	// 2. Check Frappe Desk route
	if (typeof window !== "undefined" && window.frappe && typeof window.frappe.get_route === "function") {
		const route = window.frappe.get_route();
		if (route && route[0] === "Form" && route[1] && route[2]) {
			return {
				doctype: route[1],
				docname: route[2],
				label: `${route[1]}: ${route[2]}`,
			};
		}
	}

	// 3. Check Frappe CRM Single Page App paths (/crm/leads/:id, /crm/deals/:id, etc.)
	if (typeof window === "undefined" || !window.location) return null;

	const path = window.location.pathname;
	const domTitle = getTitleFromDOM();

	const leadsMatch = path.match(/\/leads\/([^\/\?#]+)/);
	if (leadsMatch && leadsMatch[1] !== "view") {
		const id = decodeURIComponent(leadsMatch[1]);
		return { doctype: "CRM Lead", docname: id, label: `Lead: ${domTitle || id}` };
	}

	const dealsMatch = path.match(/\/deals\/([^\/\?#]+)/);
	if (dealsMatch && dealsMatch[1] !== "view") {
		const id = decodeURIComponent(dealsMatch[1]);
		return { doctype: "CRM Deal", docname: id, label: `Deal: ${domTitle || id}` };
	}

	const contactsMatch = path.match(/\/contacts\/([^\/\?#]+)/);
	if (contactsMatch && contactsMatch[1] !== "view") {
		const id = decodeURIComponent(contactsMatch[1]);
		return { doctype: "Contact", docname: id, label: `Contato: ${domTitle || id}` };
	}

	const orgsMatch = path.match(/\/organizations\/([^\/\?#]+)/);
	if (orgsMatch && orgsMatch[1] !== "view") {
		const id = decodeURIComponent(orgsMatch[1]);
		return { doctype: "CRM Organization", docname: id, label: `Organização: ${domTitle || id}` };
	}

	const tasksMatch = path.match(/\/tasks\/([^\/\?#]+)/);
	if (tasksMatch && tasksMatch[1] !== "view") {
		const id = decodeURIComponent(tasksMatch[1]);
		return { doctype: "CRM Task", docname: id, label: `Tarefa: ${domTitle || id}` };
	}

	const callLogsMatch = path.match(/\/call-logs\/([^\/\?#]+)/);
	if (callLogsMatch && callLogsMatch[1] !== "view") {
		const id = decodeURIComponent(callLogsMatch[1]);
		return { doctype: "CRM Call Log", docname: id, label: `Chamada: ${domTitle || id}` };
	}

	return null;
}
