
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
        metadata = callback.get("CallbackMetadata", {})
        items = metadata.get("Item", [])

        details = {
            item.get("Name"): item.get("Value")
            for item in items
        }

        mpesa_reference = details.get("MpesaReceiptNumber")
        paid_amount = details.get("Amount")

        # Start a transaction before changing payment or order status.
        connection.execute("BEGIN")

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
            # Determine the outcome of this callback.
            if str(result_code) == "0":
                # Confirm the amount safely before marking the payment complete.
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
                    payment_status = "COMPLETED"

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

            # Update the order only when its payment outcome is confirmed.
            if payment_status == "COMPLETED":
                cursor.execute("""
                    UPDATE orders
                    SET order_status = 'PAID'
                    WHERE order_id = ?
                      AND order_status = 'PENDING_PAYMENT'
                """, (order_id,))

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
