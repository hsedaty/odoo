/** @odoo-module **/

import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { FloatField } from "@web/views/fields/float/float_field";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

class CategoryTotalField extends FloatField {
    static props = { ...FloatField.props, total: Number };

    get value() {
        return this.props.total;
    }
}

export class ExpenseHierarchy extends X2ManyField {
    static template = "school_planning.ExpenseHierarchy";
    static components = { ...X2ManyField.components, FloatField, CategoryTotalField, Many2XAutocomplete };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.expansion = useState({});
        this.composer = useState({ busy: false, revision: 0 });
    }

    get groups() {
        const groups = new Map();
        for (const record of this.list.records) {
            const category = record.data.expense_category_id;
            const key = category?.id || 0;
            if (!groups.has(key)) {
                groups.set(key, { id: key, name: category?.display_name || "", direct: [], items: [], total: 0 });
            }
            const group = groups.get(key);
            group[record.data.expense_item_id ? "items" : "direct"].push(record);
        }
        for (const group of groups.values()) {
            group.total = group.direct.reduce((total, record) => total + (record.data.amount || 0), 0)
                || group.items.reduce((total, record) => total + (record.data.amount || 0), 0);
        }
        return [...groups.values()];
    }

    formatAmount(amount) {
        return formatFloat(amount, { digits: [16, 2] });
    }

    toggle(group) {
        this.expansion[group.id] = !this.expansion[group.id];
    }

    autocompleteProps(group = null) {
        const context = {
            default_school_id: this.props.context.default_school_id,
            default_cost_bucket: this.props.context.default_cost_bucket,
            default_display_order: 10,
            skip_expense_template_sync: true,
        };
        const domain = [["school_id", "=", context.default_school_id]];
        if (group) {
            context.default_expense_category_id = group.id;
            domain.push(["expense_category_id", "=", group.id],
                ["id", "not in", group.items.map(record => record.data.expense_item_id.id)]);
        } else {
            domain.push(["cost_bucket", "=", context.default_cost_bucket],
                ["id", "not in", this.groups.map(category => category.id)]);
        }
        const resModel = group ? "school.expense.items" : "school.expense.categories";
        return {
            resModel,
            context,
            fieldString: group ? _t("Item") : _t("Category"),
            placeholder: group ? _t("Select or create an item...") : _t("Select or create a category..."),
            value: "",
            activeActions: { create: this.canCreate, createEdit: false },
            getDomain: () => domain,
            update: (records) => this.addSelection(group, records),
            quickCreate: async (name) => {
                const [id] = await this.orm.call(resModel, "name_create", [name], { context });
                await this.addSelection(group, [{ id }]);
            },
        };
    }

    async addSelection(group, records) {
        if (!records?.length || !this.canCreate || this.composer.busy) {
            return;
        }
        const categoryId = group ? group.id : records[0].id;
        const itemId = group ? records[0].id : false;
        this.composer.busy = true;
        try {
            await this.list.addNewRecord({
                context: { ...this.props.context, default_expense_category_id: categoryId,
                    default_expense_item_id: itemId, default_amount: 0 },
                mode: "edit",
                position: "bottom",
            });
            this.expansion[categoryId] = true;
            this.composer.revision++;
        } finally {
            this.composer.busy = false;
        }
    }

    addCategoryAmount(group) {
        return this.addSelection(null, [{ id: group.id }]);
    }

    remove(record) {
        return this.list.delete(record);
    }
}

registry.category("fields").add("school_expense_hierarchy", {
    ...x2ManyField,
    component: ExpenseHierarchy,
});