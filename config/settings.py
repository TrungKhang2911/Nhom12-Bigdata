"""Shared environment configuration (loaded lazily by entry points)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap_servers: str
    kafka_topic: str
    mongo_uri: str
    mongo_database: str
    raw_data_dir: Path
    log_level: str


def load_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    return Settings(
        os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
        os.getenv('KAFKA_TOPIC', 'raw_reviews'),
        os.getenv('MONGO_URI', 'mongodb://localhost:27017'),
        os.getenv('MONGO_DATABASE', 'sentiment'),
        Path(os.getenv('RAW_DATA_DIR', 'data/raw')),
        os.getenv('LOG_LEVEL', 'INFO'),
    )
