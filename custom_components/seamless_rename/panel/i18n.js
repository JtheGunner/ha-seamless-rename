/**
 * Texts of the Seamless Rename panel.
 *
 * To add a language: add a dictionary below with every key of ``en`` and the same
 * ``{placeholders}``. The panel picks the language of the signed-in Home Assistant user
 * and falls back to English. ``tests/panel/i18n.test.mjs`` checks that nothing is missing.
 */

const en = {
  loading: "Loading…",
  "tab.single": "Single rename",
  "tab.bulk": "Bulk",
  "tab.history": "History",
  "field.from": "Entity to rename",
  "field.to": "New entity ID",
  "field.match": "Match",
  "field.replace": "Replace",
  "field.domain": "Domain (optional)",
  "field.csv": "CSV (from,to per line; overrides the pattern)",
  "bulk.hint": "Use a pattern (regular expression on the entity ID) or paste from,to lines.",
  preview: "Preview",
  apply: "Apply selected changes",
  undo: "Undo",
  "force_undo": "Force undo (overwrite later edits)",
  blocked: "Blocked – this plan cannot be applied:",
  warnings: "Warnings:",
  external: "{count} reference(s) outside the configuration are listed but not changed.",
  full_diff: "Full diff",
  "col.from": "From",
  "col.to": "To",
  "col.when": "When",
  "col.renames": "Renames",
  "col.status": "Status",
  finding: "line {line}: {old} → {new}",
  "result.status": "Status: {status}",
  "result.changed": "Changed {files} file(s), {dashboards} dashboard(s), {helpers} helper(s).",
  "result.restart": "Restart Home Assistant to finish.",
  "history.empty": "No renames recorded yet.",
  "status.completed": "completed",
  "status.undone": "undone",
  "status.rolled_back": "rolled back",
  "confidence.certain": "certain",
  "confidence.likely": "likely",
  "confidence.uncertain": "uncertain",
  "validation.invalid": "Not a valid entity ID (lowercase letters, digits, underscores).",
  "validation.domain": "The domain cannot change.",
  "validation.same": "The new ID equals the old one.",
  "validation.exists": "This entity ID already exists.",
  "message.same_id": "{entity}: the new ID is identical to the old ID.",
  "message.invalid_id": "{entity}: '{target}' is not a valid entity ID.",
  "message.domain_change": "{entity}: the domain cannot change ('{target}').",
  "message.not_in_registry":
    "{entity}: not in the entity registry (a YAML entity without unique_id cannot be renamed automatically).",
  "message.no_state": "{entity}: has no state (disabled or unavailable).",
  "message.target_exists": "{entity}: the target '{target}' already exists.",
  "message.renamed_twice": "{entity}: renamed more than once in the same plan.",
  "message.duplicate_target": "{entity}: is the target of more than one rename.",
  "message.pattern_reference": "{file}: possible pattern reference, check manually ({heuristic}).",
  "message.file_unreadable": "{file}: could not be read and was skipped ({error}).",
  "message.reload_failed": "Reload failed, restart Home Assistant: {error}",
  "message.helper_not_in_plan":
    "Helper {helper} references a renamed entity but was not in the plan; plan again.",
  "message.missing_after_apply": "{entity} is missing from the entity registry after the apply.",
  "message.manifest_not_updated": "The manifest could not be updated: {error}",
  "message.not_located": "{entity} could not be located in the registry; check it.",
  "message.found_elsewhere": "{entity} was found as {current}; it is moved back anyway.",
  "error.plan_not_found": "This plan or backup does not exist.",
  "error.plan_blocked": "The plan has blockers and cannot be applied.",
  "error.plan_stale": "A file changed since the plan was made. Plan again.",
  "error.plan_expired": "The plan is too old. Plan again.",
  "error.config_check_failed": "Home Assistant rejected the changed configuration; the files were restored.",
  "error.apply_failed": "The rename failed and was rolled back.",
  "error.unknown_finding": "The selection contains a finding that is not part of the plan.",
  "error.undo_refused": "The undo was refused.",
  "error.invalid_request": "The request is invalid.",
};

