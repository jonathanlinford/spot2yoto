"""Custom exception hierarchy for spot2yoto."""


class Spot2YotoError(Exception):
    """Base exception for all spot2yoto errors."""


class ConfigError(Spot2YotoError):
    """Configuration file missing, invalid, or incomplete."""


class AuthError(Spot2YotoError):
    """Authentication failure (expired tokens, bad credentials, etc.)."""


class YotoAPIError(Spot2YotoError):
    """Yoto API returned an unexpected response."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class SpotifyError(Spot2YotoError):
    """Spotify API or spotdl failure."""


class DownloadError(SpotifyError):
    """spotdl failed to download a track."""


class UploadError(YotoAPIError):
    """Failed to upload audio to Yoto."""


class TranscodeError(YotoAPIError):
    """Yoto transcode polling timed out or failed."""


class SyncError(Spot2YotoError):
    """Error during sync orchestration."""
