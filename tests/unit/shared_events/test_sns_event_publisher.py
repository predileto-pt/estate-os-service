"""SNS topic-name translation rules — dot→dash mapping."""

import pytest

from shared.events.adapters.sns_event_publisher import SNSEventPublisher


class TestTopicSuffixMapping:
    """AWS SNS topic names permit only [A-Za-z0-9_-]; dots must become dashes."""

    @pytest.mark.parametrize(
        "event_type, expected_suffix",
        [
            ("PROPERTY_CREATED.v1", "PROPERTY_CREATED-v1"),
            ("APPLICANT_SCREENED.v1", "APPLICANT_SCREENED-v1"),
            ("USER_REGISTERED.v1", "USER_REGISTERED-v1"),
            ("PROPERTY_UPDATED.v1", "PROPERTY_UPDATED-v1"),
            ("SOMETHING.v2", "SOMETHING-v2"),
            # No-dot edge case: legacy event types that never gained a suffix
            # would map 1:1. We don't use these today but the mapping must not
            # break them.
            ("NO_VERSION", "NO_VERSION"),
        ],
    )
    def test_translates_dots_to_dashes(self, event_type: str, expected_suffix: str) -> None:
        assert SNSEventPublisher._topic_suffix(event_type) == expected_suffix

    def test_multiple_dots_all_translated(self) -> None:
        # Defensive: if we ever introduce a multi-dot form, every dot maps.
        assert SNSEventPublisher._topic_suffix("FOO.v1.beta") == "FOO-v1-beta"
