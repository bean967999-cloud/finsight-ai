"""Allowlisted financial schema context and deterministic text rendering."""

from finsight.domain.financial_data import (
    CompanyStatus,
    ReportingPeriodType,
    SecurityType,
    StatementType,
)
from finsight.domain.query_schema import (
    QueryColumn,
    QueryDataType,
    QueryRelationship,
    QuerySchemaContext,
    QueryTable,
)

COMPANY_STATUSES = tuple(item.value for item in CompanyStatus)
SECURITY_TYPES = tuple(item.value for item in SecurityType)
REPORTING_PERIOD_TYPES = tuple(item.value for item in ReportingPeriodType)
STATEMENT_TYPES = tuple(item.value for item in StatementType)


def _column(
    name: str,
    data_type: QueryDataType,
    description: str,
    *,
    nullable: bool = False,
    selectable: bool = True,
    filterable: bool = True,
    groupable: bool = False,
    orderable: bool = False,
    unit: str | None = None,
    allowed_values: tuple[str, ...] = (),
) -> QueryColumn:
    return QueryColumn(
        name=name, data_type=data_type, description=description, nullable=nullable,
        selectable=selectable, filterable=filterable, groupable=groupable,
        orderable=orderable, unit=unit, allowed_values=allowed_values,
    )


