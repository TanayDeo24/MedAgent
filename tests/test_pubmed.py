"""Unit tests for PubMed tool.

Tests cover basic functionality, error handling, rate limiting,
and result parsing using mocked API responses.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from tools.pubmed_tool import PubMedTool
from config.settings import settings


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
    """Test rate limiting functionality.

    NOTE: this used to @patch PubMedTool._search_ids/_fetch_details directly.
    unittest.mock.patch replaces the entire bound method - including the
    @rate_limit(...) decorator wrapping it - with a MagicMock, so the token
    bucket / RateLimiter code in utils/rate_limiter.py was never invoked and
    the test could not observe rate limiting no matter how the limiter
    behaved. Fixed by mocking only the HTTP layer (session.get), leaving the
    decorated methods (and thus the real rate limiter) in the call path, and
    by injecting a fake clock instead of relying on real wall-clock timing -
    see tests/test_rate_limiter.py for direct, deterministic coverage of the
    limiter itself.
    """

    def test_rate_limit_applied(self, pubmed_tool, mock_search_response, mock_fetch_response, monkeypatch):
        """4 rapid real (decorated) calls at PUBMED_RATE_LIMIT=3/sec must
        consume the token bucket and trigger at least one wait_for_token
        sleep, deterministically via a fake clock."""
        import utils.rate_limiter as rl_module
        from tests.test_rate_limiter import FakeClock

        clock = FakeClock()
        monkeypatch.setattr(rl_module.time, "time", clock.time)
        monkeypatch.setattr(rl_module.time, "sleep", clock.sleep)
        # Use a fresh bucket key so this test doesn't inherit state from
        # other tests/modules sharing the global rate limiter.
        monkeypatch.setitem(rl_module._rate_limiter.buckets, "pubmed", rl_module.TokenBucket(rate=3, capacity=3))

        mock_search_resp = Mock()
        mock_search_resp.json.return_value = mock_search_response
        mock_search_resp.raise_for_status = Mock()

        mock_fetch_resp = Mock()
        mock_fetch_resp.text = mock_fetch_response
        mock_fetch_resp.raise_for_status = Mock()

        def fake_get(url, params=None, **kwargs):
            return mock_search_resp if "esearch" in url else mock_fetch_resp

        monkeypatch.setattr(pubmed_tool.session, "get", fake_get)

        # Distinct queries so the tool's response cache (tested separately in
        # TestPubMedCaching) doesn't short-circuit calls before they reach
        # the rate-limited, decorated methods.
        for i in range(4):
            result = pubmed_tool.search_pubmed(f"test query {i}", max_results=1)
            assert result.success is True

        # 4 calls against a 3-token bucket must have required at least one
        # refill wait, observed as fake-clock advancement, not real sleeping.
        assert clock.now > 0
        assert len(clock.sleep_calls) > 0


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
        assert "timed out" in result.error.lower()


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


class TestPubMedDateRangeFix:
    """Regression tests for the Phase 4 date-filter fix
    (docs/v2/PHASE4_BASELINE_MEASUREMENT.md Section 2 /
    docs/v2/PHASE4_HETEROGENEOUS_RETRIEVAL.md): search_pubmed() used to
    silently apply PUBMED_DEFAULT_DATE_RANGE (2 years) whenever the caller
    passed neither years_back nor date_from, which measured as the root
    cause of the live PubMed path's Recall@10=0.045 vs RAG's 0.773 on the
    same 22-case benchmark. This had zero dedicated test coverage before
    this file -- these tests inspect the actual constructed request params
    via a mocked _search_ids, not just that the call 'runs'.
    """

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_unconstrained_search_applies_no_date_filter(self, mock_search, pubmed_tool):
        """A plain search_pubmed(query) call (no years_back, no date_from)
        must NOT inject any date restriction -- _search_ids must be called
        with date_from=None and date_to=None."""
        mock_search.return_value = []

        result = pubmed_tool.search_pubmed("EGFR inhibitors lung cancer")

        assert result.success is True
        assert mock_search.call_count == 1
        call_args = mock_search.call_args
        # _search_ids(self, query, max_results, date_from=None, date_to=None)
        # Called positionally in search_pubmed(); inspect both positional
        # and keyword forms defensively so this test doesn't depend on the
        # exact calling convention, only on the actual values passed.
        args, kwargs = call_args
        combined = list(args) + list(kwargs.values())
        # date_from/date_to are the 3rd/4th positional args (after
        # query, max_results) or passed by keyword -- resolve explicitly.
        date_from = kwargs.get("date_from", args[2] if len(args) > 2 else None)
        date_to = kwargs.get("date_to", args[3] if len(args) > 3 else None)
        assert date_from is None
        assert date_to is None

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_unconstrained_search_does_not_use_default_date_range_constant(
        self, mock_search, pubmed_tool
    ):
        """Directly confirms the specific old defect: a plain call's
        resulting date_from is NOT what a PUBMED_DEFAULT_DATE_RANGE-years
        lookback would have produced (i.e. not ~2 years before today)."""
        from datetime import datetime, timedelta

        mock_search.return_value = []
        pubmed_tool.search_pubmed("metformin type 2 diabetes")

        args, kwargs = mock_search.call_args
        date_from = kwargs.get("date_from", args[2] if len(args) > 2 else None)

        old_defect_date_from = (
            datetime.now() - timedelta(days=settings.PUBMED_DEFAULT_DATE_RANGE * 365)
        ).strftime("%Y/%m/%d")
        assert date_from != old_defect_date_from
        assert date_from is None

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_explicit_years_back_still_honored(self, mock_search, pubmed_tool):
        """An explicit years_back MUST still produce a computed date_from
        (the fix removed the silent implicit default, not the caller's
        ability to opt into a recency filter explicitly)."""
        from datetime import datetime, timedelta

        mock_search.return_value = []
        pubmed_tool.search_pubmed("tirzepatide obesity", years_back=5)

        args, kwargs = mock_search.call_args
        date_from = kwargs.get("date_from", args[2] if len(args) > 2 else None)

        expected_date_from = (datetime.now() - timedelta(days=5 * 365)).strftime("%Y/%m/%d")
        assert date_from == expected_date_from

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_explicit_date_from_overrides_and_is_honored(self, mock_search, pubmed_tool):
        """An explicit date_from must be passed through to _search_ids
        unchanged, and takes precedence over years_back per the
        docstring's stated override behavior."""
        mock_search.return_value = []
        pubmed_tool.search_pubmed(
            "lecanemab Alzheimer", years_back=5, date_from="2019/06/01"
        )

        args, kwargs = mock_search.call_args
        date_from = kwargs.get("date_from", args[2] if len(args) > 2 else None)
        assert date_from == "2019/06/01"

    @patch('tools.pubmed_tool.PubMedTool._search_ids')
    def test_explicit_date_to_is_honored(self, mock_search, pubmed_tool):
        mock_search.return_value = []
        pubmed_tool.search_pubmed(
            "lecanemab Alzheimer", date_from="2019/06/01", date_to="2021/01/01"
        )

        args, kwargs = mock_search.call_args
        date_to = kwargs.get("date_to", args[3] if len(args) > 3 else None)
        assert date_to == "2021/01/01"

    def test_pubmed_default_date_range_not_referenced_elsewhere_in_module(self):
        """Grep the whole tools/pubmed_tool.py source for any OTHER live
        use of settings.PUBMED_DEFAULT_DATE_RANGE -- the only permitted
        appearances are inside the explanatory comment describing the
        fix itself, never as an executed default-filling expression."""
        import inspect
        import tools.pubmed_tool as pubmed_tool_module

        source = inspect.getsource(pubmed_tool_module)
        lines_with_reference = [
            line for line in source.splitlines() if "PUBMED_DEFAULT_DATE_RANGE" in line
        ]
        # It's fine for the constant name to appear in comment prose
        # explaining the historical defect/fix -- but every such line must
        # be a comment (starts with '#' once stripped), never executable
        # code that assigns/reads settings.PUBMED_DEFAULT_DATE_RANGE.
        assert lines_with_reference, (
            "Expected at least the explanatory fix comment to reference "
            "PUBMED_DEFAULT_DATE_RANGE by name."
        )
        for line in lines_with_reference:
            stripped = line.strip()
            assert stripped.startswith("#"), (
                f"Found a non-comment reference to PUBMED_DEFAULT_DATE_RANGE "
                f"in tools/pubmed_tool.py -- the default date range must "
                f"never be silently re-applied: {line!r}"
            )
        # Belt-and-suspenders: no line containing the executable attribute
        # access form may be a non-comment line either (redundant with the
        # per-line check above, kept as an explicit second assertion).
        executable_refs = [
            line for line in source.splitlines()
            if "settings.PUBMED_DEFAULT_DATE_RANGE" in line
            and not line.strip().startswith("#")
        ]
        assert executable_refs == [], (
            f"settings.PUBMED_DEFAULT_DATE_RANGE must not be read as an "
            f"executable expression in tools/pubmed_tool.py: {executable_refs}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
