from custom_components.seamless_rename.engine.messages import CodedMessage, describe


def test_coded_message_is_a_plain_string_with_code_and_params() -> None:
    message = CodedMessage("no_state", "sensor.a: has no state", entity="sensor.a")
    assert message == "sensor.a: has no state"
    assert isinstance(message, str)
    assert message.code == "no_state"
    assert message.params == {"entity": "sensor.a"}


def test_describe_a_coded_message() -> None:
    message = CodedMessage("no_state", "sensor.a: has no state", entity="sensor.a")
    assert describe(message) == {"code": "no_state", "params": {"entity": "sensor.a"}}


def test_describe_a_plain_string_has_no_code() -> None:
    assert describe("anything") == {"code": None, "params": {}}


def test_deduplication_treats_equal_messages_as_one() -> None:
    first = CodedMessage("a", "same text")
    second = CodedMessage("a", "same text")
    assert list(dict.fromkeys([first, second])) == ["same text"]
