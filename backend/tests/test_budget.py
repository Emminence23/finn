from app.api.routes import BuildBudget


def test_build_budget_caps_per_day_and_resets():
    b = BuildBudget()
    assert [b.take(2, "2026-11-16") for _ in range(3)] == [True, True, False]
    assert b.take(2, "2026-11-17")  # new day, fresh allowance
