from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.customer_order import (
    get_branch_products,
    validate_and_calculate_order,
    record_order,
    record_pending_payment,
    save_mpesa_response,
)
from src.mpesa import initiate_payment
from src.database import get_connection
from src.callback import router as mpesa_callback_router
from src.daily_setup import get_daily_stock_summary
from datetime import date
from src.daily_setup import (
    create_daily_business,
    initialize_daily_inventory,
    view_daily_setup,
    record_physical_closing,
    record_stock_delivery,
    get_daily_report_by_date,
    set_projected_sales,
    save_opening_stock_quantity
)

class DailyBusinessRequest(BaseModel):
    branch_id: int
    business_date: date

class ProjectedSalesRequest(BaseModel):
    daily_id: int
    product_id: int
    quantity: int    

app = FastAPI(
    title="Tobhe API",
    description="Business oversight and branch operations API",
    version="0.1.0",
)

app.mount(
    "/static",
    StaticFiles(directory="src/static"),
    name="static",
)

@app.get("/", include_in_schema=False)
def home():
    return FileResponse("src/static/index.html")

@app.get("/owner", include_in_schema=False)
def owner_home():
    return FileResponse("src/static/owner.html")

@app.get("/employee", include_in_schema=False)
def employee_home():
    return FileResponse("src/static/employee.html")

app.include_router(mpesa_callback_router)
@app.get("/branches")
def list_branches():
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT branch_id, branch_name, business_type
            FROM branches
            ORDER BY branch_id
        """)

        branches = cursor.fetchall()

        return {
            "branches": [
                {
                    "branch_id": branch[0],
                    "branch_name": branch[1],
                    "business_type": branch[2],
                }
                for branch in branches
            ]
        }

    finally:
        connection.close()


@app.post("/daily-business")
def start_daily_business(request: DailyBusinessRequest):
    branch_id = request.branch_id
    business_date = request.business_date

    try:
        connection = get_connection()

        try:
            existing_day = connection.execute("""
                SELECT daily_id, expected_income
                FROM daily_business
                WHERE branch_id = ?
                  AND business_date = ?
            """, (
                branch_id,
                business_date.isoformat(),
            )).fetchone()
        finally:
            connection.close()

        if existing_day is not None:
            daily_id = existing_day[0]
            expected_income = existing_day[1]

            connection = get_connection()

            try:
                opening_stock = connection.execute("""
                    SELECT product_id, starting_quantity
                    FROM daily_inventory
                    WHERE daily_id = ?
                """, (daily_id,)).fetchall()
            finally:
                connection.close()

            return {
                "daily_id": daily_id,
                "branch_id": branch_id,
                "business_date": business_date.isoformat(),
                "expected_income": expected_income,
                "opening_stock": [
                    {
                        "product_id": product_id,
                        "starting_quantity": quantity,
                    }
                    for product_id, quantity in opening_stock
                ],
                "message": "Existing business day loaded successfully.",
            }

        # Create the business day with a temporary value.
        daily_id = create_daily_business(
            branch_id,
            business_date.isoformat(),
            0,
        )


        try:
            # Initialize the opening inventory.
            opening_stock = initialize_daily_inventory(daily_id)

            connection = get_connection()

            try:
                cursor = connection.cursor()
                expected_income = 0

                # Calculate potential sales value from opening stock.
                for product_id, quantity in opening_stock:
                    quantity = 0 if quantity is None else quantity

                    cursor.execute("""
                        SELECT unit_price
                        FROM products
                        WHERE product_id = ?
                          AND branch_id = ?
                    """, (product_id, branch_id))

                    product = cursor.fetchone()

                    if product is None:
                        raise ValueError(
                            f"Product {product_id} was not found "
                            f"for branch {branch_id}."
                        )

                    expected_income += quantity * product[0]

                # Save the calculated value for this business day.
                cursor.execute("""
                    UPDATE daily_business
                    SET expected_income = ?
                    WHERE daily_id = ?
                """, (expected_income, daily_id))

                connection.commit()

            except Exception:
                connection.rollback()
                raise

            finally:
                connection.close()

        except Exception:
            # Remove the new business day if initialization fails.
            connection = get_connection()

            try:
                connection.execute(
                    "DELETE FROM daily_inventory WHERE daily_id = ?",
                    (daily_id,),
                )
                connection.execute(
                    "DELETE FROM daily_business WHERE daily_id = ?",
                    (daily_id,),
                )
                connection.commit()

            except Exception:
                connection.rollback()
                raise

            finally:
                connection.close()

            raise

        return {
            "daily_id": daily_id,
            "branch_id": branch_id,
            "business_date": business_date.isoformat(),
            "expected_income": expected_income,
            "opening_stock": [
                {
                    "product_id": product_id,
                    "starting_quantity": (
                        0 if quantity is None else quantity
                    ),
                }
                for product_id, quantity in opening_stock
            ],
            "message": "Daily business initialized successfully.",
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )



@app.post("/daily-inventory/projected-sales")
def save_projected_sales(request: ProjectedSalesRequest):
    try:
        expected_income = set_projected_sales(
            request.daily_id,
            request.product_id,
            request.quantity,
        )

        return {
            "daily_id": request.daily_id,
            "product_id": request.product_id,
            "quantity": request.quantity,
            "expected_income": expected_income,
            "message": "Product quantity saved successfully.",
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )


@app.post("/daily-inventory/opening-stock")
def save_employee_opening_stock(request: ProjectedSalesRequest):
    try:
        expected_income = save_opening_stock_quantity(
            request.daily_id,
            request.product_id,
            request.quantity,
        )

        return {
            "daily_id": request.daily_id,
            "product_id": request.product_id,
            "quantity": request.quantity,
            "expected_income": expected_income,
            "message": "Opening stock saved successfully.",
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Tobhe API",
    }


@app.get("/daily-business/{daily_id}/stock-summary")
def daily_stock_summary(daily_id: int):
    try:
        return get_daily_stock_summary(daily_id)
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )


@app.get("/branches/{branch_id}/daily-report")
def daily_report_by_date(branch_id: int, business_date: date):
    try:
        report = get_daily_report_by_date(branch_id, business_date)

        if report is None:
            raise HTTPException(
                status_code=404,
                detail="No report recorded for this branch and date."
            )

        return report

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )



@app.get("/branches/{branch_id}/products")
def branch_products(branch_id: int):
    products = get_branch_products(branch_id)

    return {
        "branch_id": branch_id,
        "products": [
            {
                "product_id": product[0],
                "product_name": product[1],
                "unit_price": product[2],
            }
            for product in products
        ],
    }


@app.post("/orders/preview")
def preview_order(branch_id: int, items: list[dict]):
    order_items, order_total = validate_and_calculate_order(items)

    return {
        "branch_id": branch_id,
        "items": order_items,
        "order_total": order_total,
    }


@app.post("/orders")
def create_order(branch_id: int, items: list[dict]):
    order_items, order_total = validate_and_calculate_order(items)

    order_id = record_order(
        branch_id,
        order_items,
        order_total,
    )

    return {
        "branch_id": branch_id,
        "order_id": order_id,
        "items": order_items,
        "order_total": order_total,
        "order_status": "PENDING_PAYMENT",
    }


def get_order_payment_details(order_id: str):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT total_amount, order_status
            FROM orders
            WHERE order_id = ?
            """,
            (order_id,),
        )
        return cursor.fetchone()
    finally:
        connection.close()


