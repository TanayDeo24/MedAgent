"""ClinicalTrials.gov API wrapper for clinical trial data.

Provides methods to search for clinical trials and retrieve detailed
information about trial protocols, status, and locations.

API Documentation: https://clinicaltrials.gov/api/gui
"""

from typing import Dict, List, Optional, Any

from config.settings import settings
from tools.base_tool import BaseTool, ToolResult
from utils.rate_limiter import rate_limit


class ClinicalTrialsTool(BaseTool):
    """Tool for searching and retrieving clinical trial data.

    ClinicalTrials.gov is a database of privately and publicly funded
    clinical studies conducted around the world.
    """

    # Valid trial statuses
    VALID_STATUSES = {
        "RECRUITING",
        "NOT_YET_RECRUITING",
        "ACTIVE_NOT_RECRUITING",
        "COMPLETED",
        "SUSPENDED",
        "TERMINATED",
        "WITHDRAWN"
    }

    # Valid trial phases
    VALID_PHASES = {
        "EARLY_PHASE1",
        "PHASE1",
        "PHASE2",
        "PHASE3",
        "PHASE4",
        "NA"
    }

    def __init__(self):
        """Initialize ClinicalTrials tool."""
        super().__init__(
            name="ClinicalTrials",
            base_url=settings.CLINICAL_TRIALS_BASE_URL,
            rate_limit=settings.CLINICAL_TRIALS_RATE_LIMIT
        )

    @rate_limit("clinical_trials", settings.CLINICAL_TRIALS_RATE_LIMIT)
    def _search_trials_page(
        self,
        query_params: Dict[str, Any],
        page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fetch a single page of clinical trials.

        Args:
            query_params: Query parameters for the API
            page_token: Token for pagination

        Returns:
            API response dictionary

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}studies"

        params = query_params.copy()
        params["format"] = "json"
        params["pageSize"] = settings.CLINICAL_TRIALS_PAGE_SIZE

        if page_token:
            params["pageToken"] = page_token

        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.json()

    def _parse_study(self, study: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a single study from the API response.

        Args:
            study: Study data from API

        Returns:
            Parsed study dictionary
        """
        protocol_section = study.get("protocolSection", {})
        id_module = protocol_section.get("identificationModule", {})
        status_module = protocol_section.get("statusModule", {})
        sponsor_module = protocol_section.get("sponsorCollaboratorsModule", {})
        conditions_module = protocol_section.get("conditionsModule", {})
        interventions_module = protocol_section.get("armsInterventionsModule", {})
        contacts_module = protocol_section.get("contactsLocationsModule", {})
        design_module = protocol_section.get("designModule", {})

        # Extract NCT ID
        nct_id = id_module.get("nctId", "")

        # Extract title
        title = id_module.get("officialTitle") or id_module.get("briefTitle", "No title")

        # Extract status
        status = status_module.get("overallStatus", "Unknown")

        # Extract phase
        phases = design_module.get("phases", [])
        phase = ", ".join(phases) if phases else "N/A"

        # Extract conditions
        conditions = conditions_module.get("conditions", [])

        # Extract interventions
        interventions = []
        for intervention in interventions_module.get("interventions", []):
            interventions.append({
                "type": intervention.get("type", ""),
                "name": intervention.get("name", ""),
                "description": intervention.get("description", "")
            })

        # Extract sponsor
        lead_sponsor = sponsor_module.get("leadSponsor", {})
        sponsor = lead_sponsor.get("name", "Unknown")

        # Extract locations
        locations = []
        for location in contacts_module.get("locations", []):
            facility = location.get("facility", "")
            city = location.get("city", "")
            country = location.get("country", "")
            loc_str = f"{facility}, {city}, {country}".strip(", ")
            if loc_str:
                locations.append(loc_str)

        # Extract enrollment
        enrollment_info = design_module.get("enrollmentInfo", {})
        enrollment = enrollment_info.get("count", "N/A")

        # Extract dates
        start_date_struct = status_module.get("startDateStruct", {})
        start_date = start_date_struct.get("date", "N/A")

        completion_date_struct = status_module.get("completionDateStruct", {})
        completion_date = completion_date_struct.get("date", "N/A")

        # Extract brief summary
        description_module = protocol_section.get("descriptionModule", {})
        brief_summary = description_module.get("briefSummary", "No summary available")

        return {
            "nct_id": nct_id,
            "title": title,
            "status": status,
            "phase": phase,
            "conditions": conditions,
            "interventions": interventions,
            "sponsor": sponsor,
            "locations": locations[:10],  # Limit to first 10 locations
            "enrollment": enrollment,
            "start_date": start_date,
            "completion_date": completion_date,
            "brief_summary": brief_summary[:500],  # Limit summary length
            "url": f"https://clinicaltrials.gov/study/{nct_id}"
        }

    def parse_results(self, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse API response into structured data.

        Args:
            raw_data: Raw API response

        Returns:
            List of parsed study dictionaries
        """
        studies = raw_data.get("studies", [])

        parsed_studies = []
        for study in studies:
            try:
                parsed = self._parse_study(study)
                parsed_studies.append(parsed)
            except Exception as e:
                self.logger.warning(f"Failed to parse study: {e}")
                continue

        return parsed_studies

    def search_trials(
        self,
        condition: Optional[str] = None,
        intervention: Optional[str] = None,
        status: Optional[str] = "RECRUITING",
        phase: Optional[str] = None,
        max_results: Optional[int] = None,
        sponsor: Optional[str] = None,
        country: Optional[str] = None
    ) -> ToolResult:
        """Search for clinical trials.

        Args:
            condition: Disease or condition (e.g., "lung cancer")
            intervention: Intervention/treatment (e.g., "pembrolizumab")
            status: Trial status (RECRUITING, COMPLETED, etc.)
            phase: Trial phase (PHASE1, PHASE2, PHASE3, PHASE4)
            max_results: Maximum number of results
            sponsor: Sponsor organization name
            country: Country where trial is conducted

        Returns:
            ToolResult with list of trial dictionaries

        Example:
            >>> tool = ClinicalTrialsTool()
            >>> result = tool.search_trials(
            ...     condition="lung cancer",
            ...     intervention="pembrolizumab",
            ...     status="RECRUITING"
            ... )
            >>> if result.success:
            ...     for trial in result.data:
            ...         print(trial['title'])
        """
        # Build query
        query_parts = []
        if condition:
            query_parts.append(f"AREA[ConditionSearch]{condition}")
        if intervention:
            query_parts.append(f"AREA[InterventionSearch]{intervention}")
        if sponsor:
            query_parts.append(f"AREA[LeadSponsorName]{sponsor}")
        if country:
            query_parts.append(f"AREA[LocationCountry]{country}")

        query = " AND ".join(query_parts) if query_parts else "AREA[StudyType]INTERVENTIONAL"

        # Build query parameters
        query_params = {
            "query.term": query,
        }

        # Add filters
        filters = []
        if status and status in self.VALID_STATUSES:
            filters.append(f"overallStatus:{status}")

        if phase and phase in self.VALID_PHASES:
            filters.append(f"phase:{phase}")

        if filters:
            query_params["filter.overallStatus"] = status if status else None
            query_params["filter.phase"] = phase if phase else None

        # Remove None values
        query_params = {k: v for k, v in query_params.items() if v is not None}

        def _execute():
            all_studies = []
            page_token = None
            max_results_limit = max_results or 100

            while len(all_studies) < max_results_limit:
                response_data = self._search_trials_page(query_params, page_token)

                studies = response_data.get("studies", [])
                all_studies.extend(studies)

                # Check if there are more pages
                page_token = response_data.get("nextPageToken")
                if not page_token or len(all_studies) >= max_results_limit:
                    break

            # Trim to max_results
            all_studies = all_studies[:max_results_limit]

            return {"studies": all_studies}

        query_str = f"condition={condition}, intervention={intervention}, status={status}"
        return self._execute_with_monitoring(
            "search_trials",
            query_str,
            _execute
        )

    def get_trial_details(self, nct_id: str) -> ToolResult:
        """Get detailed information for a specific trial.

        Args:
            nct_id: NCT identifier (e.g., "NCT01234567")

        Returns:
            ToolResult with trial details dictionary

        Example:
            >>> tool = ClinicalTrialsTool()
            >>> result = tool.get_trial_details("NCT01234567")
            >>> if result.success:
            ...     print(result.data['title'])
        """
        def _execute():
            query_params = {
                "query.term": f"AREA[NCTId]{nct_id}"
            }
            response_data = self._search_trials_page(query_params)
            return response_data

        return self._execute_with_monitoring(
            "get_trial_details",
            nct_id,
            _execute
        )

    def execute(
        self,
        query: str = None,
        condition: str = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute a clinical trials search (default tool action).

        Args:
            query: Search query (used as condition if no condition specified)
            condition: Disease or condition
            **kwargs: Additional arguments for search_trials

        Returns:
            ToolResult with search results
        """
        # Use query as condition if condition not specified
        if query and not condition:
            condition = query

        return self.search_trials(condition=condition, **kwargs)
