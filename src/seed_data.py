import sqlite3

from mpesa import get_connection


# ============================================================
# SEED BRANCHES
# ============================================================

def seed_branches(connection):

    cursor = connection.cursor()

    branches = [
        ("Migori Eatery", "Restaurant"),
        ("Nairobi Clothing", "Clothing"),
        ("Kisumu Accommodation", "Accommodation"),
    ]

    cursor.executemany("""
        INSERT INTO branches (
            branch_name,
            business_type
        )
        VALUES (?, ?)
    """, branches)

    print(f"Added {len(branches)} branches.")


# ============================================================
# SEED EMPLOYEES
# ============================================================

def seed_employees(connection):

    cursor = connection.cursor()

    # Get branch IDs
    cursor.execute("""
        SELECT branch_id, branch_name
        FROM branches
    """)

    branches = {
        branch_name: branch_id
        for branch_id, branch_name in cursor.fetchall()
    }

    employees = [
        ("EMP-MIG-001", "Achieng Otieno", branches["Migori Eatery"]),
        ("EMP-MIG-002", "Kevin Ouma", branches["Migori Eatery"]),
        ("EMP-NAI-001", "Mercy Wanjiku", branches["Nairobi Clothing"]),
        ("EMP-NAI-002", "Brian Kamau", branches["Nairobi Clothing"]),
        ("EMP-KIS-001", "Faith Akinyi", branches["Kisumu Accommodation"]),
        ("EMP-KIS-002", "David Onyango", branches["Kisumu Accommodation"]),
    ]

    cursor.executemany("""
        INSERT INTO employees (
            employee_id,
            employee_name,
            branch_id
        )
        VALUES (?, ?, ?)
    """, employees)

    print(f"Added {len(employees)} employees.")


# ============================================================
# SEED PRODUCTS
# ============================================================

def seed_products(connection):

    cursor = connection.cursor()

    # Get branch IDs
    cursor.execute("""
        SELECT branch_id, branch_name
        FROM branches
    """)

    branches = {
        branch_name: branch_id
        for branch_id, branch_name in cursor.fetchall()
    }

    products = [
        # ----------------------------------------------------
        # MIGORI EATERY
        # ----------------------------------------------------
        ("Beef Stew", 350.00, branches["Migori Eatery"]),
        ("Chicken and Chips", 500.00, branches["Migori Eatery"]),
        ("Ugali and Fish", 450.00, branches["Migori Eatery"]),
        ("Pilau", 300.00, branches["Migori Eatery"]),
        ("Soda", 100.00, branches["Migori Eatery"]),
        ("Fresh Juice", 150.00, branches["Migori Eatery"]),

        # ----------------------------------------------------
        # NAIROBI CLOTHING
        # ----------------------------------------------------
        ("Ladies Dress", 2500.00, branches["Nairobi Clothing"]),
        ("Men's Shirt", 1800.00, branches["Nairobi Clothing"]),
        ("Jeans", 3000.00, branches["Nairobi Clothing"]),
        ("T-Shirt", 1200.00, branches["Nairobi Clothing"]),
        ("Handbag", 2200.00, branches["Nairobi Clothing"]),

        # ----------------------------------------------------
        # KISUMU ACCOMMODATION
        # ----------------------------------------------------
        ("Standard Room - Night", 3500.00, branches["Kisumu Accommodation"]),
        ("Deluxe Room - Night", 5500.00, branches["Kisumu Accommodation"]),
        ("Breakfast", 500.00, branches["Kisumu Accommodation"]),
        ("Lunch", 800.00, branches["Kisumu Accommodation"]),
        ("Dinner", 800.00, branches["Kisumu Accommodation"]),
    ]

    cursor.executemany("""
        INSERT INTO products (
            product_name,
            unit_price,
            branch_id
        )
        VALUES (?, ?, ?)
    """, products)

    print(f"Added {len(products)} products.")


# ============================================================
# RUN SEEDING
# ============================================================

def seed_database():

    connection = get_connection()

    try:

        # Make sure foreign keys are enforced
        connection.execute("PRAGMA foreign_keys = ON")

        # ----------------------------------------------------
        # Prevent accidental duplicate seed data
        # ----------------------------------------------------

        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) FROM branches")
        branch_count = cursor.fetchone()[0]

        if branch_count > 0:
            print("Database already contains branch data.")
            print("Seeding cancelled to prevent duplicate records.")
            return

        # ----------------------------------------------------
        # Populate tables
        # ----------------------------------------------------

        seed_branches(connection)
        seed_employees(connection)
        seed_products(connection)

        connection.commit()

        print()
        print("Tobhe database populated successfully.")

    except Exception as error:

        connection.rollback()

        print("Database seeding failed.")
        print(f"Error: {error}")

    finally:

        connection.close()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    seed_database()
