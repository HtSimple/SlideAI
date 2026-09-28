from slideai.domain.tasks.complexity import ComplexityTier, score_complexity


def test_complexity_boundaries_select_expected_tier() -> None:
    low = score_complexity(
        target_page_count=8,
        estimated_reference_tokens=20_000,
        constraint_count=2,
        domain_expertise="general",
        analysis_depth="overview",
    )
    middle = score_complexity(
        target_page_count=9,
        estimated_reference_tokens=20_001,
        constraint_count=3,
        domain_expertise="professional",
        analysis_depth="comparison",
    )
    high = score_complexity(
        target_page_count=16,
        estimated_reference_tokens=100_001,
        constraint_count=6,
        domain_expertise="specialized",
        analysis_depth="strategic",
    )

    assert (low.total_score, low.tier) == (0, ComplexityTier.FAST)
    assert (middle.total_score, middle.tier) == (5, ComplexityTier.BALANCED)
    assert (high.total_score, high.tier) == (10, ComplexityTier.ADVANCED)
