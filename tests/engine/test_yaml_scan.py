from custom_components.entity_rename_safe.engine.models import Confidence
from custom_components.entity_rename_safe.engine.yaml_scan import scan_yaml

MAPPING = {"sensor.foo": "sensor.bar"}


def _only(text: str, mapping: dict[str, str] = MAPPING):  # type: ignore[no-untyped-def]
    findings = scan_yaml(text, "x.yaml", mapping)
    assert len(findings) == 1, findings
    return findings[0]


def test_certain_exact_scalar() -> None:
    finding = _only("entity_id: sensor.foo\n")
    assert finding.confidence is Confidence.CERTAIN
    assert (finding.old, finding.new, finding.line) == ("sensor.foo", "sensor.bar", 1)


def test_entity_id_comma_list_is_certain() -> None:
    findings = scan_yaml("entity_id: sensor.foo, light.x\n", "x.yaml", MAPPING)
    assert [f.confidence for f in findings] == [Confidence.CERTAIN]


def test_mapping_key_is_found() -> None:
    finding = _only("customize:\n  sensor.foo:\n    icon: mdi:x\n")
    assert finding.confidence is Confidence.CERTAIN
    assert finding.line == 2


def test_quoted_jinja_is_likely() -> None:
    finding = _only("v: \"{{ states('sensor.foo') }}\"\n")
    assert finding.confidence is Confidence.LIKELY


def test_dotted_states_access_in_jinja_is_likely() -> None:
    finding = _only('v: "{{ states.sensor.foo.state }}"\n')
    assert finding.confidence is Confidence.LIKELY


def test_free_text_is_uncertain() -> None:
    finding = _only("message: Playing sensor.foo now\n")
    assert finding.confidence is Confidence.UNCERTAIN


def test_comment_hit_is_uncertain() -> None:
    finding = _only("a: 1  # see sensor.foo\n")
    assert finding.confidence is Confidence.UNCERTAIN


def test_custom_tags_ignored() -> None:
    text = "a: !include other.yaml\nb: !secret token\nc: !input player\nd: sensor.foo\n"
    assert _only(text).line == 4


def test_registry_uuid_ignored() -> None:
    assert scan_yaml("entity_id: 0123456789abcdef0123456789abcdef\n", "x.yaml", MAPPING) == []


def test_no_match_in_suffix_id() -> None:
    assert scan_yaml("entity_id: sensor.foo_2\n", "x.yaml", MAPPING) == []


def test_unparseable_yaml_reports_uncertain_only() -> None:
    findings = scan_yaml("a: [unclosed sensor.foo\n", "x.yaml", MAPPING)
    assert [f.confidence for f in findings] == [Confidence.UNCERTAIN]


def test_offsets_point_at_the_id() -> None:
    text = "x: 1\nentity_id: sensor.foo\n"
    finding = _only(text)
    assert finding.offset is not None and finding.length is not None
    assert text[finding.offset : finding.offset + finding.length] == "sensor.foo"


def test_aliased_node_yields_one_finding() -> None:
    text = "base: &base\n  entity_id: sensor.foo\nother:\n  <<: *base\n"
    assert len(scan_yaml(text, "x.yaml", MAPPING)) == 1


def test_self_referencing_alias_does_not_crash() -> None:
    findings = scan_yaml("a: &x [*x, sensor.foo]\n", "x.yaml", MAPPING)
    assert len(findings) == 1
