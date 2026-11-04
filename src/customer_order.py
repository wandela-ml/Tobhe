import sqlite3
from datetime import datetime
from uuid import uuid4
import re

from src.database import get_connection
from src.mpesa import initiate_payment

#====================================================
#SETTING PRICES
#====================================================
def get_effective_product_price(product_id, order_date):
    """
    Return the product price applicable on the given order date.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT unit_price
            FROM product_price_history
            WHERE product_id = ?
              AND effective_from <= ?
            ORDER BY effective_from DESC,
                     recorded_at DESC,
                     history_id DESC
            LIMIT 1
        """, (product_id, order_date))

        price_record = cursor.fetchone()

        if price_record is not None:
            return price_record[0]

        cursor.execute("""
            SELECT unit_price
            FROM products
            WHERE product_id = ?
        """, (product_id,))

        product = cursor.fetchone()

        if product is None:
            raise ValueError("Product not found.")

        return product[0]

    finally:
        connection.close()

#=====================================================
#
#====================================================

def get_available_stock(cursor, branch_id, product_id, order_date):
    """
    Calculate the remaining sellable stock for a branch product.
    """

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
        return 0

    starting_quantity, deliveries_quantity, stock_handling = inventory

    if starting_quantity is None:
        return 0

    if stock_handling == "PERISHABLE":
        sellable_stock = starting_quantity

    else:
        if deliveries_quantity is None:
            return 0

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

    return max(0, sellable_stock - already_sold)

#=======================================================
# GET THE PRODUCTS FOR THE BRANCH
#=======================================================
def get_branch_products(branch_id, order_date):
    """
    Retrieve branch products with prices effective on the order date.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                product_id,
                product_name,
                stock_handling
            FROM products
            WHERE branch_id = ?
            ORDER BY product_id
        """, (branch_id,))

        products = cursor.fetchall()

        branch_products = []

        for product_id, product_name, stock_handling in products:
            effective_price = get_effective_product_price(
                product_id,
                order_date
            )
            available_quantity = get_available_stock(
                cursor,
                branch_id,
                product_id,
                order_date
                )

            branch_products.append((
                product_id,
                product_name,
                effective_price,
                stock_handling,
                available_quantity
            ))

        return branch_products

    finally:
        connection.close()
#==============================================================
# VALIDATE AND CALCULATE THE ORDER
#==============================================================

