import pytest
from app.planner.models import QueryPlan, FilterClause, FilterOp, SortClause, Aggregation, AggMetric, Intent
from app.planner.validator import validate_plan, ValidationError
from app.data.schema import DatasetSchema, ColumnInfo


@pytest.fixture
def sample_schema():
    return DatasetSchema(
        row_count=100,
        display_column="title",
        columns=[
            ColumnInfo(name="title", dtype="string", unique_count=100),
            ColumnInfo(name="authors", dtype="string", unique_count=80),
            ColumnInfo(name="average_rating", dtype="number", unique_count=40),
            ColumnInfo(name="num_pages", dtype="number", unique_count=90),
            ColumnInfo(name="published_year", dtype="number", unique_count=50),
            ColumnInfo(name="categories", dtype="string", unique_count=30),
            ColumnInfo(name="ratings_count", dtype="number", unique_count=95),
        ],
    )


def test_valid_plan_passes(sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="average_rating", op=FilterOp.gt, value=4.0)],
        sort=SortClause(column="average_rating", direction="desc"),
        limit=10,
        intent=Intent.rank,
    )
    result = validate_plan(plan, sample_schema)
    assert result.limit == 10
    assert result.sort.column == "average_rating"


def test_unknown_column_rejected(sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="nonexistent_col", op=FilterOp.eq, value="foo")],
        limit=10,
        intent=Intent.filter,
    )
    with pytest.raises(ValidationError, match="Unknown column"):
        validate_plan(plan, sample_schema)


def test_contains_on_numeric_rejected(sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="average_rating", op=FilterOp.contains, value="4")],
        limit=10,
        intent=Intent.filter,
    )
    with pytest.raises(ValidationError, match="contains"):
        validate_plan(plan, sample_schema)


def test_between_requires_two_values(sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="published_year", op=FilterOp.between, value=[2000])],
        limit=10,
        intent=Intent.filter,
    )
    with pytest.raises(ValidationError, match="between"):
        validate_plan(plan, sample_schema)


def test_limit_capped(sample_schema):
    plan = QueryPlan(filters=[], limit=50, intent=Intent.filter)
    result = validate_plan(plan, sample_schema)
    assert result.limit == 50


def test_aggregation_mean_on_string_rejected(sample_schema):
    plan = QueryPlan(
        filters=[],
        limit=10,
        intent=Intent.aggregate,
        aggregation=Aggregation(
            groupby=["categories"],
            metrics=[AggMetric(op="mean", column="authors")],
        ),
    )
    with pytest.raises(ValidationError, match="numeric"):
        validate_plan(plan, sample_schema)


def test_aggregation_valid(sample_schema):
    plan = QueryPlan(
        filters=[],
        limit=10,
        intent=Intent.aggregate,
        aggregation=Aggregation(
            groupby=["categories"],
            metrics=[AggMetric(op="mean", column="average_rating")],
        ),
    )
    result = validate_plan(plan, sample_schema)
    assert result.aggregation.groupby == ["categories"]


def test_synonym_resolution(sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="rating", op=FilterOp.gt, value=4.0)],
        limit=5,
        intent=Intent.rank,
    )
    result = validate_plan(plan, sample_schema)
    assert result.filters[0].column == "average_rating"


def test_select_unknown_column_rejected(sample_schema):
    plan = QueryPlan(
        select_columns=["title", "bad_column"],
        filters=[],
        limit=10,
        intent=Intent.lookup,
    )
    with pytest.raises(ValidationError, match="Unknown column"):
        validate_plan(plan, sample_schema)


def test_sort_unknown_column_rejected(sample_schema):
    plan = QueryPlan(
        filters=[],
        sort=SortClause(column="fake_column", direction="desc"),
        limit=10,
        intent=Intent.rank,
    )
    with pytest.raises(ValidationError, match="Unknown column"):
        validate_plan(plan, sample_schema)


def test_numeric_value_conversion(sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="average_rating", op=FilterOp.gt, value="3.5")],
        limit=10,
        intent=Intent.filter,
    )
    result = validate_plan(plan, sample_schema)
    assert result.filters[0].value == 3.5
