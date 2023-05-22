from __future__ import annotations

from typing import Any, Dict

from django.conf import settings

from sentry import features
from sentry.eventstore.models import Event
from sentry.issues.grouptype import GroupCategory
from sentry.utils.safe import get_path, set_path
from sentry.utils.sdk_crashes.cocoa_sdk_crash_detector import CocoaSDKCrashDetector
from sentry.utils.sdk_crashes.event_stripper import EventStripper
from sentry.utils.sdk_crashes.sdk_crash_detector import SDKCrashDetector


class SDKCrashReporter:
    def __init__(self):
        self

    def report(self, event_data: Dict[str, Any], event_project_id: int) -> Event:
        from sentry.event_manager import EventManager

        manager = EventManager(event_data)
        return manager.save(project_id=event_project_id)


class SDKCrashDetection:
    def __init__(
        self,
        sdk_crash_reporter: SDKCrashReporter,
        sdk_crash_detector: SDKCrashDetector,
        event_stripper: EventStripper,
    ):
        self
        self.sdk_crash_reporter = sdk_crash_reporter
        self.cocoa_sdk_crash_detector = sdk_crash_detector
        self.event_stripper = event_stripper

    def detect_sdk_crash(self, event: Event) -> Event:
        if not features.has("organizations:sdk-crash-reporting", event.project.organization):
            return None

        should_detect_sdk_crash = (
            event.group
            and event.group.issue_category == GroupCategory.ERROR
            and event.group.platform == "cocoa"
        )
        if should_detect_sdk_crash is False:
            return

        context = get_path(event.data, "contexts", "sdk_crash_detection")
        if context is not None and context.get("detected", False):
            return None

        is_unhandled = (
            get_path(event.data, "exception", "values", -1, "mechanism", "data", "handled") is False
        )
        if is_unhandled is False:
            return None

        frames = get_path(event.data, "exception", "values", -1, "stacktrace", "frames")
        if not frames:
            return None

        if self.cocoa_sdk_crash_detector.is_sdk_crash(frames):
            sdk_crash_event_data = self.event_stripper.strip_event_data(event)

            set_path(
                sdk_crash_event_data, "contexts", "sdk_crash_detection", value={"detected": True}
            )

            if settings.SDK_CRASH_DETECTION_PROJECT_ID is None:
                return None

            return self.sdk_crash_reporter.report(
                sdk_crash_event_data, settings.SDK_CRASH_DETECTION_PROJECT_ID
            )


_crash_reporter = SDKCrashReporter()
_cocoa_sdk_crash_detector = CocoaSDKCrashDetector()
_event_stripper = EventStripper(sdk_crash_detector=_cocoa_sdk_crash_detector)

sdk_crash_detection = SDKCrashDetection(
    _crash_reporter,
    _cocoa_sdk_crash_detector,
    _event_stripper,
)
