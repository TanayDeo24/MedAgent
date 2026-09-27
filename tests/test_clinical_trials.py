"""Unit tests for ClinicalTrials tool.

Tests cover search functionality, pagination, filtering,
and error handling using mocked API responses.
"""

import pytest
from unittest.mock import Mock, patch
from tools.clinical_trials_tool import ClinicalTrialsTool


@pytest.fixture
def clinical_trials_tool():
    """Create a ClinicalTrials tool instance for testing."""
    return ClinicalTrialsTool()


@pytest.fixture
def mock_study_response():
    """Mock JSON response for clinical trials search."""
    return {
        "studies": [
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT01234567",
                        "officialTitle": "Test Study for Lung Cancer Treatment"
                    },
                    "statusModule": {
                        "overallStatus": "RECRUITING",
                        "startDateStruct": {"date": "2024-01-01"},
                        "completionDateStruct": {"date": "2025-12-31"}
                    },
                    "sponsorCollaboratorsModule": {
                        "leadSponsor": {"name": "Test University"}
                    },
                    "conditionsModule": {
                        "conditions": ["Lung Cancer", "Non-Small Cell Lung Cancer"]
                    },
                    "armsInterventionsModule": {
                        "interventions": [
                            {
                                "type": "Drug",
                                "name": "Pembrolizumab",
                                "description": "Immune checkpoint inhibitor"
                            }
                        ]
                    },
                    "contactsLocationsModule": {
                        "locations": [
                            {
                                "facility": "Test Hospital",
                                "city": "Boston",
                                "country": "United States"
                            }
                        ]
                    },
                    "designModule": {
                        "phases": ["PHASE3"],
                        "enrollmentInfo": {"count": 100}
                    },
                    "descriptionModule": {
                        "briefSummary": "A test study for lung cancer"
                    }
                }
            }
        ],
        "nextPageToken": None
    }


class TestClinicalTrialsToolBasic:
    """Test basic ClinicalTrials tool functionality."""

    def test_tool_initialization(self, clinical_trials_tool):
        """Test that tool initializes correctly."""
        assert clinical_trials_tool.name == "ClinicalTrials"
        assert "clinicaltrials.gov" in clinical_trials_tool.base_url
        assert clinical_trials_tool.rate_limit == 10

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_search_trials_success(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """Test successful clinical trials search."""
        mock_search.return_value = mock_study_response

        result = clinical_trials_tool.search_trials(
            condition="lung cancer",
            status="RECRUITING"
        )

        assert result.success is True
        assert result.data is not None
        assert len(result.data) == 1
        assert result.data[0]["nct_id"] == "NCT01234567"
        assert "Lung Cancer" in result.data[0]["title"]

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_search_trials_with_intervention(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """Test search with intervention filter."""
        mock_search.return_value = mock_study_response

        result = clinical_trials_tool.search_trials(
            condition="lung cancer",
            intervention="pembrolizumab"
        )

        assert result.success is True
        assert len(result.data) == 1
        assert result.data[0]["interventions"][0]["name"] == "Pembrolizumab"

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_search_trials_no_results(self, mock_search, clinical_trials_tool):
        """Test search with no results."""
        mock_search.return_value = {"studies": [], "nextPageToken": None}

        result = clinical_trials_tool.search_trials(condition="nonexistent disease xyz")

        assert result.success is True
        assert result.data == []

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_get_trial_details(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """Test getting details for specific trial."""
        mock_search.return_value = mock_study_response

        result = clinical_trials_tool.get_trial_details("NCT01234567")

        assert result.success is True
        assert len(result.data) >= 1


class TestClinicalTrialsParsing:
    """Test clinical trials result parsing."""

    def test_parse_study_basic(self, clinical_trials_tool, mock_study_response):
        """Test parsing of basic study response."""
        parsed = clinical_trials_tool.parse_results(mock_study_response)

        assert len(parsed) == 1
        study = parsed[0]
        assert study["nct_id"] == "NCT01234567"
        assert study["status"] == "RECRUITING"
        assert study["phase"] == "PHASE3"
        assert len(study["conditions"]) == 2
        assert len(study["interventions"]) == 1
        assert study["sponsor"] == "Test University"

    def test_parse_study_missing_fields(self, clinical_trials_tool):
        """Test parsing with missing fields."""
        minimal_study = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT99999999"
                        }
                    }
                }
            ]
        }

        parsed = clinical_trials_tool.parse_results(minimal_study)
        assert len(parsed) == 1
        assert parsed[0]["nct_id"] == "NCT99999999"


