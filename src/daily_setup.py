import sqlite3
from src.database import get_connection
from datetime import datetime, timedelta
import re
import math



def recalculate_expected_income(cursor, daily_id):
    """
    Recalculate and save expected income for a business day.

    PERISHABLE:
        starting_quantity * unit_price

    CARRY_FORWARD:
        (starting_quantity + deliveries_quantity) * unit_price

    Products with missing applicable stock quantities are excluded.
    Zero is treated as a valid recorded quantity.
    """

    cursor.execute("""
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN products.stock_handling = 'PERISHABLE'
                         AND daily_inventory.starting_quantity IS NOT NULL
                    THEN
                        daily_inventory.starting_quantity
                        * products.unit_price

                    WHEN products.stock_handling = 'CARRY_FORWARD'
                         AND daily_inventory.starting_quantity IS NOT NULL
                         AND daily_inventory.deliveries_quantity IS NOT NULL
                    THEN
                        (
                            daily_inventory.starting_quantity
                            + daily_inventory.deliveries_quantity
                        ) * products.unit_price

                    ELSE 0
                END
            ),
            0
        )
        FROM daily_inventory
        JOIN products
            ON products.product_id = daily_inventory.product_id
        WHERE daily_inventory.daily_id = ?
    """, (daily_id,))

    expected_income = cursor.fetchone()[0]

    cursor.execute("""
        UPDATE daily_business
        SET expected_income = ?
        WHERE daily_id = ?
    """, (expected_income, daily_id))

    return expected_income

#======================================================
#
#======================================================
def calculate_expected_income(cursor, daily_id):
    """Calculate expected income without updating the database."""

    cursor.execute("""
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN products.stock_handling = 'PERISHABLE'
                         AND daily_inventory.starting_quantity IS NOT NULL
                    THEN
                        daily_inventory.starting_quantity
                        * products.unit_price

                    WHEN products.stock_handling = 'CARRY_FORWARD'
                         AND daily_inventory.starting_quantity IS NOT NULL
                         AND daily_inventory.deliveries_quantity IS NOT NULL
                    THEN
                        (
                            daily_inventory.starting_quantity
                            + daily_inventory.deliveries_quantity
                        ) * products.unit_price

                    ELSE 0
                END
            ),
            0
        )
        FROM daily_inventory
        JOIN products
            ON products.product_id = daily_inventory.product_id
        WHERE daily_inventory.daily_id = ?
    """, (daily_id,))

    return cursor.fetchone()[0]

#========================================================
# DAILY BUSINESS
#========================================================
def create_daily_business(branch_id, business_date, expected_income):
    """Create a business day if one doesn't already exist."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT daily_id
            FROM daily_business
            WHERE branch_id = ?
                AND status = 'OPEN'
        """, (branch_id,))

        if cursor.fetchone() is not None:
            raise ValueError(
                "This branch already has an open business day. "
                "Complete it before opening another."
                )

        cursor.execute("""
            SELECT daily_id
            FROM daily_business
            WHERE branch_id = ?
              AND business_date = ?
        """, (branch_id, business_date))

        if cursor.fetchone() is not None:
            raise ValueError(
                "A business day already exists for this branch and date."
            )

        cursor.execute("""
            INSERT INTO daily_business (
                branch_id,
                business_date,
                expected_income
            )
            VALUES (?, ?, ?)
        """, (branch_id, business_date, expected_income))

        daily_id = cursor.lastrowid
        connection.commit()

        return daily_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


