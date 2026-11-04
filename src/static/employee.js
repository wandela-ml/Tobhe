
document.addEventListener("DOMContentLoaded", () => {
    loadBranches();

    document
        .getElementById("daily-entry-form")
        .addEventListener("submit", startBusinessDay);

    document
        .getElementById("save-inventory-button")
        .addEventListener("click", saveInventory);

    document
        .getElementById("close-business-day-button")
        .addEventListener("click", closeBusinessDay);
});


// --------------------------------------------------
// 1. LOAD BRANCHES
// --------------------------------------------------

async function loadBranches() {
    const branchSelect = document.getElementById("branch");
    const message = document.getElementById("entry-message");

    try {
        const response = await fetch("/branches");
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Could not load branches.");
        }

        data.branches.forEach((branch) => {
            const option = document.createElement("option");

            option.value = branch.branch_id;
            option.textContent = branch.branch_name;

            branchSelect.appendChild(option);
        });

    } catch (error) {
        message.textContent =
            "Unable to load branches. Please refresh the page.";

        console.error("Branch loading error:", error);
    }
}


// --------------------------------------------------
// 2. INITIALIZE THE BUSINESS DAY
// --------------------------------------------------

async function startBusinessDay(event) {
    event.preventDefault();

    const branchId = Number(
        document.getElementById("branch").value
    );

    const businessDate =
        document.getElementById("business-date").value;

    const message =
        document.getElementById("entry-message");

    const button =
        event.target.querySelector("button");

    const inventorySection =
        document.getElementById("inventory-section");

    const container =
        document.getElementById("inventory-table-container");

    if (!branchId || !businessDate) {
        message.textContent =
            "Please select a branch and business date.";
        return;
    }

    button.disabled = true;
    inventorySection.hidden = true;
    container.textContent = "Checking business day...";
    message.textContent = "";

    try {
        const lookupResponse = await fetch(
            `/branches/${branchId}/daily-business?business_date=${encodeURIComponent(businessDate)}`
        );

        const lookupData = await lookupResponse.json();

        if (!lookupResponse.ok) {
            throw new Error(
                lookupData.detail ||
                "Could not check the business day."
            );
        }

        let dailyId;
        let dayStatus;
        let openingStock = [];
        let savedSummary = null;

        if (lookupData.exists) {
            dailyId = lookupData.daily_id;
            dayStatus = lookupData.status;

            const summaryResponse = await fetch(
                `/daily-business/${dailyId}/stock-summary`
            );

            savedSummary = await summaryResponse.json();

            if (!summaryResponse.ok) {
                throw new Error(
                    savedSummary.detail ||
                    "Could not retrieve saved inventory."
                );
            }

            message.textContent =
                "Existing business day found. Loading saved inventory...";

        } else {
            message.textContent =
                "No existing day found. Creating a new business day...";

            const createResponse = await fetch(
                "/daily-business",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        branch_id: branchId,
                        business_date: businessDate
                    })
                }
            );

            const createData = await createResponse.json();

            if (!createResponse.ok) {
                throw new Error(
                    createData.detail ||
                    "Could not create the business day."
                );
            }

            dailyId = createData.daily_id;
            dayStatus = "OPEN";
            openingStock = createData.opening_stock || [];
        }

        inventorySection.hidden = false;

        await loadInventory(
            branchId,
            dailyId,
            businessDate,
            openingStock,
            savedSummary
        );

        const saveButton =
            document.getElementById("save-inventory-button");

        const closeButton =
            document.getElementById("close-business-day-button");

        if (dayStatus === "COMPLETE") {
            container
                .querySelectorAll("input, select")
                .forEach((control) => {
                    control.disabled = true;
                });

            saveButton.disabled = true;

            closeButton.disabled = true;
            closeButton.textContent = "Business Day Closed";

            message.textContent =
                "Completed business day retrieved. Inventory is read-only.";

        } else if (dayStatus === "OPEN") {
            saveButton.disabled = false;

            closeButton.disabled = false;
            closeButton.textContent = "Close Business Day";

            message.textContent = lookupData.exists
                ? "Existing open business day retrieved. You can continue updating its inventory."
                : "New business day created and initialized successfully.";

        } else {
            throw new Error(
                `Unrecognized business day status: ${dayStatus}`
            );
        }

        console.log("Daily ID:", dailyId);
        console.log("Business day status:", dayStatus);

    } catch (error) {
        inventorySection.hidden = true;
        container.textContent = "";
        message.textContent = error.message;

        console.error("Business day operation error:", error);

    } finally {
        button.disabled = false;
    }
}


