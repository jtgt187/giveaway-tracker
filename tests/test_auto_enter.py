"""Tests for entry/auto_enter.py -- pure function logic (no browser needed).

Covers:
  - _detect_excluded_countries (T&C exclusion scanning)
  - _detect_included_region (T&C inclusion scanning)
  - analyze_terms_text (combined analysis)
  - find_browser_profile (profile path detection)
"""

import os

import pytest


# ===========================================================================
# _detect_excluded_countries
# ===========================================================================

class TestDetectExcludedCountries:
    def test_no_exclusion_keywords(self):
        from entry.auto_enter import _detect_excluded_countries
        assert _detect_excluded_countries("welcome to our giveaway") == []

    def test_empty_string(self):
        from entry.auto_enter import _detect_excluded_countries
        assert _detect_excluded_countries("") == []

    def test_exclusion_with_us(self):
        from entry.auto_enter import _detect_excluded_countries
        text = "this giveaway is not eligible in the united states"
        result = _detect_excluded_countries(text)
        assert "us" in result

    def test_exclusion_with_uk(self):
        from entry.auto_enter import _detect_excluded_countries
        text = "void in united kingdom and excluded countries include england"
        result = _detect_excluded_countries(text)
        assert "uk" in result

    def test_exclusion_with_multiple_countries(self):
        from entry.auto_enter import _detect_excluded_countries
        text = "not eligible in the united states, canada, and australia"
        result = _detect_excluded_countries(text)
        assert "us" in result
        assert "canada" in result
        assert "australia" in result

    def test_exclusion_keyword_without_country_returns_empty(self):
        from entry.auto_enter import _detect_excluded_countries
        # Has the trigger phrase but no recognizable country
        text = "not eligible in the moon"
        result = _detect_excluded_countries(text)
        assert result == []

    def test_exclusion_void_where_prohibited(self):
        from entry.auto_enter import _detect_excluded_countries
        text = "void where prohibited. excluded countries: france, spain, italy"
        result = _detect_excluded_countries(text)
        assert "france" in result
        assert "spain" in result
        assert "italy" in result

    def test_exclusion_germany(self):
        from entry.auto_enter import _detect_excluded_countries
        text = "not available in germany and deutschland residents are excluded"
        result = _detect_excluded_countries(text)
        assert "germany" in result

    def test_no_duplicates(self):
        from entry.auto_enter import _detect_excluded_countries
        # "usa" and "united states" both match "us"
        text = "not eligible in usa and united states residents"
        result = _detect_excluded_countries(text)
        assert result.count("us") == 1

    def test_exclusion_with_excluding_keyword(self):
        from entry.auto_enter import _detect_excluded_countries
        text = "excluding japan and brazil from participation"
        result = _detect_excluded_countries(text)
        assert "japan" in result
        assert "brazil" in result


# ===========================================================================
# _detect_included_region
# ===========================================================================

