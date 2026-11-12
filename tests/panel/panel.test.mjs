import assert from "node:assert/strict";
import test from "node:test";

import { fakeHass, installDom } from "./dom-harness.mjs";

const registry = installDom();
const { SeamlessRenamePanel, parseCsv, validateNewId } = await import(
  "../../custom_components/seamless_rename/panel/seamless-rename-panel.js"
);

const finding = (id, confidence, extra = {}) => ({
  finding_id: id,
  kind: "file",
  source: "automations.yaml",
  line: 4,
  confidence,
  old: "sensor.foo",
  new: "sensor.bar",
  selected: true,
  ...extra,
});

const plan = (overrides = {}) => ({
  plan_id: "plan-1",
  renames: [{ from: "sensor.foo", to: "sensor.bar" }],
  blockers: [],
  warnings: [],
  summary: {},
  findings: [finding("a:1", "certain"), finding("a:2", "likely"), finding("a:3", "uncertain")],
  external: [],
  diff: "--- a\n+++ b\n",
  ...overrides,
});

function mount(handlers, ids, language) {
  const hass = fakeHass(handlers, ids, language);
  const panel = new SeamlessRenamePanel();
  panel.hass = hass;
  return { panel, hass };
}

const find = (panel, name) => panel.querySelector(`[data-test="${name}"]`);
const findAll = (panel, name) => panel.querySelectorAll(`[data-test="${name}"]`);

async function previewSingle(panel) {
  await find(panel, "input-from").fire("input", { value: "sensor.foo" });
  await find(panel, "input-to").fire("input", { value: "sensor.bar" });
  await find(panel, "preview").fire("click");
}

test("registers the custom element", () => {
  assert.equal(registry.get("seamless-rename-panel"), SeamlessRenamePanel);
});

test("renders blockers and warnings", async () => {
  const { panel } = mount({
    plan: () => plan({ blockers: ["sensor.foo: the target 'sensor.bar' already exists"], warnings: ["careful"] }),
  });
  await previewSingle(panel);

  assert.match(find(panel, "blockers").textContent, /already exists/);
  assert.match(find(panel, "warnings").textContent, /careful/);
  assert.equal(find(panel, "apply").disabled, true);
});

test("uncertain findings are deselected by default", async () => {
  const { panel } = mount({ plan: () => plan() });
  await previewSingle(panel);

  const boxes = Object.fromEntries(
    findAll(panel, "finding-checkbox").map((box) => [box.getAttribute("data-id"), box.checked]),
  );
  assert.deepEqual(boxes, { "a:1": true, "a:2": true, "a:3": false });
});

test("apply sends only the deselected findings as exclusions", async () => {
  const { panel, hass } = mount({
    plan: () => plan(),
    apply: () => ({
      apply_id: "apply-1", status: "completed", changed_files: ["automations.yaml"],
      changed_dashboards: [], changed_helpers: [], restart_required: true, warnings: [],
    }),
  });
  await previewSingle(panel);
  const likely = findAll(panel, "finding-checkbox").find((box) => box.getAttribute("data-id") === "a:2");
  await likely.fire("change", { checked: false });
  await find(panel, "apply").fire("click");

  const sent = hass.sent.find((message) => message.type.endsWith("/apply"));
  assert.equal(sent.plan_id, "plan-1");
  assert.deepEqual(sent.exclude.sort(), ["a:2", "a:3"]);
  assert.match(find(panel, "apply-result").textContent, /completed/);
  assert.ok(find(panel, "restart-required"));
});

test("plan requests include uncertain findings so they can be ticked", async () => {
  const { panel, hass } = mount({ plan: () => plan() });
  await previewSingle(panel);
  assert.equal(hass.sent[0].include_uncertain, true);
  assert.equal(hass.sent[0].from, "sensor.foo");
});

test("bulk table shows collisions", async () => {
  const { panel, hass } = mount({
    plan: () => plan({
      renames: [
        { from: "sensor.a", to: "sensor.same" },
        { from: "sensor.b", to: "sensor.same" },
        { from: "sensor.c", to: "sensor.fine" },
      ],
      blockers: ["sensor.same: is the target of more than one rename"],
      findings: [],
    }),
  });
  await find(panel, "tab-bulk").fire("click");
  await find(panel, "input-csv").fire("input", {
    value: "from,to\nsensor.a,sensor.same\nsensor.b,sensor.same\nsensor.c,sensor.fine\n",
  });
  await find(panel, "preview").fire("click");

  assert.deepEqual(hass.sent[0].renames.length, 3);
  const flags = findAll(panel, "rename-row").map((row) => row.getAttribute("data-collision"));
  assert.deepEqual(flags, ["true", "true", "false"]);
  assert.equal(find(panel, "apply").disabled, true);
});