#====================================================================
# RECORD STARTING INVENTORY
#====================================================================
def add_inventory(daily_id, product_id, starting_quantity):
    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT status
        FROM daily_business
        WHERE daily_id = ?
    """, (daily_id,))

    business_day = cursor.fetchone()

    if business_day is None:
        connection.close()
        raise ValueError("Business day does not exist.")

    if business_day[0] != "OPEN":
        connection.close()
        raise ValueError(
            "Inventory can only be added to open business days."
        )

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



#==================================================================
#INITIALIZING THE DAILY INVENTORY
#==================================================================

def initialize_daily_inventory(daily_id):
    """Initialize inventory records and starting quantities for a business day."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 1. Identify the business day.
        cursor.execute("""
            SELECT branch_id, business_date, status
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        current_day = cursor.fetchone()

        if current_day is None:
            raise ValueError("Business day does not exist.")

        branch_id, business_date, status = current_day

        if status != "OPEN":
            raise ValueError(
                "Inventory can only be initialized on open business days."
            )

        # 2. Normalize supported business date formats.
        date_expression = """
            CASE
                WHEN db.business_date GLOB '????-??-??'
                THEN date(db.business_date)
                ELSE date(
                    substr(db.business_date, -4) || '-' ||
                    CASE
                        WHEN db.business_date LIKE '%January%' THEN '01'
                        WHEN db.business_date LIKE '%February%' THEN '02'
                        WHEN db.business_date LIKE '%March%' THEN '03'
                        WHEN db.business_date LIKE '%April%' THEN '04'
                        WHEN db.business_date LIKE '%May%' THEN '05'
                        WHEN db.business_date LIKE '%June%' THEN '06'
                        WHEN db.business_date LIKE '%July%' THEN '07'
                        WHEN db.business_date LIKE '%August%' THEN '08'
                        WHEN db.business_date LIKE '%September%' THEN '09'
                        WHEN db.business_date LIKE '%October%' THEN '10'
                        WHEN db.business_date LIKE '%November%' THEN '11'
                        WHEN db.business_date LIKE '%December%' THEN '12'
                    END || '-' ||
                    printf('%02d', CAST(db.business_date AS INTEGER))
                )
            END
        """

        # 3. Find the most recent earlier business day.
        cursor.execute(f"""
            WITH current_business_day AS (
                SELECT {date_expression} AS normalized_date
                FROM daily_business db
                WHERE db.daily_id = ?
            ),
            previous_business_days AS (
                SELECT
                    db.daily_id,
                    db.status,
                    {date_expression} AS normalized_date
                FROM daily_business db
                WHERE db.branch_id = ?
            )
            SELECT previous.daily_id, previous.status
            FROM previous_business_days previous
            CROSS JOIN current_business_day current
            WHERE previous.normalized_date < current.normalized_date
            ORDER BY previous.normalized_date DESC
            LIMIT 1
        """, (daily_id, branch_id))

        previous_day = cursor.fetchone()

        previous_daily_id = None

        if previous_day is not None:
            previous_daily_id, previous_status = previous_day

            if previous_status != "COMPLETE":
               previous_daily_id=None

        # 4. Retrieve products belonging to this branch.
        cursor.execute("""
            SELECT product_id, stock_handling
            FROM products
            WHERE branch_id = ?
        """, (branch_id,))

        products = cursor.fetchall()

        starting_stock = []

        # 5. Initialize each product.
        for product_id, stock_handling in products:

            cursor.execute("""
                SELECT starting_quantity
                FROM daily_inventory
                WHERE daily_id = ?
                  AND product_id = ?
            """, (daily_id, product_id))

            existing_inventory = cursor.fetchone()

            # Determine the correct starting quantity.
            if stock_handling == "PERISHABLE":
                starting_quantity = None

            elif stock_handling == "CARRY_FORWARD":

                if previous_daily_id is None:
                    # First business day: initial stock goes into deliveries.
                    starting_quantity = 0

                else:
                    cursor.execute("""
                        SELECT physical_closing_quantity
                        FROM daily_inventory
                        WHERE daily_id = ?
                          AND product_id = ?
                    """, (previous_daily_id, product_id))

                    previous_stock = cursor.fetchone()

                    if (
                        previous_stock is None
                        or previous_stock[0] is None
                    ):
                        raise ValueError(
                            f"Physical closing quantity is missing for "
                            f"product ID {product_id} on the previous day."
                        )

                    starting_quantity = previous_stock[0]

            else:
                raise ValueError(
                    f"Invalid stock handling type for product ID "
                    f"{product_id}: {stock_handling}"
                )

            if existing_inventory is None:
                # Create a new inventory record.
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

            else:
                # Preserve existing valid entries.
                saved_quantity = existing_inventory[0]

                if (
                    stock_handling == "CARRY_FORWARD"
                    and saved_quantity is None
                ):
                    # Correct an uninitialized carry-forward quantity.
                    cursor.execute("""
                        UPDATE daily_inventory
                        SET starting_quantity = ?
                        WHERE daily_id = ?
                          AND product_id = ?
                    """, (
                        starting_quantity,
                        daily_id,
                        product_id
                    ))

                else:
                    starting_quantity = saved_quantity

            starting_stock.append(
                (product_id, starting_quantity)
            )

        # Recalculate expected income using the shared calculation.
        recalculate_expected_income(cursor, daily_id)
        connection.commit()

        return starting_stock

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()




#===============================================================
#RECORD PHYSICAL AT CLOSING
#===============================================================
def record_physical_closing(daily_id, product_id, closing_quantity):
    """Record the physical stock counted at the end of the business day."""

    if (
        not isinstance(closing_quantity, int)
        or isinstance(closing_quantity, bool)
        or closing_quantity < 0
    ):
        raise ValueError("Closing quantity must be a non-negative integer.")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Check whether the business day is still open.
        cursor.execute("""
            SELECT status
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        record = cursor.fetchone()

        if record is None:
            raise ValueError("Business day does not exist.")

        if record[0] != "OPEN":
            raise ValueError(
                "Physical closing can only be edited on open business days."
            )

        cursor.execute("""
            UPDATE daily_inventory
            SET physical_closing_quantity = ?
            WHERE daily_id = ?
              AND product_id = ?
        """, (closing_quantity, daily_id, product_id))

        if cursor.rowcount == 0:
            raise ValueError(
                "Product has not been added to this business day."
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

#==============================================================
#VALIDATE PHYSICAL CLOSING COUNTS
#==============================================================
def validate_physical_closing_counts(daily_id):
    """Ensure every product has a physical closing count."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT products.product_name
            FROM daily_inventory
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_inventory.daily_id = ?
              AND daily_inventory.physical_closing_quantity IS NULL
            ORDER BY products.product_name
        """, (daily_id,))

        missing_products = [
            row[0] for row in cursor.fetchall()
        ]

        if missing_products:
            raise ValueError(
                "Physical closing counts are missing for: "
                + ", ".join(missing_products)
            )

        return True

    finally:
        connection.close()

#===================================================================
#COMPLETE A BUSINESS DAY
#===================================================================
def complete_business_day(daily_id):
    """Complete a business day only when all inventory requirements are met."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 1. Confirm that the business day exists and is OPEN.
        cursor.execute("""
            SELECT status, branch_id
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        business_day = cursor.fetchone()

        if business_day is None:
            raise ValueError("Business day not found.")

        status, branch_id = business_day

        if status != "OPEN":
            raise ValueError(
                f"Business day cannot be completed. "
                f"Current status: {status}."
            )

        # 2. Confirm every branch product has an inventory record.
        cursor.execute("""
            SELECT products.product_name
            FROM products
            LEFT JOIN daily_inventory
                ON products.product_id = daily_inventory.product_id
                AND daily_inventory.daily_id = ?
            WHERE products.branch_id = ?
              AND daily_inventory.inventory_id IS NULL
            ORDER BY products.product_name
        """, (daily_id, branch_id))

        missing_inventory = [
            row[0] for row in cursor.fetchall()
        ]

        if missing_inventory:
            raise ValueError(
                "Inventory records are missing for: "
                + ", ".join(missing_inventory)
            )

        # 3. Confirm starting quantities have been entered.
        cursor.execute("""
            SELECT products.product_name
            FROM daily_inventory
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_inventory.daily_id = ?
              AND daily_inventory.starting_quantity IS NULL
            ORDER BY products.product_name
        """, (daily_id,))

        missing_starting_quantities = [
            row[0] for row in cursor.fetchall()
        ]

        if missing_starting_quantities:
            raise ValueError(
                "Starting quantities have not been entered for: "
                + ", ".join(missing_starting_quantities)
            )

        # 4. Confirm delivery status for carry-forward products.
        cursor.execute("""
            SELECT products.product_name
            FROM daily_inventory
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_inventory.daily_id = ?
              AND products.stock_handling = 'CARRY_FORWARD'
              AND daily_inventory.deliveries_quantity IS NULL
            ORDER BY products.product_name
        """, (daily_id,))

        missing_deliveries = [
            row[0] for row in cursor.fetchall()
        ]

        if missing_deliveries:
            raise ValueError(
                "Delivery status has not been confirmed for: "
                + ", ".join(missing_deliveries)
            )

        # 5. Confirm physical closing quantities for every product.
        cursor.execute("""
            SELECT products.product_name
            FROM daily_inventory
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_inventory.daily_id = ?
              AND daily_inventory.physical_closing_quantity IS NULL
            ORDER BY products.product_name
        """, (daily_id,))

        missing_closing_quantities = [
            row[0] for row in cursor.fetchall()
        ]

        if missing_closing_quantities:
            raise ValueError(
                "Physical closing quantities have not been entered for: "
                + ", ".join(missing_closing_quantities)
            )

        # 6. Mark the business day as COMPLETE.
        cursor.execute("""
            UPDATE daily_business
            SET status = 'COMPLETE'
            WHERE daily_id = ?
              AND status = 'OPEN'
        """, (daily_id,))

        if cursor.rowcount != 1:
            raise ValueError(
                "Business day status changed before completion."
            )

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

#=================================================================
# VIEW DAILY SETUP
#=================================================================
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


# ============================================================
# RECORD STOCK DELIVERY
# ============================================================

def record_stock_delivery(daily_id, product_id, quantity_received, notes=None):
    """
    Record a stock delivery or confirm that no delivery was received.

    Positive quantities create individual stock movement records.
    Zero confirms that no delivery was received.
    Only CARRY_FORWARD products can receive deliveries.
    """

    # 1. Validate the quantity.
    if (
        not isinstance(quantity_received, int)
        or isinstance(quantity_received, bool)
        or quantity_received < 0
    ):
        raise ValueError(
            "Delivery quantity must be a non-negative integer."
        )

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 2. Retrieve the business day and product details.
        cursor.execute("""
            SELECT
                daily_business.branch_id,
                products.branch_id,
                daily_business.status,
                products.stock_handling
            FROM daily_business
            JOIN products
                ON products.product_id = ?
            WHERE daily_business.daily_id = ?
        """, (product_id, daily_id))

        record = cursor.fetchone()

        if record is None:
            raise ValueError(
                "Business day or product does not exist."
            )

        (
            daily_branch_id,
            product_branch_id,
            status,
            stock_handling
        ) = record

        # 3. Validate the business day.
        if status != "OPEN":
            raise ValueError(
                "Stock deliveries can only be recorded "
                "on open business days."
            )

        # 4. Verify that the product belongs to the branch.
        if daily_branch_id != product_branch_id:
            raise ValueError(
                "This product does not belong to the selected branch."
            )

        # 5. Only CARRY_FORWARD products can receive deliveries.
        if stock_handling == "PERISHABLE":
            raise ValueError(
                "Deliveries cannot be recorded for PERISHABLE products."
            )

        if stock_handling != "CARRY_FORWARD":
            raise ValueError(
                f"Invalid stock handling type: {stock_handling}"
            )

        # 6. Confirm that daily inventory has been initialized.
        cursor.execute("""
            SELECT deliveries_quantity
            FROM daily_inventory
            WHERE daily_id = ?
              AND product_id = ?
        """, (daily_id, product_id))

        inventory = cursor.fetchone()

        if inventory is None:
            raise ValueError(
                "Initialize daily inventory before recording deliveries."
            )

        current_deliveries = inventory[0]

        # 7. Handle an explicit confirmation of zero deliveries.
        if quantity_received == 0:

            cursor.execute("""
                SELECT COUNT(*), COALESCE(SUM(quantity_received), 0)
                FROM stock_movements
                WHERE daily_id = ?
                  AND product_id = ?
            """, (daily_id, product_id))

            movement_count, movement_total = cursor.fetchone()

            if movement_count > 0 or (
                current_deliveries is not None
                and current_deliveries > 0
            ):
                raise ValueError(
                    "Cannot confirm zero deliveries while "
                    "positive delivery records exist."
                )

            cursor.execute("""
                UPDATE daily_inventory
                SET deliveries_quantity = 0
                WHERE daily_id = ?
                  AND product_id = ?
            """, (daily_id, product_id))

            movement_id = None

        # 8. Record a positive delivery.
        else:

            cursor.execute("""
                INSERT INTO stock_movements (
                    daily_id,
                    product_id,
                    quantity_received,
                    received_at,
                    notes
                )
                VALUES (?, ?, ?, datetime('now', 'localtime'), ?)
            """, (daily_id, product_id, quantity_received, notes))

            movement_id = cursor.lastrowid

            # Recalculate cumulative deliveries from the movement history.
            cursor.execute("""
                SELECT COALESCE(SUM(quantity_received), 0)
                FROM stock_movements
                WHERE daily_id = ?
                  AND product_id = ?
            """, (daily_id, product_id))

            cumulative_deliveries = cursor.fetchone()[0]

            cursor.execute("""
                UPDATE daily_inventory
                SET deliveries_quantity = ?
                WHERE daily_id = ?
                  AND product_id = ?
            """, (
                cumulative_deliveries,
                daily_id,
                product_id
            ))

        # 9. Recalculate expected income.
        expected_income = recalculate_expected_income(
            cursor,
            daily_id
        )

        connection.commit()

        return movement_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

# ============================================================
# VIEW STOCK DELIVERY HISTORY
# ============================================================

def get_stock_delivery_history(daily_id):
    """
    Retrieve individual stock deliveries and their cumulative
    quantity for each product on a business day.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                stock_movements.movement_id,
                stock_movements.product_id,
                products.product_name,
                stock_movements.quantity_received,
                stock_movements.received_at,
                stock_movements.notes,
                daily_inventory.deliveries_quantity
                    AS cumulative_deliveries
            FROM stock_movements
            JOIN products
                ON products.product_id = stock_movements.product_id
            JOIN daily_inventory
                ON daily_inventory.daily_id = stock_movements.daily_id
                AND daily_inventory.product_id = stock_movements.product_id
            WHERE stock_movements.daily_id = ?
            ORDER BY stock_movements.received_at DESC
        """, (daily_id,))

        return cursor.fetchall()

    finally:
        connection.close()