def build_financial_query_schema() -> QuerySchemaContext:
    """Return the reviewed v1 schema, not unrestricted database reflection."""
    tables = (
        QueryTable(
            name="companies",
            description="公司主体信息；使用 company_code 作为对外稳定标识。",
            columns=(
                _column("id", QueryDataType.INTEGER, "内部关联键。", selectable=False),
                _column("company_code", QueryDataType.STRING, "公司业务代码。", groupable=True),
                _column("legal_name", QueryDataType.STRING, "公司法定名称。", groupable=True),
                _column("short_name", QueryDataType.STRING, "公司简称。", nullable=True, groupable=True),
                _column("industry", QueryDataType.STRING, "所属行业。", nullable=True, groupable=True),
                _column("country", QueryDataType.STRING, "ISO 3166-1 两位国家代码。", groupable=True),
                _column("established_date", QueryDataType.DATE, "公司成立日期。", nullable=True, orderable=True),
                _column(
                    "status", QueryDataType.STRING, "公司状态。", groupable=True,
                    allowed_values=COMPANY_STATUSES,
                ),
            ),
        ),
        QueryTable(
            name="securities",
            description="证券身份与上市信息；同一公司可以有多个证券。",
            columns=(
                _column("id", QueryDataType.INTEGER, "内部证券关联键。", selectable=False),
                _column("company_id", QueryDataType.INTEGER, "关联公司内部键。", selectable=False),
                _column("exchange", QueryDataType.STRING, "交易所代码。", groupable=True),
                _column("ticker", QueryDataType.STRING, "交易代码。", groupable=True),
                _column("name", QueryDataType.STRING, "证券名称。", groupable=True),
                _column(
                    "security_type", QueryDataType.STRING, "证券类型。", groupable=True,
                    allowed_values=SECURITY_TYPES,
                ),
                _column("currency", QueryDataType.STRING, "证券计价币种。", groupable=True),
                _column("listing_date", QueryDataType.DATE, "上市日期。", nullable=True, orderable=True),
                _column("delisting_date", QueryDataType.DATE, "退市日期。", nullable=True, orderable=True),
                _column("is_active", QueryDataType.BOOLEAN, "是否仍为有效证券。", groupable=True),
            ),
        ),
        QueryTable(
            name="financial_statements",
            description="资产负债表、利润表和现金流量表的标准化科目值。",
            columns=(
                _column("company_id", QueryDataType.INTEGER, "关联公司内部键。", selectable=False),
                _column("report_date", QueryDataType.DATE, "报告期截止日，不等同于发布日期。", groupable=True, orderable=True),
                _column(
                    "period_type", QueryDataType.STRING, "报告期间类型。", groupable=True,
                    allowed_values=REPORTING_PERIOD_TYPES,
                ),
                _column(
                    "statement_type", QueryDataType.STRING, "财务报表类型。", groupable=True,
                    allowed_values=STATEMENT_TYPES,
                ),
                _column("item_code", QueryDataType.STRING, "标准化财务科目代码。", groupable=True),
                _column("item_name", QueryDataType.STRING, "财务科目名称。", groupable=True),
                _column("value", QueryDataType.DECIMAL, "科目数值；必须结合 unit 和 currency 解读。", nullable=True, orderable=True, unit="由 unit 与 currency 列共同决定"),
                _column("currency", QueryDataType.STRING, "金额币种；非金额科目仍需结合 unit。", groupable=True),
                _column("unit", QueryDataType.STRING, "数值单位，例如 yuan、thousand_yuan。", groupable=True),
                _column("consolidation_scope", QueryDataType.STRING, "合并或母公司口径。", groupable=True),
                _column("data_version", QueryDataType.INTEGER, "同一来源的数据修订版本。", selectable=False, orderable=True),
            ),
        ),
        QueryTable(
            name="financial_indicators",
            description="已经标准化或计算得到的财务指标。",
            columns=(
                _column("company_id", QueryDataType.INTEGER, "关联公司内部键。", selectable=False),
                _column("report_date", QueryDataType.DATE, "指标所属报告期截止日。", groupable=True, orderable=True),
                _column(
                    "period_type", QueryDataType.STRING, "报告期间类型。", groupable=True,
                    allowed_values=REPORTING_PERIOD_TYPES,
                ),
                _column("indicator_code", QueryDataType.STRING, "标准化指标代码。", groupable=True),
                _column("indicator_name", QueryDataType.STRING, "指标名称。", groupable=True),
                _column("value", QueryDataType.DECIMAL, "指标数值，必须结合 unit 解读。", nullable=True, orderable=True, unit="由 unit 列决定"),
                _column("unit", QueryDataType.STRING, "指标单位，例如 percent、ratio。", groupable=True),
                _column("calculation_method", QueryDataType.STRING, "指标计算方法或口径说明。", nullable=True, filterable=False),
                _column("data_version", QueryDataType.INTEGER, "同一来源的数据修订版本。", selectable=False, orderable=True),
            ),
        ),
        QueryTable(
            name="market_prices",
            description="证券日频行情；价格币种来自 securities.currency。",
            columns=(
                _column("security_id", QueryDataType.INTEGER, "关联证券内部键。", selectable=False),
                _column("trade_date", QueryDataType.DATE, "交易日期。", groupable=True, orderable=True),
                _column("open_price", QueryDataType.DECIMAL, "开盘价。", orderable=True, unit="securities.currency/股"),
                _column("high_price", QueryDataType.DECIMAL, "最高价。", orderable=True, unit="securities.currency/股"),
                _column("low_price", QueryDataType.DECIMAL, "最低价。", orderable=True, unit="securities.currency/股"),
                _column("close_price", QueryDataType.DECIMAL, "收盘价。", orderable=True, unit="securities.currency/股"),
                _column("volume", QueryDataType.DECIMAL, "成交量。", orderable=True, unit="股"),
                _column("amount", QueryDataType.DECIMAL, "成交额。", nullable=True, orderable=True, unit="securities.currency"),
                _column("adjustment_type", QueryDataType.STRING, "复权口径。", groupable=True),
                _column("data_version", QueryDataType.INTEGER, "同一来源的数据修订版本。", selectable=False, orderable=True),
            ),
        ),
    )
    relationships = (
        QueryRelationship(
            left_table="securities", left_column="company_id",
            right_table="companies", right_column="id", cardinality="many-to-one",
            description="证券所属公司。",
        ),
        QueryRelationship(
            left_table="financial_statements", left_column="company_id",
            right_table="companies", right_column="id", cardinality="many-to-one",
            description="财务报表科目所属公司。",
        ),
        QueryRelationship(
            left_table="financial_indicators", left_column="company_id",
            right_table="companies", right_column="id", cardinality="many-to-one",
            description="财务指标所属公司。",
        ),
        QueryRelationship(
            left_table="market_prices", left_column="security_id",
            right_table="securities", right_column="id", cardinality="many-to-one",
            description="日行情所属证券。",
        ),
    )
    return QuerySchemaContext(version="v1", dialect="postgres", tables=tables, relationships=relationships)


def render_query_schema(context: QuerySchemaContext) -> str:
    """Render only reviewed metadata in a deterministic, compact form."""
    lines = [f"schema_version={context.version}; dialect={context.dialect}"]
    for table in context.tables:
        lines.append(f"TABLE {table.name}: {table.description}")
        for column in table.columns:
            access = [
                name for name, enabled in (
                    ("select", column.selectable), ("filter", column.filterable),
                    ("group", column.groupable), ("order", column.orderable),
                ) if enabled
            ]
            details = [column.data_type.value, f"access={','.join(access) or 'join-only'}"]
            if column.nullable:
                details.append("nullable")
            if column.unit:
                details.append(f"unit={column.unit}")
            if column.allowed_values:
                details.append(f"values={','.join(column.allowed_values)}")
            lines.append(f"  {column.name} [{'; '.join(details)}]: {column.description}")
    lines.append("RELATIONSHIPS")
    for relation in context.relationships:
        lines.append(
            f"  {relation.left_table}.{relation.left_column} -> "
            f"{relation.right_table}.{relation.right_column} "
            f"[{relation.cardinality}]: {relation.description}"
        )
    return "\n".join(lines)
