
from fastapi import APIRouter, Body
from src.database import get_connection

router = APIRouter()



@router.post("/mpesa/callback")
async def mpesa_callback(callback_data: dict = Body(...)):
    # Extract Safaricom's callback information.
    try:
        callback = callback_data["Body"]["stkCallback"]
    except (KeyError, TypeError):
        print("Invalid M-Pesa callback received.")
        return {
            "ResultCode": 0,
            "ResultDesc": "Accepted"
        }

    checkout_request_id = callback.get("CheckoutRequestID")
    result_code = callback.get("ResultCode")
    result_description = callback.get("ResultDesc", "")

    # Find the payment record created earlier.
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT payment_id, order_id, amount
            FROM payments
            WHERE checkout_request_id = ?
        """, (checkout_request_id,))

        payment = cursor.fetchone()

        if payment is None:
            print(
                "No payment found for CheckoutRequestID:",
                checkout_request_id
            )
            return {
                "ResultCode": 0,
                "ResultDesc": "Accepted"
            }

        payment_id, order_id, expected_amount = payment

        # Read extra details included when payment succeeds.
        metadata = callback.get("CallbackMetadata") or {}
        items = metadata.get("Item") or []

        details = {
            item.get("Name"): item.get("Value")
            for item in items
        }

        mpesa_reference = details.get("MpesaReceiptNumber")
        paid_amount = details.get("Amount")

        # Start a write transaction before checking or changing statuses.
        connection.execute("BEGIN IMMEDIATE")

        cursor.execute("""
            SELECT payment_status
            FROM payments
            WHERE payment_id = ?
        """, (payment_id,))

        status_row = cursor.fetchone()

        if status_row is None:
            raise ValueError(f"Payment not found: {payment_id}")

        current_status = status_row[0]

        if current_status == "COMPLETED":
            # Never allow a duplicate callback to reverse a completed payment.
            connection.commit()
            print("Duplicate callback ignored:", payment_id)

        else:
            order_status = None

            # Determine the outcome of this callback.
            if str(result_code) == "0":
                # Confirm the amount before considering stock availability.
                try:
                    amount_matches = (
                        paid_amount is not None
                        and round(float(paid_amount), 2)
                        == round(float(expected_amount), 2)
                    )
                except (TypeError, ValueError):
                    amount_matches = False

                if not amount_matches:
                    payment_status = "REVIEW_REQUIRED"
                    print(
                        "Payment amount is missing or does not match:",
                        order_id
                    )

                else:
                    # Check stock before confirming the order as PAID.
                    if has_sufficient_stock(cursor, order_id):
                        payment_status = "COMPLETED"
                        order_status = "PAID"

                    else:
                        # Money was received, but stock is insufficient.
                        payment_status = "COMPLETED"
                        order_status = "REVIEW_REQUIRED"

                        print(
                            "Payment received, but stock is insufficient:",
                            order_id
                        )

            elif str(result_code) == "1032":
                payment_status = "CANCELLED"

            else:
                payment_status = "FAILED"

            # Update the payment record.
            cursor.execute("""
                UPDATE payments
                SET payment_status = ?,
                    result_code = ?,
                    result_description = ?,
                    mpesa_reference = ?
                WHERE payment_id = ?
                  AND payment_status != 'COMPLETED'
            """, (
                payment_status,
                str(result_code),
                result_description,
                mpesa_reference,
                payment_id
            ))

            # Update the order according to the payment outcome.
            if order_status in ("PAID", "REVIEW_REQUIRED"):
                cursor.execute("""
                    UPDATE orders
                    SET order_status = ?
                    WHERE order_id = ?
                      AND order_status = 'PENDING_PAYMENT'
                """, (order_status, order_id))

            elif payment_status == "FAILED":
                cursor.execute("""
                    UPDATE orders
                    SET order_status = 'PAYMENT_FAILED'
                    WHERE order_id = ?
                      AND order_status = 'PENDING_PAYMENT'
                """, (order_id,))

            connection.commit()

            print("Payment updated:", payment_id)
            print("Payment status:", payment_status)
            print("Order:", order_id)

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return {
        "ResultCode": 0,
        "ResultDesc": "Accepted"
    }


#=================================================
#IN CASE THE STOCK AVAILABLE IS INSUFFICIENT
#================================================
def has_sufficient_stock(cursor, order_id):
    """
    Check whether an order can be fulfilled using current sellable stock.

    Only successfully paid orders are deducted from available stock.
    """

    cursor.execute("""
        SELECT branch_id, order_date
        FROM orders
        WHERE order_id = ?
    """, (order_id,))

    order = cursor.fetchone()

    if order is None:
        return False

    branch_id, order_date = order

    cursor.execute("""
        SELECT product_id, SUM(quantity)
        FROM order_items
        WHERE order_id = ?
        GROUP BY product_id
    """, (order_id,))

    requested_items = cursor.fetchall()
    if not requested_items:
        return False

    for product_id, requested_quantity in requested_items:

        cursor.execute("""
            SELECT
                di.starting_quantity,
                di.deliveries_quantity,
                p.stock_handling
            FROM daily_business db
            JOIN daily_inventory di
                ON di.daily_id = db.daily_id
            JOIN products p
                ON p.product_id = di.product_id
            WHERE db.branch_id = ?
              AND db.business_date = ?
              AND di.product_id = ?
        """, (branch_id, order_date, product_id))

        inventory = cursor.fetchone()

        if inventory is None:
            return False

        starting_quantity, deliveries_quantity, stock_handling = inventory

        if starting_quantity is None:
            return False

        if stock_handling == "PERISHABLE":
            sellable_stock = starting_quantity

        else:
            if deliveries_quantity is None:
                return False

            sellable_stock = starting_quantity + deliveries_quantity

        cursor.execute("""
            SELECT COALESCE(SUM(oi.quantity), 0)
            FROM orders o
            JOIN order_items oi
                ON oi.order_id = o.order_id
            WHERE o.branch_id = ?
              AND o.order_date = ?
              AND o.order_status IN ('PAID', 'REVIEW_REQUIRED')
              AND oi.product_id = ?
        """, (branch_id, order_date, product_id))

        already_sold = cursor.fetchone()[0]

        remaining_stock = sellable_stock - already_sold

        if requested_quantity > remaining_stock:
            return False

    return True