# ============================================================
# UPDATE AN EXISTING STOCK DELIVERY
# ============================================================

def update_stock_delivery(movement_id, quantity_received, notes=None):
    """
    Edit an existing stock delivery without creating a duplicate.

    Recalculate cumulative deliveries and expected income.
    Preserve the original received_at timestamp.
    """

    # 1. Validate the new delivery quantity.
    if (
        not isinstance(quantity_received, int)
        or isinstance(quantity_received, bool)
        or quantity_received <= 0
    ):
        raise ValueError(
            "Delivery quantity must be a positive integer."
        )

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 2. Retrieve the delivery, business day and product details.
        cursor.execute("""
            SELECT
                stock_movements.daily_id,
                stock_movements.product_id,
                daily_business.status,
                products.stock_handling
            FROM stock_movements
            JOIN daily_business
                ON daily_business.daily_id = stock_movements.daily_id
            JOIN products
                ON products.product_id = stock_movements.product_id
            WHERE stock_movements.movement_id = ?
        """, (movement_id,))

        record = cursor.fetchone()

        if record is None:
            raise ValueError("Stock delivery does not exist.")

        daily_id, product_id, status, stock_handling = record

        # 3. Only OPEN business days can be edited.
        if status != "OPEN":
            raise ValueError(
                "Stock deliveries can only be edited "
                "on open business days."
            )

        # 4. Verify that the product supports deliveries.
        if stock_handling != "CARRY_FORWARD":
            raise ValueError(
                "Only CARRY_FORWARD products can have delivery records."
            )

        # 5. Update the existing movement.
        # received_at is deliberately left unchanged.
        cursor.execute("""
            UPDATE stock_movements
            SET
                quantity_received = ?,
                notes = ?
            WHERE movement_id = ?
        """, (quantity_received, notes, movement_id))

        # 6. Recalculate cumulative deliveries from movement history.
        cursor.execute("""
            SELECT COALESCE(SUM(quantity_received), 0)
            FROM stock_movements
            WHERE daily_id = ?
              AND product_id = ?
        """, (daily_id, product_id))

        cumulative_deliveries = cursor.fetchone()[0]

        cursor.execute("""
            UPDATE daily_inventory
            SET deliveries_quantity = ?
            WHERE daily_id = ?
              AND product_id = ?
        """, (cumulative_deliveries, daily_id, product_id))

        if cursor.rowcount == 0:
            raise ValueError(
                "Daily inventory record does not exist."
            )

        # 7. Recalculate expected income.
        expected_income = recalculate_expected_income(
            cursor,
            daily_id
        )

        connection.commit()

        return movement_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def delete_stock_delivery(movement_id):
    """
    Delete one stock delivery record.

    Recalculate cumulative deliveries and expected income.
    Only OPEN business days can be modified.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 1. Retrieve the delivery and its business-day details.
        cursor.execute("""
            SELECT
                stock_movements.daily_id,
                stock_movements.product_id,
                daily_business.status,
                products.stock_handling
            FROM stock_movements
            JOIN daily_business
                ON daily_business.daily_id = stock_movements.daily_id
            JOIN products
                ON products.product_id = stock_movements.product_id
            WHERE stock_movements.movement_id = ?
        """, (movement_id,))

        record = cursor.fetchone()

        if record is None:
            raise ValueError("Stock delivery does not exist.")

        daily_id, product_id, status, stock_handling = record

        # 2. Only OPEN business days can be modified.
        if status != "OPEN":
            raise ValueError(
                "Stock deliveries can only be deleted "
                "on open business days."
            )

        # 3. Verify that the product supports deliveries.
        if stock_handling != "CARRY_FORWARD":
            raise ValueError(
                "Only CARRY_FORWARD products can have delivery records."
            )

        # 4. Delete only the selected delivery.
        cursor.execute("""
            DELETE FROM stock_movements
            WHERE movement_id = ?
        """, (movement_id,))

        # 5. Recalculate cumulative deliveries.
        cursor.execute("""
            SELECT COALESCE(SUM(quantity_received), 0)
            FROM stock_movements
            WHERE daily_id = ?
              AND product_id = ?
        """, (daily_id, product_id))

        cumulative_deliveries = cursor.fetchone()[0]

        cursor.execute("""
            UPDATE daily_inventory
            SET deliveries_quantity = ?
            WHERE daily_id = ?
              AND product_id = ?
        """, (cumulative_deliveries, daily_id, product_id))

        if cursor.rowcount == 0:
            raise ValueError(
                "Daily inventory record does not exist."
            )

        # 6. Recalculate expected income.
        recalculate_expected_income(cursor, daily_id)

        connection.commit()

        return movement_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

#=================================================================
#SET PRODUCT TARGET STOCK
#=================================================================
def set_product_target_stock(product_id, target_quantity):
    """Set the owner's target stock quantity for a product."""

    if (
        not isinstance(target_quantity, int)
        or isinstance(target_quantity, bool)
        or target_quantity < 0
    ):
        raise ValueError("Target stock must be a non-negative integer.")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE products
            SET target_stock_quantity = ?
            WHERE product_id = ?
        """, (target_quantity, product_id))

        if cursor.rowcount == 0:
            raise ValueError("Product not found.")

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def set_product_price(product_id, new_price):
    """
    Schedule a new product price to take effect the next calendar day.

    Every price change is retained in product_price_history.
    Multiple changes on the same day are allowed.
    """

    if (
        isinstance(new_price, bool)
        or not isinstance(new_price, (int, float))
        or not math.isfinite(new_price)
        or new_price < 0
    ):
        raise ValueError("Product price must be a non-negative number.")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Confirm that the product exists.
        cursor.execute("""
            SELECT product_id
            FROM products
            WHERE product_id = ?
        """, (product_id,))

        if cursor.fetchone() is None:
            raise ValueError("Product not found.")

        # The new price becomes effective tomorrow.
        effective_date = (
            datetime.now().date() + timedelta(days=1)
        ).isoformat()

        cursor.execute("""
            INSERT INTO product_price_history (
                product_id,
                unit_price,
                effective_from,
                recorded_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            product_id,
            new_price,
            effective_date,
            datetime.now().isoformat(timespec="seconds")
        ))

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

