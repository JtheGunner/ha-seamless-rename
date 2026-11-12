/**
 * Seamless Rename panel: a vanilla web component without a build chain.
 *
 * It only talks to the integration through its websocket commands and holds no rename logic.
 * All text is inserted as text nodes, never as HTML.
 */

import { errorText, messageText, translate } from "./i18n.js";

const COMMAND_PREFIX = "seamless_rename/";
const OBJECT_ID = "[a-z0-9]+(?:_[a-z0-9]+)*";
const ENTITY_ID_SHAPE = new RegExp(`^${OBJECT_ID}\\.${OBJECT_ID}$`);

const STYLE = `
  :host, seamless-rename-panel {
    display: block; min-height: 100%; box-sizing: border-box;
    background: var(--primary-background-color); color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
  }
  .header {
    display: flex; align-items: center; gap: 12px; height: 56px; padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff));
    font-size: 20px; font-weight: 500;
  }
  .page { max-width: 880px; margin: 0 auto; padding: 16px; }
  .tabs {
    display: inline-flex; gap: 4px; padding: 4px; margin-bottom: 16px;
    background: var(--secondary-background-color); border-radius: 12px;
  }
  button {
    font: inherit; cursor: pointer; border-radius: 8px; padding: 8px 16px;
    border: 1px solid var(--divider-color); background: var(--card-background-color);
    color: var(--primary-text-color);
  }
  button:hover:not(:disabled) { border-color: var(--primary-color); }
  button:focus-visible, input:focus-visible, textarea:focus-visible {
    outline: 2px solid var(--primary-color); outline-offset: 1px;
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .tabs button { border-color: transparent; background: transparent; }
  .tabs button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  button.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  button.danger { color: var(--error-color, #db4437); border-color: var(--error-color, #db4437); }
  .card {
    background: var(--card-background-color); border: 1px solid var(--divider-color);
    border-radius: var(--ha-card-border-radius, 12px); padding: 16px; margin: 16px 0;
  }
  .card > :first-child { margin-top: 0; }
  .hint { color: var(--secondary-text-color); margin: 0 0 8px; }
  .field { display: flex; flex-direction: column; gap: 4px; margin: 12px 0; font-weight: 500; }
  input, textarea {
    font: inherit; box-sizing: border-box; width: 100%; padding: 10px 12px; border-radius: 8px;
    border: 1px solid var(--divider-color); background: var(--card-background-color);
    color: var(--primary-text-color);
  }
  textarea { min-height: 96px; resize: vertical; }
  .actions { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
  .error, .blocker { color: var(--error-color, #db4437); }
  .error:empty { display: none; }
  .error { margin: 8px 0; }
  .warning { color: var(--warning-color, #ffa600); }
  .collision td { background: color-mix(in srgb, var(--error-color, #db4437) 15%, transparent); }
  .finding { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
  .finding input { width: auto; }
  .badge { border-radius: 12px; padding: 2px 8px; font-size: 0.8em; }
  .badge-certain { background: var(--success-color, #43a047); color: #fff; }
  .badge-likely { background: var(--info-color, #039be5); color: #fff; }
  .badge-uncertain { background: var(--warning-color, #ffa600); color: #000; }
  pre { overflow: auto; max-height: 400px; background: var(--secondary-background-color); padding: 12px; border-radius: 8px; }
  .table-wrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; }
  th { color: var(--secondary-text-color); font-weight: 500; }
  td, th { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--divider-color); }
  tbody tr:hover td { background: var(--secondary-background-color); }
  @media (max-width: 600px) { .page { padding: 8px; } .tabs { display: flex; } .tabs button { flex: 1; padding: 8px; } }
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
export function validateNewId(from, to, knownIds, language = "en") {
  if (!to) return "";
  if (!ENTITY_ID_SHAPE.test(to)) return translate(language, "validation.invalid");
  if (from && from.split(".")[0] !== to.split(".")[0]) return translate(language, "validation.domain");
  if (from === to) return translate(language, "validation.same");
  if (knownIds.has(to)) return translate(language, "validation.exists");
  return "";
}

/** Format an ISO timestamp for the user's language; unparseable values are shown as received. */
export function formatTimestamp(value, language) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value ?? "") : date.toLocaleString(language || undefined);
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

export class SeamlessRenamePanel extends HTMLElement {
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

  /** The text for ``key`` in the language of the signed-in Home Assistant user. */
  _t(key, params) {
    return translate(this._language(), key, params);
  }

  _language() {
    return this._hass?.language ?? this._hass?.locale?.language;
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
      this._state.error = errorText(this._language(), error);
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
    const body = this._hass === null ? [h("p", {}, this._t("loading"))] : [
      h("div", { class: "tabs" }, ...this._tabs()),
      state.error ? h("div", { class: "error", "data-test": "error" }, state.error) : null,
      state.forceFor
        ? h("button", { class: "danger", "data-test": "force-undo", onclick: () => this._undo(state.forceFor, true) },
            this._t("force_undo"))
        : null,
      state.tab === "single" ? this._singleTab() : null,
      state.tab === "bulk" ? this._bulkTab() : null,
      state.tab === "history" ? this._historyTab() : null,
      state.applied ? this._appliedCard(state.applied) : null,
    ].filter((node) => node !== null);
    this.replaceChildren(
      h("style", {}, STYLE),
      h("div", { class: "header" }, "Seamless Rename"),
      h("div", { class: "page" }, ...body),
    );
  }

  _tabs() {
    return [["single", "tab.single"], ["bulk", "tab.bulk"], ["history", "tab.history"]].map(
      ([id, label]) =>
        h("button", {
          "data-test": `tab-${id}`,
          class: this._state.tab === id ? "active" : "",
          onclick: () => this._setTab(id),
        }, this._t(label)),
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
    message.textContent = validateNewId(from, to, this._knownIds(), this._language());
  }

  _singleTab() {
    const { from, to, busy } = this._state;
    const ids = [...this._knownIds()].sort();
    return h("div", {},
      h("div", { class: "card" },
        h("datalist", { id: "seamless-rename-ids" }, ...ids.map((id) => h("option", { value: id }))),
        this._field(this._t("field.from"), "from", { list: "seamless-rename-ids" }),
        this._field(this._t("field.to"), "to"),
        h("div", { class: "error", "data-test": "validation" }, validateNewId(from, to, this._knownIds(), this._language())),
        h("div", { class: "actions" },
          h("button", {
            class: "primary", "data-test": "preview", disabled: busy || !from || !to,
            onclick: () => this._previewSingle(),
          }, this._t("preview")))),
      this._state.plan ? this._planCard(this._state.plan) : null);
  }

  _bulkTab() {
    const { busy } = this._state;
    return h("div", {},
      h("div", { class: "card" },
        h("p", { class: "hint" }, this._t("bulk.hint")),
        this._field(this._t("field.match"), "match"),
        this._field(this._t("field.replace"), "replace"),
        this._field(this._t("field.domain"), "domain"),
        h("label", { class: "field" }, this._t("field.csv"),
          h("textarea", {
            "data-test": "input-csv",
            value: this._state.csv,
            oninput: (event) => { this._state.csv = event.target.value; },
          })),
        h("div", { class: "actions" },
          h("button", { class: "primary", "data-test": "preview", disabled: busy, onclick: () => this._previewBulk() },
            this._t("preview")))),
      this._state.plan ? this._planCard(this._state.plan) : null);
  }

  /** Translate backend messages by code; messages without a known code stay in English. */
  _messageTexts(texts, details = []) {
    return texts.map((text, index) => messageText(this._language(), details[index], text));
  }

  _planCard(plan) {
    const { busy, selected } = this._state;
    const blocked = plan.blockers.length > 0;
    return h("div", { class: "card", "data-test": "plan" },
      blocked
        ? h("div", { "data-test": "blockers" },
            h("strong", {}, this._t("blocked")),
            h("ul", {}, ...this._messageTexts(plan.blockers, plan.blocker_details)
              .map((text) => h("li", { class: "blocker" }, text))))
        : null,
      plan.warnings.length > 0
        ? h("div", { "data-test": "warnings" },
            h("strong", {}, this._t("warnings")),
            h("ul", {}, ...this._messageTexts(plan.warnings, plan.warning_details)
              .map((text) => h("li", { class: "warning" }, text))))
        : null,
      this._renamesTable(plan),
      ...[...groupBySource(plan.findings)].map(([source, findings]) =>
        h("div", { "data-test": "finding-group" },
          h("h4", {}, source),
          ...findings.map((finding) => this._findingRow(finding, selected.has(finding.finding_id))))),
      plan.external.length > 0
        ? h("p", { "data-test": "external" }, this._t("external", { count: plan.external.length }))
        : null,
      h("details", {}, h("summary", {}, this._t("full_diff")), h("pre", { "data-test": "diff" }, plan.diff ?? "")),
      h("div", { class: "actions" },
        h("button", { class: "primary", "data-test": "apply", disabled: busy || blocked, onclick: () => this._apply() },
          this._t("apply"))));
  }

  _renamesTable(plan) {
    const involved = (rename) => plan.blockers.some((text, index) => {
      const entity = plan.blocker_details?.[index]?.params?.entity;
      return entity === undefined
        ? text.startsWith(`${rename.from}:`) || text.startsWith(`${rename.to}:`)
        : entity === rename.from || entity === rename.to;
    });
    return h("div", { class: "table-wrap" }, h("table", { "data-test": "renames-table" },
      h("tr", {}, h("th", {}, this._t("col.from")), h("th", {}, this._t("col.to"))),
      ...plan.renames.map((rename) =>
        h("tr", {
          "data-test": "rename-row",
          class: involved(rename) ? "collision" : "",
          "data-collision": involved(rename) ? "true" : "false",
        }, h("td", {}, rename.from), h("td", {}, rename.to)))));
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
      h("span", { class: `badge badge-${finding.confidence}`, "data-test": "badge" },
        this._label("confidence", finding.confidence)),
      this._t("finding", { line: finding.line, old: finding.old, new: finding.new }));
  }

  /** Translate an enum value such as a status; an unknown value is shown as received. */
  _label(group, value) {
    const key = `${group}.${value}`;
    const text = this._t(key);
    return text === key ? String(value) : text;
  }

  _appliedCard(result) {
    return h("div", { class: "card", "data-test": "apply-result" },
      h("strong", {}, this._t("result.status", { status: this._label("status", result.status) })),
      h("p", {}, this._t("result.changed", {
        files: result.changed_files.length,
        dashboards: result.changed_dashboards.length,
        helpers: result.changed_helpers.length,
      })),
      result.restart_required
        ? h("p", { class: "warning", "data-test": "restart-required" }, this._t("result.restart"))
        : null,
      ...this._messageTexts(result.warnings, result.warning_details)
        .map((text) => h("p", { class: "warning" }, text)),
      result.status === "completed"
        ? h("button", { class: "danger", "data-test": "undo", onclick: () => this._undo(result.apply_id) },
            this._t("undo"))
        : null);
  }

  _historyTab() {
    const history = this._state.history;
    if (history === null) return h("p", { class: "hint" }, this._t("loading"));
    if (history.length === 0) {
      return h("p", { class: "hint", "data-test": "history-empty" }, this._t("history.empty"));
    }
    return h("div", { class: "card table-wrap" }, h("table", { "data-test": "history-table" },
      h("tr", {}, h("th", {}, this._t("col.when")), h("th", {}, this._t("col.renames")),
        h("th", {}, this._t("col.status")), h("th", {}, "")),
      ...history.map((item) =>
        h("tr", { "data-test": "history-row" },
          h("td", {}, formatTimestamp(item.created_at, this._language())),
          h("td", {}, item.renames.map((r) => `${r.from} → ${r.to}`).join(", ")),
          h("td", {}, this._label("status", item.status)),
          h("td", {}, item.status === "completed"
            ? h("button", {
              class: "danger", "data-test": "undo", "data-id": item.apply_id,
              onclick: () => this._undo(item.apply_id),
            }, this._t("undo"))
            : null)))));
  }
}

customElements.define("seamless-rename-panel", SeamlessRenamePanel);
