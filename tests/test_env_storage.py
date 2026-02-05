"""Regression tests for .env persistence.

These tests ensure we preserve:
- Comments and blank lines
- Existing key order
- Unrelated environment variables

And that we handle duplicate keys deterministically.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from strawberry.shared.settings import FieldType, SettingField, SettingsManager
from strawberry.shared.settings.storage import EnvStorage


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for file-based tests."""

    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


class TestEnvStorageSave:
    """Tests for EnvStorage.save()."""

    def test_save_preserves_comments_and_order_and_updates_keys(self, temp_dir: Path) -> None:
        """save() should preserve comments and update only targeted keys."""

        env_path = temp_dir / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "# Header comment",
                    "UNRELATED=keep_me",
                    "",
                    "# Section",
                    "FOO=old",
                    "BAR=keep",
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        storage = EnvStorage(env_path)
        storage.save({"FOO": "new", "BAZ": "added"})

        contents = env_path.read_text(encoding="utf-8").splitlines()

        assert contents[0] == "# Header comment"
        assert contents[1] == "UNRELATED=keep_me"
        assert contents[2] == ""
        assert contents[3] == "# Section"
        assert contents[4] == "FOO=new"
        assert contents[5] == "BAR=keep"
        assert contents[-1] == "BAZ=added"

    def test_save_drops_later_duplicates_keeps_first(self, temp_dir: Path, caplog) -> None:
        """save() should keep the first key and drop later duplicate definitions."""

        env_path = temp_dir / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "FOO=first",
                    "FOO=second",
                    "BAR=keep",
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        storage = EnvStorage(env_path)
        storage.save({"FOO": "updated"})

        contents = env_path.read_text(encoding="utf-8")
        assert contents.splitlines()[0] == "FOO=updated"
        assert "FOO=second" not in contents
        assert "BAR=keep" in contents

        assert "Removed duplicate env keys during save" in caplog.text


class TestSettingsManagerEnvMerge:
    """Tests for SettingsManager.save() interaction with .env."""

    def test_manager_save_merges_env_without_wiping_unrelated(self, temp_dir: Path) -> None:
        """SettingsManager.save() should not wipe unrelated .env entries or comments."""

        env_path = temp_dir / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "# Keep this comment",
                    "UNRELATED=keep_me",
                    "TEST__API_KEY=old_secret",
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        manager = SettingsManager(config_dir=temp_dir)
        manager.register(
            namespace="test",
            display_name="Test",
            schema=[
                SettingField(
                    key="api_key",
                    label="API Key",
                    type=FieldType.PASSWORD,
                    secret=True,
                ),
            ],
        )

        manager.set("test", "api_key", "new_secret")
        manager.save()

        contents = env_path.read_text(encoding="utf-8")
        assert "# Keep this comment" in contents
        assert "UNRELATED=keep_me" in contents
        assert "TEST__API_KEY=new_secret" in contents
