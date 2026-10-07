"""Kafka -> Engine -> Redis + Kafka(aiops.anomalies)."""
import asyncio, json, os, sys

import redis.asyncio as aioredis
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from .engine import Engine

BOOT = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
TOPICS = ("telemetry.metrics", "telemetry.logs", "telemetry.traces")


async def connect(factory):
    while True:
        try:
            c = factory()
            await c.start()
            return c
        except Exception as e:
            print(f"[processor] waiting for kafka: {e!r}", file=sys.stderr, flush=True)
            await asyncio.sleep(3)


async def main():
    r = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
    producer = await connect(lambda: AIOKafkaProducer(bootstrap_servers=BOOT, value_serializer=lambda v: json.dumps(v).encode()))
    consumer = await connect(lambda: AIOKafkaConsumer(*TOPICS, bootstrap_servers=BOOT, group_id="aiops-processor",
                                                      auto_offset_reset="latest", value_deserializer=lambda b: json.loads(b)))

    async def publish(anomaly):
        await producer.send("aiops.anomalies", anomaly)
        print(f"[anomaly] {anomaly['service']} {anomaly['type']} {anomaly['severity']} {anomaly['detail']}", flush=True)

    engine = Engine(r, publish, mem_limit=float(os.getenv("MEM_LIMIT_MB", "256")))

    async def ticker():
        while True:
            await asyncio.sleep(2)
            try:
                await engine.tick()
            except Exception as e:
                print(f"[processor] tick error {e!r}", file=sys.stderr, flush=True)

    asyncio.create_task(ticker())
    handlers = {"telemetry.metrics": engine.on_metric, "telemetry.logs": engine.on_log, "telemetry.traces": engine.on_span}
    print("[processor] consuming", TOPICS, flush=True)
    async for msg in consumer:
        try:
            await handlers[msg.topic](msg.value)
        except Exception as e:
            print(f"[processor] error handling {msg.topic}: {e!r}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
