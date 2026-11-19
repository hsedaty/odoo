import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    models,
    mountWithCleanup,
    preloadBundle,
} from "@web/../tests/web_test_helpers";
import { SchoolDashboard } from "@school_planning/js/dashboard";

class School extends models.Model {
    _name = "school.schools";

    get_dashboard() {
        const totals = {
            fee_gross_total: 2000, operating_cost_total: 1250.5,
            net_budget: 749.5, margin: 37.5, students: 25,
        };
        return {
            school_id: 1, schools: [{ id: 1, name: "Test School" }],
            years: [{ id: 1, name: "2026-2027" }],
            currency: "EUR", currency_digits: 2, totals,
            rows: [{ id: 1, name: "2026-2027", status: "draft", ...totals }],
            trend_metrics: [{ key: "net_budget", label: "Net budget", unit: "money" }],
            breakdown_metrics: [
                { key: "expense_category_spend", label: "Expenses by category", unit: "money" },
                { key: "students_by_grade", label: "Students by grade", unit: "count" },
            ],
            breakdowns: {
                expense_category_spend: [{ label: "Materials", value: 1250.5 }],
                students_by_grade: [{ label: "Grade 1", value: 25 }],
            },
            comparisons: [],
            chart_preferences: {
                trend_metric: "net_budget", trend_type: "line",
                breakdown_metric: "expense_category_spend", breakdown_type: "doughnut",
                comparison_metric: "net_budget",
            },
            can_save_chart_preferences: false,
        };
    }
}

defineModels([School]);
defineMailModels();
preloadBundle("web.chartjs_lib");

for (const style of ["doughnut", "bar"]) {
    test(`breakdown ${style} tooltips format money and counts`, async () => {
        await mountWithCleanup(SchoolDashboard, { props: { action: {} } });
        await contains("label:contains(Breakdown chart style) select").select(style);
        for (const [metric, label] of [
            ["expense_category_spend", "Materials: \u20ac1,250.50"],
            ["students_by_grade", "Grade 1: 25"],
        ]) {
            await contains("label:contains(Breakdown metric) select").select(metric);
            const chart = Chart.getChart(queryOne(".sp-cost-chart canvas"));
            chart.tooltip.setActiveElements([{ datasetIndex: 0, index: 0 }], { x: 0, y: 0 });
            expect(chart.tooltip.body[0].lines).toEqual([label]);
        }
    });
}

for (const value of [-50, 0]) {
    test(`breakdown bars display an all-${value < 0 ? "negative" : "zero"} series`, async () => {
        const dashboard = await mountWithCleanup(SchoolDashboard, { props: { action: {} } });
        dashboard.state.data.breakdowns.expense_category_spend = [{ label: "Adjustment", value }];
        await contains("label:contains(Breakdown chart style) select").select("bar");
        expect(".sp-cost-chart canvas").toHaveCount(1);
        const chart = Chart.getChart(queryOne(".sp-cost-chart canvas"));
        expect(chart.getDatasetMeta(0).controller.getParsed(0).x).toBe(value);
        await contains("label:contains(Breakdown chart style) select").select("doughnut");
        expect(".sp-cost-chart canvas").toHaveCount(0);
    });
}
