from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class QueryRequest(BaseModel):
    sql: str = Field(..., description="Requête HiveQL à exécuter")
    preferred_chart: Optional[str] = None


class NLQRequest(BaseModel):
    question: str
    schema_context: Optional[str] = ""
    preferred_chart: Optional[str] = None


class QueryResponse(BaseModel):
    sql: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    chart_suggestion: Dict[str, Any]
    explanation: Optional[str] = None


class SchemaResponse(BaseModel):
    database: str
    tables: Dict[str, List[str]]


class OverviewKPI(BaseModel):
    label: str
    value: Union[int, float]
    helper: str = ""
    is_currency: bool = False


class PeriodRevenuePoint(BaseModel):
    period: str
    revenue: Union[int, float]


class PeriodValuePoint(BaseModel):
    period: str
    value: Union[int, float]


class LabelValuePoint(BaseModel):
    label: str
    value: Union[int, float]


class CountryMetric(BaseModel):
    country: str
    orders_count: Union[int, float]
    revenue: Union[int, float]


class CategoryMetric(BaseModel):
    category: str
    sub_category: str
    revenue: Union[int, float]


class TopProductMetric(BaseModel):
    product: str
    revenue: Union[int, float]
    quantity: Union[int, float]
    orders_count: Union[int, float]


class OverviewResponse(BaseModel):
    database: str
    generated_at: str
    kpis: List[OverviewKPI]
    revenue_trend: List[PeriodRevenuePoint]
    payments: List[LabelValuePoint]
    countries: List[CountryMetric]
    category_rows: List[CategoryMetric]
    order_status: List[LabelValuePoint]
    top_products: List[TopProductMetric]
    customer_growth: List[PeriodValuePoint]
    unavailable_sections: List[str]
