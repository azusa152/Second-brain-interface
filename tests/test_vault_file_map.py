import os
from pathlib import Path

import pytest

from backend.infrastructure.vault_file_map import VaultFileMap
from backend.logging_config import setup_logging

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "test_vault")


class TestVaultFileMapScan:
    def test_scan_should_find_all_md_files(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        assert file_map.file_count == 5

    def test_scan_should_clear_previous_entries(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()
        file_map.scan()

        assert file_map.file_count == 5


class TestVaultFileMapResolve:
    def test_resolve_should_find_root_level_file(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        result = file_map.resolve("note1")
        assert result == "note1.md"

    def test_resolve_should_find_nested_file(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        result = file_map.resolve("architecture")
        assert result == os.path.join("concepts", "architecture.md")

    def test_resolve_should_find_file_in_projects(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        result = file_map.resolve("migration")
        assert result == os.path.join("projects", "migration.md")

    def test_resolve_should_be_case_insensitive(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        assert file_map.resolve("Architecture") is not None
        assert file_map.resolve("ARCHITECTURE") is not None

    def test_resolve_should_return_none_for_missing_file(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        assert file_map.resolve("nonexistent") is None

    def test_resolve_should_strip_heading_anchors(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        result = file_map.resolve("architecture#layers")
        assert result == os.path.join("concepts", "architecture.md")


class TestVaultFileMapUpdate:
    def test_update_file_should_add_new_entry(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        file_map.update_file(None, "new-note.md")
        assert file_map.resolve("new-note") == "new-note.md"

    def test_update_file_should_handle_rename(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        file_map.update_file("note1.md", "renamed-note.md")
        assert file_map.resolve("note1") is None
        assert file_map.resolve("renamed-note") == "renamed-note.md"

    def test_remove_file_should_delete_entry(self) -> None:
        file_map = VaultFileMap(FIXTURES_DIR)
        file_map.scan()

        file_map.remove_file("note1.md")
        assert file_map.resolve("note1") is None
        assert file_map.file_count == 4


class TestVaultFileMapCollisionLogging:
    @pytest.fixture()
    def collision_vault(self, tmp_path: Path) -> Path:
        """Vault with two files sharing the same stem (duplicate.md in root and sub/)."""
        (tmp_path / "duplicate.md").write_text("root")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "duplicate.md").write_text("nested")
        return tmp_path

    def test_scan_should_log_collision_summary_at_info_when_collisions_exist(
        self, collision_vault: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        setup_logging(log_level="INFO", json_output=False)
        file_map = VaultFileMap(str(collision_vault))

        # Act
        file_map.scan()
        captured = capsys.readouterr()

        # Assert — summary appears at INFO, includes the count
        assert "1 name collisions" in captured.out
        assert "LOG_LEVEL=DEBUG" in captured.out

    def test_scan_should_not_log_individual_collisions_at_info_level(
        self, collision_vault: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        setup_logging(log_level="INFO", json_output=False)
        file_map = VaultFileMap(str(collision_vault))

        # Act
        file_map.scan()
        captured = capsys.readouterr()

        # Assert — individual path detail is suppressed at INFO
        assert "resolves to both" not in captured.out

    def test_scan_should_log_individual_collisions_at_debug_level(
        self, collision_vault: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        setup_logging(log_level="DEBUG", json_output=False)
        file_map = VaultFileMap(str(collision_vault))

        # Act
        file_map.scan()
        captured = capsys.readouterr()

        # Assert — individual path detail surfaces at DEBUG
        assert "resolves to both" in captured.out

    def test_scan_should_log_simple_message_when_no_collisions(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        setup_logging(log_level="INFO", json_output=False)
        file_map = VaultFileMap(FIXTURES_DIR)

        # Act
        file_map.scan()
        captured = capsys.readouterr()

        # Assert — no collision count in simple message
        assert "name collisions" not in captured.out
        assert "scanned 5 files" in captured.out
