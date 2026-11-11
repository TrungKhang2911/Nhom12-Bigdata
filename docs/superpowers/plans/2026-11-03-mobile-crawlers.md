# Mobile crawlers implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Dựng cấu trúc README và hoàn thiện crawler Google Play / App Store.
**Architecture:** Iterator phát từng review thô kèm metadata nguồn; CLI ghi JSONL hoặc Kafka. Các module xử lý ngoài phạm vi chỉ dựng khung, không giả lập kết quả NLP.
**Tech Stack:** Python 3.10, google-play-scraper, requests, kafka-python, unittest.
**Spec:** README.md.

## Global Constraints
- Python 3.10; PySpark 3.5; JDK 11; Hadoop 3.3.6.
- Ingestion chỉ thu thập; giữ nguyên nội dung review, không chuẩn hóa unified schema.
- Kafka, Zookeeper, MongoDB là hạ tầng Docker.

## Review Focus
- Hết trang hoặc continuation token lặp: dừng hữu hạn.
- Lỗi mạng/429/5xx: retry có giới hạn; lỗi cuối phải báo thất bại.
- Feed rỗng hoặc sai cấu trúc: phân biệt rõ; không âm thầm nuốt lỗi.
- Unicode và datetime: JSON hợp lệ, không mất nội dung.
- Kafka gửi thất bại: chờ acknowledgment, không báo thành công giả.

### Task 1: Scaffold and raw transport
**Files:** config/*, src/* packages, notebooks/*, docker-compose.yml, requirements*.txt, .env.example, .gitignore.
**Interfaces:** raw envelope contains source_domain, item_id, country, language, collected_at, app, review; JSONL and Kafka consume the same dictionary.
- [x] Create packages matching README; mark unimplemented processing modules explicitly.
- [x] Add settings, logging, JSON serialization and Kafka sink.
- [x] Verify imports, JSON datetime/Unicode roundtrip and producer acknowledgment with unittest.

### Task 2: Crawlers and CLI
**Files:** src/ingestion/{common,gplay_crawler,appstore_crawler,cli,__main__}.py; tests/test_crawlers.py.
**Interfaces:** crawl(app_id, *, country, limit, ...) -> Iterator[dict]; CLI via python -m src.ingestion.
- [x] Write tests for pagination, exact limits, empty pages, invalid feeds, retries and payload preservation. Tests were added after initial implementation; the Google wrapped HTTP regression was verified failing before its fix.
- [x] Implement Google continuation pagination and Apple RSS pagination, metadata lookup, bounded retry and pacing.
- [x] Implement CLI validation, multiple IDs, JSONL append and optional Kafka delivery.
- [x] Run unittest suite and real small requests for both stores where available.

### Task 3: Documentation and verification
**Files:** README.md, docs/crawlers.md.
- [x] Document setup, commands, raw contract, limits, partial output and integration boundaries.
- [x] Run compileall, unittest, CLI help, Docker Compose validation and inspect git diff.
- [x] Report actual results and any unavailable infrastructure without claiming untested integration.
