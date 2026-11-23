import { Component, onWillStart, onWillUpdateProps, useEffect, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { formatMonetary, formatPercentage } from "@web/views/fields/formatters";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { DismissibleNotice } from "./dismissible_notice";

class DetailedExpenses extends Component {
    static template = "school_planning.DetailedExpenses";
    static props = standardWidgetProps;
    static components = { DismissibleNotice };
    get kind() { return "expense"; }

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({ data: null, busy: false, modes: {} });
        let incomeNeedsRefresh = false;
        const load = async (id) => {
            this.yearId = id;
            incomeNeedsRefresh = false;
            this.state.modes = {};
            this.state.data = id
                ? await this.orm.call("school.academic.years", `get_detailed_${this.kind}_list`, [[id]])
                : null;
        };
        onWillStart(() => load(this.props.record.resId));
        useBus(this.env.bus, "school-income-grade-updated", async ({ detail }) => {
            if (this.kind === "income" && detail.yearId === this.yearId) {
                this.state.data = await this.orm.call("school.academic.years", "get_detailed_income_list", [[this.yearId]]);
            }
        });
        onWillUpdateProps((props) => {
            if (props.record.resId !== this.yearId) {
                return load(props.record.resId);
            }
        });
        useEffect(() => {
            const id = this.yearId;
            if (this.kind === "income" && this.props.record.dirty) {
                incomeNeedsRefresh = true;
            }
            if (this.kind !== "income" || !id || this.state.busy || this.props.record.dirty || !this.state.data
                || (!incomeNeedsRefresh && this.state.data.baseline === this.props.record.data.tuition_gross_total)) {
                return;
            }
            incomeNeedsRefresh = false;
            let active = true;
            this.orm.call("school.academic.years", "get_detailed_income_list", [[id]]).then((data) => {
                if (active && id === this.yearId) {
                    this.state.data = data;
                }
            });
            return () => { active = false; };
        }, () => [this.props.record.resId, this.props.record.data.tuition_gross_total, this.props.record.dirty, this.state.data?.baseline, this.state.busy]);
        useEffect(() => {
            const id = this.yearId;
            if (this.kind !== "expense" || !id || this.state.busy || this.props.record.dirty || !this.state.data
                || this.state.data.gross_revenue === this.props.record.data.fee_gross_total) {
                return;
            }
            let active = true;
            this.orm.call("school.academic.years", "get_detailed_expense_list", [[id]]).then((data) => {
                if (active && id === this.yearId) {
                    this.state.data = data;
                }
            });
            return () => { active = false; };
        }, () => [this.props.record.resId, this.props.record.data.fee_gross_total, this.props.record.dirty, this.state.data?.gross_revenue, this.state.busy]);
    }

    get tuitionTotal() { return this.props.record.data.tuition_gross_total ?? this.state.data.baseline; }

    money(amount) {
        return formatMonetary(amount, { currencyId: this.state.data.currency });
    }

    percentage(ratio) {
        return formatPercentage(ratio, { digits: [16, 2] });
    }

    async createList() {
        await this.update(`create_detailed_${this.kind}_list`);
    }

    deleteList() {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete detailed expense list?"),
            body: _t("This permanently removes this year's expense selections and entered amounts and selects No Details for reports. Income details and other years are not affected."),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            cancel: () => {},
            confirm: async () => {
                await this.update("delete_detailed_expense_list");
                this.state.modes = {};
            },
        });
    }

    selectItem(item) {
        return this.update(`set_detailed_${this.kind}_selection`, item.id, !item.selected);
    }

    occurrenceMode(item) {
        return this.state.modes[item.id] || item.occurrence_mode
            || (item.basis === "student_percent" ? "student_percent" : "amount");
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

    setStudentPercentage(item, field, event) {
        const value = event.target.value === "" ? null : event.target.valueAsNumber;
        if (value !== null && (!Number.isFinite(value) || value < 0 || (field === "percentage" && value > 100))) {
            event.target.reportValidity();
            return;
        }
        const current = item.occurrence_mode === "student_percent" ? item : {};
        const amount = field === "amount" ? value : current.occurrence_value ?? null;
        const percentage = field === "percentage" ? value : current.occurrence_percentage ?? null;
        return this.update("set_detailed_student_percentage", this.kind, item.id, amount, percentage);
    }

    setGradeAmount(item, gradeId, event) {
        const value = event.target.valueAsNumber;
        if (!Number.isFinite(value) || value < 0) {
            event.target.setCustomValidity("Enter a non-negative number.");
            event.target.reportValidity();
            event.target.setCustomValidity("");
            return;
        }
        return this.update("set_detailed_student_grade", item.id, gradeId, value);
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
            if (!(await this.props.record.save())) {
                return;
            }
            const data = await this.orm.call("school.academic.years", method, [[yearId], ...args]);
            if (yearId === this.yearId) {
                this.state.data = data;
                await this.props.record.load();
                if (this.kind === "income") {
                    this.env.bus.trigger("school-detailed-income-updated", { yearId });
                }
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
