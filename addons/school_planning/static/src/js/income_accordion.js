/** @odoo-module **/

import { onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useBus } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { formatMonetary } from "@web/views/fields/formatters";
import { ListRenderer } from "@web/views/list/list_renderer";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

export class IncomeAccordionRenderer extends ListRenderer {
    static rowsTemplate = "school_planning.IncomeAccordionRows";
    static props = [...ListRenderer.props, "parentRecord"];

    setup() {
        super.setup();
        this.expansion = useState({});
        this.income = useState({ data: null, busy: false });
        onWillStart(() => this.loadDetailedIncome());
        onWillUpdateProps((props) => {
            if (props.parentRecord.resId !== this.props.parentRecord.resId) {
                return this.loadDetailedIncome(props);
            }
        });
        useBus(this.env.bus, "school-detailed-income-updated", ({ detail }) => {
            if (detail.yearId === this.props.parentRecord.resId) {
                return this.loadDetailedIncome();
            }
        });
    }

    async loadDetailedIncome(props = this.props) {
        const parent = props.parentRecord;
        if (props.list.resModel === "school.fee.values" && parent.data.dataset_type === "forecast" && parent.resId) {
            this.income.data = await this.orm.call("school.academic.years", "get_detailed_income_list", [[parent.resId]]);
        } else {
            this.income.data = null;
        }
    }

    get gradeGroups() {
        const groups = new Map();
        for (const record of this.props.list.records) {
            const grade = record.data.grade_level_id;
            const key = grade?.id || 0;
            if (!groups.has(key)) {
                groups.set(key, { id: key, name: grade?.display_name || _t("Select Grade Level"), records: [], incomes: [] });
            }
            groups.get(key).records.push(record);
        }
        for (const group of this.income.data?.groups || []) {
            for (const category of group.categories) {
                for (const item of category.items) {
                    if (!item.selected || item.basis !== "student" || item.student_paid) {
                        continue;
                    }
                    for (const grade of item.grades) {
                        if (!groups.has(grade.id)) {
                            groups.set(grade.id, { id: grade.id, name: grade.name, records: [], incomes: [] });
                        }
                        groups.get(grade.id).incomes.push({ item, grade });
                    }
                }
            }
        }
        return [...groups.values()];
    }

    incomeAmount(grade) {
        return formatMonetary(grade.rate * grade.students, { currencyId: this.income.data.currency });
    }

    async setIncomeGrade(item, grade, event) {
        const amount = event.target.valueAsNumber;
        if (!Number.isFinite(amount) || amount < 0) {
            event.target.setCustomValidity(_t("Enter a non-negative number."));
            event.target.reportValidity();
            event.target.setCustomValidity("");
            return;
        }
        if (this.income.busy || !(await this.props.list.leaveEditMode({ validate: true }))) {
            return;
        }
        this.income.busy = true;
        const parent = this.props.parentRecord;
        try {
            if (!(await parent.save())) {
                return;
            }
            this.income.data = await this.orm.call(
                "school.academic.years", "set_detailed_student_grade", [[parent.resId], item.id, grade.id, amount]
            );
            await parent.load();
            this.env.bus.trigger("school-income-grade-updated", { yearId: parent.resId });
        } finally {
            this.income.busy = false;
        }
    }

    isExpanded(group) {
        return this.expansion[group.id] || group.records.some(record => record === this.props.list.editedRecord);
    }

    async toggleGrade(group) {
        const expanded = this.isExpanded(group);
        if (expanded && !(await this.props.list.leaveEditMode({ validate: true }))) {
            return;
        }
        this.expansion[group.id] = !expanded;
    }
}

export class IncomeAccordion extends X2ManyField {
    static components = { ...X2ManyField.components, ListRenderer: IncomeAccordionRenderer };

    get rendererProps() {
        return { ...super.rendererProps, parentRecord: this.props.record };
    }
}

registry.category("fields").add("school_income_accordion", {
    ...x2ManyField,
    component: IncomeAccordion,
});