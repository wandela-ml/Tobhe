from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.callback import router as mpesa_callback_router
from src.customer_order import (
    get_branch_products,
    validate_and_calculate_order,
    record_order,
    record_pending_payment,
    save_mpesa_response,
)
from src.database import get_connection
from src.daily_setup import (
    create_daily_business,
    initialize_daily_inventory,
    record_physical_closing,
    record_stock_delivery,
    get_daily_report_by_date,
    save_starting_quantity,
    complete_business_day,
    get_stock_delivery_history,
    update_stock_delivery,
    set_product_target_stock,
    set_product_price,
    get_daily_stock_summary,
    clear_inventory_cell,
    clear_product_inventory,
    clear_inventory_column,
    reset_daily_inventory,
    delete_stock_delivery
)
from src.mpesa import initiate_payment


class DailyBusinessRequest(BaseModel):
    branch_id: int
    business_date: date


class StartingQuantityRequest(BaseModel):
    daily_id: int
    product_id: int
    quantity: int = Field(ge=0)


class PhysicalClosingRequest(BaseModel):
    daily_id: int
    product_id: int
    quantity: int = Field(ge=0)


class StockDeliveryRequest(BaseModel):
    daily_id: int
    product_id: int
    quantity_received: int = Field(ge=0)
    notes: str | None = None


class UpdateStockDeliveryRequest(BaseModel):
    quantity_received: int = Field(gt=0)
    notes: str | None = None


class TargetStockRequest(BaseModel):
    target_quantity: int = Field(ge=0)


class ProductPriceRequest(BaseModel):
    new_price: float = Field(ge=0)


class ClearInventoryCellRequest(BaseModel):
    daily_id: int
    product_id: int
    field_name: str


class ClearProductInventoryRequest(BaseModel):
    daily_id: int
    product_id: int


class ClearInventoryColumnRequest(BaseModel):
    daily_id: int
    field_name: str


class ResetDailyInventoryRequest(BaseModel):
    daily_id: int

class OrderItemRequest(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class CustomerOrderRequest(BaseModel):
    branch_id: int
    items: list[OrderItemRequest]
    phone_number: str
   


def get_active_business_date(branch_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT business_date
            FROM daily_business
            WHERE branch_id = ?
              AND status = 'OPEN'
        """, (branch_id,))

        business_day = cursor.fetchone()

        if business_day is None:
            return None

        return business_day[0]

    finally:
        connection.close()


app = FastAPI(
    title="Tobhe API",
    description="Business oversight and branch operations API",
    version="0.2.0",
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/owner", include_in_schema=False)
def owner_home():
    return FileResponse(STATIC_DIR / "owner.html")


@app.get("/employee", include_in_schema=False)
def employee_home():
    return FileResponse(STATIC_DIR / "employee.html")


app.include_router(mpesa_callback_router)


def raise_bad_request(error: ValueError):
    raise HTTPException(status_code=400, detail=str(error))


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Tobhe API"}


@app.get("/branches")
def list_branches():
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT branch_id, branch_name, business_type
            FROM branches
            ORDER BY branch_id
            """
        ).fetchall()

        return {
            "branches": [
                {
                    "branch_id": row[0],
                    "branch_name": row[1],
                    "business_type": row[2],
                }
                for row in rows
            ]
        }
    finally:
        connection.close()


@app.post("/daily-business")
def start_daily_business(request: DailyBusinessRequest):
    business_date = request.business_date.isoformat()

    try:
        daily_id = create_daily_business(
            request.branch_id,
            business_date,
            0,
        )
    except ValueError as error:
        raise_bad_request(error)

    # Roll back the newly created day only if inventory initialization fails.
    try:
        opening_stock = initialize_daily_inventory(daily_id)
    except Exception as error:
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

        if isinstance(error, ValueError):
            raise_bad_request(error)
        raise

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT expected_income
            FROM daily_business
            WHERE daily_id = ?
            """,
            (daily_id,),
        ).fetchone()
    finally:
        connection.close()

    return {
        "daily_id": daily_id,
        "branch_id": request.branch_id,
        "business_date": business_date,
        "expected_income": row[0] if row else None,
        "opening_stock": [
            {"product_id": product_id, "starting_quantity": quantity}
            for product_id, quantity in opening_stock
        ],
        "message": "Daily business initialized successfully.",
    }


@app.get("/branches/{branch_id}/daily-business")
def get_existing_daily_business(
    branch_id: int,
    business_date: date
):
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT daily_id, status, expected_income
            FROM daily_business
            WHERE branch_id = ?
              AND business_date = ?
        """, (branch_id, business_date.isoformat()))

        record = cursor.fetchone()

        if record is None:
            return {
                "exists": False,
                "message": "No business day exists for this branch and date."
            }

        return {
            "exists": True,
            "daily_id": record[0],
            "branch_id": branch_id,
            "business_date": business_date.isoformat(),
            "status": record[1],
            "expected_income": record[2]
        }

    finally:
        connection.close()


