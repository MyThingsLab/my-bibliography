from __future__ import annotations

import pytest

from mybibliography.retrieval import Locator, retrieve


@pytest.mark.slow
def test_retrieve_doi_against_real_crossref() -> None:
    # A real, stable Crossref-registered DOI (Watson & Crick, 1953).
    candidates = retrieve(Locator("doi", "10.1038/171737a0"))
    assert candidates
    assert candidates[0].doi.lower() == "10.1038/171737a0"
