from custom_components.entity_rename_safe.engine.classify import classify
from custom_components.entity_rename_safe.engine.models import Confidence


def test_quoted_literal_in_query_is_likely() -> None:
    value = "SELECT state FROM states WHERE entity_id = 'sensor.foo' LIMIT 1"
    assert classify(value, "sensor.foo", "query", jinja=False) is Confidence.LIKELY


def test_unquoted_mention_in_query_stays_uncertain() -> None:
    assert classify("-- sensor.foo", "sensor.foo", "query", jinja=False) is Confidence.UNCERTAIN


def test_quoted_literal_under_another_key_stays_uncertain() -> None:
    assert classify("note 'sensor.foo'", "sensor.foo", "name", jinja=False) is Confidence.UNCERTAIN


def test_exact_value_and_entity_id_lists_stay_certain() -> None:
    assert classify("sensor.foo", "sensor.foo", None, jinja=False) is Confidence.CERTAIN
    assert classify("a.b, sensor.foo", "sensor.foo", "entity_id", jinja=False) is Confidence.CERTAIN
