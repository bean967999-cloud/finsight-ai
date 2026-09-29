"""Summarize an explicitly supplied local structured-trace JSONL export."""

from argparse import ArgumentParser
from pathlib import Path

from finsight.services.runtime_metrics import aggregate_runtime_metrics
from finsight.services.structured_trace import TraceEvent


def report_file(path: Path):
    events: list[TraceEvent] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                events.append(TraceEvent.model_validate_json(line))
            except ValueError as error:
                raise ValueError(f"invalid trace event at line {line_number}") from error
    return aggregate_runtime_metrics(events)


def main() -> int:
    parser = ArgumentParser(description="Summarize local structured-trace JSONL")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    print(report_file(args.input).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
