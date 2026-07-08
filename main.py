from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from uuid import uuid4
import time
import base64

app = FastAPI()

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Accepts browser requests
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOTAL_ORDERS = 55
RATE_LIMIT = 15
WINDOW = 10  # seconds


# ----------------------------
# In-memory storage
# ----------------------------
idempotency_store = {}
created_orders = []

client_requests = {}


class OrderCreate(BaseModel):
    item: str = "default"
    quantity: int = 1


# ----------------------------
# Rate Limiter
# ----------------------------
def check_rate_limit(client_id: str, response: Response):
    now = time.time()

    timestamps = client_requests.get(client_id, [])

    timestamps = [t for t in timestamps if now - t < WINDOW]

    if len(timestamps) >= RATE_LIMIT:
        retry_after = WINDOW - (now - timestamps[0])
        response.headers["Retry-After"] = str(max(1, int(retry_after)))
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )

    timestamps.append(now)
    client_requests[client_id] = timestamps


# ----------------------------
# POST /orders (Idempotent)
# ----------------------------
@app.post("/orders", status_code=201)
def create_order(
    order: OrderCreate,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    client_id: str = Header(..., alias="X-Client-Id"),
):

    check_rate_limit(client_id, response)

    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    new_order = {
        "id": str(uuid4()),
        "item": order.item,
        "quantity": order.quantity,
    }

    idempotency_store[idempotency_key] = new_order
    created_orders.append(new_order)

    return new_order


# ----------------------------
# Cursor Helpers
# ----------------------------
def encode_cursor(index: int):
    return base64.urlsafe_b64encode(str(index).encode()).decode()


def decode_cursor(cursor: Optional[str]):
    if not cursor:
        return 0
    return int(base64.urlsafe_b64decode(cursor.encode()).decode())


# ----------------------------
# GET /orders (Cursor Pagination)
# ----------------------------
@app.get("/orders")
def list_orders(
    limit: int = 10,
    cursor: Optional[str] = None,
    response: Response = None,
    client_id: str = Header(..., alias="X-Client-Id"),
):

    check_rate_limit(client_id, response)

    start = decode_cursor(cursor)

    end = min(start + limit, TOTAL_ORDERS)

    items = [
        {
            "id": i,
            "item": f"Order-{i}"
        }
        for i in range(start + 1, end + 1)
    ]

    next_cursor = None
    if end < TOTAL_ORDERS:
        next_cursor = encode_cursor(end)

    return {
        "items": items,
        "next_cursor": next_cursor
    }