def validate_and_calculate_order(items, branch_id, order_date):
    """
    Validate customer order items against branch products
    and available stock, then calculate the order total.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()

        order_items = []
        order_total = 0

        for item in items:
            product_id = item["product_id"]
            quantity = item["quantity"]

            # Confirm that the product belongs to this branch.
            cursor.execute("""
                SELECT product_id, product_name
                FROM products
                WHERE product_id = ?
                  AND branch_id = ?
            """, (product_id, branch_id))

            product = cursor.fetchone()

            if product is None:
                raise ValueError(
                    "Product does not belong to this branch."
                )

            # Validate the requested quantity.
            if (
                not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity <= 0
            ):
                raise ValueError(
                    "Quantity must be a positive integer."
                )

            # Check the latest available sellable stock.
            available_quantity = get_available_stock(
                cursor,
                branch_id,
                product_id,
                order_date
            )

            if quantity > available_quantity:
                raise ValueError(
                    f"Insufficient stock for {product[1]}. "
                    f"Available quantity: {available_quantity}."
                )

            # Retrieve the effective product price.
            unit_price = get_effective_product_price(
                product_id,
                order_date
            )

            subtotal = unit_price * quantity

            order_item = {
                "product_id": product[0],
                "product_name": product[1],
                "unit_price": unit_price,
                "quantity": quantity,
                "subtotal": subtotal
            }

            order_items.append(order_item)
            order_total += subtotal

        return order_items, order_total

    finally:
        connection.close()



#==============================================================
# RECORD THE ORDER IN THE DATABASE
#==============================================================
def record_order(branch_id, order_items, order_total, order_date):
    order_id = f"TBH-{uuid4().hex[:12].upper()}"

    now =datetime.now()
    order_time = now.strftime("%H:%M:%S")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor.execute("""
            INSERT INTO orders(
                order_id,
                order_date,
                order_time,
                branch_id,
                total_amount,
                order_status
            )
            VALUES(?, ?, ? , ?, ?, ?)
        """, (
            order_id,
            order_date,
            order_time,
            branch_id,
            order_total,
            "PENDING_PAYMENT"
        ))
        for item in order_items:
            product_id = item["product_id"]
            quantity = item["quantity"]
            unit_price= item["unit_price"]
            subtotal = item["subtotal"]

            cursor.execute("""
                INSERT INTO order_items(
                    order_id,
                    product_id,
                    quantity,
                    unit_price,
                    subtotal
                )
                VALUES(?, ?, ?, ?, ?)
            """,(
                order_id,
                product_id,
                quantity,
                unit_price,
                subtotal
            ))
        connection.commit()

    except Exception as error:
        connection.rollback()
        print(f"order failed:{error}")
        raise
    finally:
        connection.close()
    return order_id

#==============================================
#PROMPT PAYMENT
#==============================================
def prompt_payment():

    while True:

        phone_number = input("Enter your M-Pesa phone number: ")

        phone_number = phone_number.strip()

        if phone_number.startswith("0"):
            phone_number = "+254" + phone_number[1:]

        elif phone_number.startswith("254"):
            phone_number = "+" + phone_number

        if re.fullmatch(r"\+254(7\d{8}|1\d{8})", phone_number):

            return phone_number

        print("Invalid Kenyan mobile number. Please try again.")

#=================================================================
# RECORD PENDING PAYMENT
#================================================================

def record_pending_payment(order_id, phone_number, amount, payment_channel):
    payment_id = f"PAY-{uuid4().hex[:12].upper()}"

    now = datetime.now()
    payment_date = now.date().isoformat()
    payment_time = now.strftime("%H:%M:%S")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO payments (
                payment_id,
                order_id,
                phone_number,
                payment_date,
                payment_time,
                amount,
                payment_channel,
                payment_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payment_id,
            order_id,
            phone_number,
            payment_date,
            payment_time,
            amount,
            payment_channel,
            "PENDING"
        ))

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return payment_id

#=====================================================
# Save Mpesa record
#=====================================================

def save_mpesa_response(payment_id, response):
    response_code = response.get("ResponseCode")
    checkout_request_id = response.get("CheckoutRequestID")
    merchant_request_id = response.get("MerchantRequestID")
    response_description = response.get("ResponseDescription", "")

    if str(response_code) == "0":
        payment_status = "PENDING"
    else:
        payment_status = "FAILED"

    connection = get_connection()

    try:
        cursor = connection.cursor()

        
        cursor.execute("""
            UPDATE payments
            SET checkout_request_id = ?,
                merchant_request_id = ?,
                result_code = ?,
                result_description = ?,
                payment_status = CASE
                    WHEN payment_status = 'COMPLETED'
                    THEN payment_status
                    ELSE ?
                END
            WHERE payment_id = ?
        """, (checkout_request_id, merchant_request_id,
              str(response_code) if response_code is not None else None,
              response_description, payment_status, payment_id))


        if cursor.rowcount == 0:
            raise ValueError(
                f"Payment record not found: {payment_id}"
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()





if __name__ == "__main__":
    items = [
        {"product_id": 1, "quantity": 2},
        {"product_id": 5, "quantity": 1}
    ]

    order_items, order_total = validate_and_calculate_order(items)

    order_id = record_order(
        branch_id=1,
        order_items=order_items,
        order_total=order_total
    )

    print("Order created:", order_id)
    print("Amount to pay: KES", order_total)

    phone_number = prompt_payment()

    payment_id = record_pending_payment(
        order_id,
        phone_number,
        order_total,
        "M-Pesa"
    )

    print("Payment record created:", payment_id)

    try:
        payment_response = initiate_payment(
            order_id,
            phone_number,
            order_total
        )

        save_mpesa_response(payment_id, payment_response)

        print("Safaricom response:", payment_response)

        if str(payment_response.get("ResponseCode")) == "0":
            print(
                "STK Push request accepted. "
                "Check your phone and complete the payment."
            )
        else:
            print(
                "Safaricom did not accept the payment request. "
                "Check the response before trying again."
            )

    except Exception as error:
        print("Could not complete the STK request:", error)
        print(
            "The payment record has been retained. "
            "Check its status before retrying, to avoid "
            "creating a duplicate payment request."
        )

