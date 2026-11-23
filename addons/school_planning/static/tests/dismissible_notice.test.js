import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { DismissibleNotice } from "@school_planning/js/dismissible_notice";

defineMailModels();

test("notices can be dismissed and return on reopening", async () => {
    await mountWithCleanup(DismissibleNotice, {
        props: { message: "Forecast help", variant: "help" },
    });
    expect(".sp-workspace-help").toHaveCount(1);
    await contains(".sp-workspace-help .btn-close").click();
    expect(".sp-workspace-help").toHaveCount(0);
    await mountWithCleanup(DismissibleNotice, {
        props: { message: "Forecast help", variant: "help" },
    });
    expect(".sp-workspace-help").toHaveCount(1);
});
