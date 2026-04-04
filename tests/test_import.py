"""Tests for app.py import_ndjson_links and scan_existing_entries.

Covers:
  - import_ndjson_links: directory not found, no matching files, empty files,
    valid NDJSON, malformed lines, non-gleam URLs filtered, files cleared
    after import, multi-file import, backwards compat with old config key
  - scan_existing_entries: eligibility transitions for new giveaways
"""

import json
import os
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Helpers -- import app functions without triggering Streamlit init
# ---------------------------------------------------------------------------
# app.py calls init_db() and st.set_page_config() at module level, which
# requires a running Streamlit context.  We mock streamlit before importing.

@pytest.fixture()
def app_module(monkeypatch, tmp_db, tmp_config):
    """Import app.py with Streamlit mocked out, using temp DB and config."""
    import unittest.mock as mock
    import sys

    # Create a comprehensive Streamlit mock
    st_mock = mock.MagicMock()
    st_mock.cache_data = lambda **kwargs: lambda fn: fn
    monkeypatch.setitem(sys.modules, "streamlit", st_mock)
    monkeypatch.setitem(sys.modules, "pandas", mock.MagicMock())

    # Force re-import of app module with mocks in place
    if "app" in sys.modules:
        del sys.modules["app"]

    import app
    return app


def _write_ndjson(path, entries):
    """Write a list of dicts as NDJSON lines to *path*."""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _setup_import_dir(tmp_path, config_module, filename="gleam-links.ndjson", entries=None):
    """Create a directory with a gleam-links NDJSON file and point config at it.

    Returns the path to the NDJSON file.
    """
    import config as cfg
    from config import load_config, save_config

    ndjson_path = tmp_path / filename
    if entries is not None:
        _write_ndjson(str(ndjson_path), entries)
    else:
        ndjson_path.write_text("")

    config = load_config()
    config["ndjson_import_dir"] = str(tmp_path)
    save_config(config)
    cfg._config_cache = None

    return ndjson_path


# ===========================================================================
# import_ndjson_links
# ===========================================================================

class TestImportNdjsonLinks:
    def test_dir_not_found(self, app_module, tmp_config, tmp_path):
        """Returns 0 and error message when import directory doesn't exist."""
        import config as cfg
        from config import load_config, save_config

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path / "nonexistent_dir")
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 0
        assert "not found" in msg.lower()

    def test_no_matching_files(self, app_module, tmp_config, tmp_path):
        """Returns 0 when directory exists but has no gleam-links*.ndjson files."""
        import config as cfg
        from config import load_config, save_config

        # Create a directory with a non-matching file
        (tmp_path / "other.ndjson").write_text('{"href": "https://gleam.io/a/b"}\n')

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 0
        assert "no gleam-links" in msg.lower()

    def test_empty_file(self, app_module, tmp_config, tmp_path):
        """Returns 0 when matching file exists but is empty."""
        _setup_import_dir(tmp_path, None)

        count, msg = app_module.import_ndjson_links()
        assert count == 0
        assert "empty" in msg.lower()

    def test_valid_gleam_links(self, app_module, tmp_config, tmp_db, tmp_path):
        """Valid gleam.io links are imported into the database."""
        from database import get_giveaways

        entries = [
            {"href": "https://gleam.io/abc/win-stuff", "text": "Win Stuff"},
            {"href": "https://gleam.io/def/win-more", "text": "Win More"},
        ]
        _setup_import_dir(tmp_path, None, entries=entries)

        count, msg = app_module.import_ndjson_links()
        assert count == 2
        assert "2" in msg

        rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
        urls = {r["url"] for r in rows}
        assert "https://gleam.io/abc/win-stuff" in urls
        assert "https://gleam.io/def/win-more" in urls

    def test_non_gleam_urls_filtered(self, app_module, tmp_config, tmp_db, tmp_path):
        """Non-gleam.io URLs should be ignored."""
        from database import get_giveaways

        entries = [
            {"href": "https://gleam.io/abc/win", "text": "Gleam"},
            {"href": "https://example.com/giveaway", "text": "Other"},
            {"href": "https://rafflecopter.com/123", "text": "Raffle"},
        ]
        _setup_import_dir(tmp_path, None, entries=entries)

        count, msg = app_module.import_ndjson_links()
        assert count == 1  # only the gleam.io link

        rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
        assert len(rows) == 1
        assert rows[0]["url"] == "https://gleam.io/abc/win"

    def test_malformed_lines_skipped(self, app_module, tmp_config, tmp_db, tmp_path):
        """Malformed JSON lines should be skipped without error."""
        import config as cfg
        from config import load_config, save_config

        ndjson_path = tmp_path / "gleam-links.ndjson"
        content = (
            '{"href": "https://gleam.io/good/link", "text": "Good"}\n'
            "not valid json at all\n"
            '{"href": "https://gleam.io/also/good", "text": "Also Good"}\n'
        )
        ndjson_path.write_text(content)

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 2

    def test_non_dict_entries_skipped(self, app_module, tmp_config, tmp_db, tmp_path):
        """JSON lines that are not dicts (e.g. arrays, strings) should be skipped."""
        import config as cfg
        from config import load_config, save_config

        ndjson_path = tmp_path / "gleam-links.ndjson"
        content = (
            '["this", "is", "an", "array"]\n'
            '"just a string"\n'
            '42\n'
            '{"href": "https://gleam.io/ok/link", "text": "OK"}\n'
        )
        ndjson_path.write_text(content)

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 1

    def test_file_cleared_after_import(self, app_module, tmp_config, tmp_db, tmp_path):
        """The NDJSON file should be truncated after successful import."""
        ndjson_path = _setup_import_dir(
            tmp_path, None,
            entries=[{"href": "https://gleam.io/x/y", "text": "T"}],
        )

        app_module.import_ndjson_links()

        # File should be empty after import
        assert ndjson_path.read_text() == ""

    def test_text_fallback_when_missing(self, app_module, tmp_config, tmp_db, tmp_path):
        """When 'text' key is missing, href should be used as title."""
        from database import get_giveaways

        _setup_import_dir(
            tmp_path, None,
            entries=[{"href": "https://gleam.io/notitle/test"}],
        )

        app_module.import_ndjson_links()

        rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
        assert rows[0]["title"] == "https://gleam.io/notitle/test"

    def test_blank_lines_ignored(self, app_module, tmp_config, tmp_db, tmp_path):
        """Blank lines in the NDJSON file should be silently skipped."""
        import config as cfg
        from config import load_config, save_config

        ndjson_path = tmp_path / "gleam-links.ndjson"
        content = (
            "\n"
            '{"href": "https://gleam.io/a/b", "text": "A"}\n'
            "\n"
            "\n"
        )
        ndjson_path.write_text(content)

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 1

    def test_source_is_extension(self, app_module, tmp_config, tmp_db, tmp_path):
        """Imported links should have source='extension'."""
        from database import get_giveaways

        _setup_import_dir(
            tmp_path, None,
            entries=[{"href": "https://gleam.io/src/test", "text": "T"}],
        )

        app_module.import_ndjson_links()

        rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
        assert rows[0]["source"] == "extension"


