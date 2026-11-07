import pytest

from spotify_dj.config import PROJECT_ROOT, TOKEN_PATH, ConfigError, Settings


def test_defaults_apply_when_only_client_id_is_set():
    settings = Settings.load({"SPOTIFY_CLIENT_ID": "abc"})

    assert settings.client_id == "abc"
    assert settings.queue_depth == 3
    assert settings.poll_seconds == 5.0
    assert settings.redirect_uri == "http://127.0.0.1:8888/callback"


def test_overrides_are_read_from_env():
    settings = Settings.load(
        {"SPOTIFY_CLIENT_ID": "abc", "DJ_QUEUE_DEPTH": "5", "DJ_POLL_SECONDS": "2.5"}
    )

    assert settings.queue_depth == 5
    assert settings.poll_seconds == 2.5


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"SPOTIFY_CLIENT_ID": "  "},
        {"SPOTIFY_CLIENT_ID": "abc", "DJ_QUEUE_DEPTH": "0"},
        {"SPOTIFY_CLIENT_ID": "abc", "DJ_QUEUE_DEPTH": "many"},
        {"SPOTIFY_CLIENT_ID": "abc", "DJ_POLL_SECONDS": "0"},
    ],
)
def test_invalid_settings_raise_config_error(env):
    with pytest.raises(ConfigError):
        Settings.load(env)


def test_runtime_files_live_in_the_project_root():
    assert TOKEN_PATH.parent == PROJECT_ROOT
    assert (PROJECT_ROOT / "pyproject.toml").exists()
