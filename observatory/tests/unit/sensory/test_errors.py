"""ForbiddenTopicError + PublishFailedError shape per spec §4.3-4.4."""
import aiomqtt

from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError


def test_forbidden_topic_error_carries_topic() -> None:
    err = ForbiddenTopicError("hive/cognitive/pfc/oops")
    assert err.topic == "hive/cognitive/pfc/oops"
    assert "hive/cognitive/pfc/oops" in str(err)


def test_publish_failed_wraps_mqtt_error() -> None:
    """Spec §4.3: 'On aiomqtt.MqttError, raises PublishFailedError wrapping the original.'"""
    underlying = aiomqtt.MqttError("connection refused")
    err = PublishFailedError(underlying)
    assert err.cause is underlying
    assert "connection refused" in str(err)
