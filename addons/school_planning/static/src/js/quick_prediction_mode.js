/** @odoo-module **/

import { onMounted, onWillUnmount, useChildSubEnv, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { ActionDialog } from "@web/webclient/actions/action_dialog";
import { SelectionField, selectionField } from "@web/views/fields/selection/selection_field";

class ExpenseTrendField extends SelectionField {
    static template = "school_planning.ExpenseTrendField";

    trendHelp(trend) {
        const instructions = {
            stable: "Base Amount: enter the annual expense amount. It stays the same each year. Annual Change is not used.",
            increase: "Base Amount: enter the annual expense amount. Annual Change: enter a percentage, such as 5 for 5% compounded growth each year.",
            decrease: "Base Amount: enter the annual expense amount. Annual Change: enter a percentage, such as 5 for a 5% compounded reduction each year.",
            revenue_stable: "Base Amount: enter 30 for 30% of each year's revenue before tax, not 0.30 or 30%. Annual Change is not used.",
            revenue_increase: "Base Amount: enter 30 for 30% of revenue before tax. Annual Change: enter 5 to increase the rate by 5 percentage points: 30%, 35%, 40%. The rate stops at 100%.",
            revenue_decrease: "Base Amount: enter 30 for 30% of revenue before tax. Annual Change: enter 5 to decrease the rate by 5 percentage points: 30%, 25%, 20%. The rate stops at 0%.",
            revenue_after_tax_increase: "Base Amount: enter 30 for 30% of revenue after fee-tax deductions. Annual Change: enter 5 to increase the rate by 5 percentage points: 30%, 35%, 40%. The rate stops at 100%.",
            revenue_after_tax_decrease: "Base Amount: enter 30 for 30% of revenue after fee-tax deductions. Annual Change: enter 5 to decrease the rate by 5 percentage points: 30%, 25%, 20%. The rate stops at 0%.",
            per_student: "Base Amount: enter the expense per student. Each year's expense equals this amount multiplied by that year's student count. Annual Change is not used.",
        };
        return (instructions[trend] || "Choose a trend to see its input format.") + " Costs begin in Start Year; the first annual change applies the following year.";
    }
}

registry.category("fields").add("school_expense_trend", {
    ...selectionField,
    component: ExpenseTrendField,
});

patch(ActionDialog.prototype, {
    setup() {
        super.setup(...arguments);
        this.quickPredictionHeader = null;
        if (this.props.actionProps?.resModel === "school.prediction.quick.setup.wizard") {
            this.quickPredictionHeader = useState({ record: null, busy: false });
            useChildSubEnv({ quickPredictionHeader: this.quickPredictionHeader });
        }
    },

    async toggleQuickPredictionMode(event) {
        const header = this.quickPredictionHeader;
        if (!header?.record || header.busy) {
            return;
        }
        header.busy = true;
        try {
            await header.record.update({ extreme_efficiency: event.target.checked });
        } finally {
            header.busy = false;
        }
    },
});

class QuickPredictionController extends FormController {
    setup() {
        super.setup(...arguments);
        const header = this.env.quickPredictionHeader;
        onMounted(() => {
            if (header) {
                header.record = this.model.root;
            }
        });
        onWillUnmount(() => {
            if (header?.record === this.model.root) {
                header.record = null;
            }
        });
    }
}

registry.category("views").add("school_quick_prediction", {
    ...formView,
    Controller: QuickPredictionController,
});