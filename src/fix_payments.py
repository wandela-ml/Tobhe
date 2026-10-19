from database import get_connection

connection = get_connection()

try:
    cursor = connection.cursor()

    # Temporarily disable foreign-key enforcement for this connection
    cursor.execute("PRAGMA foreign_keys = OFF")

    cursor.execute("BEGIN")

    # Create a replacement table with the correct foreign key
    cursor.execute("""
        CREATE TABLE payments_new (
            payment_id TEXT PRIMARY KEY,
            order_id TEXT,
            payment_date TEXT NOT NULL,
            payment_time TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_channel TEXT NOT NULL,
            phone_number TEXT,
            mpesa_reference TEXT,
            checkout_request_id TEXT,
            merchant_request_id TEXT,
            payment_status TEXT,
            result_code TEXT,
            result_description TEXT,
            FOREIGN KEY (order_id)
                REFERENCES orders(order_id)
        )
    """)

    # Copy all existing payment records
    cursor.execute("""
        INSERT INTO payments_new (
            payment_id,
            order_id,
            payment_date,
            payment_time,
            amount,
            payment_channel,
            phone_number,
            mpesa_reference,
            checkout_request_id,
            merchant_request_id,
            payment_status,
            result_code,
            result_description
        )
        SELECT
            payment_id,
            order_id,
            payment_date,
            payment_time,
            amount,
            payment_channel,
            phone_number,
            mpesa_reference,
            checkout_request_id,
            merchant_request_id,
            payment_status,
            result_code,
            result_description
        FROM payments
    """)

    # Replace the old table with the corrected one
    cursor.execute("DROP TABLE payments")
    cursor.execute("ALTER TABLE payments_new RENAME TO payments")

    connection.commit()

    # Re-enable and verify foreign-key enforcement
    cursor.execute("PRAGMA foreign_keys = ON")

    print("Foreign keys:", cursor.execute(
        "PRAGMA foreign_key_list(payments)"
    ).fetchall())

    print("Foreign-key violations:", cursor.execute(
        "PRAGMA foreign_key_check"
    ).fetchall())

except Exception:
    connection.rollback()
    raise

finally:
    connection.close()
