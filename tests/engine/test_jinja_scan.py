import pytest

from custom_components.entity_rename_safe.engine.jinja_scan import find_pattern_warnings

OLD = ["sensor.snap_volume_living"]
PREFIX = "possible pattern reference, check manually"


@pytest.mark.parametrize(
    "scalar",
    [
        "{{ states.sensor | selectattr('entity_id', 'search', 'snap') | list }}",
        '{{ states | selectattr("entity_id", "match", "sensor.snap") | list }}',
        "{{ states.sensor | selectattr('object_id', 'startswith', 'snap') | list }}",
        "{% if entity.entity_id.startswith('sensor.snap') %}x{% endif %}",
        "{{ states.sensor | map(attribute='state') | list }}",
        "{{ states('sensor.' ~ room ~ '_volume') }}",
    ],
)
def test_dynamic_constructs_warn(scalar: str) -> None:
    warnings = find_pattern_warnings(scalar, OLD)
    assert warnings
    assert all(w.startswith(PREFIX) for w in warnings)


def test_fragment_of_object_id_in_literal_warns() -> None:
    assert find_pattern_warnings("{{ states('sensor.' ~ 'snap_volume') }}", OLD)


def test_literal_with_full_old_id_is_not_a_pattern_reference() -> None:
    assert find_pattern_warnings("{{ states('sensor.snap_volume_living') }}", OLD) == []


@pytest.mark.parametrize(
    "scalar",
    [
        "{{ states('sensor.other') }}",
        "{{ states('sensor.other') | float > 5 }}",
        "{{ states.sensor.other.state }}",
        "{{ state_attr('sensor.other', 'snap') }}",
        "plain text without jinja snap_volume",
    ],
)
def test_plain_references_do_not_warn(scalar: str) -> None:
    assert find_pattern_warnings(scalar, OLD) == []


def test_short_fragment_no_warning() -> None:
    assert find_pattern_warnings("{{ 'snap_' ~ x }}", ["sensor.snap_volume_living"]) == []


def test_fragment_in_double_quoted_literal_warns() -> None:
    assert find_pattern_warnings('{{ states("sensor." ~ "snap_volume") }}', OLD)
