"""One image, five microservices. SERVICE_NAME selects which routes are registered."""
import asyncio, os, random

from fastapi import Request
from aiops_common.app import UpstreamError, create_app

SERVICE = os.environ.get("SERVICE_NAME", "gateway")


async def work(lo, hi):
    await asyncio.sleep(random.uniform(lo, hi) / 1000)


def gateway(app, ctx):
    @app.get("/api/users/{uid}")
    async def user(uid: int, request: Request):
        return await ctx.call(request, "user-service", "GET", f"/users/{uid}")

    @app.post("/api/checkout")
    async def checkout(body: dict, request: Request):
        await ctx.call(request, "user-service", "GET", f"/users/{body['user_id']}")
        return await ctx.call(request, "order-service", "POST", "/orders", json=body)

    @app.get("/api/orders/{oid}")
    async def order(oid: int, request: Request):
        return await ctx.call(request, "order-service", "GET", f"/orders/{oid}")


def user_service(app, ctx):
    @app.get("/users/{uid}")
    async def get_user(uid: int):
        await work(5, 20)
        return {"id": uid, "name": f"user-{uid}", "tier": "gold" if uid % 5 == 0 else "basic"}


def order_service(app, ctx):
    @app.post("/orders")
    async def create(body: dict, request: Request):
        await ctx.call(request, "user-service", "GET", f"/users/{body['user_id']}")
        await ctx.call(request, "payment-service", "POST", "/charge", json={"amount": body["amount"]})
        try:
            await ctx.call(request, "notification-service", "POST", "/notify", json={"user_id": body["user_id"]})
        except UpstreamError:
            ctx.tel.log("WARN", "notification failed, order continues", request.state.trace[0])
        await work(10, 40)
        return {"order_id": random.randint(1000, 99999), "status": "confirmed"}

    @app.get("/orders/{oid}")
    async def get_order(oid: int):
        await work(5, 25)
        return {"order_id": oid, "status": "confirmed"}


def payment_service(app, ctx):
    @app.post("/charge")
    async def charge(body: dict):
        await work(20, 60)
        return {"approved": True, "amount": body.get("amount")}


def notification_service(app, ctx):
    @app.post("/notify")
    async def notify(body: dict):
        await work(5, 15)
        return {"queued": True}


ROUTES = {"gateway": gateway, "user-service": user_service, "order-service": order_service,
          "payment-service": payment_service, "notification-service": notification_service}
app = create_app(SERVICE, ROUTES[SERVICE])