test("bulk pattern is sent as a pattern", async () => {
  const { panel, hass } = mount({ plan: () => plan({ findings: [] }) });
  await find(panel, "tab-bulk").fire("click");
  await find(panel, "input-match").fire("input", { value: "^sensor\\.old_(.*)$" });
  await find(panel, "input-replace").fire("input", { value: "sensor.new_\\1" });
  await find(panel, "preview").fire("click");
  assert.deepEqual(hass.sent[0].pattern, { match: "^sensor\\.old_(.*)$", replace: "sensor.new_\\1" });
});

test("live validation flags bad and taken entity IDs", async () => {
  const { panel } = mount({});
  await find(panel, "input-from").fire("input", { value: "sensor.foo" });
  await find(panel, "input-to").fire("input", { value: "Sensor.Bad" });
  assert.match(find(panel, "validation").textContent, /not a valid/i);
  await find(panel, "input-to").fire("input", { value: "sensor.taken" });
  assert.match(find(panel, "validation").textContent, /already exists/);
  await find(panel, "input-to").fire("input", { value: "light.other" });
  assert.match(find(panel, "validation").textContent, /domain/);
  await find(panel, "input-to").fire("input", { value: "sensor.fresh" });
  assert.equal(find(panel, "validation").textContent, "");
});

test("history lists applies and undo calls the backend", async () => {
  const history = [
    { apply_id: "apply-2", created_at: "2026-11-12T10:00:00", status: "completed",
      renames: [{ from: "sensor.a", to: "sensor.b" }] },
    { apply_id: "apply-1", created_at: "2026-11-11T10:00:00", status: "rolled_back", renames: [] },
  ];
  const { panel, hass } = mount({
    history: () => ({ history }),
    undo: () => ({
      apply_id: "apply-2", status: "undone", changed_files: [], changed_dashboards: [],
      changed_helpers: [], restart_required: false, warnings: [],
    }),
  });
  await find(panel, "tab-history").fire("click");

  assert.equal(findAll(panel, "history-row").length, 2);
  const undoButtons = findAll(panel, "undo");
  assert.equal(undoButtons.length, 1);
  await undoButtons[0].fire("click");
  const sent = hass.sent.find((message) => message.type.endsWith("/undo"));
  assert.deepEqual([sent.apply_id, sent.force], ["apply-2", false]);
});

test("a refused undo shows the error and offers a forced undo", async () => {
  const { panel, hass } = mount({
    history: () => ({
      history: [{ apply_id: "apply-9", created_at: "t", status: "completed", renames: [] }],
    }),
    undo: (message) => {
      if (!message.force) throw new Error("a.yaml changed since the apply");
      return { apply_id: "apply-9", status: "undone", changed_files: [], changed_dashboards: [],
        changed_helpers: [], restart_required: false, warnings: [] };
    },
  });
  await find(panel, "tab-history").fire("click");
  await find(panel, "undo").fire("click");
  assert.match(find(panel, "error").textContent, /changed since/);
  await find(panel, "force-undo").fire("click");
  const undos = hass.sent.filter((message) => message.type.endsWith("/undo"));
  assert.deepEqual(undos.map((message) => message.force), [false, true]);
  assert.equal(find(panel, "error"), null);
});

test("backend errors are shown instead of thrown", async () => {
  const { panel } = mount({ plan: () => { throw new Error("boom"); } });
  await previewSingle(panel);
  assert.equal(find(panel, "error").textContent, "boom");
});

test("no tab renders stray null text", async () => {
  const { panel } = mount({ history: () => ({ history: [] }), plan: () => plan() });
  const noNull = () => assert.doesNotMatch(panel.textContent, /null|undefined/);
  noNull();
  await find(panel, "tab-bulk").fire("click");
  noNull();
  await find(panel, "tab-history").fire("click");
  noNull();
  await find(panel, "tab-single").fire("click");
  await previewSingle(panel);
  noNull();
});

test("history shows a readable timestamp", async () => {
  const created = "2026-11-12T20:10:03.763221+00:00";
  const { panel } = mount({
    history: () => ({ history: [{ apply_id: "a", created_at: created, status: "undone", renames: [] }] }),
  });
  await find(panel, "tab-history").fire("click");
  const cell = find(panel, "history-row").querySelector("td");
  assert.equal(cell.textContent, new Date(created).toLocaleString());
});

