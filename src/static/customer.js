const branchesContainer = document.getElementById("branches-container");
const orderingSection = document.getElementById("ordering-section");
const selectedBranchName = document.getElementById("selected-branch-name");
const productsContainer = document.getElementById("products-container");
const customerOrderForm = document.getElementById("customer-order-form");
const orderStatus = document.getElementById("order-status");
const orderTotal = document.getElementById("order-total");
const placeOrderButton = document.getElementById("place-order-button");

let selectedBranchId = null;

function normalizeKenyanPhoneNumber(phoneNumber) {
    let phone = phoneNumber.replace(/[\s-]/g, "");

    if (phone.startsWith("+")) {
        phone = phone.slice(1);
    }

    if (phone.startsWith("0")) {
        phone = "254" + phone.slice(1);
    }

    if (!/^254[17]\d{8}$/.test(phone)) {
        throw new Error(
            "Enter a valid Kenyan M-Pesa number, e.g. 0712345678."
        );
    }

    return phone;
}


async function loadBranches() {
    try {
        const response = await fetch("/branches");

        if (!response.ok) {
            throw new Error("Could not load businesses.");
        }

        const data = await response.json();
        branchesContainer.replaceChildren();

        data.branches.forEach((branch) => {
            const card = document.createElement("div");
            card.className = "branch-card";

            const name = document.createElement("h4");
            name.textContent = branch.branch_name;

            const type = document.createElement("p");
            type.textContent = branch.business_type;

            const button = document.createElement("button");
            button.type = "button";
            button.className = "branch-button";
            button.textContent = "Browse Products";

            button.addEventListener("click", () => {
                selectedBranchId = branch.branch_id;

                selectedBranchName.textContent =
                    `Order from ${branch.branch_name}`;

                orderingSection.hidden = false;
                orderStatus.textContent = "";
                customerOrderForm.reset();

                loadProducts(selectedBranchId);
            });

            card.append(name, type, button);
            branchesContainer.appendChild(card);
        });

        if (data.branches.length === 0) {
            branchesContainer.textContent =
                "No businesses are currently available.";
        }
    } catch (error) {
        branchesContainer.textContent =
            "Businesses could not be loaded. Please try again later.";

        console.error(error);
    }
}


async function loadProducts(branchId) {
    productsContainer.textContent = "Loading products...";
    orderTotal.textContent = "Total: KSh 0.00";

    try {
        const response = await fetch(`/branches/${branchId}/products`);

        if (!response.ok) {
            throw new Error("Could not load products.");
        }

        const data = await response.json();
        productsContainer.replaceChildren();

        if (data.products.length === 0) {
            productsContainer.textContent =
                "No products are available for this business.";
            return;
        }

        data.products.forEach((product) => {
            const productRow = document.createElement("div");
            productRow.className = "product-row";

            const name = document.createElement("span");
            name.textContent = product.product_name;

            const price = document.createElement("span");
            price.textContent =
                `KSh ${Number(product.unit_price).toFixed(2)}`;

            const quantity = document.createElement("input");
            quantity.type = "number";
            quantity.min = "0";
            quantity.step = "1";
            quantity.value = "0";
            quantity.required = true;
            quantity.dataset.productId = product.product_id;
            quantity.dataset.unitPrice = product.unit_price;

            quantity.setAttribute(
                "aria-label",
                `Quantity of ${product.product_name}`
            );

            quantity.addEventListener("input", calculateOrderTotal);

            productRow.append(name, price, quantity);
            productsContainer.appendChild(productRow);
        });
    } catch (error) {
        productsContainer.textContent =
            "Products could not be loaded. Please try again.";

        console.error(error);
    }
}


function calculateOrderTotal() {
    let total = 0;

    const quantityInputs = productsContainer.querySelectorAll(
        "input[data-product-id]"
    );

    quantityInputs.forEach((input) => {
        const quantity = Number(input.value);
        const unitPrice = Number(input.dataset.unitPrice);

        if (
            input.value.trim() === "" ||
            !Number.isInteger(quantity) ||
            quantity < 0
        ) {
            input.setCustomValidity(
                "Enter a whole number that is zero or greater."
            );
            return;
        }

        input.setCustomValidity("");
        total += quantity * unitPrice;
    });

    orderTotal.textContent = `Total: KSh ${total.toFixed(2)}`;
}


customerOrderForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!selectedBranchId) {
        orderStatus.textContent = "Please select a business first.";
        return;
    }

    if (!customerOrderForm.reportValidity()) {
        return;
    }

    const items = [];
    const quantityInputs = productsContainer.querySelectorAll(
        "input[data-product-id]"
    );

    quantityInputs.forEach((input) => {
        const quantity = Number(input.value);

        if (quantity > 0) {
            items.push({
                product_id: Number(input.dataset.productId),
                quantity: quantity,
            });
        }
    });

    if (items.length === 0) {
        orderStatus.textContent =
            "Please select at least one product.";
        return;
    }

    let phoneNumber;
    try {
        phoneNumber = normalizeKenyanPhoneNumber(
            document.getElementById("customer-phone").value
        );
    } catch (error) {
        orderStatus.textContent = error.message;
        return;
    }
    
    orderStatus.textContent = "Preparing your order...";

    if (placeOrderButton) {
        placeOrderButton.disabled = true;
    }

    try {
        const response = await fetch(
            `/orders?branch_id=${selectedBranchId}`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(items),
            }
        );

        const responseText = await response.text();
        
        let data;
        
        try {
            data = JSON.parse(responseText);
        } catch {
            data = { detail: responseText };
        }
        
        if (!response.ok) {
            throw new Error(
                typeof data.detail === "string"
                ? data.detail
                : JSON.stringify(data.detail || data)
            );
        }
        
        orderStatus.textContent =
            `Order created. Order ID: ${data.order_id}. ` +
            `Total: KSh ${Number(data.order_total).toFixed(2)}. ` +
            "Requesting M-Pesa payment...";
        
        const paymentQuery = new URLSearchParams({
            phone_number: phoneNumber,
        });
        const paymentResponse = await fetch(
            `/orders/${encodeURIComponent(data.order_id)}/payment?${paymentQuery}`,
            {
                method: "POST",
            }
        );
        const paymentText = await paymentResponse.text();
        let paymentData;
        
        try {
            paymentData = JSON.parse(paymentText);
        } catch {
            paymentData = { detail: paymentText };
        }
        
        if (!paymentResponse.ok) {
            
            const detail = paymentData.detail;
            const message =
            typeof detail === "string"
                ? detail
                : detail?.message || JSON.stringify(detail || paymentData);
        
            orderStatus.textContent =
                `Order ${data.order_id} was created, but the payment request failed: ${message}`;
            return;
        }
        orderStatus.textContent =
            `Order ${data.order_id} created. ` +
            `Payment request submitted for KSh ${Number(paymentData.amount).toFixed(2)}. ` +
            "Check your phone for the M-Pesa prompt. Payment is not yet confirmed.";
    } catch (error) {
        orderStatus.textContent =
            error.message || "Something went wrong. Please try again.";

        console.error(error);
    } finally {
        if (placeOrderButton) {
            placeOrderButton.disabled = false;
        }
    }
});


loadBranches();