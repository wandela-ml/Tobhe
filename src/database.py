import sqlite3
from pathlib import Path


# ==========================================
# DATABASE PATHS
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "tobhe.db"


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_connection():
    """
    Create and return a connection to the Tobhe database.

    Returns
    -------
    sqlite3.Connection
        Active connection to the Tobhe SQLite database.
    """

    DATA_DIR.mkdir(exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)

    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ==========================================
# CREATE TABLES
# ==========================================

def create_tables():
    """
    Create all Tobhe database tables if they do not exist.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # ------------------------------------------
    # BRANCHES
    # ------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            branch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_name TEXT NOT NULL,
            business_type TEXT NOT NULL
        )
    """)

    # ------------------------------------------
    # EMPLOYEES
    # ------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            employee_id TEXT PRIMARY KEY,
            employee_name TEXT NOT NULL,
            branch_id INTEGER NOT NULL,
            FOREIGN KEY (branch_id)
                REFERENCES branches(branch_id)
        )
    """)

    # ------------------------------------------
    # PRODUCTS
    # ------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            unit_price REAL NOT NULL,
            branch_id INTEGER NOT NULL,
            FOREIGN KEY (branch_id)
                REFERENCES branches(branch_id)
        )
    """)

    # ------------------------------------------
    # ORDERS
    # ------------------------------------------
    #
    # Customer-created orders do not require
    # an employee.
    #
    # order_status tracks the order lifecycle.
    #

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            order_date TEXT NOT NULL,
            order_time TEXT NOT NULL,
            branch_id INTEGER NOT NULL,
            employee_id TEXT,
            total_amount REAL NOT NULL,
            order_status TEXT NOT NULL,
            FOREIGN KEY (branch_id)
                REFERENCES branches(branch_id),
            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
        )
    """)

    # ------------------------------------------
    # ORDER ITEMS
    # ------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
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

    # ------------------------------------------
    # PAYMENTS
    # ------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            order_id TEXT,
            phone_number TEXT,
            payment_date TEXT NOT NULL,
            payment_time TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_channel TEXT NOT NULL,
            mpesa_reference TEXT,
            FOREIGN KEY (order_id)
                REFERENCES orders(order_id)
        )
    """)

    # ------------------------------------------
    # DAILY BUSINESS
    # ------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_business (
            daily_id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL,
            business_date TEXT NOT NULL,
            expected_income REAL NOT NULL,
            FOREIGN KEY (branch_id)
                REFERENCES branches(branch_id)
        )
    """)

    # ------------------------------------------
    # DAILY INVENTORY
    # ------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_inventory (
            inventory_id INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            starting_quantity INTEGER NOT NULL,
            FOREIGN KEY (daily_id)
                REFERENCES daily_business(daily_id),
            FOREIGN KEY (product_id)
                REFERENCES products(product_id)
        )
    """)

    connection.commit()
    connection.close()


# ==========================================
# CHECK ORDERS TABLE STRUCTURE
# ==========================================

def orders_table_needs_migration(connection):
    """
    Check whether the existing orders table uses
    the new Tobhe order structure.

    Parameters
    ----------
    connection : sqlite3.Connection
        Active database connection.

    Returns
    -------
    bool
        True if the orders table needs migration.
    """

    cursor = connection.cursor()

    cursor.execute("PRAGMA table_info(orders)")

    columns = cursor.fetchall()

    column_names = [column[1] for column in columns]

    required_columns = {
        "order_id",
        "order_date",
        "order_time",
        "branch_id",
        "employee_id",
        "total_amount",
        "order_status"
    }

    if not required_columns.issubset(column_names):
        return True

    # employee_id must be nullable.
    for column in columns:
        column_name = column[1]
        not_null = column[3]

        if column_name == "employee_id" and not_null == 1:
            return True

    return False


# ==========================================
# MIGRATE ORDERS TABLE
# ==========================================

