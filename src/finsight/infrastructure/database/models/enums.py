from enum import StrEnum

from finsight.domain.financial_data import (
    CompanyStatus,
    ImportJobStatus,
    ImportJobType,
    ReportingPeriodType,
    SecurityType,
    StatementType,
)


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    """Persist stable business values instead of Python member names."""
    return [member.value for member in enum_class]
__all__ = [
    "CompanyStatus",
    "ImportJobStatus",
    "ImportJobType",
    "ReportingPeriodType",
    "SecurityType",
    "StatementType",
    "enum_values",
]
