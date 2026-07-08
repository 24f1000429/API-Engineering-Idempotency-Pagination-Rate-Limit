from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from uuid import uuid4
import time
import base64

app = FastAPI()

# ----------------------------
# CORS
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Constants
# ----------------------------
TOTAL_ORDERS = 55
RATE_LIMIT = 15
WINDOW = 10  # seconds

# ----------------------------
# In-memory storage
# ----------------------------
idempotency_store = {}
client_requests = {}


class OrderCreate(BaseModel):
    item: str = "default"
    quantity: int = 1


# ----------------------------
# Rate Limiter
# ----------------------------
def check_rate_limit(client_id: str):
    now = time.time()

    timestamps = client_requests.get(client_id, [])

    # Keep only requests within the last WINDOW seconds
    timestamps = [t for t in timestamps if now - t < WINDOW]

    if len(timestamps) >= RATE_LIMIT:
        retry_after = max(1, int(WINDOW - (now - timestamps[0])))

        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={
                "Retry-After": str(retry_after)
            },
        )

    timestamps.append(now)
    client_requests[client_id] = timestamps
    return None


# ----------------------------
# Cursor Helpers
# ----------------------------
def encode_cursor(index: int) -> str:
    return base64.urlsafe_b64encode(str(index).encode()).decode()


def decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    return int(base64.urlsafe_b64decode(cursor.encode()).decode())


# ----------------------------
# POST /orders
# ----------------------------
@app.post("/orders", status_code=201)
def create_order(
    order: OrderCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    client_id: str = Header(..., alias="X-Client-Id"),
):
    limited = check_rate_limit(client_id)
    if limited:
        return limited

    # Idempotent response
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    new_order = {
        "id": str(uuid4()),
        "item": order.item,
        "quantity": order.quantity,
    }

    idempotency_store[idempotency_key] = new_order

    return JSONResponse(
        status_code=201,
        content=new_order,
    )


# ----------------------------
# GET /orders
# ----------------------------
@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: Optional[str] = None,
    client_id: str = Header(..., alias="X-Client-Id"),
):
    limited = check_rate_limit(client_id)
    if limited:
        return limited

    # Safety
    limit = max(1, limit)

    start = decode_cursor(cursor)
    end = min(start + limit, TOTAL_ORDERS)

    items = [
        {
            "id": i,
            "item": f"Order-{i}",
        }
        for i in range(start + 1, end + 1)
    ]

    next_cursor = None
    if end < TOTAL_ORDERS:
        next_cursor = encode_cursor(end)

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


# ----------------------------
# Health Check
# ----------------------------
@app.get("/")
def root():
    return {"status": "ok"}
