
const branchesContainer = document.getElementById("branches-container");
const statusMessage = document.getElementById("status-message");
const dailySetupForm = document.getElementById("daily-setup-form");
const dailySetupResult = document.getElementById("daily-setup-result");

async function loadBranches() {
    branchesContainer.innerHTML = "<p>Loading your branches...</p>";
    statusMessage.textContent = "";

    try {
        const response = await fetch("/branches");

        if (!response.ok) {
            throw new Error("Could not load branches.");
        }

        const data = await response.json();
        branchesContainer.innerHTML = "";

        if (!data.branches || data.branches.length === 0) {
            branchesContainer.innerHTML =
                "<p>No branches have been registered yet.</p>";
            return;
        }

        data.branches.forEach((branch) => {
            const card = document.createElement("article");
            card.className = "branch-card";

            const businessType = branch.business_type.toLowerCase();

            let icon = "fa-building";
            let iconClass = "accommodation";
            
            if (businessType.includes("restaurant")) {
                icon = "fa-utensils";
                iconClass = "restaurant";
            } else if (businessType.includes("clothing")) {
                icon = "fa-shirt";
                iconClass = "clothing";
            } else if (businessType.includes("accommodation")) {
                icon = "fa-bed";
                iconClass = "accommodation";
            }

            const iconElement = document.createElement("div");
            iconElement.className = `branch-icon ${iconClass}`;
            iconElement.setAttribute("aria-hidden", "true");
            
            const iconGraphic = document.createElement("i");
            iconGraphic.className = `fa-solid ${icon}`;
            iconElement.appendChild(iconGraphic);

            const name = document.createElement("h4");
            name.textContent = branch.branch_name;

            const type = document.createElement("p");
            type.textContent = branch.business_type;

            const button = document.createElement("button");
            button.className = "branch-button";
            button.textContent = "Manage Branch";

            button.addEventListener("click", () => {
                const setupSection = document.getElementById("daily-setup-section");
                const selectedBranchName = document.getElementById("selected-branch-name");
                const selectedBranchId = document.getElementById("selected-branch-id");
                
                selectedBranchName.textContent =`Setting up business day for ${branch.branch_name}`;
                
                selectedBranchId.value = branch.branch_id;
                setupSection.hidden = false;
                
                setupSection.scrollIntoView({
                    behavior: "smooth",
                    block: "start"
                });
                
                statusMessage.textContent = "";
            });

            card.append(iconElement, name, type, button);
            branchesContainer.appendChild(card);
        });
    } catch (error) {
        branchesContainer.innerHTML =
            "<p>Unable to load branches. Please try again.</p>";
        statusMessage.textContent = error.message;
    }
}

loadBranches();




dailySetupForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const branchId = document.getElementById("selected-branch-id").value;
    const businessDate = document.getElementById("business-date").value;

    dailySetupResult.textContent = "Loading daily report...";

    try {
        const response = await fetch(
            `/branches/${branchId}/daily-report?business_date=${encodeURIComponent(businessDate)}`
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                typeof result.detail === "string"
                    ? result.detail
                    : JSON.stringify(result.detail)
            );
        }

        const money = (value) =>
            `KES ${Number(value).toLocaleString("en-KE", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            })}`;

        const openingStockValue = result.products.reduce(
            (total, product) =>
                total + Number(product.opening_stock_subtotal || 0),
            0
        );

        const openingStockRows = result.products.map((product) => `
           <tr>
                <td>${product.product_name}</td>
                <td>${product.starting_stock}</td>
                <td>${Number(product.unit_price).toLocaleString("en-KE", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                })}</td>
                <td>${Number(product.opening_stock_subtotal).toLocaleString("en-KE", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                })}</td>
            </tr>
        `).join("");


        const salesRows = result.products.map((product) => `
            <tr>
                <td>${product.product_name}</td>
                <td>${product.units_sold}</td>
                <td>${Number(product.unit_price).toLocaleString("en-KE", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                })}</td>
                <td>${Number(product.sales_subtotal).toLocaleString("en-KE", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                })}</td>
            </tr>
        `).join("");


        const stockReconciliationRows = result.products.map((product) => `
            <tr>
                <td>${product.product_name}</td>
                <td>${product.starting_stock ?? 0}</td>
                <td>${product.total_deliveries ?? 0}</td>
                <td>${product.total_stock ?? 0}</td>
                <td>${product.units_sold ?? 0}</td>
                <td>${product.expected_closing_stock ?? 0}</td>
                <td>${product.physical_closing_stock === null
                    ? "Not recorded"
                    : product.physical_closing_stock}</td>
                    <td>${product.stock_discrepancy === null
                        ? "Not recorded"
                        : product.stock_discrepancy > 0
                            ? `+${product.stock_discrepancy}`
                            : product.stock_discrepancy}</td>
            </tr>
        `).join("");


        dailySetupResult.innerHTML = `
            <h3>Opening Inventory and Stock Value</h3>

            <p><strong>Branch:</strong> ${result.branch_name}</p>
            <p><strong>Business date:</strong> ${result.business_date}</p>

            <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Product</th>
                        <th>Opening Quantity</th>
                        <th>Unit Price(KES)</th>
                        <th>Opening Value(KES)</th>
                    </tr>
                </thead>
                <tbody>
                     ${openingStockRows}
                    <tr>
                        <th>Total Opening Stock Value</th>
                        <th>${openingStockValue.toLocaleString("en-KE", {
                            minimumFractionDigits: 2,
                             maximumFractionDigits: 2
                        })}</th>
                        <th></th>
                        <th></th>
                    </tr>
                </tbody>
            </table>
            </div>

            <h3>Daily Sales and Actual Income</h3>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Quantity Sold</th>
                            <th>Unit Price(KES)</th>
                            <th>Sales Value(KES)</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${salesRows}
                        <tr>
                            <th colspan="3">Total Sales Value</th>
                            <th>${Number(result.products.reduce(
                                (total, product) =>
                                    total + Number(product.sales_subtotal || 0),
                                0
                             )).toLocaleString("en-KE", {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            })}</th>
                        </tr>
                    </tbody>
                </table>
            </div>
            <p><strong>Expected Income:</strong> KES ${Number(result.expected_income).toLocaleString("en-KE", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            })}</p>
            <p><strong>Actual Income (confirmed paid orders):</strong> KES ${Number(result.actual_income).toLocaleString("en-KE", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            })}</p>
            <p><strong>Income Discrepancy:</strong> KES ${Number(result.income_discrepancy).toLocaleString("en-KE", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            })}</p>

            <h3>Stock Reconciliation</h3>
                <div class="table-container">
                    <table>
                        <tr>
                            <th>Product</th>
                            <th>Opening Stock</th>
                            <th>Deliveries Today</th>
                            <th>Total Available</th>
                            <th>Units Sold</th>
                            <th>Expected Closing Stock</th>
                            <th>Physical Closing Stock</th>
                            <th>Stock Discrepancy</th>
                        </tr>
                        <tbody>
                            ${stockReconciliationRows}
                        </tbody>
                    </table>
                </div>

        `;

    } catch (error) {
        dailySetupResult.textContent =
            `Could not load daily report: ${error.message}`;
    }
});

