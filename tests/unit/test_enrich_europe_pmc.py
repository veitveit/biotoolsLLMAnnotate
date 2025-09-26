from biotoolsllmannotate.enrich.europe_pmc import (
    enrich_candidates_with_europe_pmc,
    reset_europe_pmc_cache,
)


class DummyResponse:
    def __init__(self, *, json_data=None, text="", status=200):
        self._json = json_data
        self.text = text
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


def test_enrich_adds_abstract(monkeypatch):
    search_payload = {
        "resultList": {
            "result": [
                {
                    "title": "Sample Publication",
                    "abstractText": "This is an abstract.",
                    "pmcid": None,
                    "pmid": "12345",
                }
            ]
        }
    }

    responses = iter([DummyResponse(json_data=search_payload)])

    def fake_get(url, params=None, timeout=None):
        return next(responses)

    monkeypatch.setattr(
        "biotoolsllmannotate.enrich.europe_pmc.requests.get", fake_get
    )

    candidates = [
        {"title": "Tool", "publication": [{"PMID": "12345"}]}
    ]

    config = {
        "enabled": True,
        "include_full_text": False,
        "timeout": 10,
        "max_publications": 1,
    }

    enrich_candidates_with_europe_pmc(
        candidates,
        config=config,
        logger=None,
        offline=False,
    )

    assert candidates[0]["publication_abstract"] == "This is an abstract."
    assert "publication_full_text" not in candidates[0]
    assert candidates[0]["publication_ids"] == ["pmid:12345"]
    reset_europe_pmc_cache()


def test_enrich_adds_full_text_when_available(monkeypatch):
    search_payload = {
        "resultList": {
            "result": [
                {
                    "title": "Sample Publication",
                    "abstractText": "This is an abstract.",
                    "pmcid": "PMC1234567",
                    "pmid": "12345",
                    "fullTextUrlList": {
                        "fullTextUrl": [
                            {"url": "https://example.org/fulltext.pdf"}
                        ]
                    },
                }
            ]
        }
    }

    fulltext_xml = "<article><body><p>This is the full text content.</p></body></article>"

    responses = iter(
        [
            DummyResponse(json_data=search_payload),
            DummyResponse(text=fulltext_xml),
        ]
    )

    def fake_get(url, params=None, timeout=None):
        return next(responses)

    monkeypatch.setattr(
        "biotoolsllmannotate.enrich.europe_pmc.requests.get", fake_get
    )

    candidates = [
        {"title": "Tool", "publication": [{"PMCID": "PMC1234567", "pmid": "12345"}]}
    ]

    config = {
        "enabled": True,
        "include_full_text": True,
        "timeout": 10,
        "max_publications": 1,
        "max_full_text_chars": 100,
    }

    enrich_candidates_with_europe_pmc(
        candidates,
        config=config,
        logger=None,
        offline=False,
    )

    assert "This is the full text content." in candidates[0]["publication_full_text"]
    assert candidates[0]["publication_abstract"] == "This is an abstract."
    assert set(candidates[0]["publication_ids"]) == {"pmid:12345", "pmcid:PMC1234567"}
    reset_europe_pmc_cache()