def migrate_orders_table():
    """
    Migrate the existing orders table to the
    new customer-driven Tobhe structure.

    Existing orders are preserved.

    Returns
    -------
    None
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # ------------------------------------------
        # Check whether orders table exists
        # ------------------------------------------

        cursor.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'orders'
        """)

        orders_exists = cursor.fetchone()

        if not orders_exists:
            connection.close()
            return

        # ------------------------------------------
        # Check whether migration is necessary
        # ------------------------------------------

        if not orders_table_needs_migration(connection):
            connection.close()
            return

        print("Migrating orders table...")

        # ------------------------------------------
        # Temporarily disable foreign keys
        # ------------------------------------------

        connection.execute("PRAGMA foreign_keys = OFF")

        # ------------------------------------------
        # Rename old orders table
        # ------------------------------------------

        cursor.execute("""
            ALTER TABLE orders
            RENAME TO orders_old
        """)

        # ------------------------------------------
        # Create new orders table
        # ------------------------------------------

        cursor.execute("""
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY,
                order_date TEXT NOT NULL,
                order_time TEXT NOT NULL,
                branch_id INTEGER NOT NULL,
                employee_id TEXT,
                total_amount REAL NOT NULL,
                order_status TEXT NOT NULL,
                FOREIGN KEY (branch_id)
                    REFERENCES branches(branch_id),
                FOREIGN KEY (employee_id)
                    REFERENCES employees(employee_id)
            )
        """)

        # ------------------------------------------
        # Copy existing orders
        # ------------------------------------------

        cursor.execute("""
            INSERT INTO orders (
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
                'PAID'
            FROM orders_old
        """)

        # ------------------------------------------
        # Remove old orders table
        # ------------------------------------------

        cursor.execute("""
            DROP TABLE orders_old
        """)

        # ------------------------------------------
        # Re-enable foreign keys
        # ------------------------------------------

        connection.execute("PRAGMA foreign_keys = ON")

        # ------------------------------------------
        # Verify foreign-key integrity
        # ------------------------------------------

        cursor.execute("PRAGMA foreign_key_check")

        foreign_key_errors = cursor.fetchall()

        if foreign_key_errors:
            raise sqlite3.IntegrityError(
                f"Foreign key check failed: {foreign_key_errors}"
            )

        connection.commit()

        print("Orders table migrated successfully.")

    except Exception:
        connection.rollback()

        # Make sure foreign keys are enabled again
        connection.execute("PRAGMA foreign_keys = ON")

        raise

    finally:
        connection.close()

#==================================================================
# MIGRATE PAYMENTS TABLE
#==================================================================
def payments_table_needs_migration(connection):
    cursor = connection.cursor()
    cursor.execute("""
        PRAGMA table_info(payments)
    """)
    columns = cursor.fetchall()
    column_names = [column[1] for column in columns]
    required_columns = {
        "payment_id",
        "order_id",
        "phone_number",
        "payment_date",
        "payment_time",
        "amount",
        "payment_channel",
        "mpesa_reference"
    }
    if not required_columns.issubset(column_names):
        return True
    return False

#===========================================
# MIGRATE PAYMENT TABLE
#===========================================
def migrate_payments_table():
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            PRAGMA table_info(payments)

        """)
        columns = cursor.fetchall()
        column_names =[column[1] for column in columns]

        if "phone_number" not in column_names:
            cursor.execute("""
                ALTER TABLE payments
                ADD COLUMN phone_number TEXT
            """)

        if "mpesa_reference" not in column_names:
            cursor.execute("""
                ALTER TABLE payments
                ADD COLUMN mpesa_reference TEXT
            """)

        if "checkout_request_id" not in column_names:
            cursor.execute("""
                ALTER TABLE payments
                ADD COLUMN checkout_request_id TEXT
            """)
        if "merchant_request_id" not in column_names:
            cursor.execute("""
                ALTER TABLE payments
                ADD COLUMN merchant_request_id TEXT
            """)

        if "payment_status" not in column_names:
            cursor.execute("""
                ALTER TABLE payments
                ADD COLUMN payment_status TEXT
            """)

        if "result_code" not in column_names:
            cursor.execute("""
                ALTER TABLE payments
                ADD COLUMN result_code TEXT
            """)

        if "result_description" not in column_names:
            cursor.execute("""
                ALTER TABLE payments
                ADD COLUMN result_description TEXT
            """)
        connection.commit()
        print("Payments table migration completed successfully.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

# ==========================================
# DATABASE INITIALIZATION
# ==========================================

def initialize_database():
    """
    Create the Tobhe database structure and
    migrate the existing orders table if necessary.

    Returns
    -------
    None
    """

    create_tables()
    migrate_orders_table()
    migrate_payments_table()


# ==========================================
# RUN DIRECTLY
# ==========================================

if __name__ == "__main__":
    initialize_database()

    print()
    print("Tobhe database initialized successfully.")
    print(f"Database location: {DATABASE_PATH}")