# ============================================================
# RECORD PROJECTED SALES AND CALCULATE EXPECTED INCOME
# ============================================================

def set_projected_sales(daily_id, product_id, projected_quantity):
    """Save projected sales and recalculate expected daily income."""

    if (
        not isinstance(projected_quantity, int)
        or isinstance(projected_quantity, bool)
        or projected_quantity < 0
    ):
        raise ValueError(
            "Projected sales quantity must be a non-negative integer."
        )

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Confirm that the product belongs to this business day
        # and retrieve its starting stock.
        cursor.execute("""
            SELECT
                daily_business.branch_id,
                products.branch_id,
                daily_inventory.starting_quantity,
                daily_business.status,
                products.stock_handling
            FROM daily_business
            JOIN daily_inventory
                ON daily_inventory.daily_id = daily_business.daily_id
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_business.daily_id = ?
              AND products.product_id = ?
        """, (daily_id, product_id))

        record = cursor.fetchone()

        if record is None:
            raise ValueError(
                "Product has not been added to this business day."
            )

        daily_branch_id, product_branch_id, starting_stock, status, stock_handling = record


        if status != "OPEN":
            raise ValueError(
                "Projected sales can only be edited on open business days."
            )

        if daily_branch_id != product_branch_id:
            raise ValueError(
                "This product does not belong to the selected branch."
            )

        # Calculate available stock according to the product type.
        if stock_handling == "PERISHABLE":
            # Only prepared portions are available for sale.
            total_stock = starting_stock

        else:
            # Carry-forward products include opening stock and deliveries.
            cursor.execute("""
                SELECT COALESCE(SUM(quantity_received), 0)
                FROM stock_movements
                WHERE daily_id = ?
                    AND product_id = ?
            """, (daily_id, product_id))

            total_deliveries = cursor.fetchone()[0]
            total_stock = starting_stock + total_deliveries

        if projected_quantity > total_stock:
            raise ValueError(
                f"Projected sales ({projected_quantity}) cannot exceed "
                f"available stock ({total_stock})."
            )

        # Save the owner's projected sales quantity.
        cursor.execute("""
            UPDATE daily_inventory
            SET projected_sales_quantity = ?
            WHERE daily_id = ?
              AND product_id = ?
        """, (projected_quantity, daily_id, product_id))

        # Recalculate expected income across all products for this day.
        cursor.execute("""
            SELECT COALESCE(
                SUM(
                    daily_inventory.projected_sales_quantity
                    * products.unit_price
                ),
                0
            )
            FROM daily_inventory
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_inventory.daily_id = ?
        """, (daily_id,))

        expected_income = cursor.fetchone()[0]

        cursor.execute("""
            UPDATE daily_business
            SET expected_income = ?
            WHERE daily_id = ?
        """, (expected_income, daily_id))

        connection.commit()

        return expected_income

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


