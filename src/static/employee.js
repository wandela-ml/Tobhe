document.addEventListener("DOMContentLoaded", loadBranches);

async function loadBranches() {
    const branchSelect = document.getElementById("branch");
    const message = document.getElementById("entry-message");

    try {
        const response = await fetch("/branches");

        if (!response.ok) {
            throw new Error("Could not load branches.");
        }

        const data = await response.json();

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

document
    .getElementById("daily-entry-form")
    .addEventListener("submit", startBusinessDay);

async function startBusinessDay(event) {
    event.preventDefault();

    const branchId = document.getElementById("branch").value;
    const businessDate = document.getElementById("business-date").value;
    const message = document.getElementById("entry-message");
    const button = event.target.querySelector("button");

    message.textContent = "Initializing business day...";
    button.disabled = true;

    try {
        const response = await fetch("/daily-business", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                branch_id: Number(branchId),
                business_date: businessDate
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Could not initialize the business day."
            );
        }

        message.textContent =
            `Business day initialized successfully. Expected income: ${data.expected_income}.`;

        document.getElementById("inventory-section").hidden = false;
        await loadInventory(branchId, data.daily_id, data.opening_stock);

    } catch (error) {
        message.textContent = error.message;
    } finally {
        button.disabled = false;
    }
}

async function loadInventory(branchId, dailyId, openingStock) {
    const container = document.getElementById("inventory-table-container");

    container.textContent = "Loading products...";

    try {
        const response = await fetch(`/branches/${branchId}/products`);

        if (!response.ok) {
            throw new Error("Could not load branch products.");
        }

        const data = await response.json();

        const table = document.createElement("table");
        table.className = "inventory-table";

        table.innerHTML = `
            <thead>
                <tr>
                    <th>Product</th>
                    <th>Unit Price</th>
                    <th>Quantity</th>
                    <th>Expected Income</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;

        const tbody = table.querySelector("tbody");

        data.products.forEach((product) => {
            const row = document.createElement("tr");

            row.innerHTML = `
                <td class="product-name"></td>
                <td class="unit-price"></td>
                <td>
                    <input
                        type="number"
                        class="quantity-input"
                        min="0"
                        step="1"
                        value="${getStartingQuantity(openingStock, product.product_id)}"
                        aria-label="Quantity for ${product.product_name}"
                    >
                </td>
                <td class="subtotal">0.00</td>
            `;

            row.querySelector(".product-name").textContent =
                product.product_name;

            row.querySelector(".unit-price").textContent =
                Number(product.unit_price).toFixed(2);

            const quantityInput = row.querySelector(".quantity-input");
            const subtotalCell = row.querySelector(".subtotal");

            quantityInput.addEventListener("input", () => {
                const quantity = Number(quantityInput.value);
                const price = Number(product.unit_price);

                const subtotal = quantity * price;

                subtotalCell.textContent = subtotal.toFixed(2);

                updateExpectedIncome(tbody);
            });

            quantityInput.addEventListener("change", async () => {
                const quantity = Number(quantityInput.value);
                if (
                    quantityInput.value.trim() === "" ||
                    !Number.isInteger(quantity) ||
                    quantity < 0
                ) {
                    alert("Please enter a whole number greater than or equal to zero.");
                    return;
                }
                try {
                    const response = await fetch("/daily-inventory/opening-stock", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            daily_id: dailyId,
                            product_id: product.product_id,
                            quantity: quantity
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (!response.ok) {
                        throw new Error(
                            data.detail || "Could not save the quantity."
                        );
                    }
                    
                    document.getElementById("entry-message").textContent =
                    `${product.product_name}: quantity saved. Expected income: ${Number(data.expected_income).toFixed(2)}.`;
                
                } catch (error) {
                    document.getElementById("entry-message").textContent =
                    `Could not save ${product.product_name}: ${error.message}`;
                    console.error("Opening stock save error:", error);
                }
            });

            tbody.appendChild(row);
        });

        container.replaceChildren(table);

        const total = document.createElement("p");
        total.id = "expected-income-total";
        total.textContent = "Expected Income: 0.00";

        container.appendChild(total);

        console.log("Daily ID:", dailyId);
        console.log("Products loaded:", data.products.length);

    } catch (error) {
        container.textContent = error.message;
        console.error("Inventory loading error:", error);
    }
}

function updateExpectedIncome(tbody) {
    let total = 0;

    tbody.querySelectorAll("tr").forEach((row) => {
        total += Number(row.querySelector(".subtotal").textContent);
    });

    document.getElementById("expected-income-total").textContent =
        `Expected Income: ${total.toFixed(2)}`;
}

function getStartingQuantity(openingStock, productId) {
    const savedProduct = openingStock.find(
        (item) => item.product_id === productId
    );

    return savedProduct ? savedProduct.starting_quantity : 0;
}
