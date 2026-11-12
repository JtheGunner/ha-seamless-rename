/**
 * Seamless Rename panel: a vanilla web component without a build chain.
 *
 * It only talks to the integration through its websocket commands and holds no rename logic.
 * All text is inserted as text nodes, never as HTML.
 */

const COMMAND_PREFIX = "entity_rename_safe/";
const OBJECT_ID = "[a-z0-9]+(?:_[a-z0-9]+)*";
const ENTITY_ID_SHAPE = new RegExp(`^${OBJECT_ID}\\.${OBJECT_ID}$`);

const STYLE = `
  :host, entity-rename-safe-panel { display: block; padding: 16px; color: var(--primary-text-color); }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tabs button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .card { border: 1px solid var(--divider-color); border-radius: 8px; padding: 12px; margin: 12px 0; }
  .field { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; max-width: 480px; }
  .error, .blocker { color: var(--error-color, #db4437); }
  .warning { color: var(--warning-color, #ffa600); }
  .collision td { background: color-mix(in srgb, var(--error-color, #db4437) 15%, transparent); }
  .badge { border-radius: 4px; padding: 0 6px; margin: 0 6px; font-size: 0.8em; }
  .badge-certain { background: var(--success-color, #43a047); color: #fff; }
  .badge-likely { background: var(--info-color, #039be5); color: #fff; }
  .badge-uncertain { background: var(--warning-color, #ffa600); color: #000; }
  pre { overflow: auto; max-height: 400px; }
  table { border-collapse: collapse; }
  td, th { padding: 2px 8px; text-align: left; }
`;

/** Create an element; ``on*`` props are listeners, ``value``/``checked``/``disabled`` properties. */
function h(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("on")) {
      element.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "class") {
      element.className = value;
    } else if (key === "value" || key === "checked" || key === "disabled") {
      element[key] = value;
    } else if (value !== false && value != null) {
      element.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    element.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return element;
}

/** Parse ``from,to`` lines (comma, semicolon or tab separated) into rename pairs. */
export function parseCsv(text) {
  const renames = [];
  for (const line of text.split(/\r?\n/)) {
    const cells = line.split(/[,;\t]/).map((cell) => cell.trim());
    if (cells.length < 2 || !cells[0] || !cells[1]) continue;
    if (cells[0].toLowerCase() === "from" && cells[1].toLowerCase() === "to") continue;
    renames.push({ from: cells[0], to: cells[1] });
  }
  return renames;
}

/** Return a short problem description for a new entity ID, or ``""`` when it looks fine. */
export function validateNewId(from, to, knownIds) {
  if (!to) return "";
  if (!ENTITY_ID_SHAPE.test(to)) return "Not a valid entity ID (lowercase letters, digits, underscores).";
  if (from && from.split(".")[0] !== to.split(".")[0]) return "The domain cannot change.";
  if (from === to) return "The new ID equals the old one.";
  if (knownIds.has(to)) return "This entity ID already exists.";
  return "";
}