#================================================================
# SAVE STARTING QUANTITY
#================================================================


# ================================================================
# SAVE STARTING QUANTITY
# ================================================================
def save_starting_quantity(daily_id, product_id, quantity):
    """
    Save or edit the starting quantity for a PERISHABLE product.

    CARRY_FORWARD starting quantities are initialized automatically
    and cannot be edited through this function.
    """

    # 1. Validate the quantity.
    if (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity < 0
    ):
        raise ValueError(
            "Starting quantity must be a non-negative integer."
        )

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 2. Retrieve the business day, product and inventory details.
        cursor.execute("""
            SELECT
                daily_business.branch_id,
                products.branch_id,
                daily_business.status,
                products.stock_handling
            FROM daily_business
            JOIN daily_inventory
                ON daily_inventory.daily_id = daily_business.daily_id
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_business.daily_id = ?
              AND products.product_id = ?
        """, (daily_id, product_id))

        record = cursor.fetchone()

        if record is None:
            raise ValueError(
                "Product has not been added to this business day."
            )

        (
            daily_branch_id,
            product_branch_id,
            status,
            stock_handling
        ) = record

        # 3. Validate the business day.
        if status != "OPEN":
            raise ValueError(
                "Starting quantities can only be edited "
                "on open business days."
            )

        # 4. Verify branch ownership.
        if daily_branch_id != product_branch_id:
            raise ValueError(
                "This product does not belong to the selected branch."
            )

        # 5. Allow both supported stock-handling types.
        if stock_handling not in ("PERISHABLE", "CARRY_FORWARD"):
            raise ValueError(
                f"Invalid stock handling type: {stock_handling}"
                )

        # 6. Save or edit the PERISHABLE starting quantity.
        cursor.execute("""
            UPDATE daily_inventory
            SET starting_quantity = ?
            WHERE daily_id = ?
              AND product_id = ?
        """, (quantity, daily_id, product_id))

        # 7. Recalculate expected income using the shared helper.
        expected_income = recalculate_expected_income(
            cursor,
            daily_id
        )

        connection.commit()

        return expected_income

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()




