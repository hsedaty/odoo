import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary, formatPercentage } from "@web/views/fields/formatters";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

class DetailedExpenses extends Component {
    static template = "school_planning.DetailedExpenses";
    static props = standardWidgetProps;

    setup() {
        this.orm = useService("orm");
        this.state = useState({ data: null, busy: false });
        const load = async (id) => {
            this.yearId = id;
            this.state.data = id
                ? await this.orm.call("school.academic.years", "get_detailed_expense_list", [[id]])
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