// --------------------------------------------------
// 3. LOAD PRODUCTS AND BUILD THE INVENTORY TABLE
// --------------------------------------------------

async function loadInventory(
    branchId,
    dailyId,
    businessDate,
    openingStock,
    savedSummary = null
) {
    const container =
        document.getElementById("inventory-table-container");

    const message =
        document.getElementById("entry-message");

    container.textContent = "Loading products...";

    try {
        const response = await fetch(
            `/branches/${branchId}/products?order_date=${encodeURIComponent(businessDate)}`
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Could not load branch products."
            );
        }

        const savedProducts = savedSummary?.products || [];

        await loadStockDeliveryHistory(dailyId);

        function getSavedProduct(productId) {
            return savedProducts.find(
                (item) => item.product_id === productId
            );
        }

        function getOpeningQuantity(productId) {
            const savedProduct = getSavedProduct(productId);

            if (savedProduct) {
                return savedProduct.starting_stock ?? null;
            }

            return getStartingQuantity(openingStock, productId);
        }

        function getDeliveryQuantity(productId) {
            const savedProduct = getSavedProduct(productId);

            if (savedProduct) {
                return savedProduct.total_deliveries ?? 0;
            }

            return 0;
        }

        function getClosingQuantity(productId) {
            const savedProduct = getSavedProduct(productId);

            if (!savedProduct) {
                return null;
            }

            return savedProduct.physical_closing_stock ?? null;
        }

        const table = document.createElement("table");
        table.className = "inventory-table";

        table.innerHTML = `
            <thead>
                <tr>
                    <th>Product</th>
                    <th>Opening Stock</th>
                    <th>Stock Delivered</th>
                    <th>Available Stock</th>
                    <th>Unit Price</th>
                    <th>Product Subtotal</th>
                    <th>Physical Closing Stock</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;

        const tbody = table.querySelector("tbody");

        const totalRow = document.createElement("div");
        totalRow.className = "expected-income-total";

        totalRow.innerHTML = `
            <strong>Expected Income:</strong>
            <span id="expected-income-value">—</span>
        `;

        const expectedIncomeValue =
            totalRow.querySelector("#expected-income-value");

        function recalculateInventoryTotals() {
            let dailyExpectedIncome = 0;
            let allProductsRecorded = true;

            tbody.querySelectorAll("tr").forEach((row) => {
                const openingInput =
                    row.querySelector(".opening-input");

                const deliveryInput =
                    row.querySelector(".delivery-input");

                const availableCell =
                    row.querySelector(".available-stock");

                const subtotalCell =
                    row.querySelector(".product-subtotal");

                const unitPrice =
                    Number(row.dataset.unitPrice);

                const openingValue = openingInput.value.trim();

                const deliveryValue = deliveryInput
                    ? deliveryInput.value.trim()
                    : "0";

                if (openingValue === "") {
                    availableCell.textContent = "—";
                    subtotalCell.textContent = "—";
                    allProductsRecorded = false;
                    return;
                }

                const openingQuantity = Number(openingValue);
                const deliveryQuantity =
                    deliveryValue === "" ? 0 : Number(deliveryValue);

                if (
                    !Number.isInteger(openingQuantity) ||
                    openingQuantity < 0 ||
                    !Number.isInteger(deliveryQuantity) ||
                    deliveryQuantity < 0
                ) {
                    availableCell.textContent = "—";
                    subtotalCell.textContent = "—";
                    allProductsRecorded = false;
                    return;
                }

                const availableStock =
                    openingQuantity + deliveryQuantity;

                const subtotal = availableStock * unitPrice;

                availableCell.textContent = availableStock;
                subtotalCell.textContent = subtotal.toFixed(2);

                dailyExpectedIncome += subtotal;
            });

            expectedIncomeValue.textContent =
                allProductsRecorded
                    ? dailyExpectedIncome.toFixed(2)
                    : `${dailyExpectedIncome.toFixed(2)} (incomplete)`;
        }

        data.products.forEach((product) => {
            const productId = product.product_id;

            const openingQuantity =
                getOpeningQuantity(productId);

            const deliveryQuantity =
                getDeliveryQuantity(productId);

            const closingQuantity =
                getClosingQuantity(productId);

            const row = document.createElement("tr");

            row.dataset.productId = productId;
            row.dataset.unitPrice = Number(product.unit_price);

            // Product name.
            const nameCell = document.createElement("td");
            nameCell.textContent = product.product_name;
            row.appendChild(nameCell);

            // Opening stock.
            const openingCell = document.createElement("td");
            const openingInput = document.createElement("input");

            openingInput.type = "number";
            openingInput.min = "0";
            openingInput.step = "1";
            openingInput.className = "opening-input";
            openingInput.placeholder = "Enter opening stock";

            openingInput.setAttribute(
                "aria-label",
                `Opening stock for ${product.product_name}`
            );

            if (openingQuantity !== null) {
                openingInput.value = openingQuantity;
            }

            openingInput.addEventListener("input", () => {
                openingInput.dataset.dirty = "true";
                recalculateInventoryTotals();
            });

            openingCell.appendChild(openingInput);
            row.appendChild(openingCell);

            // Stock delivery.
            const deliveryCell = document.createElement("td");

            if (product.stock_handling === "CARRY_FORWARD") {
                const deliveryTotal = document.createElement("input");

                deliveryTotal.type = "number";
                deliveryTotal.className = "delivery-input";
                deliveryTotal.value = deliveryQuantity;
                deliveryTotal.readOnly = true;

                deliveryTotal.setAttribute(
                    "aria-label",
                    `Total deliveries for ${product.product_name}`
                );

                deliveryTotal.addEventListener(
                    "input",
                    recalculateInventoryTotals
                );

                const actionSelect = document.createElement("select");
                actionSelect.className = "delivery-action-select";

                actionSelect.innerHTML = `
                    <option value="">Choose action</option>
                    <option value="clear">Clear Cell</option>
                    <option value="add">Add Value</option>
                `;

                const operationContainer =
                    document.createElement("div");

                operationContainer.className = "delivery-operation";

                actionSelect.addEventListener("change", async () => {
                    operationContainer.replaceChildren();
                    delete operationContainer.dataset.dirty;

                    if (actionSelect.value === "clear") {
                        actionSelect.disabled = true;

                        try {
                            const latestHistory =
                                await loadStockDeliveryHistory(dailyId);

                            const productDeliveries =
                                latestHistory.filter(
                                    (item) =>
                                        Number(item.product_id) ===
                                        Number(productId)
                                );

                            if (productDeliveries.length === 0) {
                                operationContainer.textContent =
                                    "No delivery records available to clear.";

                                actionSelect.disabled = false;
                                return;
                            }

                            const recordSelect =
                                document.createElement("select");

                            recordSelect.className =
                                "delivery-record-select";

                            recordSelect.innerHTML =
                                '<option value="">Select delivery to clear</option>';

                            productDeliveries.forEach((record) => {
                                const option =
                                    document.createElement("option");

                                option.value = record.movement_id;

                                option.textContent =
                                    `${record.quantity_received} units — ${record.received_at}`;

                                recordSelect.appendChild(option);
                            });

                            recordSelect.addEventListener("change", () => {
                                if (recordSelect.value) {
                                    recordSelect.dataset.dirty = "true";
                                } else {
                                    delete recordSelect.dataset.dirty;
                                }
                            });

                            operationContainer.appendChild(recordSelect);

                        } catch (error) {
                            operationContainer.textContent =
                                `Could not load delivery records: ${error.message}`;

                        } finally {
                            actionSelect.disabled = false;
                        }

                    } else if (actionSelect.value === "add") {
                        const additionInput =
                            document.createElement("input");

                        additionInput.type = "number";
                        additionInput.min = "1";
                        additionInput.step = "1";
                        additionInput.placeholder =
                            "New delivery quantity";

                        additionInput.className =
                            "delivery-add-input";

                        additionInput.addEventListener("input", () => {
                            additionInput.dataset.dirty = "true";
                        });

                        operationContainer.appendChild(additionInput);
                    }
                });

                deliveryCell.append(
                    deliveryTotal,
                    actionSelect,
                    operationContainer
                );

            } else {
                deliveryCell.textContent = "Not applicable";
            }

            row.appendChild(deliveryCell);

            // Available stock.
            const availableCell = document.createElement("td");
            availableCell.className = "available-stock";
            availableCell.textContent = "—";
            row.appendChild(availableCell);

            // Unit price.
            const priceCell = document.createElement("td");
            priceCell.textContent =
                Number(product.unit_price).toFixed(2);

            row.appendChild(priceCell);

            // Product subtotal.
            const subtotalCell = document.createElement("td");
            subtotalCell.className = "product-subtotal";
            subtotalCell.textContent = "—";
            row.appendChild(subtotalCell);

            // Physical closing stock.
            const closingCell = document.createElement("td");
            const closingInput = document.createElement("input");

            closingInput.type = "number";
            closingInput.min = "0";
            closingInput.step = "1";
            closingInput.placeholder = "Enter closing stock";
            closingInput.className = "closing-input";

            closingInput.setAttribute(
                "aria-label",
                `Physical closing stock for ${product.product_name}`
            );

            if (closingQuantity !== null) {
                closingInput.value = closingQuantity;
            }

            closingInput.addEventListener("input", () => {
                closingInput.dataset.dirty = "true";
            });

            closingCell.appendChild(closingInput);
            row.appendChild(closingCell);

            tbody.appendChild(row);
        });

        container.replaceChildren(table, totalRow);

        document.getElementById("save-inventory-button").dataset.dailyId =
            dailyId;

        document.getElementById("close-business-day-button").dataset.dailyId =
            dailyId;

        recalculateInventoryTotals();

        console.log("Daily ID:", dailyId);
        console.log("Products loaded:", data.products.length);

        message.textContent =
            "Inventory loaded. Enter or update the required stock quantities.";

    } catch (error) {
        container.textContent = error.message;
        console.error("Inventory loading error:", error);
        throw error;
    }
}


// --------------------------------------------------
// 4. SAVE INVENTORY
// --------------------------------------------------

async function saveInventory() {
    const button =
        document.getElementById("save-inventory-button");

    const message =
        document.getElementById("entry-message");

    const dailyId = Number(button.dataset.dailyId);

    if (!dailyId) {
        message.textContent =
            "No active business day was found. Please retrieve the business day again.";
        return;
    }

    const rows = document.querySelectorAll(
        "#inventory-table-container tbody tr"
    );

    let savedCount = 0;
    let failedCount = 0;
    let pendingCount = 0;
    let deliveryChanged = false;

    button.disabled = true;
    button.textContent = "Saving Inventory...";

    try {
        for (const row of rows) {
            const product = {
                product_id: Number(row.dataset.productId),
                product_name: row.cells[0].textContent.trim()
            };

            // Save opening stock.
            const openingInput =
                row.querySelector('.opening-input[data-dirty="true"]');

            if (openingInput) {
                pendingCount++;

                const result = await saveOpeningStock(
                    openingInput,
                    product,
                    dailyId,
                    message
                );

                if (result === true) {
                    delete openingInput.dataset.dirty;
                    savedCount++;
                } else {
                    failedCount++;
                }
            }

            // Process stock delivery operations.
            const actionSelect =
                row.querySelector(".delivery-action-select");

            const operationContainer =
                row.querySelector(".delivery-operation");

            if (actionSelect && actionSelect.value === "clear") {
                const recordSelect =
                    operationContainer.querySelector(
                        '.delivery-record-select[data-dirty="true"]'
                    );

                if (recordSelect) {
                    pendingCount++;

                    const movementId = Number(recordSelect.value);

                    const result = movementId
                        ? await deleteStockDelivery(movementId, message)
                        : false;

                    if (result === true) {
                        savedCount++;
                        deliveryChanged = true;

                        actionSelect.value = "";
                        operationContainer.replaceChildren();

                    } else {
                        failedCount++;
                    }
                }
            }

            if (actionSelect && actionSelect.value === "add") {
                const additionInput =
                    operationContainer.querySelector(
                        '.delivery-add-input[data-dirty="true"]'
                    );

                if (additionInput) {
                    pendingCount++;

                    const result = await saveStockDelivery(
                        additionInput,
                        product,
                        dailyId,
                        message
                    );

                    if (result === true) {
                        delete additionInput.dataset.dirty;

                        savedCount++;
                        deliveryChanged = true;

                        actionSelect.value = "";
                        operationContainer.replaceChildren();

                    } else {
                        failedCount++;
                    }
                }
            }

            // Save physical closing stock.
            const closingInput =
                row.querySelector('.closing-input[data-dirty="true"]');

            if (closingInput) {
                pendingCount++;

                const result = await savePhysicalClosing(
                    closingInput,
                    product,
                    dailyId,
                    message
                );

                if (result === true) {
                    delete closingInput.dataset.dirty;
                    savedCount++;
                } else {
                    failedCount++;
                }
            }
        }

        // Refresh delivery totals after additions or deletions.
        if (deliveryChanged) {
            const latestHistory =
                await loadStockDeliveryHistory(dailyId);

            rows.forEach((row) => {
                const productId = Number(row.dataset.productId);

                const deliveryTotal =
                    row.querySelector(".delivery-input");

                if (!deliveryTotal) return;

                const productRecords = latestHistory.filter(
                    (record) =>
                        Number(record.product_id) === productId
                );

                const cumulativeTotal = productRecords.reduce(
                    (total, record) =>
                        total + Number(record.quantity_received),
                    0
                );

                deliveryTotal.value =
                    productRecords.length > 0
                        ? cumulativeTotal
                        : "";

                deliveryTotal.dispatchEvent(
                    new Event("input", { bubbles: true })
                );
            });
        }

        if (pendingCount === 0) {
            message.textContent =
                "There are no unsaved inventory changes.";

        } else if (failedCount === 0) {
            message.textContent =
                `Inventory saved successfully. ${savedCount} entries recorded.`;

        } else {
            message.textContent =
                `Inventory saving partially completed. ${savedCount} entries saved; ${failedCount} entries failed. Please retry the failed entries.`;
        }

    } catch (error) {
        console.error("Save inventory error:", error);

        message.textContent =
            `An error occurred while saving inventory: ${error.message}`;

    } finally {
        button.disabled = false;
        button.textContent = "Save Inventory";
    }
}


// --------------------------------------------------
// 5. CLOSE BUSINESS DAY
// --------------------------------------------------

async function closeBusinessDay() {
    const closeButton =
        document.getElementById("close-business-day-button");

    const saveButton =
        document.getElementById("save-inventory-button");

    const message =
        document.getElementById("entry-message");

    const dailyId = Number(closeButton.dataset.dailyId);

    if (!dailyId) {
        message.textContent =
            "No active business day found. Please retrieve the business day again.";
        return;
    }

    // Check every type of unsaved entry, including delivery selections.
    const unsavedEntries = document.querySelectorAll(
        '#inventory-table-container [data-dirty="true"]'
    );

    if (unsavedEntries.length > 0) {
        message.textContent =
            "Please save all inventory changes before closing the business day.";
        return;
    }

    const confirmed = window.confirm(
        "Are you sure you want to close this business day? Once completed, the inventory will become read-only."
    );

    if (!confirmed) return;

    closeButton.disabled = true;
    saveButton.disabled = true;
    closeButton.textContent = "Closing Business Day...";

    try {
        const response = await fetch(
            `/daily-business/${dailyId}/complete`,
            {
                method: "POST"
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail ||
                "Could not complete the business day."
            );
        }

        document
            .querySelectorAll(
                "#inventory-table-container input, #inventory-table-container select"
            )
            .forEach((control) => {
                control.disabled = true;
            });

        message.textContent =
            data.message || "Business day completed successfully.";

        closeButton.textContent = "Business Day Closed";

        console.log("Completed daily ID:", dailyId);
        console.log("Business day status:", data.status);

    } catch (error) {
        message.textContent = error.message;

        console.error("Business day completion error:", error);

        closeButton.disabled = false;
        saveButton.disabled = false;
        closeButton.textContent = "Close Business Day";
    }
}


// --------------------------------------------------
// 6. GET STARTING QUANTITY
// --------------------------------------------------

function getStartingQuantity(openingStock, productId) {
    const savedProduct = openingStock.find(
        (item) => item.product_id === productId
    );

    if (!savedProduct) {
        return null;
    }

    return savedProduct.starting_quantity;
}


// --------------------------------------------------
// 7. SAVE OPENING STOCK
// --------------------------------------------------

async function saveOpeningStock(
    input,
    product,
    dailyId,
    message
) {
    const quantity = Number(input.value);

    if (
        input.value.trim() === "" ||
        !Number.isInteger(quantity) ||
        quantity < 0
    ) {
        message.textContent =
            `Enter a valid whole-number opening quantity for ${product.product_name}.`;

        return false;
    }

    input.disabled = true;

    try {
        const response = await fetch(
            "/daily-inventory/opening-stock",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    daily_id: dailyId,
                    product_id: product.product_id,
                    quantity: quantity
                })
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Could not save opening stock."
            );
        }

        message.textContent =
            `${product.product_name}: opening stock saved successfully.`;

        return true;

    } catch (error) {
        message.textContent =
            `Could not save opening stock for ${product.product_name}: ${error.message}`;

        console.error("Opening stock save error:", error);
        return false;

    } finally {
        input.disabled = false;
    }
}


// --------------------------------------------------
// 8. SAVE STOCK DELIVERY
// --------------------------------------------------

async function saveStockDelivery(
    input,
    product,
    dailyId,
    message
) {
    const quantity = Number(input.value);

    if (
        input.value.trim() === "" ||
        !Number.isInteger(quantity) ||
        quantity < 0
    ) {
        message.textContent =
            `Enter a valid whole-number delivery quantity for ${product.product_name}.`;

        return false;
    }

    input.disabled = true;

    try {
        const response = await fetch(
            "/daily-inventory/stock-delivery",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    daily_id: dailyId,
                    product_id: product.product_id,
                    quantity_received: quantity
                })
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Could not save stock delivery."
            );
        }

        message.textContent =
            quantity === 0
                ? `${product.product_name}: no delivery confirmed.`
                : `${product.product_name}: delivery of ${quantity} saved.`;

        return true;

    } catch (error) {
        message.textContent =
            `Could not save delivery for ${product.product_name}: ${error.message}`;

        console.error("Stock delivery save error:", error);
        return false;

    } finally {
        input.disabled = false;
    }
}


// --------------------------------------------------
// 9. DELETE ONE STOCK DELIVERY RECORD
// --------------------------------------------------

async function deleteStockDelivery(movementId, message) {
    try {
        const response = await fetch(
            `/stock-deliveries/${movementId}`,
            {
                method: "DELETE"
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Could not delete the stock delivery."
            );
        }

        message.textContent =
            "Stock delivery deleted successfully.";

        return true;

    } catch (error) {
        message.textContent =
            `Could not delete stock delivery: ${error.message}`;

        console.error("Stock delivery deletion error:", error);
        return false;
    }
}


// --------------------------------------------------
// 10. LOAD STOCK DELIVERY HISTORY
// --------------------------------------------------

async function loadStockDeliveryHistory(dailyId) {
    const response = await fetch(
        `/daily-business/${dailyId}/stock-deliveries`
    );

    const data = await response.json();

    if (!response.ok) {
        throw new Error(
            data.detail || "Could not retrieve stock delivery history."
        );
    }

    return data.deliveries || [];
}


// --------------------------------------------------
// 11. SAVE PHYSICAL CLOSING STOCK
// --------------------------------------------------

async function savePhysicalClosing(
    input,
    product,
    dailyId,
    message
) {
    const quantity = Number(input.value);

    if (
        input.value.trim() === "" ||
        !Number.isInteger(quantity) ||
        quantity < 0
    ) {
        message.textContent =
            `Enter a valid whole-number closing quantity for ${product.product_name}.`;

        return false;
    }

    input.disabled = true;

    try {
        const response = await fetch(
            "/daily-inventory/physical-closing",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    daily_id: dailyId,
                    product_id: product.product_id,
                    quantity: quantity
                })
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Could not save physical closing stock."
            );
        }

        message.textContent =
            `${product.product_name}: physical closing stock saved.`;

        return true;

    } catch (error) {
        message.textContent =
            `Could not save closing stock for ${product.product_name}: ${error.message}`;

        console.error("Physical closing save error:", error);
        return false;

    } finally {
        input.disabled = false;
    }
}
