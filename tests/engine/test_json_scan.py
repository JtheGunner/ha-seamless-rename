import copy

import pytest

from custom_components.seamless_rename.engine.json_scan import rewrite_json, scan_json
from custom_components.seamless_rename.engine.models import Confidence

MAPPING = {"sensor.foo": "sensor.bar"}
SAFE = {Confidence.CERTAIN, Confidence.LIKELY}

DASHBOARD = {
    "views": [
        {
            "badges": ["sensor.foo"],
            "header": {"card": {"type": "markdown", "content": "{{ states('sensor.foo') }}"}},
            "cards": [
                {"type": "entity", "entity": "sensor.foo", "tap_action": {"entity": "sensor.foo"}},
                {"type": "entities", "entities": [{"entity": "sensor.foo"}, "light.other"]},
                {"type": "conditional", "conditions": [{"entity": "sensor.foo", "state": "on"}]},
                {"type": "custom:button-card", "variables": {"sensor.foo": 1}},
            ],
            "footer": {"card": {"type": "tile", "entity": "sensor.foo"}},
        }
    ]
}


def test_finds_every_location() -> None:
    findings = scan_json(DASHBOARD, MAPPING, "lovelace")
    paths = {f.json_path for f in findings}
    assert paths == {
        "/views/0/badges/0",
        "/views/0/header/card/content",
        "/views/0/cards/0/entity",
        "/views/0/cards/0/tap_action/entity",
        "/views/0/cards/1/entities/0/entity",
        "/views/0/cards/2/conditions/0/entity",
        "/views/0/cards/3/variables/sensor.foo#key",
        "/views/0/footer/card/entity",
    }


def test_confidence_levels() -> None:
    by_path = {f.json_path: f.confidence for f in scan_json(DASHBOARD, MAPPING, "lovelace")}
    assert by_path["/views/0/cards/0/entity"] is Confidence.CERTAIN
    assert by_path["/views/0/header/card/content"] is Confidence.LIKELY


def test_free_text_is_uncertain_and_not_rewritten_by_default() -> None:
    tree = {"title": "Check sensor.foo daily"}
    findings = scan_json(tree, MAPPING, "x")
    assert [f.confidence for f in findings] == [Confidence.UNCERTAIN]
    assert rewrite_json(tree, findings, SAFE) == tree


def test_no_match_in_suffix_id() -> None:
    assert scan_json({"entity": "sensor.foo_2"}, MAPPING, "x") == []


def test_rewrite_returns_new_tree_input_unchanged() -> None:
    original = copy.deepcopy(DASHBOARD)
    findings = scan_json(DASHBOARD, MAPPING, "lovelace")
    result = rewrite_json(DASHBOARD, findings, SAFE)
    assert original == DASHBOARD
    assert result is not DASHBOARD
    assert scan_json(result, MAPPING, "lovelace") == []
    assert result["views"][0]["cards"][0]["entity"] == "sensor.bar"
    assert "sensor.bar" in result["views"][0]["cards"][3]["variables"]
    assert result["views"][0]["header"]["card"]["content"] == "{{ states('sensor.bar') }}"


def test_two_hits_in_one_string_are_both_rewritten() -> None:
    tree = {"v": "{{ states('sensor.foo') ~ states('sensor.foo') }}"}
    result = rewrite_json(tree, scan_json(tree, MAPPING, "x"), SAFE)
    assert result == {"v": "{{ states('sensor.bar') ~ states('sensor.bar') }}"}


def test_dict_key_collision_raises() -> None:
    tree = {"sensor.foo": 1, "sensor.bar": 2}
    with pytest.raises(ValueError, match="collides"):
        rewrite_json(tree, scan_json(tree, MAPPING, "x"), SAFE)


def test_stale_finding_raises() -> None:
    findings = scan_json({"entity": "sensor.foo"}, MAPPING, "x")
    with pytest.raises(ValueError, match="changed"):
        rewrite_json({"entity": "sensor.zzz"}, findings, SAFE)


def test_pointer_escaping_for_slash_in_key() -> None:
    tree = {"a/b": {"entity": "sensor.foo"}}
    assert [f.json_path for f in scan_json(tree, MAPPING, "x")] == ["/a~1b/entity"]
    assert rewrite_json(tree, scan_json(tree, MAPPING, "x"), SAFE) == {
        "a/b": {"entity": "sensor.bar"}
    }
