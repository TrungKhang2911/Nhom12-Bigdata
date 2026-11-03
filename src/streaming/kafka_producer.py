"""Acknowledged raw event delivery. No business transformations."""
from kafka import KafkaProducer

from src.ingestion.common import dumps


class RawReviewProducer:
    def __init__(self, bootstrap_servers, topic):
        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(','),
            acks='all', retries=3,
            value_serializer=lambda value: dumps(value).encode('utf-8'),
            key_serializer=lambda key: key.encode('utf-8'),
        )

    def send(self, event):
        key = f"{event['source_domain']}:{event['item_id']}"
        self.producer.send(self.topic, key=key, value=event).get(timeout=60)

    def close(self):
        try:
            self.producer.flush(timeout=60)
        finally:
            self.producer.close(timeout=60)
