"""Unit tests for ChEMBL tool.

Tests cover target search, molecule search, indication search,
and error handling using mocked API responses.
"""

import pytest
from unittest.mock import Mock, patch
from tools.chembl_tool import ChEMBLTool


@pytest.fixture
def chembl_tool():
    """Create a ChEMBL tool instance for testing."""
    return ChEMBLTool()


@pytest.fixture
def mock_target_response():
    """Mock JSON response for target search."""
    return {
        "targets": [
            {
                "target_chembl_id": "CHEMBL203",
                "target_type": "SINGLE PROTEIN",
                "organism": "Homo sapiens",
                "pref_name": "Epidermal growth factor receptor",
                "target_components": []
            }
        ]
    }


@pytest.fixture
def mock_molecule_response():
    """Mock JSON response for molecule search."""
    return {
        "molecules": [
            {
                "molecule_chembl_id": "CHEMBL941",
                "pref_name": "Gefitinib",
                "molecule_type": "Small molecule",
                "max_phase": 4,
                "molecule_properties": {
                    "full_mwt": 446.9,
                    "alogp": 4.15
                },
                "molecule_mechanisms": [
                    {
                        "mechanism_of_action": "Epidermal growth factor receptor inhibitor",
                        "target_name": "Epidermal growth factor receptor"
                    }
                ]
            }
        ]
    }


@pytest.fixture
def mock_drug_indication_response():
    """Mock JSON response for drug indication search."""
    return {
        "drug_indications": [
            {
                "molecule_chembl_id": "CHEMBL941",
                "parent_molecule_name": "GEFITINIB",
                "mesh_heading": "Carcinoma, Non-Small-Cell Lung",
                "max_phase_for_ind": 4,
                "efo_term": "non-small cell lung carcinoma"
            }
        ]
    }


class TestChEMBLToolBasic:
    """Test basic ChEMBL tool functionality."""

    def test_tool_initialization(self, chembl_tool):
        """Test that tool initializes correctly."""
        assert chembl_tool.name == "ChEMBL"
        assert "ebi.ac.uk/chembl" in chembl_tool.base_url
        assert chembl_tool.rate_limit == 10

    @patch('tools.chembl_tool.ChEMBLTool._search_targets')
    @patch('tools.chembl_tool.ChEMBLTool._search_molecules')
    def test_search_by_target_success(
        self,
        mock_search_molecules,
        mock_search_targets,
        chembl_tool,
        mock_target_response,
        mock_molecule_response
    ):
        """Test successful target-based search."""
        mock_search_targets.return_value = mock_target_response
        mock_search_molecules.return_value = mock_molecule_response

        result = chembl_tool.search_by_target("EGFR", max_results=5)

        assert result.success is True
        assert result.data is not None
        assert len(result.data) == 1
        assert result.data[0]["chembl_id"] == "CHEMBL941"
        assert result.data[0]["name"] == "Gefitinib"

    @patch('tools.chembl_tool.ChEMBLTool._search_targets')
    def test_search_by_target_no_results(self, mock_search, chembl_tool):
        """Test target search with no results."""
        mock_search.return_value = {"targets": []}

        result = chembl_tool.search_by_target("nonexistent_target_xyz")

        assert result.success is True
        assert result.data == []

    @patch('tools.chembl_tool.ChEMBLTool._get_molecule_details')
    def test_get_drug_info_success(
        self,
        mock_get_molecule,
        chembl_tool,
        mock_molecule_response
    ):
        """Test getting drug information."""
        mock_get_molecule.return_value = mock_molecule_response["molecules"][0]

        result = chembl_tool.get_drug_info("CHEMBL941")

        assert result.success is True
        assert result.data["chembl_id"] == "CHEMBL941"
        assert result.data["name"] == "Gefitinib"
        assert result.data["development_phase"] == "Approved"

    @patch('tools.chembl_tool.ChEMBLTool._search_by_indication')
    def test_search_by_indication_success(
        self,
        mock_search,
        chembl_tool,
        mock_drug_indication_response
    ):
        """Test searching by disease indication."""
        mock_search.return_value = mock_drug_indication_response

        result = chembl_tool.search_by_indication("lung cancer", max_results=10)

        assert result.success is True
        assert len(result.data) == 1
        assert result.data[0]["drug_name"] == "GEFITINIB"
        assert "Lung" in result.data[0]["indication"]


