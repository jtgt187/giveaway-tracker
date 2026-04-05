"""Tests for utils/ -- probability, country eligibility, region detection.

Covers:
  - calculate_win_probability / format_probability (Win chance column)
  - is_eligible_for_country (Refresh Eligibility button, scan_existing_entries)
  - is_region_blocked (Enter button result handling)
  - is_ended (Enter button result handling)
  - detect_country_restriction (Check T&C button)
"""

import pytest


# ===========================================================================
# Probability  (Win % column in Giveaway table)
# ===========================================================================

class TestCalculateWinProbability:
    def test_normal(self):
        from utils.probability import calculate_win_probability
        assert calculate_win_probability(5, 1000) == pytest.approx(0.5)

    def test_zero_total_entries(self):
        from utils.probability import calculate_win_probability
        assert calculate_win_probability(0, 0) == 0.0

    def test_single_entry(self):
        from utils.probability import calculate_win_probability
        assert calculate_win_probability(1, 100) == pytest.approx(1.0)

    def test_all_entries(self):
        from utils.probability import calculate_win_probability
        assert calculate_win_probability(100, 100) == pytest.approx(100.0)


class TestFormatProbability:
    def test_high_probability(self):
        from utils.probability import format_probability
        assert format_probability(5.5) == "5.5%"

    def test_one_percent(self):
        from utils.probability import format_probability
        assert format_probability(1.0) == "1.0%"

    def test_medium_probability(self):
        from utils.probability import format_probability
        assert format_probability(0.35) == "0.35%"

    def test_low_probability(self):
        from utils.probability import format_probability
        result = format_probability(0.05)
        assert result == "0.0500%"

    def test_zero(self):
        from utils.probability import format_probability
        result = format_probability(0.0)
        assert result == "N/A"

    def test_none(self):
        from utils.probability import format_probability
        result = format_probability(None)
        assert result == "N/A"


# ===========================================================================
# Country Eligibility  (Refresh Eligibility button / scan_existing_entries)
# ===========================================================================