/** Group plan findings by the file, dashboard or helper they belong to. */
function groupBySource(findings) {
  const groups = new Map();
  for (const finding of findings) {
    const key = `${finding.kind}: ${finding.source}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(finding);
  }
  return groups;
}

export class EntityRenameSafePanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._state = {
      tab: "single",
      from: "",
      to: "",
      match: "",
      replace: "",
      domain: "",
      csv: "",
      plan: null,
      selected: new Set(),
      applied: null,
      history: null,
      busy: false,
      error: "",
      forceFor: "",
    };
  }

  set hass(value) {
    const first = this._hass === null;
    this._hass = value;
    if (first) this._render();
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this._render();
  }

  _knownIds() {
    const source = this._hass?.entities ?? this._hass?.states ?? {};
    return new Set(Object.keys(source));
  }

  async _call(type, payload = {}) {
    return this._hass.connection.sendMessagePromise({ type: COMMAND_PREFIX + type, ...payload });
  }

  async _run(action) {
    this._state.busy = true;
    this._state.error = "";
    this._render();
    try {
      await action();
    } catch (error) {
      this._state.error = error?.message ?? String(error);
    } finally {
      this._state.busy = false;
      this._render();
    }
  }

  _setTab(tab) {
    this._state.tab = tab;
    this._state.error = "";
    if (tab === "history") return this._loadHistory();
    this._render();
    return undefined;
  }

  _loadHistory() {
    return this._run(async () => {
      this._state.history = (await this._call("history")).history;
    });
  }

  _preview(payload) {
    return this._run(async () => {
      // Plan with uncertain findings included so they can be ticked; they start deselected.
      const plan = await this._call("plan", { ...payload, include_uncertain: true });
      this._state.plan = plan;
      this._state.applied = null;
      this._state.selected = new Set(
        plan.findings.filter((finding) => finding.confidence !== "uncertain").map((f) => f.finding_id),
      );
    });
  }

  _previewSingle() {
    const { from, to } = this._state;
    return this._preview({ from, to });
  }

  _previewBulk() {
    const { csv, match, replace, domain } = this._state;
    const renames = parseCsv(csv);
    if (renames.length > 0) return this._preview({ renames });
    const pattern = { match, replace };
    if (domain) pattern.domain = domain;
    return this._preview({ pattern });
  }

  _apply() {
    const { plan, selected } = this._state;
    const exclude = plan.findings
      .filter((finding) => !selected.has(finding.finding_id))
      .map((finding) => finding.finding_id);
    return this._run(async () => {
      this._state.applied = await this._call("apply", { plan_id: plan.plan_id, exclude });
      this._state.plan = null;
    });
  }

  _undo(applyId, force = false) {
    return this._run(async () => {
      try {
        this._state.applied = await this._call("undo", { apply_id: applyId, force });
        this._state.forceFor = "";
        this._state.plan = null;
        this._state.history = (await this._call("history")).history;
      } catch (error) {
        this._state.forceFor = applyId;
        throw error;
      }
    });
  }

  _toggleFinding(findingId, checked) {
    if (checked) this._state.selected.add(findingId);
    else this._state.selected.delete(findingId);
  }

  _render() {
    const state = this._state;
    const body = this._hass === null ? [h("p", {}, "Loading…")] : [
      h("div", { class: "tabs" }, ...this._tabs()),
      state.error ? h("div", { class: "error", "data-test": "error" }, state.error) : null,
      state.forceFor
        ? h("button", { "data-test": "force-undo", onclick: () => this._undo(state.forceFor, true) },
            "Force undo (overwrite later edits)")
        : null,
      state.tab === "single" ? this._singleTab() : null,
      state.tab === "bulk" ? this._bulkTab() : null,
      state.tab === "history" ? this._historyTab() : null,
      state.applied ? this._appliedCard(state.applied) : null,
    ];
    this.replaceChildren(h("style", {}, STYLE), ...body);
  }

  _tabs() {
    return [["single", "Single rename"], ["bulk", "Bulk"], ["history", "History"]].map(
      ([id, label]) =>
        h("button", {
          "data-test": `tab-${id}`,
          class: this._state.tab === id ? "active" : "",
          onclick: () => this._setTab(id),
        }, label),
    );
  }

  _field(label, name, extra = {}) {
    return h("label", { class: "field" }, label,
      h("input", {
        "data-test": `input-${name}`,
        value: this._state[name],
        oninput: (event) => {
          this._state[name] = event.target.value;
          this._updateValidation();
        },
        ...extra,
      }));
  }

  _updateValidation() {
    const message = this.querySelector('[data-test="validation"]');
    if (!message) return;
    const { from, to } = this._state;
    message.textContent = validateNewId(from, to, this._knownIds());
  }

  _singleTab() {
    const { from, to, busy } = this._state;
    const ids = [...this._knownIds()].sort();
    return h("div", {},
      h("datalist", { id: "entity-rename-safe-ids" }, ...ids.map((id) => h("option", { value: id }))),
      this._field("Entity to rename", "from", { list: "entity-rename-safe-ids" }),
      this._field("New entity ID", "to"),
      h("div", { class: "error", "data-test": "validation" }, validateNewId(from, to, this._knownIds())),
      h("button", { "data-test": "preview", disabled: busy || !from || !to, onclick: () => this._previewSingle() },
        "Preview"),
      this._state.plan ? this._planCard(this._state.plan) : null);
  }

  _bulkTab() {
    const { busy } = this._state;
    return h("div", {},
      h("p", {}, "Use a pattern (regular expression on the entity ID) or paste from,to lines."),
      this._field("Match", "match"),
      this._field("Replace", "replace"),
      this._field("Domain (optional)", "domain"),
      h("label", { class: "field" }, "CSV (from,to per line; overrides the pattern)",
        h("textarea", {
          "data-test": "input-csv",
          value: this._state.csv,
          oninput: (event) => { this._state.csv = event.target.value; },
        })),
      h("button", { "data-test": "preview", disabled: busy, onclick: () => this._previewBulk() }, "Preview"),
      this._state.plan ? this._planCard(this._state.plan) : null);
  }

  _planCard(plan) {
    const { busy, selected } = this._state;
    const blocked = plan.blockers.length > 0;
    return h("div", { class: "card", "data-test": "plan" },
      blocked
        ? h("div", { "data-test": "blockers" },
            h("strong", {}, "Blocked – this plan cannot be applied:"),
            h("ul", {}, ...plan.blockers.map((text) => h("li", { class: "blocker" }, text))))
        : null,
      plan.warnings.length > 0
        ? h("div", { "data-test": "warnings" },
            h("strong", {}, "Warnings:"),
            h("ul", {}, ...plan.warnings.map((text) => h("li", { class: "warning" }, text))))
        : null,
      this._renamesTable(plan),
      ...[...groupBySource(plan.findings)].map(([source, findings]) =>
        h("div", { "data-test": "finding-group" },
          h("h4", {}, source),
          ...findings.map((finding) => this._findingRow(finding, selected.has(finding.finding_id))))),
      plan.external.length > 0
        ? h("p", { "data-test": "external" },
            `${plan.external.length} reference(s) outside the configuration are listed but not changed.`)
        : null,
      h("details", {}, h("summary", {}, "Full diff"), h("pre", { "data-test": "diff" }, plan.diff ?? "")),
      h("button", { "data-test": "apply", disabled: busy || blocked, onclick: () => this._apply() },
        "Apply selected changes"));
  }

  _renamesTable(plan) {
    const isCollision = (rename) =>
      plan.blockers.some((text) => text.startsWith(`${rename.from}:`) || text.startsWith(`${rename.to}:`));
    return h("table", { "data-test": "renames-table" },
      h("tr", {}, h("th", {}, "From"), h("th", {}, "To")),
      ...plan.renames.map((rename) =>
        h("tr", {
          "data-test": "rename-row",
          class: isCollision(rename) ? "collision" : "",
          "data-collision": isCollision(rename) ? "true" : "false",
        }, h("td", {}, rename.from), h("td", {}, rename.to))));
  }

  _findingRow(finding, checked) {
    return h("label", { class: "finding", "data-test": "finding" },
      h("input", {
        type: "checkbox",
        "data-test": "finding-checkbox",
        "data-id": finding.finding_id,
        checked,
        onchange: (event) => this._toggleFinding(finding.finding_id, event.target.checked),
      }),
      h("span", { class: `badge badge-${finding.confidence}`, "data-test": "badge" }, finding.confidence),
      `line ${finding.line}: ${finding.old} → ${finding.new}`);
  }

  _appliedCard(result) {
    const counts = `${result.changed_files.length} file(s), ${result.changed_dashboards.length} dashboard(s), `
      + `${result.changed_helpers.length} helper(s)`;
    return h("div", { class: "card", "data-test": "apply-result" },
      h("strong", {}, `Status: ${result.status}`),
      h("p", {}, `Changed ${counts}.`),
      result.restart_required
        ? h("p", { class: "warning", "data-test": "restart-required" }, "Restart Home Assistant to finish.")
        : null,
      ...result.warnings.map((text) => h("p", { class: "warning" }, text)),
      result.status === "completed"
        ? h("button", { "data-test": "undo", onclick: () => this._undo(result.apply_id) }, "Undo")
        : null);
  }

  _historyTab() {
    const history = this._state.history;
    if (history === null) return h("p", {}, "Loading…");
    if (history.length === 0) return h("p", { "data-test": "history-empty" }, "No renames recorded yet.");
    return h("table", { "data-test": "history-table" },
      h("tr", {}, h("th", {}, "When"), h("th", {}, "Renames"), h("th", {}, "Status"), h("th", {}, "")),
      ...history.map((item) =>
        h("tr", { "data-test": "history-row" },
          h("td", {}, item.created_at),
          h("td", {}, item.renames.map((r) => `${r.from} → ${r.to}`).join(", ")),
          h("td", {}, item.status),
          h("td", {}, item.status === "completed"
            ? h("button", { "data-test": "undo", "data-id": item.apply_id, onclick: () => this._undo(item.apply_id) }, "Undo")
            : null))));
  }
}

customElements.define("entity-rename-safe-panel", EntityRenameSafePanel);
