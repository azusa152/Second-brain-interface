"""Unit tests for HashRegistry: hash comparison, persistence, and incremental diff logic."""

import json
import os
import shutil
import tempfile

import pytest

from backend.infrastructure.hash_registry import HashRegistry, compute_sha256


@pytest.fixture()
def data_dir():
    """Temporary directory acting as the /data volume."""
    d = tempfile.mkdtemp(prefix="test_hash_registry_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestComputeSha256:
    def test_deterministic_for_same_content(self) -> None:
        assert compute_sha256("hello") == compute_sha256("hello")

    def test_different_for_different_content(self) -> None:
        assert compute_sha256("hello") != compute_sha256("world")

    def test_returns_64_char_hex_string(self) -> None:
        result = compute_sha256("test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestHashRegistryInit:
    def test_starts_empty_when_no_file_exists(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        assert reg.get_all_known_paths() == set()

    def test_loads_existing_registry_from_disk(self, data_dir: str) -> None:
        registry_path = os.path.join(data_dir, "hash_registry.json")
        with open(registry_path, "w") as f:
            json.dump({"notes/a.md": "abc123", "notes/b.md": "def456"}, f)

        reg = HashRegistry(data_dir)
        assert reg.get_hash("notes/a.md") == "abc123"
        assert reg.get_hash("notes/b.md") == "def456"

    def test_recovers_gracefully_from_corrupt_file(self, data_dir: str) -> None:
        registry_path = os.path.join(data_dir, "hash_registry.json")
        with open(registry_path, "w") as f:
            f.write("not valid json {{{{")

        reg = HashRegistry(data_dir)
        assert reg.get_all_known_paths() == set()

    def test_recovers_gracefully_from_wrong_type(self, data_dir: str) -> None:
        registry_path = os.path.join(data_dir, "hash_registry.json")
        with open(registry_path, "w") as f:
            json.dump(["list", "not", "dict"], f)

        reg = HashRegistry(data_dir)
        assert reg.get_all_known_paths() == set()


class TestHashRegistryMutations:
    def test_set_hash_stores_in_memory(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        reg.set_hash("notes/a.md", "aabbcc")
        assert reg.get_hash("notes/a.md") == "aabbcc"

    def test_get_hash_returns_none_for_unknown_path(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        assert reg.get_hash("unknown.md") is None

    def test_remove_deletes_path_from_memory(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        reg.set_hash("notes/a.md", "aabbcc")
        reg.remove("notes/a.md")
        assert reg.get_hash("notes/a.md") is None
        assert "notes/a.md" not in reg.get_all_known_paths()

    def test_remove_is_idempotent_for_unknown_path(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        reg.remove("does_not_exist.md")  # Should not raise

    def test_get_all_known_paths_returns_copy(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        reg.set_hash("a.md", "h1")
        reg.set_hash("b.md", "h2")
        paths = reg.get_all_known_paths()
        assert paths == {"a.md", "b.md"}


class TestHashRegistrySave:
    def test_save_persists_to_json_file(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        reg.set_hash("notes/a.md", "hash1")
        reg.save()

        registry_path = os.path.join(data_dir, "hash_registry.json")
        assert os.path.exists(registry_path)
        with open(registry_path) as f:
            data = json.load(f)
        assert data["notes/a.md"] == "hash1"

    def test_mutations_not_visible_before_save(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        reg.set_hash("notes/a.md", "hash1")

        registry_path = os.path.join(data_dir, "hash_registry.json")
        assert not os.path.exists(registry_path)

    def test_reloaded_registry_reflects_saved_state(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        reg.set_hash("a.md", "h1")
        reg.set_hash("b.md", "h2")
        reg.remove("b.md")
        reg.save()

        reg2 = HashRegistry(data_dir)
        assert reg2.get_hash("a.md") == "h1"
        assert reg2.get_hash("b.md") is None

    def test_save_uses_atomic_rename(self, data_dir: str) -> None:
        reg = HashRegistry(data_dir)
        reg.set_hash("a.md", "h1")
        reg.save()

        tmp_path = os.path.join(data_dir, "hash_registry.json.tmp")
        assert not os.path.exists(tmp_path), "Temp file should have been renamed"


class TestIncrementalRebuildDiffLogic:
    """Verify the diff logic used by IndexService.incremental_rebuild()."""

    def test_detect_new_file(self, data_dir: str) -> None:
        """A file not in the registry is considered new (hash will differ)."""
        reg = HashRegistry(data_dir)
        assert reg.get_hash("new_note.md") is None

    def test_detect_changed_file(self, data_dir: str) -> None:
        """A file whose hash differs from the stored one is considered changed."""
        reg = HashRegistry(data_dir)
        reg.set_hash("note.md", "old_hash")

        new_hash = compute_sha256("updated content")
        assert reg.get_hash("note.md") != new_hash

    def test_detect_unchanged_file(self, data_dir: str) -> None:
        """A file whose hash matches the stored value is unchanged."""
        content = "# My Note\n\nSome content."
        current_hash = compute_sha256(content)

        reg = HashRegistry(data_dir)
        reg.set_hash("note.md", current_hash)

        assert reg.get_hash("note.md") == compute_sha256(content)

    def test_detect_deleted_files(self, data_dir: str) -> None:
        """Files in registry but absent from vault should be removed."""
        reg = HashRegistry(data_dir)
        reg.set_hash("alive.md", "h1")
        reg.set_hash("deleted.md", "h2")

        vault_paths = {"alive.md"}
        stale = reg.get_all_known_paths() - vault_paths
        assert stale == {"deleted.md"}