#================================================================
#DAILY STOCK SUMMARY
#================================================================

def get_daily_stock_summary(daily_id):
    """Calculate the daily stock summary for every product."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 1. Retrieve the business day's details.
        cursor.execute("""
            SELECT
                daily_business.business_date,
                daily_business.branch_id,
                branches.branch_name
            FROM daily_business
            JOIN branches
                ON branches.branch_id = daily_business.branch_id
            WHERE daily_business.daily_id = ?
        """, (daily_id,))

        business = cursor.fetchone()

        if business is None:
            raise ValueError("Business day not found.")

        business_date, branch_id, branch_name = business

        # 2. Normalize the business date for matching paid orders.
        try:
            normalized_date = datetime.strptime(
                business_date, "%Y-%m-%d"
            ).date().isoformat()

        except ValueError:
            cleaned_date = re.sub(
                r"(\d+)(st|nd|rd|th)",
                r"\1",
                business_date
            )

            normalized_date = datetime.strptime(
                cleaned_date, "%d %B %Y"
            ).date().isoformat()

        # 3. Recalculate expected income using the reusable helper.
        expected_income = calculate_expected_income(
            cursor,
            daily_id
        )

        # 4. Retrieve inventory records using the final schema.
        cursor.execute("""
            SELECT
                products.product_id,
                products.product_name,
                products.unit_price,
                products.target_stock_quantity,
                products.stock_handling,
                daily_inventory.starting_quantity,
                daily_inventory.deliveries_quantity,
                daily_inventory.physical_closing_quantity
            FROM daily_inventory
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_inventory.daily_id = ?
            ORDER BY products.product_name
        """, (daily_id,))

        products = cursor.fetchall()

        # 5. Calculate actual income from PAID orders only.
        cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0)
            FROM orders
            WHERE branch_id = ?
              AND order_date = ?
              AND order_status = 'PAID'
              AND order_id NOT LIKE 'TBH-TEST-%'
        """, (branch_id, normalized_date))

        actual_income = cursor.fetchone()[0]

        summary = []

        # 6. Calculate stock and sales information per product.
        for product in products:

            (
                product_id,
                product_name,
                unit_price,
                target_stock,
                stock_handling,
                starting_quantity,
                deliveries_quantity,
                physical_closing
            ) = product

            # Count units sold from PAID orders only.
            cursor.execute("""
                SELECT COALESCE(SUM(order_items.quantity), 0)
                FROM orders
                JOIN order_items
                    ON order_items.order_id = orders.order_id
                WHERE orders.branch_id = ?
                  AND orders.order_date = ?
                  AND orders.order_status = 'PAID'
                  AND order_items.product_id = ?
            """, (branch_id, normalized_date, product_id))

            units_sold = cursor.fetchone()[0]

            sales_subtotal = units_sold * unit_price

            # 7. Calculate available stock without treating NULL as zero.
            if stock_handling == "PERISHABLE":

                available_stock = starting_quantity

            elif stock_handling == "CARRY_FORWARD":

                if (
                    starting_quantity is not None
                    and deliveries_quantity is not None
                ):
                    available_stock = (
                        starting_quantity + deliveries_quantity
                    )
                else:
                    available_stock = None

            else:
                raise ValueError(
                    f"Invalid stock handling type: {stock_handling}"
                )

            # 8. Calculate expected closing stock.
            if available_stock is not None:
                expected_closing = available_stock - units_sold
            else:
                expected_closing = None

            # 9. Compare expected and physical closing quantities.
            if (
                physical_closing is not None
                and expected_closing is not None
            ):
                stock_discrepancy = (
                    physical_closing - expected_closing
                )
            else:
                stock_discrepancy = None

            # 10. Calculate the restock requirement.
            if target_stock is None:
                restock_quantity = None

            elif stock_handling == "PERISHABLE":
                # Perishable products require fresh preparation.
                restock_quantity = target_stock

            else:
                # Prefer the physical closing count when available.
                stock_for_restock = (
                    physical_closing
                    if physical_closing is not None
                    else expected_closing
                )

                if stock_for_restock is None:
                    restock_quantity = None
                else:
                    restock_quantity = max(
                        0,
                        target_stock - stock_for_restock
                    )

            # 11. Add the product's summary.
            summary.append({
                "product_id": product_id,
                "product_name": product_name,
                "unit_price": unit_price,
                "starting_stock": starting_quantity,
                "total_deliveries": deliveries_quantity,
                "total_stock": available_stock,
                "available_stock": available_stock,
                "units_sold": units_sold,
                "sales_subtotal": sales_subtotal,
                "expected_closing_stock": expected_closing,
                "physical_closing_stock": physical_closing,
                "stock_discrepancy": stock_discrepancy,
                "target_stock": target_stock,
                "restock_quantity": restock_quantity
            })

        # 12. Calculate the income discrepancy.
        income_discrepancy = actual_income - expected_income

        connection.commit()

        return {
            "daily_id": daily_id,
            "business_date": business_date,
            "branch_id": branch_id,
            "branch_name": branch_name,
            "expected_income": expected_income,
            "actual_income": actual_income,
            "income_discrepancy": income_discrepancy,
            "products": summary
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


#=================================================
# DAILY REPORT BY DATE
#=================================================

def get_daily_report_by_date(branch_id, business_date):
    """Retrieve an existing business report by branch and date."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT daily_id, business_date
            FROM daily_business
            WHERE branch_id = ?
        """, (branch_id,))

        business_days = cursor.fetchall()

        # Normalize the requested date.
        requested_date = (
            business_date.isoformat()
            if hasattr(business_date, "isoformat")
            else str(business_date)
        )

        requested_date = datetime.strptime(
            requested_date, "%Y-%m-%d"
        ).date()

        # Find the matching date, including older date formats.
        matching_daily_id = None

        for daily_id, stored_date in business_days:
            try:
                normalized_date = datetime.strptime(
                    stored_date, "%Y-%m-%d"
                ).date()
            except ValueError:
                cleaned_date = re.sub(
                    r"(\d+)(st|nd|rd|th)",
                    r"\1",
                    stored_date
                )
                normalized_date = datetime.strptime(
                    cleaned_date, "%d %B %Y"
                ).date()

            if normalized_date == requested_date:
                matching_daily_id = daily_id
                break

        if matching_daily_id is None:
            return None

    finally:
        connection.close()

    return get_daily_stock_summary(matching_daily_id)

