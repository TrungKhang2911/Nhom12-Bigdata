# Crawler delivery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish standalone mobile review collection with JSON and CSV delivery, resumable jobs and honest count reports; defer Kafka.
**Architecture:** Keep existing raw envelope and CLI compatible. Add a batch collector using SQLite as a durable local journal, transactional page cursors, and streaming exports. Google calls run in isolated processes with a deadline. Apple resumes by page. No NLP or content cleaning.
**Tech Stack:** Python 3.10, existing crawler dependencies, stdlib sqlite3/multiprocessing/csv.
**Spec:** README.md and user request to finish crawler, export JSON and CSV, and defer Kafka.

## Global Constraints
- Do not invent a dataset quota: README contains no app list or numeric target. Ask the user while implementing independent code.
- Preserve raw payloads; deduplicate delivery IDs only to make resume safe.
- JSON means a valid JSON array; additionally retain JSONL and CSV.
- Never report a shortfall as a completed quota.

## Review Focus
- Crash between review persistence and page checkpoint: transaction rolls back the page.
- Resume after completion: no duplicate fetch/export rows; increased quota can continue if cursor remains.
- One app unavailable: record error and continue other jobs.
- Apple feed exhausted: report shortfall without fabricating/repeating reviews.
- CSV nested values and Unicode/newlines/formulas: reversible payload columns and safe display fields.

### Task 1: Source cursors and Google deadlines
**Files:** src/ingestion/source_pages.py, google_transport.py. Existing crawler iterators remain compatible.
**Interfaces:** pages(job, cursor, delay=..., attempts=..., timeout=...) yields (raw_events, next_cursor, exhausted). State is JSON serializable; collector persists the page and cursor atomically.
- [x] Add checkpoint support without breaking existing raw iterator callers.
- [x] Test cursor restore, final-page state and subprocess deadline.

### Task 2: Durable local collection and exports
**Files:** src/ingestion/dataset.py, collect.py, config/crawl_jobs.example.json, tests/test_collection.py.
**Interfaces:** python -m src.ingestion.collect --config PATH --output-dir PATH; automatic resume per source/app/country/language.
- [x] Validate config before crawling; one row limit per job, global attempts/delay/timeout.
- [x] Persist pages atomically and emit status report after each job, including errors/shortfalls.
- [x] Export source-specific JSON arrays, JSONL and CSV without loading all payloads into RAM.
- [x] Test resume/rollback, increased targets, per-job failures and export round trips.

### Task 3: Delivery and verification
**Files:** README.md, docs/crawlers.md, docs/verification.md.
- [x] Document primary batch command, quota semantics, outputs, limitations and legacy CLI.
- [x] Run offline suite, compile check and real limited collection/resume checks for both stores.
- [x] Quota not supplied: collected and verified explicitly labeled sample of 3,000 reviews. Official quota remains pending user input.