class TestDetectIncludedRegion:
    def test_no_inclusion_keywords(self):
        from entry.auto_enter import _detect_included_region
        assert _detect_included_region("welcome to our giveaway") is None

    def test_empty_string(self):
        from entry.auto_enter import _detect_included_region
        assert _detect_included_region("") is None

    def test_worldwide(self):
        from entry.auto_enter import _detect_included_region
        text = "this giveaway is open worldwide to all participants"
        assert _detect_included_region(text) == "worldwide"

    def test_eu_region(self):
        from entry.auto_enter import _detect_included_region
        text = "open to residents of european union member countries"
        assert _detect_included_region(text) == "eu"

    def test_dach_explicit(self):
        from entry.auto_enter import _detect_included_region
        text = "only open to residents of the dach region"
        assert _detect_included_region(text) == "dach"

    def test_dach_from_individual_countries(self):
        from entry.auto_enter import _detect_included_region
        text = "open to residents of germany, austria and switzerland"
        assert _detect_included_region(text) == "dach"

    def test_dach_from_germany_austria(self):
        from entry.auto_enter import _detect_included_region
        # Germany + Austria without Switzerland should still return "dach"
        text = "must be a resident of germany or austria"
        assert _detect_included_region(text) == "dach"

    def test_germany_only(self):
        from entry.auto_enter import _detect_included_region
        text = "only open to legal residents of germany"
        assert _detect_included_region(text) == "germany"

    def test_restricted_no_germany(self):
        from entry.auto_enter import _detect_included_region
        # Inclusion phrase found but Germany not mentioned
        text = "only open to residents of canada"
        assert _detect_included_region(text) == "restricted"

    def test_german_language_inclusion(self):
        from entry.auto_enter import _detect_included_region
        text = "teilnahmeberechtigt sind personen mit wohnsitz in deutschland"
        assert _detect_included_region(text) == "germany"

    def test_german_language_dach(self):
        from entry.auto_enter import _detect_included_region
        text = "nur offen für bewohner von deutschland, österreich und schweiz"
        assert _detect_included_region(text) == "dach"

    def test_sweepstakes_open_to_worldwide(self):
        from entry.auto_enter import _detect_included_region
        text = "sweepstakes is open to all countries worldwide"
        assert _detect_included_region(text) == "worldwide"

    def test_eea_detected_as_eu(self):
        from entry.auto_enter import _detect_included_region
        text = "open to residents of the european economic area"
        assert _detect_included_region(text) == "eu"


# ===========================================================================
# analyze_terms_text (combined)
# ===========================================================================

class TestAnalyzeTermsText:
    def test_no_restrictions(self):
        from entry.auto_enter import analyze_terms_text
        excluded, region = analyze_terms_text("welcome to our fun giveaway")
        assert excluded == []
        assert region is None

    def test_empty_text(self):
        from entry.auto_enter import analyze_terms_text
        excluded, region = analyze_terms_text("")
        assert excluded == []
        assert region is None

    def test_excluded_countries_only(self):
        from entry.auto_enter import analyze_terms_text
        text = "void in the united states and canada"
        excluded, region = analyze_terms_text(text)
        assert "us" in excluded
        assert "canada" in excluded
        assert region is None

    def test_included_region_only(self):
        from entry.auto_enter import analyze_terms_text
        text = "this giveaway is open worldwide"
        excluded, region = analyze_terms_text(text)
        assert excluded == []
        assert region == "worldwide"

    def test_both_excluded_and_included(self):
        from entry.auto_enter import analyze_terms_text
        text = (
            "this giveaway is open worldwide. "
            "void in the united states and excluded countries include japan."
        )
        excluded, region = analyze_terms_text(text)
        assert "us" in excluded
        assert "japan" in excluded
        assert region == "worldwide"

    def test_germany_inclusion_with_exclusions(self):
        from entry.auto_enter import analyze_terms_text
        text = (
            "only open to legal residents of germany. "
            "not eligible in the united states."
        )
        excluded, region = analyze_terms_text(text)
        assert "us" in excluded
        assert region == "germany"


# ===========================================================================
# find_browser_profile
# ===========================================================================

class TestFindBrowserProfile:
    def test_no_profile_found(self, monkeypatch):
        from entry.auto_enter import find_browser_profile
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        assert find_browser_profile() == (None, None)

    def test_chrome_profile_found_unix(self, monkeypatch):
        import platform
        from entry.auto_enter import find_browser_profile
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        chrome_path = os.path.expanduser("~/.config/google-chrome")
        monkeypatch.setattr(os.path, "exists", lambda p: p == chrome_path)
        result = find_browser_profile()
        assert result == (chrome_path, "chrome")

    def test_chrome_profile_found_macos(self, monkeypatch):
        import platform
        from entry.auto_enter import find_browser_profile
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        chrome_path = os.path.expanduser("~/Library/Application Support/Google/Chrome")
        monkeypatch.setattr(os.path, "exists", lambda p: p == chrome_path)
        result = find_browser_profile()
        assert result == (chrome_path, "chrome")
