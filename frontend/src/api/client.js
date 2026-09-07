import { __ } from "@/lib/translate";

export function getCsrfToken() {
	if (typeof window === "undefined") return "";
	if (window.frappe?.csrf_token) return window.frappe.csrf_token;
	if (window.csrf_token) return window.csrf_token;
	try {
		const cookies = new URLSearchParams(document.cookie.split("; ").join("&"));
		return cookies.get("csrf_token") || "";
	} catch (_) {
		return "";
	}
}

export function getCurrentUser() {
	if (typeof window === "undefined") return "Administrator";
	if (window.frappe?.session?.user) return window.frappe.session.user;
	if (window.user_id && window.user_id !== "Guest") return window.user_id;
	try {
		const cookies = new URLSearchParams(document.cookie.split("; ").join("&"));
		const uid = cookies.get("user_id");
		if (uid && uid !== "Guest") return uid;
	} catch (_) {}
	return "Administrator";
}

import { marked } from "marked";

// Polyfill window.frappe so that legacy Desk calls continue to work seamlessly
if (typeof window !== "undefined") {
	window.frappe = window.frappe || {};
	window.frappe.boot = window.frappe.boot || {};
	window.frappe.csrf_token = window.frappe.csrf_token || getCsrfToken();
	window.frappe.session = window.frappe.session || { user: getCurrentUser() };
	if (!window.frappe.markdown) {
		window.frappe.markdown = (s) => marked.parse(s, { gfm: true, breaks: true });
	}
}

async function rawFetchCall(method, params = {}) {
	const token = getCsrfToken();
	const headers = {
		"Content-Type": "application/json",
		Accept: "application/json",
	};
	if (token) {
		headers["X-Frappe-CSRF-Token"] = token;
	}

	const resp = await fetch(`/api/method/${method}`, {
		method: "POST",
		headers,
		body: JSON.stringify(params),
	});

	const data = await resp.json().catch(() => ({}));
	if (!resp.ok) {
		throw new Error(serverMessage(data) || `Request failed (${resp.status})`);
	}
	return data.message;
}

export async function xcall(method, params = {}) {
	if (
		typeof window !== "undefined" &&
		typeof window.frappe?.xcall === "function" &&
		window.frappe.xcall !== xcall
	) {
		return window.frappe.xcall(method, params);
	}
	return rawFetchCall(method, params);
}

if (typeof window !== "undefined") {
	window.frappe.xcall = window.frappe.xcall || xcall;
}

// Read-only data fetches over the client API.
function getList(doctype, options) {
	return xcall("frappe.client.get_list", { doctype, ...options });
}

export const loadAgents = () =>
	getList("Flow Agent", { filters: { enabled: 1 }, fields: ["name", "title"], limit: 50 });

export const loadModels = () =>
	getList("Flow Model", { filters: { enabled: 1 }, fields: ["name", "title"], limit: 50 });

export const loadHistory = () =>
	getList("Flow Session", {
		filters: { owner: getCurrentUser(), source: ["!=", "Trigger"] },
		fields: ["name", "title", "modified"],
		order_by: "modified desc",
		limit: 15,
	});

// Escape LIKE wildcards so a literal % or _ matches itself, not "anything".
const escapeLike = (s) => s.replace(/[\\%_]/g, "\\$&");

export const searchSessions = (query) =>
	getList("Flow Session", {
		filters: {
			owner: getCurrentUser(),
			source: ["!=", "Trigger"],
			title: ["like", `%${escapeLike(query)}%`],
		},
		fields: ["name", "title", "modified"],
		order_by: "modified desc",
		limit: 20,
	});

export const getSession = (name) =>
	xcall("frappe.client.get", { doctype: "Flow Session", name });

export const getPausedRun = (session) =>
	getList("Flow Run", {
		filters: { session, status: "Paused" },
		fields: ["name", "questions"],
		order_by: "creation desc",
		limit: 1,
	});

// Feedback the user already gave on this session's runs, to restore thumbs state on reload.
export const getRunFeedback = (session) =>
	getList("Flow Run", {
		filters: { session, feedback_rating: ["is", "set"] },
		fields: ["name", "feedback_rating", "feedback_comment"],
		limit: 100,
	});

// Record thumbs feedback on a run; optionally store a Down comment as agent memory.
export const submitFeedback = (args) => xcall("flow.api.submit_feedback", args);

// Fail any Running run left behind by a stream that was cut off (refresh/navigation),
// so a reloaded session isn't blocked from starting the next turn.
export const recoverSession = (session) => xcall("flow.api.recover_session", { session });

// Stop a run at the user's request: finalize an aborted stream's run or terminate a
// paused run so the agent won't continue.
export const stopRun = (run_name) => xcall("flow.api.stop_run", { run_name });

// Map of the agent's tool slugs → requires_confirmation, so the panel can tell an
// approval tool call from an inline one.
export const getAgentTools = (agent) => xcall("flow.api.get_agent_tools", { agent });

// Upload a file as private, returning the created File doc. The chat attachment
// flow needs the File name to stage it via attachFile.
export async function uploadFile(file) {
	const form = new FormData();
	form.append("file", file, file.name);
	form.append("is_private", "1");

	const token = getCsrfToken();
	const headers = {};
	if (token) headers["X-Frappe-CSRF-Token"] = token;

	const resp = await fetch("/api/method/upload_file", {
		method: "POST",
		headers,
		body: form,
	});
	const data = await resp.json().catch(() => ({}));
	if (!resp.ok) throw new Error(serverMessage(data) || __("Upload failed ({0})", [resp.status]));
	return data.message;
}

// Validate and stage an uploaded File for use as a chat attachment. Returns chip
// metadata; throws (unsupported type, unreadable, …) which surfaces on the chip.
export const attachFile = (file) => xcall("flow.api.attach_file", { file });

// Extract the human-readable message from a frappe error body.
export function serverMessage(data) {
	try {
		const msgs = JSON.parse(data._server_messages || "[]");
		if (msgs.length) return JSON.parse(msgs[0]).message;
	} catch {
		// fall through to other error fields
	}
	return data.exception || data._error_message || null;
}
