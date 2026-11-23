import { Component, useEffect, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class DismissibleNotice extends Component {
    static template = "school_planning.DismissibleNotice";
    static props = {
        record: { type: Object, optional: true },
        readonly: { type: Boolean, optional: true },
        message: { type: String, optional: true },
        title: { type: String, optional: true },
        variant: { type: String, optional: true },
        slots: { type: Object, optional: true },
    };

    setup() {
        this.state = useState({ dismissed: false });
        useEffect(() => { this.state.dismissed = false; }, () => [this.props.record?.resId]);
    }

    get noticeClass() {
        if (this.props.variant === "help") {
            return "sp-workspace-help";
        }
        if (this.props.variant === "inline-warning") {
            return "text-warning mb-2";
        }
        return `alert alert-${this.props.variant || "info"} mt-3`;
    }
}

registry.category("view_widgets").add("school_dismissible_notice", {
    component: DismissibleNotice,
    extractProps: ({ attrs }) => ({ message: attrs.string, title: attrs.title, variant: attrs.variant }),
});