# ===========================================================================
# Multi-file import scenarios
# ===========================================================================

class TestMultiFileImport:
    def test_multiple_files_imported(self, app_module, tmp_config, tmp_db, tmp_path):
        """All gleam-links*.ndjson files in the directory are imported."""
        import config as cfg
        from config import load_config, save_config
        from database import get_giveaways

        _write_ndjson(str(tmp_path / "gleam-links.ndjson"), [
            {"href": "https://gleam.io/aaa/one", "text": "One"},
        ])
        _write_ndjson(str(tmp_path / "gleam-links-extra.ndjson"), [
            {"href": "https://gleam.io/bbb/two", "text": "Two"},
        ])
        _write_ndjson(str(tmp_path / "gleam-links-2024.ndjson"), [
            {"href": "https://gleam.io/ccc/three", "text": "Three"},
        ])

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 3
        assert "3 file(s)" in msg

        rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
        urls = {r["url"] for r in rows}
        assert "https://gleam.io/aaa/one" in urls
        assert "https://gleam.io/bbb/two" in urls
        assert "https://gleam.io/ccc/three" in urls

    def test_browser_duplicate_filename(self, app_module, tmp_config, tmp_db, tmp_path):
        """Files like 'gleam-links (1).ndjson' from browser downloads are found."""
        import config as cfg
        from config import load_config, save_config
        from database import get_giveaways

        _write_ndjson(str(tmp_path / "gleam-links.ndjson"), [
            {"href": "https://gleam.io/aaa/one", "text": "One"},
        ])
        _write_ndjson(str(tmp_path / "gleam-links (1).ndjson"), [
            {"href": "https://gleam.io/bbb/two", "text": "Two"},
        ])
        _write_ndjson(str(tmp_path / "gleam-links (2).ndjson"), [
            {"href": "https://gleam.io/ccc/three", "text": "Three"},
        ])

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 3
        assert "3 file(s)" in msg

    def test_non_matching_files_ignored(self, app_module, tmp_config, tmp_db, tmp_path):
        """Only gleam-links*.ndjson files are imported; other .ndjson files are ignored."""
        import config as cfg
        from config import load_config, save_config
        from database import get_giveaways

        _write_ndjson(str(tmp_path / "gleam-links.ndjson"), [
            {"href": "https://gleam.io/aaa/one", "text": "One"},
        ])
        # These should NOT be picked up
        _write_ndjson(str(tmp_path / "other.ndjson"), [
            {"href": "https://gleam.io/bbb/two", "text": "Two"},
        ])
        _write_ndjson(str(tmp_path / "links.ndjson"), [
            {"href": "https://gleam.io/ccc/three", "text": "Three"},
        ])

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 1
        assert "1 file(s)" in msg

        rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
        assert len(rows) == 1
        assert rows[0]["url"] == "https://gleam.io/aaa/one"

    def test_all_files_cleared_after_import(self, app_module, tmp_config, tmp_db, tmp_path):
        """All matched files should be truncated after import."""
        import config as cfg
        from config import load_config, save_config

        files = []
        for name in ["gleam-links.ndjson", "gleam-links (1).ndjson", "gleam-links-extra.ndjson"]:
            p = tmp_path / name
            _write_ndjson(str(p), [
                {"href": f"https://gleam.io/{name}/link", "text": name},
            ])
            files.append(p)

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        app_module.import_ndjson_links()

        for p in files:
            assert p.read_text() == "", f"{p.name} should be empty after import"

    def test_message_format(self, app_module, tmp_config, tmp_db, tmp_path):
        """Message should include count of new imports, file count, and total."""
        import config as cfg
        from config import load_config, save_config

        _write_ndjson(str(tmp_path / "gleam-links.ndjson"), [
            {"href": "https://gleam.io/aaa/one", "text": "One"},
            {"href": "https://gleam.io/bbb/two", "text": "Two"},
        ])
        _write_ndjson(str(tmp_path / "gleam-links (1).ndjson"), [
            {"href": "https://gleam.io/ccc/three", "text": "Three"},
        ])

        config = load_config()
        config["ndjson_import_dir"] = str(tmp_path)
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 3
        assert "3 new links" in msg
        assert "2 file(s)" in msg
        assert "3 total in files" in msg


