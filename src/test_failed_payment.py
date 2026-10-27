
from database import get_connection
from customer_order import (
    validate_and_calculate_order,
    record_order,
    record_pending_payment,
)

# 1. Create a test order using existing products.
items, total = validate_and_calculate_order([
    {"product_id": 1, "quantity": 1},
])

order_id = record_order(
    branch_id=1,
    order_items=items,
    order_total=total,
)

# 2. Create a pending payment linked to the order.
payment_id = record_pending_payment(
    order_id=order_id,
    phone_number="+254712345678",
    amount=total,
    payment_channel="M-Pesa",
)

# 3. Assign a simulated checkout ID for our callback test.
checkout_id = f"TEST-FAIL-{payment_id}"

connection = get_connection()

try:
    connection.execute(
        """
        UPDATE payments
        SET checkout_request_id = ?
        WHERE payment_id = ?
        """,
        (checkout_id, payment_id),
    )
    connection.commit()
finally:
    connection.close()

print("Test order:", order_id)
print("Test payment:", payment_id)
print("Checkout ID:", checkout_id)
print("Expected amount: KES", total)