test("the panel speaks the language of the Home Assistant user", async () => {
  const { panel } = mount({ history: () => ({ history: [] }) }, undefined, "de");
  assert.equal(find(panel, "tab-single").textContent, "Einzelumbenennung");
  assert.equal(find(panel, "preview").textContent, "Vorschau");
  assert.doesNotMatch(panel.textContent, /Single rename|Entity to rename|Preview/);
  await find(panel, "tab-history").fire("click");
  assert.equal(find(panel, "history-empty").textContent, "Noch keine Umbenennungen aufgezeichnet.");
});

test("an unsupported language falls back to english", () => {
  const { panel } = mount({}, undefined, "fr");
  assert.equal(find(panel, "tab-single").textContent, "Single rename");
});

test("validation messages are translated", async () => {
  const { panel } = mount({}, undefined, "de");
  await find(panel, "input-from").fire("input", { value: "sensor.foo" });
  await find(panel, "input-to").fire("input", { value: "light.other" });
  assert.equal(find(panel, "validation").textContent, "Die Domain kann nicht geändert werden.");
});

test("coded blockers and warnings are translated and mark collisions", async () => {
  const { panel } = mount({
    plan: () => plan({
      renames: [{ from: "sensor.a", to: "sensor.same" }, { from: "sensor.b", to: "sensor.same" }],
      blockers: ["english blocker"],
      blocker_details: [{ code: "duplicate_target", params: { entity: "sensor.same" } }],
      warnings: ["english warning", "other english"],
      warning_details: [
        { code: "no_state", params: { entity: "sensor.a" } },
        { code: "not_yet_known", params: {} },
      ],
      findings: [],
    }),
  }, undefined, "de");
  await find(panel, "tab-bulk").fire("click");
  await find(panel, "input-csv").fire("input", { value: "sensor.a,sensor.same\nsensor.b,sensor.same" });
  await find(panel, "preview").fire("click");

  assert.match(find(panel, "blockers").textContent, /Ziel von mehr als einer Umbenennung/);
  assert.doesNotMatch(find(panel, "blockers").textContent, /english blocker/);
  assert.match(find(panel, "warnings").textContent, /Hat keinen Zustand/);
  assert.match(find(panel, "warnings").textContent, /other english/);
  const flags = findAll(panel, "rename-row").map((row) => row.getAttribute("data-collision"));
  assert.deepEqual(flags, ["true", "true"]);
});

test("a plan without details still shows the english text", async () => {
  const { panel } = mount({ plan: () => plan({ blockers: ["plain text"] }) }, undefined, "de");
  await previewSingle(panel);
  assert.match(find(panel, "blockers").textContent, /plain text/);
});

test("confidence badges and statuses are translated", async () => {
  const { panel } = mount({
    plan: () => plan(),
    history: () => ({
      history: [{ apply_id: "a", created_at: "t", status: "completed", renames: [] }],
    }),
  }, undefined, "de");
  await previewSingle(panel);
  assert.deepEqual(findAll(panel, "badge").map((badge) => badge.textContent), [
    "sicher", "wahrscheinlich", "unsicher",
  ]);
  await find(panel, "tab-history").fire("click");
  assert.match(find(panel, "history-row").textContent, /abgeschlossen/);
});

test("backend errors with a translation key are translated", async () => {
  const error = Object.assign(new Error("no plan x"), { translation_key: "plan_not_found" });
  const { panel } = mount({ plan: () => { throw error; } }, undefined, "de");
  await previewSingle(panel);
  assert.equal(find(panel, "error").textContent, "Dieser Plan oder dieses Backup existiert nicht. (no plan x)");
});

test("history timestamps follow the user's language", async () => {
  const created = "2026-11-12T20:10:03.763221+00:00";
  const { panel } = mount({
    history: () => ({ history: [{ apply_id: "a", created_at: created, status: "undone", renames: [] }] }),
  }, undefined, "de");
  await find(panel, "tab-history").fire("click");
  const cell = find(panel, "history-row").querySelector("td");
  assert.equal(cell.textContent, new Date(created).toLocaleString("de"));
});

test("parseCsv skips the header and blank or malformed lines", () => {
  assert.deepEqual(parseCsv("from,to\n\nsensor.a;sensor.b\nbroken\nsensor.c\tsensor.d\r\n"), [
    { from: "sensor.a", to: "sensor.b" },
    { from: "sensor.c", to: "sensor.d" },
  ]);
});

test("validateNewId accepts a clean new ID", () => {
  assert.equal(validateNewId("sensor.a", "sensor.b", new Set()), "");
  assert.notEqual(validateNewId("sensor.a", "sensor.a", new Set()), "");
});