class TestChEMBLParsing:
    """Test ChEMBL result parsing."""

    def test_parse_target(self, chembl_tool, mock_target_response):
        """Test parsing of target response."""
        parsed = chembl_tool.parse_results(mock_target_response)

        assert len(parsed) == 1
        target = parsed[0]
        assert target["target_chembl_id"] == "CHEMBL203"
        assert target["pref_name"] == "Epidermal growth factor receptor"
        assert target["organism"] == "Homo sapiens"

    def test_parse_molecule(self, chembl_tool, mock_molecule_response):
        """Test parsing of molecule response."""
        parsed = chembl_tool.parse_results(mock_molecule_response)

        assert len(parsed) == 1
        molecule = parsed[0]
        assert molecule["chembl_id"] == "CHEMBL941"
        assert molecule["name"] == "Gefitinib"
        assert molecule["molecular_weight"] == 446.9
        assert molecule["development_phase"] == "Approved"
        assert molecule["max_phase"] == 4

    def test_parse_drug_indication(self, chembl_tool, mock_drug_indication_response):
        """Test parsing of drug indication response."""
        parsed = chembl_tool.parse_results(mock_drug_indication_response)

        assert len(parsed) == 1
        indication = parsed[0]
        assert indication["chembl_id"] == "CHEMBL941"
        assert indication["drug_name"] == "GEFITINIB"
        assert indication["indication"] == "Carcinoma, Non-Small-Cell Lung"

    def test_parse_empty_results(self, chembl_tool):
        """Test parsing of empty results."""
        empty_response = {"molecules": []}
        parsed = chembl_tool.parse_results(empty_response)
        assert parsed == []


class TestChEMBLPhaseMapping:
    """Test development phase mapping."""

    def test_phase_mapping(self, chembl_tool):
        """Test that max_phase maps to correct development phase."""
        phase_tests = [
            ({"max_phase": 0, "molecule_chembl_id": "TEST"}, "Preclinical"),
            ({"max_phase": 1, "molecule_chembl_id": "TEST"}, "Phase 1"),
            ({"max_phase": 2, "molecule_chembl_id": "TEST"}, "Phase 2"),
            ({"max_phase": 3, "molecule_chembl_id": "TEST"}, "Phase 3"),
            ({"max_phase": 4, "molecule_chembl_id": "TEST"}, "Approved"),
        ]

        for molecule_data, expected_phase in phase_tests:
            # Add required fields
            molecule_data.update({
                "molecule_properties": {},
                "molecule_mechanisms": []
            })
            parsed = chembl_tool._parse_molecule(molecule_data)
            assert parsed["development_phase"] == expected_phase


class TestChEMBLErrorHandling:
    """Test error handling."""

    @patch('tools.chembl_tool.ChEMBLTool._search_targets')
    def test_connection_error(self, mock_search, chembl_tool):
        """Test handling of connection errors."""
        from requests.exceptions import ConnectionError

        mock_search.side_effect = ConnectionError("Network error")

        result = chembl_tool.search_by_target("EGFR")

        assert result.success is False
        assert "connect" in result.error.lower()

    @patch('tools.chembl_tool.ChEMBLTool._get_molecule_details')
    def test_http_error(self, mock_get, chembl_tool):
        """Test handling of HTTP errors."""
        from requests.exceptions import HTTPError

        mock_get.side_effect = HTTPError("404 Not Found")

        result = chembl_tool.get_drug_info("INVALID_ID")

        assert result.success is False
        assert result.error is not None

    @patch('tools.chembl_tool.ChEMBLTool._search_by_indication')
    def test_timeout_error(self, mock_search, chembl_tool):
        """Test handling of timeout errors."""
        from requests.exceptions import Timeout

        mock_search.side_effect = Timeout("Request timeout")

        result = chembl_tool.search_by_indication("test")

        assert result.success is False
        assert "timeout" in result.error.lower()


class TestChEMBLCaching:
    """Test caching functionality."""

    @patch('tools.chembl_tool.ChEMBLTool._search_targets')
    @patch('tools.chembl_tool.ChEMBLTool._search_molecules')
    def test_cache_hit(
        self,
        mock_search_molecules,
        mock_search_targets,
        chembl_tool,
        mock_target_response,
        mock_molecule_response
    ):
        """Test that identical queries use cache."""
        mock_search_targets.return_value = mock_target_response
        mock_search_molecules.return_value = mock_molecule_response

        # First call
        result1 = chembl_tool.search_by_target("EGFR")
        assert result1.success is True
        assert result1.metadata["cached"] is False

        # Second identical call - should use cache
        result2 = chembl_tool.search_by_target("EGFR")
        assert result2.success is True
        assert result2.metadata["cached"] is True

        # Should only call API once
        assert mock_search_targets.call_count == 1
        assert mock_search_molecules.call_count == 1


class TestChEMBLRateLimiting:
    """Test rate limiting functionality."""

    @patch('tools.chembl_tool.ChEMBLTool._search_by_indication')
    def test_rate_limit_applied(
        self,
        mock_search,
        chembl_tool,
        mock_drug_indication_response
    ):
        """Test that rate limiting is applied."""
        import time
        mock_search.return_value = mock_drug_indication_response

        start_time = time.time()

        # Make rapid searches
        for _ in range(5):
            chembl_tool.search_by_indication("test")

        elapsed = time.time() - start_time

        # Should have some delay due to rate limiting
        assert elapsed >= 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
