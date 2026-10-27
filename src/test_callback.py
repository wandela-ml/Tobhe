
import asyncio
from datetime import datetime
from uuid import uuid4

from database import get_connection
from callback import mpesa_callback


def create_test_records():
    """Create isolated test orders and payments."""
    connection = get_connection()

    test_id = uuid4().hex[:12].upper()
    now = datetime.now()

    scenarios = [
        {
            "name": "SUCCESS",
            "amount": 900,
            "result_code": 0,
            "paid_amount": 900,
            "expected_payment": "COMPLETED",
            "expected_order": "PAID",
        },
        {
            "name": "FAILURE",
            "amount": 900,
            "result_code": 1032,
            "paid_amount": None,
            "expected_payment": "FAILED",
            "expected_order": "PAYMENT_FAILED",
        },
        {
            "name": "MISMATCH",
            "amount": 900,
            "result_code": 0,
            "paid_amount": 500,
            "expected_payment": "REVIEW_REQUIRED",
            "expected_order": "PENDING_PAYMENT",
        },
    ]

    test_records = []

    try:
        cursor = connection.cursor()

        cursor.execute("SELECT branch_id FROM branches LIMIT 1")
        branch = cursor.fetchone()

        if branch is None:
            raise RuntimeError(
                "No branch exists. Seed the branches table first."
            )

        branch_id = branch[0]

        for scenario in scenarios:
            order_id = f"TBH-TEST-{test_id}-{scenario['name']}"
            payment_id = f"PAY-TEST-{test_id}-{scenario['name']}"
            checkout_id = f"WS_CO_TEST_{test_id}_{scenario['name']}"

            cursor.execute("""
                INSERT INTO orders (
                    order_id, order_date, order_time, branch_id,
                    employee_id, total_amount, order_status
                )
                VALUES (?, ?, ?, ?, NULL, ?, 'PENDING_PAYMENT')
            """, (
                order_id,
                now.date().isoformat(),
                now.strftime("%H:%M:%S"),
                branch_id,
                scenario["amount"],
            ))

            cursor.execute("""
                INSERT INTO payments (
                    payment_id, order_id, phone_number,
                    payment_date, payment_time, amount,
                    payment_channel, checkout_request_id,
                    payment_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """, (
                payment_id,
                order_id,
                "+254700000000",
                now.date().isoformat(),
                now.strftime("%H:%M:%S"),
                scenario["amount"],
                "M-Pesa TEST",
                checkout_id,
            ))

            scenario["order_id"] = order_id
            scenario["payment_id"] = payment_id
            scenario["checkout_id"] = checkout_id
            test_records.append(scenario)

        connection.commit()
        return test_records

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def build_callback(test, test_id):
    """Build a simulated Safaricom STK callback."""
    callback = {
        "MerchantRequestID": f"MR_TEST_{test_id}",
        "CheckoutRequestID": test["checkout_id"],
        "ResultCode": test["result_code"],
        "ResultDesc": (
            "The service request is successful"
            if test["result_code"] == 0
            else "Request cancelled by user"
        ),
    }

    if test["paid_amount"] is not None:
        callback["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": test["paid_amount"]},
                {"Name": "MpesaReceiptNumber", "Value": "TESTRECEIPT"},
            ]
        }

    return {"Body": {"stkCallback": callback}}


async def run_tests():
    test_records = create_test_records()
    passed = 0

    try:
        print("\nTesting Tobhe M-Pesa callback...\n")

        for test in test_records:
            payload = build_callback(test, test["checkout_id"])

            await mpesa_callback(payload)

            connection = get_connection()

            try:
                cursor = connection.cursor()

                cursor.execute("""
                    SELECT payment_status
                    FROM payments
                    WHERE payment_id = ?
                """, (test["payment_id"],))
                actual_payment = cursor.fetchone()[0]

                cursor.execute("""
                    SELECT order_status
                    FROM orders
                    WHERE order_id = ?
                """, (test["order_id"],))
                actual_order = cursor.fetchone()[0]

            finally:
                connection.close()

            success = (
                actual_payment == test["expected_payment"]
                and actual_order == test["expected_order"]
            )

            print(
                f"{test['name']}: "
                f"{'PASS' if success else 'FAIL'}"
            )
            print(f"  Payment: {actual_payment}")
            print(f"  Order:   {actual_order}")

            if not success:
                print(
                    f"  Expected payment: {test['expected_payment']}"
                )
                print(
                    f"  Expected order:   {test['expected_order']}"
                )
            else:
                passed += 1

        print(f"\nResults: {passed}/{len(test_records)} tests passed.")

    finally:
        # Remove only records created by this test run.
        connection = get_connection()

        try:
            cursor = connection.cursor()

            for test in test_records:
                cursor.execute("""
                    DELETE FROM payments
                    WHERE payment_id = ?
                """, (test["payment_id"],))

                cursor.execute("""
                    DELETE FROM orders
                    WHERE order_id = ?
                """, (test["order_id"],))

            connection.commit()
            print("Temporary test records cleaned up.")

        except Exception:
            connection.rollback()
            print(
                "WARNING: Cleanup failed. "
                "Check the test IDs before deleting any records."
            )
            raise

        finally:
            connection.close()


if __name__ == "__main__":
    asyncio.run(run_tests())