class TestClinicalTrialsPagination:
    """Test pagination functionality."""

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_pagination_single_page(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """Test search with single page of results."""
        mock_search.return_value = mock_study_response

        result = clinical_trials_tool.search_trials(
            condition="test",
            max_results=10
        )

        assert result.success is True
        assert mock_search.call_count == 1

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_pagination_multiple_pages(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """Test search with multiple pages."""
        # First page has next token
        first_page = mock_study_response.copy()
        first_page["nextPageToken"] = "token123"

        # Second page has no next token
        second_page = mock_study_response.copy()
        second_page["nextPageToken"] = None

        mock_search.side_effect = [first_page, second_page]

        result = clinical_trials_tool.search_trials(
            condition="test",
            max_results=200
        )

        assert result.success is True
        # Should fetch both pages
        assert mock_search.call_count == 2


class TestClinicalTrialsFiltering:
    """Test filtering functionality."""

    def test_valid_status_filter(self, clinical_trials_tool):
        """Test that valid status filters are accepted."""
        assert "RECRUITING" in clinical_trials_tool.VALID_STATUSES
        assert "COMPLETED" in clinical_trials_tool.VALID_STATUSES

    def test_valid_phase_filter(self, clinical_trials_tool):
        """Test that valid phase filters are accepted."""
        assert "PHASE1" in clinical_trials_tool.VALID_PHASES
        assert "PHASE3" in clinical_trials_tool.VALID_PHASES

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_phase_filter_uses_area_term_not_filter_phase(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """Regression test: phase filtering must NOT use `filter.phase`.

        ClinicalTrials.gov v2 API has no `filter.phase` query parameter -
        every call using it returns HTTP 400 "`filter.phase` is unknown
        parameter". Phase must instead be expressed as an AREA[Phase]<value>
        term inside `query.term`, matching how condition/intervention/
        sponsor/country are already combined.
        """
        mock_search.return_value = mock_study_response

        result = clinical_trials_tool.search_trials(
            condition="lung cancer",
            phase="PHASE3",
            status="RECRUITING"
        )

        assert result.success is True
        assert mock_search.call_count == 1

        called_params = mock_search.call_args[0][0]

        # The broken parameter must never be sent.
        assert "filter.phase" not in called_params

        # Phase must be embedded as an AREA[Phase] term in query.term,
        # ANDed together with the other AREA terms exactly like
        # condition/intervention/sponsor/country are.
        assert "AREA[Phase]PHASE3" in called_params["query.term"]
        assert "AREA[ConditionSearch]lung cancer" in called_params["query.term"]
        assert " AND " in called_params["query.term"]

        # Status filtering is unaffected and still uses filter.overallStatus.
        assert called_params["filter.overallStatus"] == "RECRUITING"

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_phase_only_filter_query_term(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """Phase-only search (no condition/intervention) still uses AREA[Phase]."""
        mock_search.return_value = mock_study_response

        result = clinical_trials_tool.search_trials(phase="PHASE2", status=None)

        assert result.success is True
        called_params = mock_search.call_args[0][0]

        assert "filter.phase" not in called_params
        assert called_params["query.term"] == "AREA[Phase]PHASE2"
        assert "filter.overallStatus" not in called_params

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_invalid_phase_omitted_from_query(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """An invalid phase value is silently omitted, not sent as filter.phase."""
        mock_search.return_value = mock_study_response

        result = clinical_trials_tool.search_trials(
            condition="lung cancer",
            phase="NOT_A_REAL_PHASE"
        )

        assert result.success is True
        called_params = mock_search.call_args[0][0]

        assert "filter.phase" not in called_params
        assert "AREA[Phase]" not in called_params["query.term"]


class TestClinicalTrialsErrorHandling:
    """Test error handling."""

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_api_error(self, mock_search, clinical_trials_tool):
        """Test handling of API errors."""
        from requests.exceptions import HTTPError

        mock_search.side_effect = HTTPError("API Error")

        result = clinical_trials_tool.search_trials(condition="test")

        assert result.success is False
        assert result.error is not None

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_timeout_error(self, mock_search, clinical_trials_tool):
        """Test handling of timeout errors."""
        from requests.exceptions import Timeout

        mock_search.side_effect = Timeout("Request timeout")

        result = clinical_trials_tool.search_trials(condition="test")

        assert result.success is False
        assert "timed out" in result.error.lower()


class TestClinicalTrialsCaching:
    """Test caching functionality."""

    @patch('tools.clinical_trials_tool.ClinicalTrialsTool._search_trials_page')
    def test_cache_hit(
        self,
        mock_search,
        clinical_trials_tool,
        mock_study_response
    ):
        """Test that identical queries use cache."""
        mock_search.return_value = mock_study_response

        # First call
        result1 = clinical_trials_tool.search_trials(
            condition="lung cancer",
            status="RECRUITING"
        )
        assert result1.success is True
        assert result1.metadata["cached"] is False

        # Second identical call - should use cache
        result2 = clinical_trials_tool.search_trials(
            condition="lung cancer",
            status="RECRUITING"
        )
        assert result2.success is True
        assert result2.metadata["cached"] is True

        # Should only call API once
        assert mock_search.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
