"""ChEMBL API wrapper for chemical and drug information.

Provides methods to search for compounds, drug information, and
protein targets from the ChEMBL database.

API Documentation: https://chembl.gitbook.io/chembl-interface-documentation/web-services
"""

import difflib
import re
from typing import Dict, List, Optional, Any

from config.settings import settings
from tools.base_tool import BaseTool, ToolResult
from utils.rate_limiter import rate_limit

# Minimum deterministic string-similarity ratio (see `_best_name_similarity`)
# a fuzzy-tier candidate's own pref_name/synonyms must clear against the
# input name before the match is trusted enough to report as `fuzzy` rather
# than `no_match`. See docs/v2/CHEMBL_FUZZY_MATCH_THRESHOLD_FIX.md for the
# rationale and the real-example calibration behind this number.
FUZZY_MATCH_MIN_SIMILARITY = 0.6


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

    @rate_limit("chembl", settings.CHEMBL_RATE_LIMIT)
    def _fuzzy_search_molecules(self, name: str, limit: int = 10) -> Dict[str, Any]:
        """Relevance-ranked molecule search (ChEMBL's ElasticSearch-backed
        `molecule/search.json` endpoint). Used only as a last-resort
        fallback in `resolve_compound_name` when neither an exact
        preferred-name nor an exact-synonym match exists -- results here are
        ChEMBL's own ranking, never re-scored or re-ordered by this tool.

        Args:
            name: Free-text compound name
            limit: Maximum number of results

        Returns:
            API response dictionary

        Raises:
            Exception: If API request fails
        """
        url = f"{self.base_url}molecule/search.json"

        params = {
            "q": name,
            "limit": limit
        }

        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.json()

    @staticmethod
    def _normalize_for_similarity(text: str) -> str:
        """Lowercase and strip to alphanumerics only, for similarity
        comparison (so punctuation/whitespace/case differences like
        "Tagrisso" vs "TAGRISSO" or "Zorblatinix-9X" don't distort the
        ratio).
        """
        return "".join(ch for ch in text.lower() if ch.isalnum())

    @classmethod
    def _best_name_similarity(cls, query: str, molecule: Dict[str, Any]) -> float:
        """Deterministic string-similarity gate for the fuzzy-match tier.

        ChEMBL's `molecule/search.json` (ElasticSearch-backed) endpoint
        returns a `score` field, but it is an unnormalized Lucene/ES
        relevance score computed over corpus-wide term statistics, not a
        calibrated similarity -- live checks against the real API show a
        genuine near-miss typo ("asprin" -> ASPIRIN) scoring 0.0 while a
        completely fabricated name ("Zorblatinix-9X") scores 30.0 against
        an unrelated compound. A fixed threshold on that score therefore
        cannot separate real near-misses from fabricated names.

        Instead this computes `difflib.SequenceMatcher` ratio between the
        normalized input and the candidate's own `pref_name` plus every
        `molecule_synonyms` entry (both present in the search response),
        and returns the best (highest) ratio found. This directly measures
        whether the candidate's real name is actually close to what the
        user typed, which is what "fuzzy match" should mean.

        Args:
            query: The (already whitespace-normalized) input name.
            molecule: A raw molecule dict from `molecule/search.json`.

        Returns:
            Best similarity ratio in [0.0, 1.0] across pref_name and all
            synonyms; 0.0 if the candidate has no usable name at all.
        """
        q = cls._normalize_for_similarity(query)
        if not q:
            return 0.0

        candidate_names: List[str] = []
        pref_name = molecule.get("pref_name")
        if pref_name:
            candidate_names.append(pref_name)
        for syn in (molecule.get("molecule_synonyms") or []):
            syn_name = syn.get("synonyms") or syn.get("molecule_synonym")
            if syn_name:
                candidate_names.append(syn_name)

        best = 0.0
        for candidate_name in candidate_names:
            c = cls._normalize_for_similarity(candidate_name)
            if not c:
                continue
            ratio = difflib.SequenceMatcher(None, q, c).ratio()
            if ratio > best:
                best = ratio
        return best

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
            if "input_name" in raw_data and "match_type" in raw_data:
                # Already-structured resolve_compound_name() output -- pass
                # through unchanged. Checked FIRST, before the "molecules"
                # branch below, since a "fuzzy"/"ambiguous_match" result may
                # carry a "candidates" list but is never itself a raw
                # ChEMBL molecule-search response.
                return raw_data
            elif "molecules" in raw_data:
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

    def resolve_compound_name(
        self,
        name: str,
        max_results: int = 5
    ) -> ToolResult:
        """Resolve a free-text drug/compound name to its real ChEMBL ID.

        No numeric confidence score is ever produced -- only a deterministic
        `match_type` category the API's own response structure actually
        supports:

            exact_id_passthrough - input already looked like a ChEMBL ID
                (e.g. "CHEMBL941") and was verified to exist via
                `_get_molecule_details`.
            exact_preferred_name - exactly one molecule's `pref_name`
                case-insensitively equals the input (ChEMBL
                `pref_name__iexact`).
            exact_synonym - exactly one DISTINCT molecule has a synonym
                case-insensitively equal to the input (ChEMBL
                `molecule_synonyms__molecule_synonym__iexact`); e.g. a brand
                name like "Keytruda" resolving to pembrolizumab.
            fuzzy - no exact preferred-name/synonym match existed; the top
                hit of ChEMBL's own relevance-ranked `molecule/search.json`
                (ElasticSearch-backed) endpoint is returned, but ONLY if
                that top hit's own `pref_name`/synonyms clear a
                deterministic string-similarity gate
                (`FUZZY_MATCH_MIN_SIMILARITY`, see `_best_name_similarity`)
                against the input name -- the remaining top hits are
                surfaced as `candidates` for transparency, never presented
                as an exact/canonical match. ChEMBL's raw relevance `score`
                is NOT used as the gate: it is an unnormalized corpus-wide
                score, not a calibrated similarity (see
                `_best_name_similarity` docstring for a live example of
                why). A top hit that fails the gate is reported as
                `no_match`, not `fuzzy` -- see `no_match` below.
            ambiguous_match - more than one DISTINCT molecule matched at the
                exact preferred-name or exact-synonym step (e.g. a base
                compound and its salt form both carry the same brand-name
                synonym). `chembl_id` is left None and every candidate is
                returned in `candidates` -- never silently collapsed to one.
            no_match - no real ChEMBL record was found by any method, OR
                ChEMBL's fuzzy search returned candidates but none cleared
                the fuzzy-tier similarity gate (a low-confidence/unrelated
                result, e.g. a fabricated compound name). `chembl_id` is
                left None; NEVER a guessed/fabricated ID, and NEVER a real
                ID for an unrelated compound presented as if it matched.

        Args:
            name: Free-text compound/drug name (or a ChEMBL ID itself, for
                passthrough validation)
            max_results: Maximum number of candidate matches to return for
                ambiguous/fuzzy results

        Returns:
            ToolResult whose `data` is a dict with keys: input_name,
            normalized_name, matched_name, chembl_id, preferred_name,
            match_type, candidates (list of {chembl_id, preferred_name}).

        Example:
            >>> tool = ChEMBLTool()
            >>> result = tool.resolve_compound_name("osimertinib")
            >>> if result.success and result.data["match_type"] != "no_match":
            ...     print(result.data["chembl_id"])
        """
        def _no_match(normalized: str) -> Dict[str, Any]:
            return {
                "input_name": name,
                "normalized_name": normalized,
                "matched_name": None,
                "chembl_id": None,
                "preferred_name": None,
                "match_type": "no_match",
                "candidates": [],
            }

        def _ambiguous(normalized: str, molecules: List[Dict[str, Any]]) -> Dict[str, Any]:
            return {
                "input_name": name,
                "normalized_name": normalized,
                "matched_name": None,
                "chembl_id": None,
                "preferred_name": None,
                "match_type": "ambiguous_match",
                "candidates": [
                    {
                        "chembl_id": m.get("molecule_chembl_id"),
                        "preferred_name": m.get("pref_name"),
                    }
                    for m in molecules
                ],
            }

        def _dedupe_by_id(molecules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            # ChEMBL's synonym filter can return one row per matching
            # synonym record, so the same molecule_chembl_id can appear more
            # than once -- dedupe before judging exact vs. ambiguous.
            seen: Dict[str, Dict[str, Any]] = {}
            for m in molecules:
                cid = m.get("molecule_chembl_id")
                if cid and cid not in seen:
                    seen[cid] = m
            return list(seen.values())

        def _execute() -> Dict[str, Any]:
            normalized = " ".join(name.strip().split()) if name else ""

            if not normalized:
                return _no_match(normalized)

            # Step 1: ChEMBL-ID passthrough/validation (never a guess -- the
            # ID must actually resolve via a real molecule lookup).
            id_candidate = normalized.upper().replace(" ", "")
            if re.fullmatch(r"CHEMBL\d+", id_candidate):
                try:
                    molecule = self._get_molecule_details(id_candidate)
                except Exception:
                    molecule = None
                if molecule and molecule.get("molecule_chembl_id"):
                    return {
                        "input_name": name,
                        "normalized_name": normalized,
                        "matched_name": molecule.get("pref_name"),
                        "chembl_id": molecule.get("molecule_chembl_id"),
                        "preferred_name": molecule.get("pref_name"),
                        "match_type": "exact_id_passthrough",
                        "candidates": [],
                    }
                return _no_match(normalized)

            # Step 2: exact preferred-name match.
            pref_data = self._search_molecules({
                "pref_name__iexact": normalized,
                "limit": max_results,
            })
            pref_molecules = _dedupe_by_id(pref_data.get("molecules", []) or [])
            if len(pref_molecules) == 1:
                m = pref_molecules[0]
                return {
                    "input_name": name,
                    "normalized_name": normalized,
                    "matched_name": m.get("pref_name"),
                    "chembl_id": m.get("molecule_chembl_id"),
                    "preferred_name": m.get("pref_name"),
                    "match_type": "exact_preferred_name",
                    "candidates": [],
                }
            if len(pref_molecules) > 1:
                return _ambiguous(normalized, pref_molecules)

            # Step 3: exact synonym match (e.g. brand names).
            syn_data = self._search_molecules({
                "molecule_synonyms__molecule_synonym__iexact": normalized,
                "limit": max(max_results, 20),
            })
            syn_molecules = _dedupe_by_id(syn_data.get("molecules", []) or [])
            if len(syn_molecules) == 1:
                m = syn_molecules[0]
                return {
                    "input_name": name,
                    "normalized_name": normalized,
                    "matched_name": normalized,
                    "chembl_id": m.get("molecule_chembl_id"),
                    "preferred_name": m.get("pref_name"),
                    "match_type": "exact_synonym",
                    "candidates": [],
                }
            if len(syn_molecules) > 1:
                return _ambiguous(normalized, syn_molecules[:max(max_results, 1)])

            # Step 4: fuzzy fallback (ChEMBL's own ranked search) -- last
            # resort only, never presented as an exact match. ChEMBL's own
            # ranking is relevance-ranked full-text search, not a name
            # similarity ranking, so before trusting any hit we gate it on
            # our own deterministic name-similarity score
            # (`_best_name_similarity`) against the input -- a fabricated
            # name like "Zorblatinix-9X" can score higher on ChEMBL's raw
            # ES `score` than a genuine near-miss typo, so that raw score
            # cannot be used as the confidence signal (see
            # `_best_name_similarity` docstring).
            try:
                fuzzy_data = self._fuzzy_search_molecules(normalized, limit=max_results)
            except Exception:
                fuzzy_data = {}
            fuzzy_molecules = fuzzy_data.get("molecules", []) or []
            if not fuzzy_molecules:
                return _no_match(normalized)

            top = fuzzy_molecules[0]
            top_similarity = self._best_name_similarity(normalized, top)

            if top_similarity < FUZZY_MATCH_MIN_SIMILARITY:
                # ChEMBL's own top-ranked hit is not actually name-similar
                # to the input -- this is what let a fabricated compound
                # name silently resolve to a real but unrelated ChEMBL ID
                # (e.g. "Zorblatinix-9X" -> an unrelated real molecule).
                # Report no_match rather than a misleading "fuzzy" success;
                # chembl_id stays None. ChEMBL's own top-ranked hit is kept
                # (not re-ranked by our own similarity) so the gate is a
                # pure accept/reject filter, not a second ranking pass.
                return _no_match(normalized)

            return {
                "input_name": name,
                "normalized_name": normalized,
                "matched_name": top.get("pref_name"),
                "chembl_id": top.get("molecule_chembl_id"),
                "preferred_name": top.get("pref_name"),
                "match_type": "fuzzy",
                "candidates": [
                    {
                        "chembl_id": m.get("molecule_chembl_id"),
                        "preferred_name": m.get("pref_name"),
                    }
                    for m in fuzzy_molecules[1:max_results]
                ],
            }

        return self._execute_with_monitoring(
            "resolve_compound_name",
            name,
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
