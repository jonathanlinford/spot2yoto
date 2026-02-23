"""Tests for the exception hierarchy."""

from spot2yoto.exceptions import (
    AuthError,
    ConfigError,
    DownloadError,
    SpotifyError,
    Spot2YotoError,
    SyncError,
    TranscodeError,
    UploadError,
    YotoAPIError,
)


def test_base_exception():
    err = Spot2YotoError("base")
    assert str(err) == "base"
    assert isinstance(err, Exception)


def test_config_error_inherits():
    err = ConfigError("bad config")
    assert isinstance(err, Spot2YotoError)


def test_auth_error_inherits():
    assert isinstance(AuthError("auth"), Spot2YotoError)


def test_yoto_api_error_status_code():
    err = YotoAPIError("not found", status_code=404)
    assert err.status_code == 404
    assert "not found" in str(err)


def test_yoto_api_error_no_status():
    err = YotoAPIError("timeout")
    assert err.status_code is None


def test_upload_error_inherits_yoto():
    err = UploadError("upload failed", status_code=500)
    assert isinstance(err, YotoAPIError)
    assert isinstance(err, Spot2YotoError)
    assert err.status_code == 500


def test_transcode_error_inherits_yoto():
    err = TranscodeError("transcode timeout", status_code=None)
    assert isinstance(err, YotoAPIError)


def test_spotify_error_inherits():
    assert isinstance(SpotifyError("sp"), Spot2YotoError)


def test_download_error_inherits_spotify():
    err = DownloadError("yt-dlp failed")
    assert isinstance(err, SpotifyError)
    assert isinstance(err, Spot2YotoError)


def test_sync_error_inherits():
    assert isinstance(SyncError("sync"), Spot2YotoError)


def test_catch_base_catches_all():
    """All specific errors should be catchable via Spot2YotoError."""
    errors = [
        ConfigError("c"),
        AuthError("a"),
        YotoAPIError("y", 400),
        UploadError("u", 500),
        TranscodeError("t", None),
        SpotifyError("s"),
        DownloadError("d"),
        SyncError("x"),
    ]
    for err in errors:
        try:
            raise err
        except Spot2YotoError:
            pass  # expected
