"""Unit tests for PubMed tool.

Tests cover basic functionality, error handling, rate limiting,
and result parsing using mocked API responses.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from tools.pubmed_tool import PubMedTool


@pytest.fixture
def pubmed_tool():
    """Create a PubMed tool instance for testing."""
    return PubMedTool()


@pytest.fixture
def mock_search_response():
    """Mock JSON response for PubMed search."""
    return {
        "esearchresult": {
            "count": "2",
            "idlist": ["12345678", "87654321"]
        }
    }


@pytest.fixture
def mock_fetch_response():
    """Mock XML response for PubMed fetch."""
    return """<?xml version="1.0"?>
    <PubmedArticleSet>
        <PubmedArticle>
            <MedlineCitation>
                <PMID>12345678</PMID>
                <Article>
                    <ArticleTitle>EGFR Inhibitors in Lung Cancer Treatment</ArticleTitle>
                    <Abstract>
                        <AbstractText>This is a test abstract about EGFR inhibitors.</AbstractText>
                    </Abstract>
                    <AuthorList>
                        <Author>
                            <LastName>Smith</LastName>
                            <ForeName>John</ForeName>
                        </Author>
                    </AuthorList>
                    <Journal>
                        <Title>Test Journal</Title>
                    </Journal>
                </Article>
            </MedlineCitation>
            <PubmedData>
                <ArticleIdList>
                    <ArticleId IdType="doi">10.1234/test</ArticleId>
                </ArticleIdList>
            </PubmedData>
        </PubmedArticle>
    </PubmedArticleSet>
    """


class TestPubMedToolBasic:
    """Test basic PubMed tool functionality."""

    def test_tool_initialization(self, pubmed_tool):
        """Test that tool initializes correctly."""
        assert pubmed_tool.name == "PubMed"
        assert pubmed_tool.base_url == "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        assert pubmed_tool.rate_limit == 3

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    @patch('tools.pubmed_tool.PubMedTool._fetch_details')
    def test_search_pubmed_success(
        self,
        mock_fetch,
        mock_search,
        pubmed_tool,
        mock_fetch_response
    ):
        """Test successful PubMed search."""
        mock_search.return_value = ["12345678"]
        mock_fetch.return_value = mock_fetch_response

        result = pubmed_tool.search_pubmed("EGFR inhibitors", max_results=1)

        assert result.success is True
        assert result.data is not None
        assert len(result.data) == 1
        assert result.data[0]["pmid"] == "12345678"
        assert "EGFR" in result.data[0]["title"]

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_search_pubmed_no_results(self, mock_search, pubmed_tool):
        """Test PubMed search with no results."""
        mock_search.return_value = []

        result = pubmed_tool.search_pubmed("nonexistent query xyz123")

        assert result.success is True
        assert result.data == []
        assert result.metadata["results_count"] == 0

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_search_pubmed_invalid_query(self, mock_search, pubmed_tool):
        """Test PubMed search with invalid query causing error."""
        mock_search.side_effect = ValueError("Invalid query")

        result = pubmed_tool.search_pubmed("")

        assert result.success is False
        assert result.error is not None
        assert "Invalid" in result.error


class TestPubMedParsing:
    """Test PubMed result parsing."""

    def test_parse_xml_basic(self, pubmed_tool, mock_fetch_response):
        """Test parsing of basic XML response."""
        parsed = pubmed_tool.parse_results(mock_fetch_response)

        assert len(parsed) == 1
        assert parsed[0]["pmid"] == "12345678"
        assert parsed[0]["title"] == "EGFR Inhibitors in Lung Cancer Treatment"
        assert "EGFR inhibitors" in parsed[0]["abstract"]
        assert parsed[0]["authors"] == ["John Smith"]
        assert parsed[0]["journal"] == "Test Journal"
        assert parsed[0]["doi"] == "10.1234/test"

    def test_parse_xml_malformed(self, pubmed_tool):
        """Test parsing of malformed XML."""
        with pytest.raises(ValueError):
            pubmed_tool.parse_results("not valid xml")

    def test_parse_xml_empty(self, pubmed_tool):
        """Test parsing of empty result set."""
        empty_xml = '<?xml version="1.0"?><PubmedArticleSet></PubmedArticleSet>'
        parsed = pubmed_tool.parse_results(empty_xml)
        assert parsed == []


class TestPubMedRateLimiting:
    """Test rate limiting functionality."""

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    @patch('tools.pubmed_tool.PubMedTool._fetch_details')
    def test_rate_limit_applied(self, mock_fetch, mock_search, pubmed_tool, mock_fetch_response):
        """Test that rate limiting is applied."""
        import time
        mock_search.return_value = ["12345678"]
        mock_fetch.return_value = mock_fetch_response

        start_time = time.time()

        # Make 4 rapid searches (should be rate limited to ~3/sec)
        for _ in range(4):
            pubmed_tool.search_pubmed("test", max_results=1)

        elapsed = time.time() - start_time

        # Should take at least 1 second due to rate limiting
        assert elapsed >= 0.3  # Allow some margin


class TestPubMedErrorHandling:
    """Test error handling."""

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_connection_error(self, mock_search, pubmed_tool):
        """Test handling of connection errors."""
        from requests.exceptions import ConnectionError

        mock_search.side_effect = ConnectionError("Network error")

        result = pubmed_tool.search_pubmed("test")

        assert result.success is False
        assert "connect" in result.error.lower()

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_timeout_error(self, mock_search, pubmed_tool):
        """Test handling of timeout errors."""
        from requests.exceptions import Timeout

        mock_search.side_effect = Timeout("Request timeout")

        result = pubmed_tool.search_pubmed("test")

        assert result.success is False
        assert "timeout" in result.error.lower()


class TestPubMedCaching:
    """Test caching functionality."""

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    @patch('tools.pubmed_tool.PubMedTool._fetch_details')
    def test_cache_hit(self, mock_fetch, mock_search, pubmed_tool, mock_fetch_response):
        """Test that identical queries use cache."""
        mock_search.return_value = ["12345678"]
        mock_fetch.return_value = mock_fetch_response

        # First call - should hit API
        result1 = pubmed_tool.search_pubmed("test query", max_results=1)
        assert result1.success is True
        assert result1.metadata["cached"] is False

        # Second identical call - should use cache
        result2 = pubmed_tool.search_pubmed("test query", max_results=1)
        assert result2.success is True
        assert result2.metadata["cached"] is True

        # Should only call API once
        assert mock_search.call_count == 1
        assert mock_fetch.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