def mark_payment_failed(payment_id: str, error_message: str):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE payments
            SET payment_status = 'FAILED',
                result_description = ?
            WHERE payment_id = ?
              AND payment_status = 'PENDING'
            """,
            (error_message, payment_id),
        )
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


@app.post("/orders/{order_id}/payment")
def pay_for_order(order_id: str, phone_number: str):
    order = get_order_payment_details(order_id)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    amount, order_status = order

    if order_status != "PENDING_PAYMENT":
        raise HTTPException(
            status_code=409,
            detail=f"Order is not awaiting payment. Current status: {order_status}",
        )

    payment_id = record_pending_payment(
        order_id,
        phone_number,
        amount,
        "MPESA",
    )

    try:
        response = initiate_payment(
            order_id,
            phone_number,
            amount,
        )

        save_mpesa_response(payment_id, response)

    except Exception as error:
        # A request failure may have an uncertain outcome, so don't
        # automatically mark the payment FAILED here.
        # Safaricom may have received the request despite a timeout.
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Could not confirm the STK Push response. Check the payment status before retrying.",
                "order_id": order_id,
                "payment_id": payment_id,
                "error": str(error),
            },
        ) from error

    response_code = response.get("ResponseCode")

    if str(response_code) != "0":
        mark_payment_failed(
            payment_id,
            response.get("ResponseDescription", "STK Push request rejected"),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Safaricom did not accept the STK Push request.",
                "order_id": order_id,
                "payment_id": payment_id,
                "response": response,
            },
        )

    return {
        "order_id": order_id,
        "payment_id": payment_id,
        "amount": amount,
        "payment_status": "PENDING",
        "checkout_request_id": response.get("CheckoutRequestID"),
        "merchant_request_id": response.get("MerchantRequestID"),
        "message": response.get(
            "ResponseDescription",
            "STK Push request submitted",
        ),
    }