# ===========================================================================
# Backwards compatibility: old ndjson_import_path config key
# ===========================================================================

class TestBackwardsCompat:
    def test_old_file_path_uses_parent_dir(self, app_module, tmp_config, tmp_db, tmp_path):
        """Old ndjson_import_path pointing to a file should use its parent directory."""
        import config as cfg
        from config import load_config, save_config
        from database import get_giveaways

        # Create the file the old config would point to
        old_file = tmp_path / "gleam-links.ndjson"
        _write_ndjson(str(old_file), [
            {"href": "https://gleam.io/old/compat", "text": "Old"},
        ])

        config = load_config()
        config["ndjson_import_dir"] = ""  # not set
        config["ndjson_import_path"] = str(old_file)  # old key
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 1

        rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
        assert rows[0]["url"] == "https://gleam.io/old/compat"

    def test_old_dir_path_used_directly(self, app_module, tmp_config, tmp_db, tmp_path):
        """Old ndjson_import_path pointing to a directory should use it directly."""
        import config as cfg
        from config import load_config, save_config

        # Create a matching file in the directory
        _write_ndjson(str(tmp_path / "gleam-links.ndjson"), [
            {"href": "https://gleam.io/dir/test", "text": "Dir"},
        ])

        config = load_config()
        config["ndjson_import_dir"] = ""  # not set
        config["ndjson_import_path"] = str(tmp_path)  # old key pointing to dir
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 1

    def test_new_dir_overrides_old_path(self, app_module, tmp_config, tmp_db, tmp_path):
        """When ndjson_import_dir is set, old ndjson_import_path is ignored."""
        import config as cfg
        from config import load_config, save_config
        from database import get_giveaways

        # Set up two directories
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        old_dir = tmp_path / "old"
        old_dir.mkdir()

        _write_ndjson(str(new_dir / "gleam-links.ndjson"), [
            {"href": "https://gleam.io/new/link", "text": "New"},
        ])
        _write_ndjson(str(old_dir / "gleam-links.ndjson"), [
            {"href": "https://gleam.io/old/link", "text": "Old"},
        ])

        config = load_config()
        config["ndjson_import_dir"] = str(new_dir)
        config["ndjson_import_path"] = str(old_dir / "gleam-links.ndjson")
        save_config(config)
        cfg._config_cache = None

        count, msg = app_module.import_ndjson_links()
        assert count == 1

        rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
        assert rows[0]["url"] == "https://gleam.io/new/link"
