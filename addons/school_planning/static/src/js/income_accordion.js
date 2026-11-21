/** @odoo-module **/

import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

export class IncomeAccordionRenderer extends ListRenderer {
    static rowsTemplate = "school_planning.IncomeAccordionRows";

    setup() {
        super.setup();
        this.expansion = useState({});
    }

    get gradeGroups() {
        const groups = new Map();
        for (const record of this.props.list.records) {
            const grade = record.data.grade_level_id;
            const key = grade?.id || 0;
            if (!groups.has(key)) {
                groups.set(key, { id: key, name: grade?.display_name || _t("Select Grade Level"), records: [] });
            }
            groups.get(key).records.push(record);
        }
        return [...groups.values()];
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
}

registry.category("fields").add("school_income_accordion", {
    ...x2ManyField,
    component: IncomeAccordion,
});