class TestIsEligibleForCountry:
    def test_worldwide_eligible_for_everyone(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("worldwide", "germany") is True
        assert is_eligible_for_country("worldwide", "us") is True
        assert is_eligible_for_country("worldwide", "uk") is True

    def test_restricted_eligible_for_nobody(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("restricted", "germany") is False
        assert is_eligible_for_country("restricted", "us") is False

    def test_exact_match(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("germany", "germany") is True
        assert is_eligible_for_country("us", "us") is True
        assert is_eligible_for_country("uk", "uk") is True

    def test_dach_includes_member_states(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("dach", "germany") is True
        assert is_eligible_for_country("dach", "austria") is True
        assert is_eligible_for_country("dach", "switzerland") is True

    def test_dach_excludes_non_members(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("dach", "france") is False
        assert is_eligible_for_country("dach", "us") is False

    def test_eu_includes_member_states(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("eu", "germany") is True
        assert is_eligible_for_country("eu", "france") is True
        assert is_eligible_for_country("eu", "italy") is True
        assert is_eligible_for_country("eu", "spain") is True

    def test_eu_excludes_non_members(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("eu", "switzerland") is False
        assert is_eligible_for_country("eu", "us") is False
        assert is_eligible_for_country("eu", "uk") is False

    def test_cross_region_not_eligible(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("us", "germany") is False
        assert is_eligible_for_country("uk", "germany") is False
        assert is_eligible_for_country("germany", "us") is False


# ===========================================================================
# Region Blocked Detection  (Enter button -> "region_restricted" result)
# ===========================================================================

class TestIsRegionBlocked:
    def test_positive_exact(self):
        from utils.country_check import is_region_blocked
        assert is_region_blocked(
            "Sorry, this promotion is not available in your region"
        ) is True

    def test_positive_in_page(self):
        from utils.country_check import is_region_blocked
        html = """
        <div class="massive-message">
            <h1>Sorry, this promotion is not available in your region.</h1>
        </div>
        """
        assert is_region_blocked(html) is True

    def test_positive_location_allowed(self):
        from utils.country_check import is_region_blocked
        # Only the negated Angular expression indicates a blocked region;
        # the bare string "location_allowed" also appears when the location IS allowed.
        assert is_region_blocked("!contestantstate.location_allowed") is True
        assert is_region_blocked("location_allowed") is False

    def test_negative_normal_page(self):
        from utils.country_check import is_region_blocked
        assert is_region_blocked("Welcome to this awesome giveaway!") is False

    def test_negative_empty(self):
        from utils.country_check import is_region_blocked
        assert is_region_blocked("") is False


# ===========================================================================
# Ended Detection  (Enter button -> "ended" result)
# ===========================================================================

class TestIsEnded:
    def test_positive_competition(self):
        from utils.country_check import is_ended
        assert is_ended("This competition has ended") is True

    def test_positive_giveaway(self):
        from utils.country_check import is_ended
        assert is_ended("This giveaway has ended. Thanks for participating.") is True

    def test_positive_promotion(self):
        from utils.country_check import is_ended
        assert is_ended("This promotion has ended") is True

    def test_positive_entries_closed(self):
        from utils.country_check import is_ended
        assert is_ended("Entries are now closed") is True

    def test_negative_active(self):
        from utils.country_check import is_ended
        assert is_ended("Enter this giveaway now!") is False

    def test_negative_empty(self):
        from utils.country_check import is_ended
        assert is_ended("") is False


# ===========================================================================
# Country Restriction Detection  (Check T&C button)
# ===========================================================================

class TestDetectCountryRestriction:
    def test_germany(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("Open to German residents only, Germany only.") == "germany"

    def test_dach(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("Open to DACH region participants") == "dach"

    def test_eu(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("EU residents only may participate") == "eu"

    def test_us(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("US only, must be US residents") == "us"

    def test_uk(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("UK only, United Kingdom residents") == "uk"

    def test_worldwide(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("Open worldwide to all participants") == "worldwide"

    def test_restricted_generic(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("This giveaway is restricted to certain regions only") == "restricted"

    def test_no_info_defaults_worldwide(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("No country info here at all") == "worldwide"

    def test_case_insensitive(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("GERMANY ONLY") == "germany"
        assert detect_country_restriction("WORLDWIDE") == "worldwide"

    def test_german_language_nur_deutschland(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("nur deutschland") == "germany"

    def test_german_language_teilnahmeberechtigt(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction(
            "teilnahmeberechtigt sind personen mit wohnsitz in deutschland"
        ) == "germany"

    def test_german_language_dach_region(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction(
            "deutschland, österreich und schweiz"
        ) == "dach"

    def test_german_language_eu(self):
        from utils.country_check import detect_country_restriction
        assert detect_country_restriction("innerhalb der eu") == "eu"

    def test_priority_germany_over_worldwide(self):
        """When text contains both 'germany only' and 'worldwide', germany should win."""
        from utils.country_check import detect_country_restriction
        text = "Germany only. This giveaway is open worldwide."
        assert detect_country_restriction(text) == "germany"

    def test_priority_dach_over_eu(self):
        """DACH should be detected before EU when both are present."""
        from utils.country_check import detect_country_restriction
        text = "Open to DACH region and EU residents"
        assert detect_country_restriction(text) == "dach"


# ===========================================================================
# Additional is_region_blocked tests (more keyword coverage)
# ===========================================================================

class TestIsRegionBlockedExtended:
    def test_angular_template_keyword(self):
        from utils.country_check import is_region_blocked
        assert is_region_blocked("!contestantstate.location_allowed") is True

    def test_not_available_in_country(self):
        from utils.country_check import is_region_blocked
        assert is_region_blocked(
            "promotion is not available in your country"
        ) is True

    def test_partial_match_in_html(self):
        from utils.country_check import is_region_blocked
        html = '<div>This page says: not available in your region</div>'
        assert is_region_blocked(html) is True


# ===========================================================================
# Additional is_ended tests (more keyword coverage)
# ===========================================================================

class TestIsEndedExtended:
    def test_sweepstakes_ended(self):
        from utils.country_check import is_ended
        assert is_ended("This sweepstakes has ended") is True

    def test_contest_ended(self):
        from utils.country_check import is_ended
        assert is_ended("This contest has ended") is True

    def test_campaign_ended(self):
        from utils.country_check import is_ended
        assert is_ended("This campaign has ended") is True

    def test_entry_period_ended(self):
        from utils.country_check import is_ended
        assert is_ended("Entry period has ended") is True

    def test_giveaway_is_over(self):
        from utils.country_check import is_ended
        assert is_ended("This giveaway is over") is True

    def test_contest_is_over(self):
        from utils.country_check import is_ended
        assert is_ended("This contest is over") is True

    def test_case_insensitive(self):
        from utils.country_check import is_ended
        assert is_ended("THIS COMPETITION HAS ENDED") is True
        assert is_ended("This Giveaway Has Ended") is True


# ===========================================================================
# Additional is_eligible_for_country edge cases
# ===========================================================================

class TestIsEligibleExtended:
    def test_austria_eligible_for_dach(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("dach", "austria") is True

    def test_switzerland_eligible_for_dach(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("dach", "switzerland") is True

    def test_france_eligible_for_eu(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("eu", "france") is True

    def test_poland_eligible_for_eu(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("eu", "poland") is True

    def test_unknown_country_not_eligible(self):
        from utils.country_check import is_eligible_for_country
        assert is_eligible_for_country("brazil", "germany") is False

    def test_restricted_eligible_for_nobody_exhaustive(self):
        from utils.country_check import is_eligible_for_country
        for country in ["germany", "austria", "france", "us", "uk", "switzerland"]:
            assert is_eligible_for_country("restricted", country) is False
