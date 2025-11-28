"""PubMed E-utilities API wrapper for scientific literature search.

Provides methods to search PubMed and retrieve paper details including
titles, abstracts, authors, and publication information.

API Documentation: https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from config.settings import settings
from tools.base_tool import BaseTool, ToolResult
from utils.rate_limiter import rate_limit


class PubMedTool(BaseTool):
    """Tool for searching and retrieving scientific literature from PubMed.

    PubMed is a free database of biomedical and life sciences literature
    maintained by the National Library of Medicine.
    """

    def __init__(self):
        """Initialize PubMed tool."""
        super().__init__(
            name="PubMed",
            base_url=settings.PUBMED_BASE_URL,
            rate_limit=settings.PUBMED_RATE_LIMIT
        )

    @rate_limit("pubmed", settings.PUBMED_RATE_LIMIT)
    def _search_ids(
        self,
        query: str,
        max_results: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[str]:
        """Search PubMed and return list of PMIDs.

        Args:
            query: Search query
            max_results: Maximum number of results
            date_from: Start date in YYYY/MM/DD format
            date_to: End date in YYYY/MM/DD format

        Returns:
            List of PubMed IDs (PMIDs)

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}esearch.fcgi"

        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance"
        }

        # Add date range if specified
        if date_from or date_to:
            date_from = date_from or "1900/01/01"
            date_to = date_to or datetime.now().strftime("%Y/%m/%d")
            params["datetype"] = "pdat"
            params["mindate"] = date_from
            params["maxdate"] = date_to

        response = self.session.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])

        self.logger.debug(f"Found {len(id_list)} PMIDs for query: {query}")
        return id_list

    @rate_limit("pubmed", settings.PUBMED_RATE_LIMIT)
    def _fetch_details(self, pmids: List[str]) -> str:
        """Fetch detailed information for a list of PMIDs.

        Args:
            pmids: List of PubMed IDs

        Returns:
            XML string with paper details

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}efetch.fcgi"

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract"
        }

        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.text

    def _parse_xml_article(self, article: ET.Element) -> Dict[str, Any]:
        """Parse a single article from PubMed XML.

        Args:
            article: XML element for a single article

        Returns:
            Dictionary with article details
        """
        # Extract PMID
        pmid_elem = article.find(".//PMID")
        pmid = pmid_elem.text if pmid_elem is not None else ""

        # Extract title
        title_elem = article.find(".//ArticleTitle")
        title = title_elem.text if title_elem is not None else "No title available"

        # Extract abstract
        abstract_parts = []
        abstract_text = article.find(".//AbstractText")
        if abstract_text is not None:
            if abstract_text.text:
                abstract_parts.append(abstract_text.text)

        # Handle structured abstracts
        for abstract_elem in article.findall(".//AbstractText"):
            label = abstract_elem.get("Label", "")
            text = abstract_elem.text or ""
            if label and text:
                abstract_parts.append(f"{label}: {text}")
            elif text:
                abstract_parts.append(text)

        abstract = " ".join(abstract_parts) if abstract_parts else "No abstract available"

        # Extract authors
        authors = []
        for author in article.findall(".//Author"):
            last_name = author.find("LastName")
            fore_name = author.find("ForeName")
            if last_name is not None and fore_name is not None:
                authors.append(f"{fore_name.text} {last_name.text}")
            elif last_name is not None:
                authors.append(last_name.text)

        # Extract publication date
        pub_date = article.find(".//PubDate")
        year = ""
        month = ""
        day = ""

        if pub_date is not None:
            year_elem = pub_date.find("Year")
            month_elem = pub_date.find("Month")
            day_elem = pub_date.find("Day")

            year = year_elem.text if year_elem is not None else ""
            month = month_elem.text if month_elem is not None else ""
            day = day_elem.text if day_elem is not None else ""

        # Format date
        date_parts = [p for p in [year, month, day] if p]
        pub_date_str = "-".join(date_parts) if date_parts else "Date not available"

        # Extract journal
        journal_elem = article.find(".//Journal/Title")
        journal = journal_elem.text if journal_elem is not None else "Unknown journal"

        # Extract DOI
        doi = ""
        for article_id in article.findall(".//ArticleId"):
            if article_id.get("IdType") == "doi":
                doi = article_id.text
                break

        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "pub_date": pub_date_str,
            "year": year,
            "journal": journal,
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        }

    def parse_results(self, raw_data: str) -> List[Dict[str, Any]]:
        """Parse XML response from PubMed into structured data.

        Args:
            raw_data: XML string from PubMed API

        Returns:
            List of dictionaries with paper details
        """
        try:
            root = ET.fromstring(raw_data)
            articles = root.findall(".//PubmedArticle")

            parsed_articles = []
            for article in articles:
                try:
                    parsed = self._parse_xml_article(article)
                    parsed_articles.append(parsed)
                except Exception as e:
                    self.logger.warning(f"Failed to parse article: {e}")
                    continue

            return parsed_articles

        except ET.ParseError as e:
            self.logger.error(f"Failed to parse XML: {e}")
            raise ValueError(f"Invalid XML response from PubMed: {e}")

    def search_pubmed(
        self,
        query: str,
        max_results: int = None,
        years_back: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> ToolResult:
        """Search PubMed for scientific papers.

        Args:
            query: Search query (supports PubMed search syntax)
            max_results: Maximum number of results to return
            years_back: Limit to papers from last N years
            date_from: Start date in YYYY/MM/DD format (overrides years_back)
            date_to: End date in YYYY/MM/DD format

        Returns:
            ToolResult with list of paper dictionaries

        Example:
            >>> tool = PubMedTool()
            >>> result = tool.search_pubmed("EGFR inhibitors lung cancer", max_results=5)
            >>> if result.success:
            ...     for paper in result.data:
            ...         print(paper['title'])
        """
        max_results = max_results or settings.PUBMED_DEFAULT_MAX_RESULTS

        # Set default date range if years_back is specified
        if years_back and not date_from:
            date_from = (datetime.now() - timedelta(days=years_back * 365)).strftime("%Y/%m/%d")

        # Default to last 2 years if no date specified
        if not date_from and not years_back:
            years_back = settings.PUBMED_DEFAULT_DATE_RANGE
            date_from = (datetime.now() - timedelta(days=years_back * 365)).strftime("%Y/%m/%d")

        def _execute():
            # Search for PMIDs
            pmids = self._search_ids(query, max_results, date_from, date_to)

            if not pmids:
                return []

            # Fetch details for all PMIDs
            xml_data = self._fetch_details(pmids)

            return xml_data

        return self._execute_with_monitoring(
            "search_pubmed",
            query,
            _execute
        )

    def get_paper_details(self, pmid: str) -> ToolResult:
        """Get detailed information about a research paper.

        Args:
            pmid: PubMed ID

        Returns:
            ToolResult with paper details dictionary

        Example:
            >>> tool = PubMedTool()
            >>> result = tool.get_paper_details("12345678")
            >>> if result.success:
            ...     print(result.data['abstract'])
        """
        def _execute():
            xml_data = self._fetch_details([pmid])
            return xml_data

        return self._execute_with_monitoring(
            "get_paper_details",
            pmid,
            _execute
        )

    def execute(self, query: str, **kwargs: Any) -> ToolResult:
        """Execute a PubMed search (default tool action).

        Args:
            query: Search query
            **kwargs: Additional arguments for search_pubmed

        Returns:
            ToolResult with search results
        """
        return self.search_pubmed(query, **kwargs)
