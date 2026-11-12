import assert from "node:assert/strict";
import test from "node:test";

import {
  TRANSLATIONS,
  errorText,
  messageText,
  resolveLanguage,
  translate,
} from "../../custom_components/seamless_rename/panel/i18n.js";

test("english and german are available", () => {
  assert.ok(TRANSLATIONS.en);
  assert.ok(TRANSLATIONS.de);
});

test("every language has the same keys and placeholders as english", () => {
  const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
  for (const [language, dictionary] of Object.entries(TRANSLATIONS)) {
    assert.deepEqual(Object.keys(dictionary).sort(), Object.keys(TRANSLATIONS.en).sort(), language);
    for (const [key, text] of Object.entries(dictionary)) {
      assert.deepEqual(placeholders(text), placeholders(TRANSLATIONS.en[key]), `${language}:${key}`);
    }
  }
});

test("resolveLanguage uses the base language and falls back to english", () => {
  assert.equal(resolveLanguage("de"), "de");
  assert.equal(resolveLanguage("de-CH"), "de");
  assert.equal(resolveLanguage("DE_at"), "de");
  assert.equal(resolveLanguage("fr"), "en");
  assert.equal(resolveLanguage(undefined), "en");
});

test("translate fills placeholders and falls back to english, then to the key", () => {
  assert.equal(translate("de", "tab.single"), TRANSLATIONS.de["tab.single"]);
  assert.equal(translate("fr", "tab.single"), TRANSLATIONS.en["tab.single"]);
  assert.equal(translate("en", "no.such.key"), "no.such.key");
  assert.match(translate("en", "external", { count: 3 }), /3/);
  assert.doesNotMatch(translate("en", "external", { count: 3 }), /\{count\}/);
});

test("messageText translates known codes and keeps the english text otherwise", () => {
  const known = { code: "duplicate_target", params: { entity: "sensor.x" } };
  assert.match(messageText("de", known, "english text"), /sensor\.x/);
  assert.notEqual(messageText("de", known, "english text"), "english text");
  assert.equal(messageText("de", { code: "nope", params: {} }, "english text"), "english text");
  assert.equal(messageText("de", { code: null, params: {} }, "english text"), "english text");
  assert.equal(messageText("de", undefined, "english text"), "english text");
});

test("errorText translates a known error key and keeps the message as detail", () => {
  const error = { code: "rename_rejected", translation_key: "plan_not_found", message: "no plan x" };
  assert.equal(errorText("de", error), `${TRANSLATIONS.de["error.plan_not_found"]} (no plan x)`);
  assert.equal(errorText("de", { message: "boom" }), "boom");
  assert.equal(errorText("de", { translation_key: "unheard_of", message: "boom" }), "boom");
  assert.equal(errorText("de", new Error("plain")), "plain");
});

test("every message code the backend emits has a translation", () => {
  const codes = [
    "same_id", "invalid_id", "domain_change", "not_in_registry", "no_state", "target_exists",
    "renamed_twice", "duplicate_target", "pattern_reference", "file_unreadable", "reload_failed",
    "helper_not_in_plan", "missing_after_apply", "manifest_not_updated", "not_located",
    "found_elsewhere",
  ];
  for (const code of codes) assert.ok(TRANSLATIONS.en[`message.${code}`], code);
  for (const key of [
    "plan_not_found", "plan_blocked", "plan_stale", "plan_expired", "config_check_failed",
    "apply_failed", "unknown_finding", "undo_refused", "invalid_request",
  ]) {
    assert.ok(TRANSLATIONS.en[`error.${key}`], key);
  }
});
