import pytest

from biotoolsllmannotate.cli.run import to_entry


@pytest.mark.benchmark
def test_batch_processing_perf(benchmark):
    # Simulate 100 candidate dicts
    candidates = [
        {
            "title": f"Tool{i}",
            "description": "desc",
            "urls": [f"https://tool{i}.org"],
            "tags": ["genomics"],
        }
        for i in range(100)
    ]
    homepages = [f"https://tool{i}.org" for i in range(100)]

    def batch():
        return [to_entry(c, h) for c, h in zip(candidates, homepages, strict=False)]

    result = benchmark(batch)
    # median < 500 ms/candidate (total < 50s for 100)
    median = benchmark.stats["median"]
    assert median < 0.5
