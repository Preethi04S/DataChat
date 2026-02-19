import pytest
import pandas as pd
from app.planner.models import (
    QueryPlan, FilterClause, FilterOp, SortClause,
    Aggregation, AggMetric, Intent,
)
from app.executor.executor import execute_plan
from app.data.schema import DatasetSchema, ColumnInfo


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "title": ["Book A", "Book B", "Book C", "Book D", "Book E"],
        "authors": ["Author 1", "Author 2", "Author 1", "Author 3", "Author 2"],
        "average_rating": [4.5, 3.8, 4.2, 4.9, 3.5],
        "num_pages": [200, 350, 150, 500, 280],
        "categories": ["Fiction", "Science", "Fiction", "History", "Science"],
        "published_year": [2000, 2005, 2010, 1995, 2020],
        "ratings_count": [1000, 500, 300, 2000, 150],
    })


@pytest.fixture
def sample_schema():
    return DatasetSchema(
        row_count=5,
        display_column="title",
        columns=[
            ColumnInfo(name="title", dtype="string", unique_count=5),
            ColumnInfo(name="authors", dtype="string", unique_count=3),
            ColumnInfo(name="average_rating", dtype="number", unique_count=5),
            ColumnInfo(name="num_pages", dtype="number", unique_count=5),
            ColumnInfo(name="categories", dtype="string", unique_count=3),
            ColumnInfo(name="published_year", dtype="number", unique_count=5),
            ColumnInfo(name="ratings_count", dtype="number", unique_count=5),
        ],
    )


def test_sort_desc(sample_df, sample_schema):
    plan = QueryPlan(
        filters=[],
        sort=SortClause(column="average_rating", direction="desc"),
        limit=3,
        intent=Intent.rank,
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 3
    assert result[0]["title"] == "Book D"
    assert result[0]["average_rating"] == 4.9


def test_filter_gt(sample_df, sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="average_rating", op=FilterOp.gt, value=4.0)],
        limit=10,
        intent=Intent.filter,
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 3
    assert all(r["average_rating"] > 4.0 for r in result)


def test_filter_contains(sample_df, sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="authors", op=FilterOp.contains, value="Author 1")],
        limit=10,
        intent=Intent.filter,
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 2


def test_filter_between(sample_df, sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="published_year", op=FilterOp.between, value=[2000, 2010])],
        limit=10,
        intent=Intent.filter,
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 3


def test_aggregation_mean(sample_df, sample_schema):
    plan = QueryPlan(
        filters=[],
        limit=10,
        intent=Intent.aggregate,
        aggregation=Aggregation(
            groupby=["categories"],
            metrics=[AggMetric(op="mean", column="average_rating")],
        ),
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 3
    fiction = next(r for r in result if r["categories"] == "Fiction")
    assert abs(fiction["__agg__mean_average_rating"] - 4.35) < 0.01


def test_aggregation_count_no_groupby(sample_df, sample_schema):
    plan = QueryPlan(
        filters=[],
        limit=10,
        intent=Intent.aggregate,
        aggregation=Aggregation(
            groupby=[],
            metrics=[AggMetric(op="count", column=None)],
        ),
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 1
    assert result[0]["__agg__count"] == 5


def test_select_columns(sample_df, sample_schema):
    plan = QueryPlan(
        select_columns=["title", "average_rating"],
        filters=[],
        limit=5,
        intent=Intent.lookup,
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert all(set(r.keys()) == {"title", "average_rating"} for r in result)


def test_filter_eq_string(sample_df, sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="categories", op=FilterOp.eq, value="Science")],
        limit=10,
        intent=Intent.filter,
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 2
    assert all(r["categories"] == "Science" for r in result)


def test_empty_result(sample_df, sample_schema):
    plan = QueryPlan(
        filters=[FilterClause(column="average_rating", op=FilterOp.gt, value=5.0)],
        limit=10,
        intent=Intent.filter,
    )
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 0


def test_limit_respected(sample_df, sample_schema):
    plan = QueryPlan(filters=[], limit=2, intent=Intent.lookup)
    result = execute_plan(plan, sample_df, sample_schema)
    assert len(result) == 2
