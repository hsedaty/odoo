import { expect, test } from "@odoo/hoot";
import { IncomeAccordionRenderer } from "@school_planning/js/income_accordion";

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
