import sqlite3
from src.database import get_connection
from datetime import datetime
import re



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

#=================================================================
#RECORD FRESH PREPARATION
#=================================================================
def record_fresh_preparation(daily_id, product_id, quantity_prepared):
    if (
        isinstance(quantity_prepared, bool)
        or not isinstance(quantity_prepared, int)
        or quantity_prepared <= 0
    ):
        raise ValueError("Prepared quantity must be a positive whole number.")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Confirm that the business day exists.
        cursor.execute("""
            SELECT branch_id
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        daily_business = cursor.fetchone()

        if daily_business is None:
            raise ValueError("Business day does not exist.")

        branch_id = daily_business[0]

        # Confirm that the product belongs to this branch
        # and is marked as perishable.
        cursor.execute("""
            SELECT stock_handling
            FROM products
            WHERE product_id = ?
            AND branch_id = ?
        """, (product_id, branch_id))

        product = cursor.fetchone()

        if product is None:
            raise ValueError("Product does not belong to this branch.")

        if product[0] != "PERISHABLE":
            raise ValueError(
                "Fresh preparation can only be recorded for perishable products."
            )

        # Find the inventory row created during daily initialization.
        cursor.execute("""
            SELECT inventory_id
            FROM daily_inventory
            WHERE daily_id = ?
            AND product_id = ?
        """, (daily_id, product_id))

        inventory = cursor.fetchone()

        if inventory is None:
            raise ValueError(
                "Initialize daily inventory before recording preparation."
            )

        # Add this preparation batch to the stock available today.
        cursor.execute("""
            UPDATE daily_inventory
            SET starting_quantity = starting_quantity + ?
            WHERE daily_id = ?
            AND product_id = ?
        """, (quantity_prepared, daily_id, product_id))

        connection.commit()

        return quantity_prepared

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


#==================================================================
#INITIALIZING THE DAILY INVENTORY
#==================================================================

def initialize_daily_inventory(daily_id):
    """Initialize opening inventory using the previous business day's closing stock."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Identify the branch and date for this business day.
        cursor.execute("""
            SELECT branch_id, business_date
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        current_day = cursor.fetchone()

        if current_day is None:
            raise ValueError("Business day does not exist.")

        branch_id, business_date = current_day

        # Find the most recent earlier business day for this branch.
        cursor.execute("""
            SELECT daily_id
            FROM daily_business
            WHERE branch_id = ?
              AND (
                  CASE
                      WHEN business_date GLOB '????-??-??'
                      THEN date(business_date)
                      ELSE date(
                          substr(business_date, -4) || '-' ||
                          CASE
                              WHEN business_date LIKE '%January%' THEN '01'
                              WHEN business_date LIKE '%February%' THEN '02'
                              WHEN business_date LIKE '%March%' THEN '03'
                              WHEN business_date LIKE '%April%' THEN '04'
                              WHEN business_date LIKE '%May%' THEN '05'
                              WHEN business_date LIKE '%June%' THEN '06'
                              WHEN business_date LIKE '%July%' THEN '07'
                              WHEN business_date LIKE '%August%' THEN '08'
                              WHEN business_date LIKE '%September%' THEN '09'
                              WHEN business_date LIKE '%October%' THEN '10'
                              WHEN business_date LIKE '%November%' THEN '11'
                              WHEN business_date LIKE '%December%' THEN '12'
                          END || '-' ||
                          printf('%02d', CAST(business_date AS INTEGER))
                      )
                  END
              ) < date(?)
            ORDER BY
                CASE
                    WHEN business_date GLOB '????-??-??'
                    THEN date(business_date)
                    ELSE date(
                        substr(business_date, -4) || '-' ||
                        CASE
                            WHEN business_date LIKE '%January%' THEN '01'
                            WHEN business_date LIKE '%February%' THEN '02'
                            WHEN business_date LIKE '%March%' THEN '03'
                            WHEN business_date LIKE '%April%' THEN '04'
                            WHEN business_date LIKE '%May%' THEN '05'
                            WHEN business_date LIKE '%June%' THEN '06'
                            WHEN business_date LIKE '%July%' THEN '07'
                            WHEN business_date LIKE '%August%' THEN '08'
                            WHEN business_date LIKE '%September%' THEN '09'
                            WHEN business_date LIKE '%October%' THEN '10'
                            WHEN business_date LIKE '%November%' THEN '11'
                            WHEN business_date LIKE '%December%' THEN '12'
                          END || '-' ||
                          printf('%02d', CAST(business_date AS INTEGER))
                    )
                END DESC
            LIMIT 1
        """, (branch_id, business_date))

        previous_day = cursor.fetchone()
        previous_daily_id = previous_day[0] if previous_day else None

        # Load all products belonging to this branch.
        cursor.execute("""
            SELECT product_id, stock_handling
            FROM products
            WHERE branch_id = ?
        """, (branch_id,))

        products = cursor.fetchall()
        opening_stock = []

        for product_id, stock_handling in products:

            # Preserve existing inventory records.
            cursor.execute("""
                SELECT starting_quantity
                FROM daily_inventory
                WHERE daily_id = ?
                  AND product_id = ?
            """, (daily_id, product_id))

            existing_inventory = cursor.fetchone()

            if existing_inventory:
                opening_stock.append(
                    (product_id, existing_inventory[0])
                )
                continue

            starting_quantity = 0

            # Carry forward only products that support it.
            if (
                previous_daily_id is not None
                and stock_handling == "CARRY_FORWARD"
            ):
                cursor.execute("""
                    SELECT physical_closing_quantity
                    FROM daily_inventory
                    WHERE daily_id = ?
                      AND product_id = ?
                """, (previous_daily_id, product_id))

                previous_stock = cursor.fetchone()

                if previous_stock is None or previous_stock[0] is None:
                    raise ValueError(
                        f"Missing closing count for carry-forward product "
                        f"{product_id} on the previous business day."
                    )

                starting_quantity = previous_stock[0]

            cursor.execute("""
                INSERT INTO daily_inventory (
                    daily_id,
                    product_id,
                    starting_quantity
                )
                VALUES (?, ?, ?)
            """, (daily_id, product_id, starting_quantity))

            opening_stock.append((product_id, starting_quantity))

        connection.commit()
        return opening_stock

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
    """Complete a business day only when all closing counts exist."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT status, branch_id
            FROM daily_business
            WHERE daily_id = ?
        """, (daily_id,))

        business_day = cursor.fetchone()

        if business_day is None:
            raise ValueError("Business day not found.")

        if business_day[0] != "OPEN":
            raise ValueError(
                f"Business day cannot be completed. "
                f"Current status: {business_day[0]}."
            )
        
        branch_id = business_day[1]

        # Confirm every branch product has an inventory record.
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
    if not isinstance(quantity_received, int) or isinstance(quantity_received, bool) or quantity_received <= 0:
        raise ValueError("Delivery quantity must be a positive integer.")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT daily_business.branch_id, products.branch_id
            FROM daily_business
            JOIN products
                ON products.product_id = ?
            WHERE daily_business.daily_id = ?
        """, (product_id, daily_id))

        record = cursor.fetchone()

        if record is None:
            raise ValueError("Business day or product does not exist.")

        daily_branch_id, product_branch_id = record

        if daily_branch_id != product_branch_id:
            raise ValueError(
                "This product does not belong to the selected branch."
            )

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

        connection.commit()

        return cursor.lastrowid

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
                daily_inventory.starting_quantity
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

        daily_branch_id, product_branch_id, starting_stock = record

        if daily_branch_id != product_branch_id:
            raise ValueError(
                "This product does not belong to the selected branch."
            )

        # Add deliveries to starting stock to get total availability.
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
def save_opening_stock_quantity(daily_id, product_id, quantity):
    """Save opening stock and projected sales for an employee's entry."""

    if (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity < 0
    ):
        raise ValueError(
            "Quantity must be a non-negative integer."
        )

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                daily_business.branch_id,
                products.branch_id
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

        daily_branch_id, product_branch_id = record

        if daily_branch_id != product_branch_id:
            raise ValueError(
                "This product does not belong to the selected branch."
            )

        cursor.execute("""
            UPDATE daily_inventory
            SET starting_quantity = ?,
                projected_sales_quantity = ?
            WHERE daily_id = ?
              AND product_id = ?
        """, (quantity, quantity, daily_id, product_id))

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
#DAILY STOCK SUMMARY
#================================================================

def get_daily_stock_summary(daily_id):
    """Calculate the daily stock summary for every product."""

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Get the selected business day's details.
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

        # Convert the business date to the order date format (YYYY-MM-DD).
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

        # Get every product recorded for this business day.
        cursor.execute("""
            SELECT
                products.product_id,
                products.product_name,
                products.unit_price,
                products.target_stock_quantity,
                products.stock_handling,
                daily_inventory.starting_quantity,
                daily_inventory.projected_sales_quantity,
                daily_inventory.physical_closing_quantity
            FROM daily_inventory
            JOIN products
                ON products.product_id = daily_inventory.product_id
            WHERE daily_inventory.daily_id = ?
            ORDER BY products.product_name
        """, (daily_id,))

        products = cursor.fetchall()

        # Calculate expected income from opening inventory value.
        expected_income = sum(
            product[5] * product[2]
            for product in products
        )

        # Calculate actual income from confirmed paid orders.
        cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0)
            FROM orders
            WHERE branch_id = ?
              AND order_date = ?
              AND order_status = 'PAID'
        """, (branch_id, normalized_date))

        actual_income = cursor.fetchone()[0]
        income_discrepancy = actual_income - expected_income

        summary = []

        for product in products:
            (
                product_id,
                product_name,
                unit_price,
                target_stock,
                stock_handling,
                starting_stock,
                projected_sales_quantity,
                physical_closing
            ) = product

            # Calculate total deliveries for this product today.
            cursor.execute("""
                SELECT COALESCE(SUM(quantity_received), 0)
                FROM stock_movements
                WHERE daily_id = ?
                  AND product_id = ?
            """, (daily_id, product_id))

            total_deliveries = cursor.fetchone()[0]

            # Count quantities from confirmed paid orders
            # for this branch and business date only.
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

            # Calculate the stock figures.
            opening_stock_subtotal = starting_stock * unit_price
            total_stock = starting_stock + total_deliveries
            expected_closing = total_stock - units_sold
            projected_closing = total_stock - projected_sales_quantity

            if physical_closing is not None:
                discrepancy = physical_closing - expected_closing
            else:
                discrepancy = None

            # Perishable stock must be prepared fresh for the next day.
            # Carry-forward stock uses the physical count when available.
            if stock_handling == "PERISHABLE":
                stock_for_restock = 0
            else:
                stock_for_restock = (
                    physical_closing
                    if physical_closing is not None
                    else expected_closing
                )

            restock_quantity = max(
                0, target_stock - stock_for_restock
            )

            summary.append({
                "product_id": product_id,
                "product_name": product_name,
                "unit_price": unit_price,
                "starting_stock": starting_stock,
                "opening_stock_subtotal": opening_stock_subtotal,
                "total_deliveries": total_deliveries,
                "total_stock": total_stock,
                "projected_sales_quantity": projected_sales_quantity,
                "units_sold": units_sold,
                "sales_subtotal": sales_subtotal,
                "expected_closing_stock": expected_closing,
                "projected_closing_stock": projected_closing,
                "physical_closing_stock": physical_closing,
                "stock_discrepancy": discrepancy,
                "target_stock": target_stock,
                "restock_quantity": restock_quantity
            })

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

    finally:
        connection.close()



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