@app.post("/daily-business/{daily_id}/complete")
def close_business_day(daily_id: int):
    try:
        complete_business_day(daily_id)
        return {
            "daily_id": daily_id,
            "status": "COMPLETE",
            "message": "Business day completed successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.post("/daily-inventory/opening-stock")
def save_employee_opening_stock(request: StartingQuantityRequest):
    try:
        expected_income = save_starting_quantity(
            request.daily_id,
            request.product_id,
            request.quantity,
        )
        return {
            "daily_id": request.daily_id,
            "product_id": request.product_id,
            "quantity": request.quantity,
            "expected_income": expected_income,
            "message": "Starting quantity saved successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.post("/daily-inventory/physical-closing")
def save_physical_closing(request: PhysicalClosingRequest):
    try:
        record_physical_closing(
            request.daily_id,
            request.product_id,
            request.quantity,
        )
        return {
            "daily_id": request.daily_id,
            "product_id": request.product_id,
            "quantity": request.quantity,
            "message": "Physical closing quantity saved successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.post("/daily-inventory/stock-delivery")
def save_stock_delivery(request: StockDeliveryRequest):
    try:
        movement_id = record_stock_delivery(
            request.daily_id,
            request.product_id,
            request.quantity_received,
            request.notes,
        )
        return {
            "daily_id": request.daily_id,
            "product_id": request.product_id,
            "quantity_received": request.quantity_received,
            "movement_id": movement_id,
            "message": "Stock delivery saved successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.put("/stock-deliveries/{movement_id}")
def edit_stock_delivery(
    movement_id: int,
    request: UpdateStockDeliveryRequest,
):
    try:
        update_stock_delivery(
            movement_id,
            request.quantity_received,
            request.notes,
        )
        return {
            "movement_id": movement_id,
            "quantity_received": request.quantity_received,
            "notes": request.notes,
            "message": "Stock delivery updated successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)

@app.delete("/stock-deliveries/{movement_id}")
def remove_stock_delivery(movement_id: int):
    try:
        delete_stock_delivery(movement_id)

        return {
            "movement_id": movement_id,
            "message": "Stock delivery deleted successfully.",
        }

    except ValueError as error:
        raise_bad_request(error)

@app.get("/daily-business/{daily_id}/stock-deliveries")
def view_stock_deliveries(daily_id: int):
    try:
        records = get_stock_delivery_history(daily_id)
        return {
            "daily_id": daily_id,
            "deliveries": [
                {
                    "movement_id": row[0],
                    "product_id": row[1],
                    "product_name": row[2],
                    "quantity_received": row[3],
                    "received_at": row[4],
                    "notes": row[5],
                    "cumulative_deliveries": row[6],
                }
                for row in records
            ],
        }
    except ValueError as error:
        raise_bad_request(error)


@app.get("/daily-business/{daily_id}/stock-summary")
def daily_stock_summary(daily_id: int):
    try:
        return get_daily_stock_summary(daily_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@app.get("/branches/{branch_id}/daily-report")
def daily_report_by_date(branch_id: int, business_date: date):
    try:
        report = get_daily_report_by_date(branch_id, business_date)
    except ValueError as error:
        raise_bad_request(error)

    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No report recorded for this branch and date.",
        )
    return report


@app.get("/branches/{branch_id}/products")
def branch_products(branch_id: int):
    effective_date = get_active_business_date(branch_id)

    if effective_date is None:
        raise HTTPException(
            status_code=404,
            detail="This business is not currently accepting orders."
        )

    try:
        products = get_branch_products(
            branch_id,
            effective_date
        )
    except ValueError as error:
        raise_bad_request(error)

    return {
        "branch_id": branch_id,
        "order_date": effective_date,
        "products": [
            {
                "product_id": row[0],
                "product_name": row[1],
                "unit_price": row[2],
                "stock_handling": row[3],
                "available_quantity": row[4],
            }
            for row in products
        ],
    }


@app.put("/products/{product_id}/target-stock")
def update_product_target_stock(
    product_id: int,
    request: TargetStockRequest,
):
    try:
        set_product_target_stock(product_id, request.target_quantity)
        return {
            "product_id": product_id,
            "target_quantity": request.target_quantity,
            "message": "Target stock updated successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.put("/products/{product_id}/price")
def schedule_product_price(
    product_id: int,
    request: ProductPriceRequest,
):
    try:
        set_product_price(product_id, request.new_price)
        return {
            "product_id": product_id,
            "new_price": request.new_price,
            "message": "New price scheduled to take effect the next calendar day.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.post("/daily-inventory/clear-cell")
def clear_one_inventory_cell(request: ClearInventoryCellRequest):
    try:
        clear_inventory_cell(
            request.daily_id,
            request.product_id,
            request.field_name,
        )
        return {
            "daily_id": request.daily_id,
            "product_id": request.product_id,
            "field_name": request.field_name,
            "message": "Inventory field cleared successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.post("/daily-inventory/clear-product")
def clear_one_product_inventory(request: ClearProductInventoryRequest):
    try:
        clear_product_inventory(request.daily_id, request.product_id)
        return {
            "daily_id": request.daily_id,
            "product_id": request.product_id,
            "message": "Product inventory quantities cleared successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.post("/daily-inventory/clear-column")
def clear_inventory_for_column(request: ClearInventoryColumnRequest):
    try:
        clear_inventory_column(request.daily_id, request.field_name)
        return {
            "daily_id": request.daily_id,
            "field_name": request.field_name,
            "message": "Inventory column cleared successfully.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.post("/daily-inventory/reset")
def reset_inventory_for_day(request: ResetDailyInventoryRequest):
    try:
        reset_daily_inventory(request.daily_id)
        return {
            "daily_id": request.daily_id,
            "message": "Daily inventory quantities reset successfully. Delivery history was preserved.",
        }
    except ValueError as error:
        raise_bad_request(error)


@app.post("/orders/preview")
def preview_order(
    branch_id: int,
    items: list[dict],
    order_date: date | None = None,
):
    effective_date = (order_date or date.today()).isoformat()
    try:
        order_items, order_total = validate_and_calculate_order(
            items,
            branch_id,
            effective_date,
        )
        return {
            "branch_id": branch_id,
            "order_date": effective_date,
            "items": order_items,
            "order_total": order_total,
        }
    except ValueError as error:
        raise_bad_request(error)




@app.post("/orders")
def create_order(request: CustomerOrderRequest):
    
    effective_date = get_active_business_date(request.branch_id)
        
    if effective_date is None:
        raise HTTPException(
            status_code=404,
            detail="This business is not currently accepting orders."
            )

    try:
        # Convert the request items into dictionaries.
        items = [
            item.model_dump()
            for item in request.items
        ]

        # 1. Validate the order and calculate its total.
        order_items, order_total = validate_and_calculate_order(
            items,
            request.branch_id,
            effective_date,
        )

        # 2. Save the order.
        order_id = record_order(
            request.branch_id,
            order_items,
            order_total,
            effective_date,
        )

        # 3. Create a pending payment record.
        payment_id = record_pending_payment(
            order_id,
            request.phone_number,
            order_total,
            "M-Pesa",
        )

        # 4. Initiate the M-Pesa STK Push.
        payment_response = initiate_payment(
            order_id,
            request.phone_number,
            order_total,
        )

        # 5. Save Safaricom's response.
        save_mpesa_response(
            payment_id,
            payment_response,
        )

        response_accepted = (
            str(payment_response.get("ResponseCode")) == "0"
        )

        return {
            "branch_id": request.branch_id,
            "order_id": order_id,
            "payment_id": payment_id,
            "order_date": effective_date,
            "items": order_items,
            "order_total": order_total,
            "order_status": "PENDING_PAYMENT",
            "payment_status": (
                "PENDING" if response_accepted else "FAILED"
            ),
            "payment_message": payment_response.get(
                "ResponseDescription", ""
            ),
        }

    except ValueError as error:
        raise_bad_request(error)

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Payment initiation failed: {error}",
        )



def get_order_payment_details(order_id: str):
    connection = get_connection()
    try:
        return connection.execute(
            """
            SELECT total_amount, order_status
            FROM orders
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()
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
        raise HTTPException(status_code=404, detail="Order not found.")

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
        response = initiate_payment(order_id, phone_number, amount)
        save_mpesa_response(payment_id, response)
    except Exception as error:
        # A timeout can have an uncertain outcome. Keep the payment record
        # pending so the user can check its status before attempting again.
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
