import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary, formatPercentage } from "@web/views/fields/formatters";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

class DetailedExpenses extends Component {
    static template = "school_planning.DetailedExpenses";
    static props = standardWidgetProps;
    get kind() { return "expense"; }

    setup() {
        this.orm = useService("orm");
        this.state = useState({ data: null, busy: false, modes: {} });
        const load = async (id) => {
            this.yearId = id;
            this.state.modes = {};
            this.state.data = id
                ? await this.orm.call("school.academic.years", `get_detailed_${this.kind}_list`, [[id]])
                : null;
        };
        onWillStart(() => load(this.props.record.resId));
        onWillUpdateProps((props) => {
            if (props.record.resId !== this.yearId) {
                return load(props.record.resId);
            }
        });
    }

    money(amount) {
        return formatMonetary(amount, { currencyId: this.state.data.currency });
    }

    percentage(ratio) {
        return formatPercentage(ratio, { digits: [16, 2] });
    }

    createList() {
        return this.update(`create_detailed_${this.kind}_list`);
    }

    selectItem(item) {
        return this.update(`set_detailed_${this.kind}_selection`, item.id, !item.selected);
    }

    setPrice(item, event) {
        const value = event.target.valueAsNumber;
        if (Number.isFinite(value) && value >= 0) {
            return this.update("set_detailed_allocated_price", this.kind, item.id, value);
        }
        event.target.setCustomValidity("Enter a non-negative amount.");
        event.target.reportValidity();
        event.target.setCustomValidity("");
    }

    occurrenceMode(item) {
        return this.state.modes[item.id] || item.occurrence_mode || "amount";
    }

    occurrenceValue(item) {
        const mode = this.occurrenceMode(item);
        if (item.occurrence_mode === mode) {
            return item.occurrence_value;
        }
        return mode === "amount" ? item.amount : null;
    }

    setOccurrenceMode(item, event) {
        this.state.modes[item.id] = event.target.value;
    }

    setOccurrence(item, event) {
        const value = event.target.valueAsNumber;
        if (Number.isFinite(value) && value >= 0) {
            return this.update("set_detailed_occurrence_value", this.kind, item.id, this.occurrenceMode(item), value);
        }
        event.target.setCustomValidity("Enter a non-negative number.");
        event.target.reportValidity();
        event.target.setCustomValidity("");
    }

    resetOccurrence(item) {
        delete this.state.modes[item.id];
        return this.update("set_detailed_occurrence_value", this.kind, item.id, "seed", null);
    }

    async update(method, ...args) {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        const yearId = this.yearId;
        try {
            const data = await this.orm.call("school.academic.years", method, [[yearId], ...args]);
            if (yearId === this.yearId) {
                this.state.data = data;
            }
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("view_widgets").add("school_detailed_expenses", { component: DetailedExpenses });

class DetailedIncomes extends DetailedExpenses {
    get kind() { return "income"; }
}
registry.category("view_widgets").add("school_detailed_incomes", { component: DetailedIncomes });
