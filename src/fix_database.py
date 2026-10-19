import sqlite3

DATABASE = "../data/tobhe.db"


connection = sqlite3.connect(DATABASE)
cursor = connection.cursor()

try:
    connection.execute("BEGIN")

    # =====================================================
    # 1. BACK UP THE EXISTING ORDER ITEMS
    # =====================================================
    cursor.execute("""
        CREATE TABLE order_items_backup AS
        SELECT *
        FROM order_items
    """)

    # =====================================================
    # 2. CREATE THE CORRECT ORDERS TABLE
    # =====================================================
    cursor.execute("""
        CREATE TABLE orders_new (
            order_id TEXT PRIMARY KEY,
            order_date TEXT NOT NULL,
            order_time TEXT NOT NULL,
            branch_id INTEGER NOT NULL,
            employee_id TEXT,
            total_amount REAL NOT NULL,
            order_status TEXT NOT NULL
        )
    """)

    # =====================================================
    # 3. MOVE THE EXISTING ORDERS FROM orders_old
    # =====================================================
    cursor.execute("""
        INSERT INTO orders_new (
            order_id,
            order_date,
            order_time,
            branch_id,
            employee_id,
            total_amount,
            order_status
        )
        SELECT
            order_id,
            order_date,
            order_time,
            branch_id,
            employee_id,
            total_amount,
            'PENDING_PAYMENT'
        FROM orders_old
    """)

    # =====================================================
    # 4. REMOVE THE OLD order_items TABLE
    # =====================================================
    cursor.execute("""
        DROP TABLE order_items
    """)

    # =====================================================
    # 5. REMOVE THE INCORRECT orders TABLE
    # =====================================================
    cursor.execute("""
        DROP TABLE orders
    """)

    # =====================================================
    # 6. RENAME THE NEW ORDERS TABLE
    # =====================================================
    cursor.execute("""
        ALTER TABLE orders_new
        RENAME TO orders
    """)

    # =====================================================
    # 7. RECREATE order_items WITH THE CORRECT FOREIGN KEY
    # =====================================================
    cursor.execute("""
        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            subtotal REAL NOT NULL,

            FOREIGN KEY (order_id)
                REFERENCES orders(order_id),

            FOREIGN KEY (product_id)
                REFERENCES products(product_id)
        )
    """)

    # =====================================================
    # 8. RESTORE THE EXISTING ORDER ITEMS
    # =====================================================
    cursor.execute("""
        INSERT INTO order_items (
            order_item_id,
            order_id,
            product_id,
            quantity,
            unit_price,
            subtotal
        )
        SELECT
            order_item_id,
            order_id,
            product_id,
            quantity,
            unit_price,
            subtotal
        FROM order_items_backup
    """)

    # =====================================================
    # 9. REMOVE THE TEMPORARY BACKUP TABLE
    # =====================================================
    cursor.execute("""
        DROP TABLE order_items_backup
    """)

    # =====================================================
    # 10. REMOVE THE OLD ORDERS TABLE
    # =====================================================
    cursor.execute("""
        DROP TABLE orders_old
    """)

    connection.commit()

    print("Database migration completed successfully.")

except Exception as error:
    connection.rollback()
    print(f"Migration failed: {error}")
    raise

finally:
    connection.close()
