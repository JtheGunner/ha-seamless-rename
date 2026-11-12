from pathlib import Path

import pytest

from custom_components.seamless_rename.engine.models import Confidence
from custom_components.seamless_rename.engine.rewrite import apply_edits
from custom_components.seamless_rename.engine.yaml_scan import scan_yaml

FIXTURES = Path(__file__).parent / "fixtures"
SAFE = {Confidence.CERTAIN, Confidence.LIKELY}


def _rewrite(text: str, mapping: dict[str, str], replace=SAFE) -> str:  # type: ignore[no-untyped-def]
    return apply_edits(text, scan_yaml(text, "x.yaml", mapping), replace)


def test_golden_diff_changes_only_planned_spans() -> None:
    original = (FIXTURES / "automations.yaml").read_text()
    expected = (FIXTURES / "automations.expected.yaml").read_text()
    mapping = {
        "media_player.snap_living": "media_player.living_room",
        "sensor.snap_volume_living": "sensor.living_room_volume",
    }
    # Free text inside a block scalar and the comment are uncertain, so they stay unchanged.
    assert _rewrite(original, mapping) == expected


def test_uncertain_not_replaced_by_default_but_replaced_on_request() -> None:
    text = "a: 1  # sensor.foo\n"
    mapping = {"sensor.foo": "sensor.bar"}
    assert _rewrite(text, mapping) == text
    assert _rewrite(text, mapping, {*SAFE, Confidence.UNCERTAIN}) == "a: 1  # sensor.bar\n"


def test_crlf_bom_no_trailing_newline_preserved() -> None:
    text = "﻿a: 1\r\nentity_id: sensor.foo"
    assert _rewrite(text, {"sensor.foo": "sensor.bar"}) == "﻿a: 1\r\nentity_id: sensor.bar"


def test_idempotent_second_run_no_change() -> None:
    mapping = {"sensor.foo": "sensor.bar"}
    once = _rewrite("entity_id: sensor.foo\n", mapping)
    assert _rewrite(once, mapping) == once


def test_single_pass_chain() -> None:
    mapping = {"sensor.a": "sensor.b", "sensor.b": "sensor.c"}
    assert _rewrite("x: sensor.a\ny: sensor.b\n", mapping) == "x: sensor.b\ny: sensor.c\n"


def test_stale_finding_raises() -> None:
    findings = scan_yaml("entity_id: sensor.foo\n", "x.yaml", {"sensor.foo": "sensor.bar"})
    with pytest.raises(ValueError, match="changed"):
        apply_edits("entity_id: sensor.zzz\n", findings, SAFE)


def test_aliased_node_is_replaced_once() -> None:
    text = "base: &base\n  entity_id: sensor.foo\nother:\n  <<: *base\n"
    assert _rewrite(text, {"sensor.foo": "sensor.bar"}) == text.replace("sensor.foo", "sensor.bar")
