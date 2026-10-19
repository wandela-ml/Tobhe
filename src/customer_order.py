import sqlite3
from datetime import datetime
from uuid import uuid4
import re

from database import get_connection
from mpesa import initiate_payment


#=======================================================
# GET THE PRODUCTS FOR THE BRANCH
#=======================================================
def get_branch_products(branch_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            product_id,
            product_name,
            unit_price
        FROM products
        WHERE branch_id=?
        ORDER BY product_id
    """,(branch_id,))
    products = cursor.fetchall()

    connection.close()
    return products

#==============================================================
# VALIDATE AND CALCULATE THE ORDER
#==============================================================
def validate_and_calculate_order(items):
    connection = get_connection()
    cursor = connection.cursor()

    order_items = []
    order_total = 0


    for item in items:
        product_id = item["product_id"]
        quantity = item["quantity"]

        cursor.execute("""
            SELECT
                product_id,
                product_name,
                unit_price
            FROM products
            WHERE product_id =?
        """, (product_id,))
        product = cursor.fetchone()


        if product is None:
            raise ValueError("Product out of Order!")

        if quantity <=0:
            raise ValueError("Quantity must be greater than 0.")

        unit_price = product[2]
        subtotal = unit_price * quantity

        order_item = {
            "product_id": product[0],
            "product_name": product[1],
            "unit_price": unit_price,
            "quantity" : quantity,
            "subtotal" : subtotal
        }
        order_items.append(order_item)
        order_total += subtotal
    connection.close()
    return order_items, order_total


#==============================================================
# RECORD THE ORDER IN THE DATABASE
#==============================================================
def record_order(branch_id, order_items, order_total):
    order_id = f"TBH-{uuid4().hex[:12].upper()}"

    now =datetime.now()
    order_date = now.date().isoformat()
    order_time = now.strftime("%H:%M:%S")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        connection.execute("BEGIN")
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
                payment_status = ?
            WHERE payment_id = ?
        """, (
            checkout_request_id,
            merchant_request_id,
            str(response_code) if response_code is not None else None,
            response_description,
            payment_status,
            payment_id
        ))

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
