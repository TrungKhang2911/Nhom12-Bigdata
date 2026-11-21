import argparse
import json
import uuid
from pathlib import Path

from src.serving.mongo_client import ingest_raw_events


def import_file(path: Path, source: str, run_id: str, batch_size: int):
    batch = []
    total_received = 0
    totals = {"inserted": 0, "already_existed": 0}

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                batch.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"Loi JSON {path}, dong {line_number}: {exc}")
                continue

            if len(batch) >= batch_size:
                result = ingest_raw_events(batch, run_id=run_id)
                total_received += result["received"]
                totals["inserted"] += result["inserted"]
                totals["already_existed"] += result["already_existed"]
                print(f"{source}: da xu ly {total_received} dong")
                batch.clear()

    if batch:
        result = ingest_raw_events(batch, run_id=run_id)
        total_received += result["received"]
        totals["inserted"] += result["inserted"]
        totals["already_existed"] += result["already_existed"]

    return {
        "received": total_received,
        "inserted": totals["inserted"],
        "already_existed": totals["already_existed"],
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

    for source in args.sources:
        path = input_dir / f"{source}.jsonl"

        if not path.exists():
            print(f"Bo qua {source}: khong tim thay {path}")
            continue

        result = import_file(path, source, run_id, args.batch_size)
        print(f"{source}: {result}")
        total_received += result["received"]

    print(f"Hoan tat. Tong so dong da doc: {total_received}")
    print(f"Ma dot nap: {run_id}")


if __name__ == "__main__":
    main()