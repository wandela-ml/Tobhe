import sqlite3
from datetime import datetime
from uuid import uuid4

from mpesa import get_connection


# ============================================================
# RECORD ORDER
# ============================================================

def record_order(
    branch_id,
    employee_id,
    items,
    payment_channel,
    payment_amount
):
    """
    Record a complete order.

    Parameters
    ----------
    branch_id : int
        Branch where the order was made.

    employee_id : str
        Employee who recorded the order.

    items : list of dictionaries
        Each item must contain:
            product_id
            quantity

        Example:
            [
                {"product_id": 1, "quantity": 2},
                {"product_id": 5, "quantity": 2}
            ]

    payment_channel : str
        Payment method, e.g. M-Pesa, Cash, Card.

    payment_amount : float
        Amount received from the customer.

    Returns
    -------
    str
        The generated order ID.
    """

    connection = get_connection()

    try:

        connection.execute("PRAGMA foreign_keys = ON")

        cursor = connection.cursor()

        # ====================================================
        # VALIDATE EMPLOYEE
        # ====================================================

        cursor.execute("""
            SELECT employee_id
            FROM employees
            WHERE employee_id = ?
              AND branch_id = ?
        """, (employee_id, branch_id))

        employee = cursor.fetchone()

        if employee is None:
            raise ValueError(
                "Employee does not belong to the selected branch."
            )

        # ====================================================
        # VALIDATE ITEMS
        # ====================================================

        if not items:
            raise ValueError("An order must contain at least one item.")

        order_items = []
        total_amount = 0.0

        for item in items:

            product_id = item["product_id"]
            quantity = item["quantity"]

            if quantity <= 0:
                raise ValueError(
                    f"Invalid quantity for product {product_id}."
                )

            cursor.execute("""
                SELECT
                    product_id,
                    product_name,
                    unit_price
                FROM products
                WHERE product_id = ?
                  AND branch_id = ?
            """, (product_id, branch_id))

            product = cursor.fetchone()

            if product is None:
                raise ValueError(
                    f"Product {product_id} does not belong "
                    f"to the selected branch."
                )

            product_id_db, product_name, unit_price = product

            subtotal = unit_price * quantity

            total_amount += subtotal

            order_items.append({
                "product_id": product_id_db,
                "product_name": product_name,
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": subtotal
            })

        # ====================================================
        # VALIDATE PAYMENT
        # ====================================================

        if payment_amount != total_amount:
            raise ValueError(
                f"Payment amount does not match order total. "
                f"Expected KES {total_amount:,.2f}, "
                f"received KES {payment_amount:,.2f}."
            )

        # ====================================================
        # GENERATE ORDER ID
        # ====================================================

        order_id = f"ORD-{uuid4().hex[:8].upper()}"

        now = datetime.now()

        order_date = now.strftime("%Y-%m-%d")
        order_time = now.strftime("%H:%M:%S")

        # ====================================================
        # INSERT ORDER
        # ====================================================

        cursor.execute("""
            INSERT INTO orders (
                order_id,
                order_date,
                order_time,
                branch_id,
                employee_id,
                total_amount
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            order_date,
            order_time,
            branch_id,
            employee_id,
            total_amount
        ))

        # ====================================================
        # INSERT ORDER ITEMS
        # ====================================================

        for item in order_items:

            cursor.execute("""
                INSERT INTO order_items (
                    order_id,
                    product_id,
                    quantity,
                    unit_price,
                    subtotal
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                order_id,
                item["product_id"],
                item["quantity"],
                item["unit_price"],
                item["subtotal"]
            ))

        # ====================================================
        # INSERT PAYMENT
        # ====================================================

        payment_id = f"PAY-{uuid4().hex[:8].upper()}"

        cursor.execute("""
            INSERT INTO payments (
                payment_id,
                order_id,
                payment_date,
                payment_time,
                amount,
                payment_channel
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            payment_id,
            order_id,
            order_date,
            order_time,
            payment_amount,
            payment_channel
        ))

        # ====================================================
        # SAVE EVERYTHING
        # ====================================================

        connection.commit()

        print()
        print("=" * 60)
        print("ORDER RECORDED SUCCESSFULLY")
        print("=" * 60)

        print(f"Order ID: {order_id}")
        print(f"Date: {order_date}")
        print(f"Time: {order_time}")
        print(f"Employee: {employee_id}")

        print("\nItems:")
        for item in order_items:
            print(
                f"  {item['product_name']} × {item['quantity']} "
                f"= KES {item['subtotal']:,.2f}"
            )

        print(f"\nTOTAL: KES {total_amount:,.2f}")
        print(f"Payment: {payment_channel}")
        print(f"Paid: KES {payment_amount:,.2f}")

        return order_id

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


# ============================================================
# TEST ORDER
# ============================================================

if __name__ == "__main__":

    record_order(
        branch_id=1,
        employee_id="EMP-MIG-001",

        items=[
            {
                "product_id": 1,
                "quantity": 2
            },
            {
                "product_id": 5,
                "quantity": 2
            }
        ],

        payment_channel="M-Pesa",
        payment_amount=900.00
    )
