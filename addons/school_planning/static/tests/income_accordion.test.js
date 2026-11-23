import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { registry } from "@web/core/registry";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import "@school_planning/js/detailed_expenses";
import { IncomeAccordionRenderer } from "@school_planning/js/income_accordion";

defineMailModels();

test("detailed income appears only after the list is created", async () => {
    const component = await mountWithCleanup(
        registry.category("view_widgets").get("school_detailed_incomes").component,
        { props: { record: { resId: false, dirty: false, data: {} } } }
    );
    component.state.data = {
        created: false, locked: false, historic_frozen: false, groups: [],
        baseline: false, total: false, currency: false, baseline_ratio: null,
    };
    await animationFrame();
    expect(".o_school_detailed_expenses > button").toHaveCount(1);
    expect(".o_school_detailed_expenses > details").toHaveCount(0);

    component.state.data.created = true;
    await animationFrame();
    expect(".o_school_detailed_expenses > button").toHaveCount(0);
    expect(".o_school_detailed_expenses > details").toHaveCount(1);

    component.state.data.created = false;
    component.state.data.locked = true;
    component.state.data.historic_frozen = true;
    await animationFrame();
    expect(".o_school_detailed_expenses > details").toHaveCount(0);
    expect(".o_school_detailed_expenses > p").toHaveCount(1);
});

test("grade accordion includes only selected per-student incomes in their applicable grades", () => {
    const grade = { id: 1, name: "Grade 1", students: 10, rate: 50 };
    const otherGrade = { id: 2, name: "Grade 2", students: 20, rate: 75 };
    const items = [
        { id: 1, name: "Transport", selected: true, basis: "student", grades: [grade] },
        { id: 2, name: "Uniform", selected: true, basis: "student", grades: [otherGrade] },
        { id: 3, name: "Fixed", selected: true, basis: "fixed", grades: [grade] },
        { id: 4, name: "Unselected", selected: false, basis: "student", grades: [grade] },
    ];
    const renderer = {
        props: { list: { records: [{ data: { grade_level_id: { id: 1, display_name: "Grade 1" } } }] } },
        income: { data: { groups: [{ categories: [{ items }] }] } },
    };
    const groups = Object.getOwnPropertyDescriptor(IncomeAccordionRenderer.prototype, "gradeGroups").get.call(renderer);
    expect(groups.map(group => [group.id, group.incomes.map(row => row.item.name)])).toEqual([
        [1, ["Transport"]],
        [2, ["Uniform"]],
    ]);
});
