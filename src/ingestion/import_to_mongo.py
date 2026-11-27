import argparse
import json
import uuid
from pathlib import Path

from src.serving.mongo_client import (
    close_client,
    finish_pipeline_run,
    ingest_raw_events,
    record_rejected_records,
    start_pipeline_run,
)


def import_file(path: Path, source: str, run_id: str, batch_size: int):
    batch = []
    parse_errors = []
    total_received = 0
    totals = {"inserted": 0, "already_existed": 0, "rejected": 0}

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                batch.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"Loi JSON {path}, dong {line_number}: {exc}")
                parse_errors.append(
                    {
                        "source_domain": source,
                        "reason": f"json_decode_error: {exc}",
                        "raw_payload": line.strip(),
                        "file_path": str(path),
                        "line_number": line_number,
                    }
                )
                totals["rejected"] += 1
                if len(parse_errors) >= batch_size:
                    record_rejected_records(run_id, parse_errors)
                    parse_errors.clear()
                continue

            if len(batch) >= batch_size:
                result = ingest_raw_events(batch, run_id=run_id)
                total_received += result["received"]
                totals["inserted"] += result["inserted"]
                totals["already_existed"] += result["already_existed"]
                totals["rejected"] += result.get("rejected", 0)
                print(f"{source}: da xu ly {total_received} dong")
                batch.clear()

    if batch:
        result = ingest_raw_events(batch, run_id=run_id)
        total_received += result["received"]
        totals["inserted"] += result["inserted"]
        totals["already_existed"] += result["already_existed"]
        totals["rejected"] += result.get("rejected", 0)

    if parse_errors:
        record_rejected_records(run_id, parse_errors)

    return {
        "received": total_received,
        "inserted": totals["inserted"],
        "already_existed": totals["already_existed"],
        "rejected": totals["rejected"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="data/raw/mobile_reviews")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["google_play", "app_store", "tiki"],
    )
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size phai lon hon 0")

    input_dir = Path(args.input_dir)
    run_id = str(uuid.uuid4())
    total_received = 0
    total_inserted = 0
    total_existing = 0
    total_rejected = 0
    per_source = {}

    start_pipeline_run(
        run_id=run_id,
        stage="raw_import",
        metadata={
            "input_dir": str(input_dir),
            "sources": args.sources,
            "batch_size": args.batch_size,
        },
    )

    try:
        for source in args.sources:
            path = input_dir / f"{source}.jsonl"

            if not path.exists():
                print(f"Bo qua {source}: khong tim thay {path}")
                continue

            result = import_file(path, source, run_id, args.batch_size)
            print(f"{source}: {result}")
            per_source[source] = result
            total_received += result["received"]
            total_inserted += result["inserted"]
            total_existing += result["already_existed"]
            total_rejected += result["rejected"]

        status = "partial" if total_rejected > 0 else "succeeded"
        finish_pipeline_run(
            run_id=run_id,
            status=status,
            stats={
                "received": total_received,
                "inserted": total_inserted,
                "already_existed": total_existing,
                "rejected": total_rejected,
                "per_source": per_source,
            },
        )
        print(f"Hoan tat. Tong so dong da doc: {total_received}")
        print(f"Ma dot nap: {run_id}")
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_id,
            status="failed",
            stats={
                "received": total_received,
                "inserted": total_inserted,
                "already_existed": total_existing,
                "rejected": total_rejected,
                "per_source": per_source,
            },
            error=exc,
        )
        raise
    finally:
        close_client()


if __name__ == "__main__":
    main()