def clear_inventory_cell(daily_id, product_id, field_name):
    """Clear one inventory quantity field for a product."""

    allowed_fields = {
        "starting_quantity",
        "deliveries_quantity",
        "physical_closing_quantity"
    }

    if field_name not in allowed_fields:
        raise ValueError("Invalid inventory field.")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Confirm that the business day exists and is OPEN.
        cursor.execute("""
            SELECT status
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        business_day = cursor.fetchone()

        if business_day is None:
            raise ValueError("Business day not found.")

        if business_day[0] != "OPEN":
            raise ValueError(
                "Inventory can only be edited on open business days."
            )

        # Confirm that the inventory record exists.
        cursor.execute("""
            SELECT inventory_id
            FROM daily_inventory
            WHERE daily_id = ?
              AND product_id = ?
        """, (daily_id, product_id))

        if cursor.fetchone() is None:
            raise ValueError("Inventory record not found.")

        # Clear only the selected field.
        cursor.execute(f"""
            UPDATE daily_inventory
            SET {field_name} = NULL
            WHERE daily_id = ?
              AND product_id = ?
        """, (daily_id, product_id))

        # Recalculate expected income after clearing a relevant quantity.
        if field_name in {
            "starting_quantity",
            "deliveries_quantity"
        }:
            recalculate_expected_income(cursor, daily_id)

        connection.commit()

        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def clear_product_inventory(daily_id, product_id):
    """Clear inventory quantities for one product on a business day."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Confirm that the business day exists and is OPEN.
        cursor.execute("""
            SELECT status
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        business_day = cursor.fetchone()

        if business_day is None:
            raise ValueError("Business day not found.")

        if business_day[0] != "OPEN":
            raise ValueError(
                "Inventory can only be edited on open business days."
            )

        # Confirm that the product has an inventory record.
        cursor.execute("""
            SELECT inventory_id
            FROM daily_inventory
            WHERE daily_id = ?
              AND product_id = ?
        """, (daily_id, product_id))

        if cursor.fetchone() is None:
            raise ValueError("Inventory record not found.")

        # Clear the starting and physical closing quantities.
        cursor.execute("""
            UPDATE daily_inventory
            SET starting_quantity = NULL,
                physical_closing_quantity = NULL
            WHERE daily_id = ?
              AND product_id = ?
        """, (daily_id, product_id))

        # Preserve delivery history and recalculate cumulative deliveries.
        cursor.execute("""
            SELECT COALESCE(SUM(quantity_received), 0)
            FROM stock_movements
            WHERE daily_id = ?
              AND product_id = ?
        """, (daily_id, product_id))

        total_deliveries = cursor.fetchone()[0]

        if total_deliveries > 0:
            cursor.execute("""
                UPDATE daily_inventory
                SET deliveries_quantity = ?
                WHERE daily_id = ?
                  AND product_id = ?
            """, (total_deliveries, daily_id, product_id))
        else:
            cursor.execute("""
                UPDATE daily_inventory
                SET deliveries_quantity = NULL
                WHERE daily_id = ?
                  AND product_id = ?
            """, (daily_id, product_id))

        # Recalculate expected income using the shared helper.
        recalculate_expected_income(cursor, daily_id)

        connection.commit()

        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def clear_inventory_column(daily_id, field_name):
    """Clear one inventory field across all products for a business day."""

    allowed_fields = {
        "starting_quantity",
        "deliveries_quantity",
        "physical_closing_quantity"
    }

    if field_name not in allowed_fields:
        raise ValueError("Invalid inventory field.")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Confirm that the business day exists and is OPEN.
        cursor.execute("""
            SELECT status
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        business_day = cursor.fetchone()

        if business_day is None:
            raise ValueError("Business day not found.")

        if business_day[0] != "OPEN":
            raise ValueError(
                "Inventory can only be edited on open business days."
            )

        # Confirm that inventory records exist for this day.
        cursor.execute("""
            SELECT COUNT(*)
            FROM daily_inventory
            WHERE daily_id = ?
        """, (daily_id,))

        if cursor.fetchone()[0] == 0:
            raise ValueError("No inventory records found for this business day.")

        if field_name == "deliveries_quantity":
            # Recalculate cumulative deliveries from the movement history.
            # Products without delivery movements will have NULL.
            cursor.execute("""
                UPDATE daily_inventory
                SET deliveries_quantity = (
                    SELECT SUM(sm.quantity_received)
                    FROM stock_movements sm
                    WHERE sm.daily_id = daily_inventory.daily_id
                      AND sm.product_id = daily_inventory.product_id
                )
                WHERE daily_id = ?
            """, (daily_id,))

        else:
            # Clear the selected field for every product.
            cursor.execute(f"""
                UPDATE daily_inventory
                SET {field_name} = NULL
                WHERE daily_id = ?
            """, (daily_id,))

        # Recalculate expected income when relevant quantities change.
        if field_name in {
            "starting_quantity",
            "deliveries_quantity"
        }:
            recalculate_expected_income(cursor, daily_id)

        connection.commit()

        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def reset_daily_inventory(daily_id):
    """Reset inventory quantities for all products on a business day."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Confirm that the business day exists and is OPEN.
        cursor.execute("""
            SELECT status
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        business_day = cursor.fetchone()

        if business_day is None:
            raise ValueError("Business day not found.")

        if business_day[0] != "OPEN":
            raise ValueError(
                "Inventory can only be reset on open business days."
            )

        # Confirm that inventory records exist.
        cursor.execute("""
            SELECT COUNT(*)
            FROM daily_inventory
            WHERE daily_id = ?
        """, (daily_id,))

        if cursor.fetchone()[0] == 0:
            raise ValueError(
                "No inventory records found for this business day."
            )

        # Clear starting and physical closing quantities.
        cursor.execute("""
            UPDATE daily_inventory
            SET starting_quantity = NULL,
                physical_closing_quantity = NULL
            WHERE daily_id = ?
        """, (daily_id,))

        # Rebuild cumulative deliveries from preserved movement records.
        cursor.execute("""
            UPDATE daily_inventory
            SET deliveries_quantity = (
                SELECT SUM(sm.quantity_received)
                FROM stock_movements sm
                WHERE sm.daily_id = daily_inventory.daily_id
                  AND sm.product_id = daily_inventory.product_id
            )
            WHERE daily_id = ?
        """, (daily_id,))

        # Recalculate expected income using the shared helper.
        recalculate_expected_income(cursor, daily_id)

        connection.commit()

        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

#=============================================
# TEST SECTION
#=============================================

if __name__ == "__main__":
    records = view_daily_setup(1)

    for record in records:
        print(record)

    movement_id = record_stock_delivery(
    daily_id=1,
    product_id=1,
    quantity_received=10,
    notes="Test stock delivery"
    )

    print("Stock movement recorded:", movement_id)


    connection = get_connection()
    cursor = connection.cursor()
    
    cursor.execute("""
        SELECT
            product_id,
            quantity_received,
            received_at,
            notes
        FROM stock_movements
        WHERE movement_id = ?
    """, (movement_id,))

    print("Saved stock delivery:", cursor.fetchone())

    connection.close()
