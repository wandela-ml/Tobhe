import sqlite3
from mpesa import get_connection


#========================================================
# DAILY BUSINESS
#========================================================
def create_daily_business(branch_id, business_date, expected_income):

    connection = get_connection()

    cursor = connection.cursor()


    cursor.execute("""
        INSERT INTO daily_business(
            branch_id,
            business_date,
            expected_income

        )
        values(?, ?, ?)
    """, (
        branch_id,
        business_date,
        expected_income

    ))
    daily_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return daily_id


#====================================================================
# RECORD STARTING INVENTORY
#====================================================================
def add_inventory(daily_id, product_id, starting_quantity):
    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT inventory_id
        FROM daily_inventory
        WHERE daily_id = ?
        AND product_id = ?
    """, (daily_id, product_id))

    existing_inventory = cursor.fetchone()

    if existing_inventory:
        connection.close()
        raise ValueError("This product has already been added to this business day.")

    cursor.execute("""
        INSERT INTO daily_inventory (
            daily_id,
            product_id,
            starting_quantity
        )
        VALUES (?, ?, ?)
    """, (
        daily_id,
        product_id,
        starting_quantity
    ))

    connection.commit()

    connection.close()


def view_daily_setup(daily_id):
    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            daily_business.business_date,
            daily_business.expected_income,
            branches.branch_name,
            products.product_name,
            daily_inventory.starting_quantity
        FROM daily_business
        JOIN branches
            ON daily_business.branch_id = branches.branch_id
        JOIN daily_inventory
            ON daily_business.daily_id = daily_inventory.daily_id
        JOIN products
            ON daily_inventory.product_id = products.product_id
        WHERE daily_business.daily_id = ?
    """, (daily_id,))

    records = cursor.fetchall()

    connection.close()

    return records









if __name__ == "__main__":
    records = view_daily_setup(1)

    for record in records:
        print(record)
