"""Steady synthetic traffic against the gateway (sinusoidal rate, mixed endpoints)."""
import asyncio, math, os, random, time

import httpx

TARGET = os.getenv("TARGET", "http://gateway:8000")
RPS = float(os.getenv("LOAD_RPS", "6"))


async def one(c, sem):
    async with sem:
        r = random.random()
        try:
            if r < 0.6:
                await c.post(f"{TARGET}/api/checkout", json={"user_id": random.randint(1, 500), "amount": random.randint(5, 400)})
            elif r < 0.85:
                await c.get(f"{TARGET}/api/users/{random.randint(1, 500)}")
            else:
                await c.get(f"{TARGET}/api/orders/{random.randint(1000, 9999)}")
        except httpx.HTTPError:
            pass


async def main():
    sem = asyncio.Semaphore(150)
    async with httpx.AsyncClient(timeout=6) as c:
        while True:
            rate = RPS * (1 + 0.25 * math.sin(time.time() / 60))
            asyncio.create_task(one(c, sem))
            await asyncio.sleep(random.expovariate(rate))


if __name__ == "__main__":
    asyncio.run(main())