const de = {
  loading: "Lädt…",
  "tab.single": "Einzelumbenennung",
  "tab.bulk": "Sammelumbenennung",
  "tab.history": "Verlauf",
  "field.from": "Zu ändernde Entität",
  "field.to": "Neue Entity-ID",
  "field.match": "Suchmuster",
  "field.replace": "Ersetzen durch",
  "field.domain": "Domain (optional)",
  "field.csv": "CSV (von,nach pro Zeile; hat Vorrang vor dem Muster)",
  "bulk.hint":
    "Verwende ein Muster (regulärer Ausdruck auf die Entity-ID) oder füge Zeilen im Format von,nach ein.",
  preview: "Vorschau",
  apply: "Ausgewählte Änderungen anwenden",
  undo: "Rückgängig",
  "force_undo": "Rückgängig erzwingen (spätere Änderungen überschreiben)",
  blocked: "Blockiert – dieser Plan kann nicht angewendet werden:",
  warnings: "Warnungen:",
  external: "{count} Verweis(e) außerhalb der Konfiguration werden aufgelistet, aber nicht geändert.",
  full_diff: "Vollständiger Diff",
  "col.from": "Von",
  "col.to": "Nach",
  "col.when": "Zeitpunkt",
  "col.renames": "Umbenennungen",
  "col.status": "Status",
  finding: "Zeile {line}: {old} → {new}",
  "result.status": "Status: {status}",
  "result.changed": "Geändert: {files} Datei(en), {dashboards} Dashboard(s), {helpers} Helfer.",
  "result.restart": "Starte Home Assistant neu, um abzuschließen.",
  "history.empty": "Noch keine Umbenennungen aufgezeichnet.",
  "status.completed": "abgeschlossen",
  "status.undone": "rückgängig gemacht",
  "status.rolled_back": "zurückgerollt",
  "confidence.certain": "sicher",
  "confidence.likely": "wahrscheinlich",
  "confidence.uncertain": "unsicher",
  "validation.invalid": "Keine gültige Entity-ID (Kleinbuchstaben, Ziffern, Unterstriche).",
  "validation.domain": "Die Domain kann nicht geändert werden.",
  "validation.same": "Die neue ID entspricht der alten.",
  "validation.exists": "Diese Entity-ID existiert bereits.",
  "message.same_id": "{entity}: Die neue ID ist identisch mit der alten.",
  "message.invalid_id": "{entity}: '{target}' ist keine gültige Entity-ID.",
  "message.domain_change": "{entity}: Die Domain kann nicht geändert werden ('{target}').",
  "message.not_in_registry":
    "{entity}: Nicht in der Entity-Registry (eine YAML-Entität ohne unique_id lässt sich nicht automatisch umbenennen).",
  "message.no_state": "{entity}: Hat keinen Zustand (deaktiviert oder nicht verfügbar).",
  "message.target_exists": "{entity}: Das Ziel '{target}' existiert bereits.",
  "message.renamed_twice": "{entity}: Wird im selben Plan mehrfach umbenannt.",
  "message.duplicate_target": "{entity}: Ist das Ziel von mehr als einer Umbenennung.",
  "message.pattern_reference":
    "{file}: Möglicher Musterverweis, bitte manuell prüfen ({heuristic}).",
  "message.file_unreadable": "{file}: Konnte nicht gelesen werden und wurde übersprungen ({error}).",
  "message.reload_failed": "Neuladen fehlgeschlagen, starte Home Assistant neu: {error}",
  "message.helper_not_in_plan":
    "Helfer {helper} verweist auf eine umbenannte Entität, war aber nicht im Plan; bitte neu planen.",
  "message.missing_after_apply": "{entity} fehlt nach dem Anwenden in der Entity-Registry.",
  "message.manifest_not_updated": "Das Manifest konnte nicht aktualisiert werden: {error}",
  "message.not_located": "{entity} wurde in der Registry nicht gefunden; bitte prüfen.",
  "message.found_elsewhere": "{entity} wurde als {current} gefunden und wird trotzdem zurückgesetzt.",
  "error.plan_not_found": "Dieser Plan oder dieses Backup existiert nicht.",
  "error.plan_blocked": "Der Plan hat Blocker und kann nicht angewendet werden.",
  "error.plan_stale": "Eine Datei hat sich seit der Planung geändert. Bitte neu planen.",
  "error.plan_expired": "Der Plan ist zu alt. Bitte neu planen.",
  "error.config_check_failed":
    "Home Assistant hat die geänderte Konfiguration abgelehnt; die Dateien wurden wiederhergestellt.",
  "error.apply_failed": "Die Umbenennung ist fehlgeschlagen und wurde zurückgerollt.",
  "error.unknown_finding": "Die Auswahl enthält einen Fund, der nicht zum Plan gehört.",
  "error.undo_refused": "Das Rückgängigmachen wurde abgelehnt.",
  "error.invalid_request": "Die Anfrage ist ungültig.",
};

export const TRANSLATIONS = { en, de };

const FALLBACK = "en";

/** Map a Home Assistant language tag such as ``de-CH`` to a supported language. */
export function resolveLanguage(language) {
  const base = String(language ?? "").toLowerCase().split(/[-_]/)[0];
  return Object.hasOwn(TRANSLATIONS, base) ? base : FALLBACK;
}

/** Return the text for ``key``: the language first, then English, then the key itself. */
export function translate(language, key, params = {}) {
  const dictionary = TRANSLATIONS[resolveLanguage(language)];
  const template = dictionary[key] ?? TRANSLATIONS[FALLBACK][key] ?? key;
  return template.replace(/\{(\w+)\}/g, (match, name) => String(params[name] ?? match));
}

/** Text of a backend message: its translation when the code is known, else the English text. */
export function messageText(language, detail, fallback) {
  const key = detail?.code ? `message.${detail.code}` : null;
  if (key === null || !Object.hasOwn(TRANSLATIONS[FALLBACK], key)) return fallback;
  return translate(language, key, detail.params);
}

/** Text of a websocket error: the translated headline plus the original message as detail. */
export function errorText(language, error) {
  const message = error?.message ?? String(error);
  const key = error?.translation_key ? `error.${error.translation_key}` : null;
  if (key === null || !Object.hasOwn(TRANSLATIONS[FALLBACK], key)) return message;
  return `${translate(language, key)} (${message})`;
}
