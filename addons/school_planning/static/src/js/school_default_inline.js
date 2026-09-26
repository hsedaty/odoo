/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";

function toPositiveInt(value) {
    if (Number.isInteger(value) && value > 0) {
        return value;
    }
    if (typeof value === "string" && /^\d+$/.test(value)) {
        const parsed = Number.parseInt(value, 10);
        return parsed > 0 ? parsed : null;
    }
    return null;
}

function getMany2oneId(value) {
    if (Number.isInteger(value)) {
        return toPositiveInt(value);
    }
    if (Array.isArray(value) && value.length) {
        return toPositiveInt(value[0]);
    }
    if (value && typeof value === "object") {
        return (
            toPositiveInt(value.resId) ||
            toPositiveInt(value.res_id) ||
            toPositiveInt(value.id) ||
            null
        );
    }
    return null;
}

function getSingleSchoolIdFromIn(value) {
    if (!Array.isArray(value) || value.length !== 1) {
        return null;
    }
    return toPositiveInt(value[0]);
}

function extractSchoolIdFromClause(clause) {
    if (!Array.isArray(clause) || clause.length < 3) {
        return null;
    }
    const [fieldName, operator, value] = clause;
    if (fieldName !== "school_id") {
        return null;
    }
    if (operator === "=") {
        return getMany2oneId(value) || toPositiveInt(value);
    }
    if (operator === "in") {
        return getSingleSchoolIdFromIn(value);
    }
    return null;
}

function extractSchoolIdFromDomain(domain) {
    if (!Array.isArray(domain)) {
        return null;
    }
    for (const token of domain) {
        if (token === "&" || token === "|" || token === "!") {
            continue;
        }
        if (Array.isArray(token)) {
            const fromClause = extractSchoolIdFromClause(token);
            if (fromClause) {
                return fromClause;
            }
            const fromNested = extractSchoolIdFromDomain(token);
            if (fromNested) {
                return fromNested;
            }
        }
    }
    return null;
}

function extractSchoolFromVisibleRecords(records) {
    if (!Array.isArray(records) || !records.length) {
        return null;
    }
    const byId = new Map();
    for (const record of records) {
        const schoolValue = record?.data?.school_id;
        const id = getMany2oneId(schoolValue);
        if (!id) {
            continue;
        }
        if (!byId.has(id)) {
            byId.set(id, schoolValue);
        }
        if (byId.size > 1) {
            return null;
        }
    }
    if (byId.size === 1) {
        return Array.from(byId.values())[0];
    }
    return null;
}

function appendSchoolDomain(domain, schoolId) {
    if (!Array.isArray(domain) || !schoolId) {
        return domain;
    }
    const hasSchoolClause = domain.some(
        (clause) => Array.isArray(clause) && clause.length >= 3 && clause[0] === "school_id"
    );
    if (hasSchoolClause) {
        return domain;
    }
    return [...domain, ["school_id", "=", schoolId]];
}

patch(DynamicRecordList.prototype, {
    async _addNewRecord(atFirstPosition) {
        const context = { ...(this.context || {}) };
        let schoolValue = null;

        if (this.activeFields?.school_id) {
            schoolValue = extractSchoolFromVisibleRecords(this.records || []);
        }

        if (!context.default_school_id && this.activeFields?.school_id) {
            const schoolId = extractSchoolIdFromDomain(this.domain || []);
            if (schoolId) {
                context.default_school_id = schoolId;
            } else if (schoolValue) {
                context.default_school_id = getMany2oneId(schoolValue);
            }
        }

        const values = await this.model._loadNewRecord({
            resModel: this.resModel,
            activeFields: this.activeFields,
            fields: this.fields,
            context,
        });

        if (!values.school_id && schoolValue) {
            values.school_id = schoolValue;
        }

        const record = this._createRecordDatapoint(values, "edit");
        this._addRecord(record, atFirstPosition ? 0 : this.records.length);
        return record;
    },
});

patch(Many2OneField.prototype, {
    get m2oProps() {
        const props = super.m2oProps;
        const isExpenseCategoryField =
            this.props?.record?.resModel === "school.expense.items" &&
            this.props?.name === "expense_category_id";

        if (!isExpenseCategoryField) {
            return props;
        }

        const schoolId = getMany2oneId(this.props.record?.data?.school_id);
        const baseDomain = props.domain;
        const baseContext = props.context || {};

        return {
            ...props,
            context: schoolId ? { ...baseContext, default_school_id: schoolId } : baseContext,
            domain: () => {
                const domain = typeof baseDomain === "function" ? baseDomain() : baseDomain;
                const normalized = Array.isArray(domain) ? domain : [];
                return appendSchoolDomain(normalized, schoolId);
            },
        };
    },
});
