import logging

logger = logging.getLogger("spidy.ui.sound")


class SoundAlertEngine:
    """
    Sound alerts disabled per user directive.
    """

    @staticmethod
    def _play_worker(event_type: str):
        pass

    @classmethod
    def trigger(cls, event_type: str):
        pass
