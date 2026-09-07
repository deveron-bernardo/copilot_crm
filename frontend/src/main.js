import { createApp, watch } from "vue";
import App from "@/App.vue";
import { useStore } from "@/store";
import { readPanelState, writePanelState } from "@/lib/panelState";
import { detectActiveCRMContext } from "@/lib/context";
import "@/index.css";

const PANEL_WIDTH = 420;
const MIN_WIDTH = 360;

// Slide-in overlay panel injected into the Frappe desk. The Vue app (with real
// frappe-ui components) mounts inside #flow-root; all bundle CSS is scoped to
// that id so nothing leaks onto the desk.
class FlowPanel {
	constructor() {
		const saved = readPanelState();
		this.visible = Boolean(saved.open);
		this._halfWidth = saved.width || PANEL_WIDTH;
		// Fullscreen is the default mode; a saved preference wins on reload.
		this._initialFullscreen = saved.fullscreen ?? true;

		this._mount();
		this._syncTheme();
		this._registerShortcut();
		this._addFloatingTrigger();

		watch(this.store.sessionName, () => this._persist());
	}

	get fullscreen() {
		return this.store.fullscreen.value;
	}

	_mount() {
		this.store = useStore();
		this.store.fullscreen.value = this._initialFullscreen;

		this.root = document.createElement("div");
		this.root.id = "flow-root";
		Object.assign(this.root.style, {
			position: "fixed",
			top: "0",
			right: "0",
			width: this.fullscreen ? "100vw" : `${this._halfWidth}px`,
			height: "100vh",
			zIndex: "1040",
			// A restored-open panel renders in place (no slide) so a refresh is seamless.
			transform: this.visible ? "translateX(0)" : "translateX(100%)",
			transition: "transform 0.22s ease",
			boxShadow: "-2px 0 16px rgba(0, 0, 0, 0.08)",
		});
		document.body.appendChild(this.root);

		this.app = createApp(App, {
			onClose: () => this.hide(),
			onToggleFullscreen: () => this.toggleFullscreen(),
		});
		this.app.mount(this.root);

		this._addResizeHandle();
	}

	// Thin grab strip on the panel's left edge. Dragging it changes the panel
	// width (anchored to the right). Appended after mount so Vue's render
	// doesn't clobber it.
	_addResizeHandle() {
		const handle = document.createElement("div");
		Object.assign(handle.style, {
			position: "absolute",
			top: "0",
			left: "0",
			width: "6px",
			height: "100%",
			cursor: "ew-resize",
			zIndex: "10",
		});
		this.root.appendChild(handle);

		const onMove = (e) => {
			const max = window.innerWidth - 80;
			const width = Math.min(max, Math.max(MIN_WIDTH, window.innerWidth - e.clientX));
			this.root.style.width = `${width}px`;
			this._halfWidth = width;
			// A manual resize takes the panel out of fullscreen; keep the header icon honest.
			this.store.fullscreen.value = false;
		};
		const onUp = () => {
			document.removeEventListener("mousemove", onMove);
			document.removeEventListener("mouseup", onUp);
			document.body.style.userSelect = "";
			this.root.style.transition = this._savedTransition;
			this._persist();
		};
		handle.addEventListener("mousedown", (e) => {
			e.preventDefault();
			// Drop the width transition while dragging so it tracks the cursor.
			this._savedTransition = this.root.style.transition;
			this.root.style.transition = "none";
			document.body.style.userSelect = "none";
			document.addEventListener("mousemove", onMove);
			document.addEventListener("mouseup", onUp);
		});
	}

	// Mirror the desk's light/dark theme onto the panel root so scoped tokens
	// resolve to the right palette.
	_syncTheme() {
		const apply = () => {
			const theme = document.documentElement.getAttribute("data-theme") || "light";
			this.root.setAttribute("data-theme", theme);
		};
		apply();
		new MutationObserver(apply).observe(document.documentElement, {
			attributes: true,
			attributeFilter: ["data-theme"],
		});
	}

	_registerShortcut() {
		// 1. Universal keyboard listener for Ctrl+I and Cmd+I in any browser / SPA route
		window.addEventListener("keydown", (e) => {
			if ((e.ctrlKey || e.metaKey) && e.key && e.key.toLowerCase() === "i") {
				e.preventDefault();
				this.toggle();
			}
		});

		// 2. Desk shortcut manager if available
		if (window.frappe?.ui?.keys?.add_shortcut) {
			try {
				window.frappe.ui.keys.add_shortcut({
					shortcut: "ctrl+i",
					action: () => this.toggle(),
					description: __("Toggle Copilot CRM panel"),
					ignore_inputs: true,
				});
			} catch (_) {}
		}
	}

	_addFloatingTrigger() {
		if (document.getElementById("copilot-crm-trigger")) return;
		const btn = document.createElement("button");
		btn.id = "copilot-crm-trigger";
		btn.setAttribute("title", "Abrir Copilot CRM (Ctrl+I)");
		btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>`;
		Object.assign(btn.style, {
			position: "fixed",
			bottom: "20px",
			right: "20px",
			zIndex: "1030",
			width: "44px",
			height: "44px",
			borderRadius: "50%",
			background: "#18181b",
			color: "#ffffff",
			border: "1px solid rgba(255,255,255,0.15)",
			boxShadow: "0 4px 14px rgba(0,0,0,0.25)",
			cursor: "pointer",
			display: "flex",
			alignItems: "center",
			justifyContent: "center",
			transition: "transform 0.15s ease, background-color 0.15s ease",
		});
		btn.addEventListener("mouseenter", () => {
			btn.style.transform = "scale(1.08)";
			btn.style.background = "#27272a";
		});
		btn.addEventListener("mouseleave", () => {
			btn.style.transform = "scale(1)";
			btn.style.background = "#18181b";
		});
		btn.addEventListener("click", () => this.toggle());
		document.body.appendChild(btn);
	}

	show() {
		this.visible = true;
		this.root.style.transform = "translateX(0)";
		if (this.store?.activeContext) {
			this.store.activeContext.value = detectActiveCRMContext();
		}
		this.store.restoreSession();
		this._persist();
	}

	hide() {
		this.visible = false;
		this.root.style.transform = "translateX(100%)";
		this._persist();
	}

	toggle() {
		this.visible ? this.hide() : this.show();
	}

	// Expand to the full viewport width, or restore the half-screen width. State
	// lives in the store so the header icon tracks it reactively.
	toggleFullscreen() {
		const next = !this.fullscreen;
		this.store.fullscreen.value = next;
		this.root.style.width = next ? "100vw" : `${this._halfWidth}px`;
		this._persist();
	}

	_persist() {
		writePanelState({
			open: this.visible,
			fullscreen: this.fullscreen,
			width: this._halfWidth,
			session: this.store.sessionName.value,
		});
	}
}

function initPanel() {
	if (window.__copilot_crm_initialized) return;
	window.__copilot_crm_initialized = true;
	if (!window.frappe) window.frappe = {};
	window.frappe.flow = window.frappe.flow || {};
	window.frappe.flow.panel = new FlowPanel();
}

if (document.readyState === "complete" || document.readyState === "interactive") {
	initPanel();
} else {
	document.addEventListener("DOMContentLoaded", initPanel);
}

if (typeof $ !== "undefined") {
	$(document).on("app_ready", initPanel);
}
