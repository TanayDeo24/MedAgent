"""ChEMBL API wrapper for chemical and drug information.

Provides methods to search for compounds, drug information, and
protein targets from the ChEMBL database.

API Documentation: https://chembl.gitbook.io/chembl-interface-documentation/web-services
"""

from typing import Dict, List, Optional, Any

from config.settings import settings
from tools.base_tool import BaseTool, ToolResult
from utils.rate_limiter import rate_limit


class ChEMBLTool(BaseTool):
    """Tool for searching chemical and drug data from ChEMBL.

    ChEMBL is a manually curated database of bioactive molecules with
    drug-like properties maintained by the European Bioinformatics Institute.
    """

    def __init__(self):
        """Initialize ChEMBL tool."""
        super().__init__(
            name="ChEMBL",
            base_url=settings.CHEMBL_BASE_URL,
            rate_limit=settings.CHEMBL_RATE_LIMIT
        )

    @rate_limit("chembl", settings.CHEMBL_RATE_LIMIT)
    def _search_targets(self, target_name: str, limit: int = 10) -> Dict[str, Any]:
        """Search for protein targets by name.

        Args:
            target_name: Name of the protein target
            limit: Maximum number of results

        Returns:
            API response dictionary

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}target/search.json"

        params = {
            "q": target_name,
            "limit": limit
        }

        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.json()

    @rate_limit("chembl", settings.CHEMBL_RATE_LIMIT)
    def _get_target_components(self, target_chembl_id: str) -> Dict[str, Any]:
        """Get detailed information about a target.

        Args:
            target_chembl_id: ChEMBL target ID

        Returns:
            API response dictionary

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}target/{target_chembl_id}.json"

        response = self.session.get(url)
        response.raise_for_status()

        return response.json()

    @rate_limit("chembl", settings.CHEMBL_RATE_LIMIT)
    def _search_molecules(self, query_params: Dict[str, Any]) -> Dict[str, Any]:
        """Search for molecules with given parameters.

        Args:
            query_params: Query parameters for molecule search

        Returns:
            API response dictionary

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}molecule.json"

        response = self.session.get(url, params=query_params)
        response.raise_for_status()

        return response.json()

    @rate_limit("chembl", settings.CHEMBL_RATE_LIMIT)
    def _get_molecule_details(self, chembl_id: str) -> Dict[str, Any]:
        """Get detailed information about a molecule.

        Args:
            chembl_id: ChEMBL molecule ID

        Returns:
            API response dictionary

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}molecule/{chembl_id}.json"

        response = self.session.get(url)
        response.raise_for_status()

        return response.json()

    @rate_limit("chembl", settings.CHEMBL_RATE_LIMIT)
    def _search_by_indication(self, disease: str, limit: int = 20) -> Dict[str, Any]:
        """Search for drugs by indication.

        Args:
            disease: Disease or indication name
            limit: Maximum number of results

        Returns:
            API response dictionary

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}drug_indication.json"

        params = {
            "mesh_heading__icontains": disease,
            "limit": limit
        }

        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.json()

    def _parse_target(self, target: Dict[str, Any]) -> Dict[str, Any]:
        """Parse target data from API response.

        Args:
            target: Target data from API

        Returns:
            Parsed target dictionary
        """
        return {
            "target_chembl_id": target.get("target_chembl_id", ""),
            "target_type": target.get("target_type", ""),
            "organism": target.get("organism", ""),
            "pref_name": target.get("pref_name", ""),
            "target_components": target.get("target_components", [])
        }

    def _parse_molecule(self, molecule: Dict[str, Any]) -> Dict[str, Any]:
        """Parse molecule data from API response.

        Args:
            molecule: Molecule data from API

        Returns:
            Parsed molecule dictionary
        """
        # Extract basic info
        chembl_id = molecule.get("molecule_chembl_id", "")
        pref_name = molecule.get("pref_name", "No name")
        molecule_type = molecule.get("molecule_type", "")

        # Extract properties
        props = molecule.get("molecule_properties", {})
        molecular_weight = props.get("full_mwt", "N/A")
        alogp = props.get("alogp", "N/A")

        # Extract development phase
        max_phase = molecule.get("max_phase", 0)
        phase_map = {
            0: "Preclinical",
            1: "Phase 1",
            2: "Phase 2",
            3: "Phase 3",
            4: "Approved"
        }
        development_phase = phase_map.get(max_phase, "Unknown")

        # Extract mechanisms
        mechanisms = []
        for mech in molecule.get("molecule_mechanisms", []):
            mechanism_of_action = mech.get("mechanism_of_action", "")
            target_name = mech.get("target_name", "")
            if mechanism_of_action:
                mechanisms.append({
                    "action": mechanism_of_action,
                    "target": target_name
                })

        # First available mechanism of action
        first_moa = mechanisms[0]["action"] if mechanisms else "Not available"

        return {
            "chembl_id": chembl_id,
            "name": pref_name,
            "molecule_type": molecule_type,
            "molecular_weight": molecular_weight,
            "alogp": alogp,
            "development_phase": development_phase,
            "max_phase": max_phase,
            "mechanism_of_action": first_moa,
            "mechanisms": mechanisms,
            "url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/"
        }

    def _parse_drug_indication(self, indication: Dict[str, Any]) -> Dict[str, Any]:
        """Parse drug indication data from API response.

        Args:
            indication: Drug indication data from API

        Returns:
            Parsed indication dictionary
        """
        return {
            "chembl_id": indication.get("molecule_chembl_id", ""),
            "drug_name": indication.get("parent_molecule_name", ""),
            "indication": indication.get("mesh_heading", ""),
            "max_phase": indication.get("max_phase_for_ind", 0),
            "efo_term": indication.get("efo_term", "")
        }

    def parse_results(self, raw_data: Any) -> Any:
        """Parse API response into structured data.

        Args:
            raw_data: Raw API response

        Returns:
            Parsed data (format depends on the specific API call)
        """
        # Handle different response types
        if isinstance(raw_data, dict):
            if "molecules" in raw_data:
                molecules = raw_data.get("molecules", [])
                return [self._parse_molecule(m) for m in molecules]
            elif "targets" in raw_data:
                targets = raw_data.get("targets", [])
                return [self._parse_target(t) for t in targets]
            elif "drug_indications" in raw_data:
                indications = raw_data.get("drug_indications", [])
                return [self._parse_drug_indication(i) for i in indications]
            else:
                # Single molecule or target
                return self._parse_molecule(raw_data) if "molecule_chembl_id" in raw_data else self._parse_target(raw_data)

        return raw_data

    def search_by_target(
        self,
        target_name: str,
        max_results: int = 10
    ) -> ToolResult:
        """Search for compounds by protein target.

        Args:
            target_name: Name of the protein target (e.g., "EGFR", "HER2")
            max_results: Maximum number of compounds to return

        Returns:
            ToolResult with list of compound dictionaries

        Example:
            >>> tool = ChEMBLTool()
            >>> result = tool.search_by_target("EGFR", max_results=5)
            >>> if result.success:
            ...     for compound in result.data:
            ...         print(compound['name'])
        """
        def _execute():
            # First, search for the target
            target_results = self._search_targets(target_name, limit=5)
            targets = target_results.get("targets", [])

            if not targets:
                return {"molecules": []}

            # Get the first target's ChEMBL ID
            target_chembl_id = targets[0].get("target_chembl_id")

            if not target_chembl_id:
                return {"molecules": []}

            # Search for molecules targeting this protein
            query_params = {
                "target_chembl_id": target_chembl_id,
                "limit": max_results
            }

            molecules_data = self._search_molecules(query_params)
            return molecules_data

        return self._execute_with_monitoring(
            "search_by_target",
            target_name,
            _execute
        )

    def get_drug_info(self, chembl_id: str) -> ToolResult:
        """Get detailed information about a drug/compound.

        Args:
            chembl_id: ChEMBL ID (e.g., "CHEMBL1234")

        Returns:
            ToolResult with drug information dictionary

        Example:
            >>> tool = ChEMBLTool()
            >>> result = tool.get_drug_info("CHEMBL941")
            >>> if result.success:
            ...     print(result.data['mechanism_of_action'])
        """
        def _execute():
            molecule_data = self._get_molecule_details(chembl_id)
            return molecule_data

        return self._execute_with_monitoring(
            "get_drug_info",
            chembl_id,
            _execute
        )

    def search_by_indication(
        self,
        disease: str,
        max_results: int = 20
    ) -> ToolResult:
        """Search for drugs by disease indication.

        Args:
            disease: Disease or condition name (e.g., "lung cancer")
            max_results: Maximum number of drugs to return

        Returns:
            ToolResult with list of drug dictionaries

        Example:
            >>> tool = ChEMBLTool()
            >>> result = tool.search_by_indication("lung cancer", max_results=10)
            >>> if result.success:
            ...     for drug in result.data:
            ...         print(f"{drug['drug_name']}: {drug['indication']}")
        """
        def _execute():
            indication_data = self._search_by_indication(disease, max_results)
            return indication_data

        return self._execute_with_monitoring(
            "search_by_indication",
            disease,
            _execute
        )

    def execute(self, query: str, **kwargs: Any) -> ToolResult:
        """Execute a ChEMBL search (default tool action).

        Args:
            query: Search query (used as disease for indication search)
            **kwargs: Additional arguments

        Returns:
            ToolResult with search results
        """
        # Default to indication search
        return self.search_by_indication(query, **kwargs)
