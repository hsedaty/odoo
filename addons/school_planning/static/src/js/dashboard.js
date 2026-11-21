/** @odoo-module **/

import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const COLORS = ["#256f73", "#e5a84b", "#5865a8", "#cf655c"];
const COLUMNS = [
    { key: "students", label: _t("Students"), number: true },
    { key: "fee_gross_total", label: _t("Gross revenue") },
    { key: "tax_deductions_total", label: _t("Tax deductions") },
    { key: "fee_total", label: _t("Net revenue") },
    { key: "operating_cost_total", label: _t("Operating costs") },
    { key: "startup_cost_total", label: _t("Startup investment") },
    { key: "net_budget", label: _t("Net budget") },
    { key: "margin", label: _t("Margin %"), percent: true },
];

export class SchoolDashboard extends Component {
    static template = "school_planning.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const previous = this.props.state || {};
        this.state = useState({
            schoolId: previous.schoolId ?? this.props.action.params?.school_id ?? false,
            dataset: previous.dataset || "forecast",
            yearIds: previous.yearIds ?? (previous.yearId ? [previous.yearId] : null),
            data: null, busy: true, error: "",
            tab: previous.tab || "overview", search: previous.search || "",
            sort: previous.sort || "name", descending: previous.descending || false,
            columns: previous.columns || ["students", "fee_gross_total", "operating_cost_total", "net_budget", "margin"],
            chartConfig: previous.chartConfig || {},
            chartPreferencesChanged: previous.chartPreferencesChanged || false,
            canSaveChartPreferences: false,
        });
        useSetupAction({
            getLocalState: () => ({
                schoolId: this.state.schoolId, dataset: this.state.dataset, yearIds: this.state.yearIds,
                tab: this.state.tab, search: this.state.search, sort: this.state.sort,
                descending: this.state.descending, columns: [...this.state.columns],
                chartConfig: { ...this.state.chartConfig },
                chartPreferencesChanged: this.state.chartPreferencesChanged,
            }),
        });
        this.trendRef = useRef("trend");
        this.breakdownRef = useRef("breakdown");
        this.comparisonRef = useRef("comparison");
        this.requestId = 0;
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
        });
        useEffect(() => this.drawCharts(), () => [
            this.state.data, this.state.tab, this.state.busy,
            ...Object.values(this.state.chartConfig),
        ]);
    }

    async load() {
        const requestId = ++this.requestId;
        this.state.busy = true;
        this.state.error = "";
        try {
            const data = await this.orm.call("school.schools", "get_dashboard", [], {
                school_id: this.state.schoolId, dataset: this.state.dataset, year_ids: this.state.yearIds,
            });
            if (requestId === this.requestId) {
                if (!this.state.chartPreferencesChanged) {
                    this.state.chartConfig = data.chart_preferences;
                }
                this.state.data = data;
                this.state.schoolId = data.school_id;
                this.state.canSaveChartPreferences = data.can_save_chart_preferences;
            }
        } catch (error) {
            if (requestId === this.requestId) {
                this.state.error = error.data?.message || error.message || _t("Unable to load dashboard.");
                this.notification.add(this.state.error, { type: "danger" });
            }
        } finally {
            if (requestId === this.requestId) {
                this.state.busy = false;
            }
        }
    }

    changeFilter(key, event) {
        this.state[key] = key === "dataset" ? event.target.value : Number(event.target.value) || false;
        this.state.yearIds = null;
        if (key === "schoolId") {
            this.state.chartPreferencesChanged = false;
        }
        this.load();
    }

    get selectedYearIds() {
        return this.state.yearIds ?? (this.state.data?.years || []).map(year => year.id);
    }

    get yearFilterLabel() {
        if (this.state.yearIds === null) return _t("All years");
        if (this.state.yearIds.length === 1) {
            return this.state.data?.years.find(year => year.id === this.state.yearIds[0])?.name || _t("1 year");
        }
        return _t("%s years selected", this.state.yearIds.length);
    }

    selectAllYears(event) {
        this.state.yearIds = event.target.checked ? null : [];
        this.load();
    }

    selectYear(id, event) {
        const selected = new Set(this.selectedYearIds);
        if (event.target.checked) {
            selected.add(id);
        } else {
            selected.delete(id);
        }
        const all = this.state.data.years;
        this.state.yearIds = selected.size === all.length ? null : [...selected];
        this.load();
    }

    get columns() {
        return COLUMNS;
    }

    get visibleColumns() {
        return COLUMNS.filter(column => this.state.columns.includes(column.key));
    }

    toggleColumn(key) {
        this.state.columns = this.state.columns.includes(key)
            ? this.state.columns.filter(item => item !== key) : [...this.state.columns, key];
    }

    get reportRows() {
        const query = this.state.search.toLocaleLowerCase();
        const rows = (this.state.data?.rows || []).filter(row => row.name.toLocaleLowerCase().includes(query));
        return [...rows].sort((a, b) => {
            const key = this.state.sort;
            const result = key === "name" ? a.name.localeCompare(b.name) : a[key] - b[key];
            return this.state.descending ? -result : result;
        });
    }

    sortBy(key) {
        this.state.descending = this.state.sort === key ? !this.state.descending : false;
        this.state.sort = key;
    }

    sortDirection(key) {
        return this.state.sort === key ? (this.state.descending ? "descending" : "ascending") : "none";
    }

    statusLabel(status) {
        return {
            draft: _t("Draft"), approved: _t("Approved"), not_started: _t("Not started"),
            in_progress: _t("In progress"), complete: _t("Complete"),
        }[status] || _t("Unclassified");
    }

    amount(value, compact = false) {
        return new Intl.NumberFormat(undefined, {
            style: "currency", currency: this.state.data.currency,
            notation: compact ? "compact" : "standard",
            maximumFractionDigits: compact ? 1 : this.state.data.currency_digits,
        }).format(value);
    }

    number(value) {
        return new Intl.NumberFormat().format(value);
    }

    percent(value) {
        return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value) + "%";
    }

    cell(row, column) {
        return column.number ? this.number(row[column.key])
            : column.percent ? this.percent(row[column.key]) : this.amount(row[column.key]);
    }

    get kpis() {
        const totals = this.state.data.totals;
        const rows = this.state.data.rows;
        return [
            { label: _t("Gross revenue"), value: this.amount(totals.fee_gross_total, true),
                detail: _t("Before tax deductions"), icon: "fa-line-chart" },
            { label: _t("Operating costs"), value: this.amount(totals.operating_cost_total, true),
                detail: _t("Payroll, expenses & equipment"), icon: "fa-credit-card" },
            { label: _t("Net budget"), value: this.amount(totals.net_budget, true),
                detail: _t("%s gross-revenue margin", this.percent(totals.margin)),
                negative: totals.net_budget < 0, icon: "fa-pie-chart" },
            { label: _t("Students"), value: this.number(totals.students),
                detail: this.state.data.combined_branches ? _t("Latest selected year per school or branch")
                    : rows.at(-1)?.name || _t("No academic years"), icon: "fa-graduation-cap" },
        ];
    }

    get trendMetric() {
        return this.state.data.trend_metrics.find(item => item.key === this.state.chartConfig.trend_metric);
    }

    get breakdownMetric() {
        return this.state.data.breakdown_metrics.find(item => item.key === this.state.chartConfig.breakdown_metric);
    }

    get comparisonMetric() {
        return this.state.data.trend_metrics.find(item => item.key === this.state.chartConfig.comparison_metric);
    }

    get breakdownRows() {
        return this.state.data?.breakdowns[this.state.chartConfig.breakdown_metric] || [];
    }

    get hasBreakdownChart() {
        const rows = this.breakdownRows;
        return rows.length > 0 && (
            this.state.chartConfig.breakdown_type !== "doughnut"
            || (rows.some(row => row.value > 0) && rows.every(row => row.value >= 0))
        );
    }

    chartPreferenceChanged(key, event) {
        this.state.chartConfig[key] = event.target.value;
        this.state.chartPreferencesChanged = true;
    }

    comparisonActualValue(comparison) {
        return comparison.actual?.[this.state.chartConfig.comparison_metric];
    }

    comparisonDifference(comparison) {
        const actual = this.comparisonActualValue(comparison);
        return actual == null ? null : actual - comparison.forecast[this.state.chartConfig.comparison_metric];
    }

    comparisonStatus(comparison) {
        if (!comparison.actual_exists) return _t("No linked Actual year yet");
        if (this.comparisonActualValue(comparison) == null) return _t("Not entered");
        return comparison.actual_provisional ? _t("Actual is provisional") : _t("Actual complete");
    }

    async saveChartPreferences(reset = false) {
        this.state.chartConfig = await this.orm.call(
            "school.schools", "save_dashboard_chart_preferences",
            [[this.state.schoolId], reset ? {} : this.state.chartConfig],
        );
        this.state.chartPreferencesChanged = false;
        this.notification.add(reset
            ? _t("The school dashboard has been restored to its default charts.")
            : _t("These chart defaults are now shared with everyone at this school."), { type: "success" });
    }

    chartValue(value, unit, compact = false) {
        if (value == null) {
            return _t("Not entered");
        }
        if (unit === "money") {
            return this.amount(value, compact);
        }
        if (unit === "percent") {
            return this.percent(value);
        }
        return this.number(value);
    }

    get provisional() {
        return this.state.dataset === "actual"
            && this.state.data.rows.some(row => row.status !== "complete");
    }

    async openYear(id) {
        const action = await this.orm.call("school.academic.years", "action_open_forecast", [[id]]);
        return this.action.doAction(action);
    }

    async openSchool() {
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: "school.schools",
            res_id: this.state.schoolId, views: [[false, "form"]], target: "current",
        });
    }

    openSchools() {
        return this.action.doAction("school_planning.action_school_schools");
    }

    async predict() {
        const action = this.state.schoolId
            ? await this.orm.call("school.schools", "action_open_quick_prediction", [[this.state.schoolId]])
            : "school_planning.action_school_schools";
        return this.action.doAction(action, { onClose: () => this.load() });
    }

    exportPdf() {
        const rows = this.state.tab === "report" ? this.reportRows : this.state.data.rows;
        return this.action.doAction({
            type: "ir.actions.act_url", target: "download",
            url: `/school_planning/financial-summary/pdf?ids=${rows.map(row => row.id).join(",")}`,
        });
    }

    exportCsv() {
        const escape = value => {
            let text = String(value);
            if (/^[=+\-@\t\r]/.test(text)) {
                text = "'" + text;
            }
            return '"' + text.replaceAll('"', '""') + '"';
        };
        const columns = this.visibleColumns;
        const metadata = [
            [_t("School"), this.state.data.schools.find(school => school.id === this.state.schoolId)?.name],
            [_t("Dataset"), this.state.dataset], [_t("Currency"), this.state.data.currency],
        ];
        const rows = [
            ...metadata, [_t("Academic year"), ...columns.map(column => column.label)],
            ...this.reportRows.map(row => [row.name, ...columns.map(column => {
                const digits = column.number ? 0 : column.percent ? 2 : this.state.data.currency_digits;
                return Number(row[column.key].toFixed(digits));
            })]),
        ];
        const url = URL.createObjectURL(new Blob(["\uFEFF" + rows.map(row => row.map(
            value => typeof value === "number" ? String(value) : escape(value)
        ).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8;" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `school-report-${this.state.dataset}.csv`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    drawCharts() {
        if (this.state.busy || this.state.error || this.state.tab !== "overview" || !this.trendRef.el) {
            return;
        }
        const rows = this.state.data.rows;
        const charts = [];
        const config = this.state.chartConfig;
        const trendType = this.state.data.combined_branches ? "bar" : config.trend_type;
        const trendMetric = this.trendMetric;
        const breakdownMetric = this.breakdownMetric;
        const comparisons = this.state.data.comparisons;
        const comparisonMetric = this.comparisonMetric;
        charts.push(new Chart(this.trendRef.el, {
            type: trendType,
            data: {
                labels: rows.map(row => row.name),
                datasets: [
                    {
                        label: trendMetric.label, data: rows.map(row => row[trendMetric.key]),
                        borderColor: COLORS[0], backgroundColor: trendType === "line" ? "#256f7314" : COLORS[0],
                        fill: trendType === "line", tension: 0.25,
                    },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                scales: {
                    y: { beginAtZero: true, ticks: { callback: value => this.chartValue(value, trendMetric.unit, true) } },
                    x: { grid: { display: false } },
                },
                plugins: { legend: { display: false }, tooltip: { callbacks: {
                    label: context => this.chartValue(context.parsed.y, trendMetric.unit),
                } } },
                onClick: (_event, elements) => {
                    if (elements.length) this.openYear(rows[elements[0].index].id);
                },
            },
        }));

        const breakdownRows = this.breakdownRows;
        const breakdownOptions = {
            responsive: true, maintainAspectRatio: false, animation: false,
            indexAxis: config.breakdown_type === "bar" ? "y" : "x",
            plugins: { legend: { display: config.breakdown_type === "doughnut", position: "bottom" } },
            scales: config.breakdown_type === "bar" ? {
                x: { beginAtZero: true, ticks: { callback: value => this.chartValue(value, breakdownMetric.unit, true) } },
                y: { grid: { display: false } },
            } : {},
        };
        if (this.breakdownRef.el && this.hasBreakdownChart) {
            charts.push(new Chart(this.breakdownRef.el, {
                type: config.breakdown_type,
                data: {
                    labels: breakdownRows.map(row => row.label),
                    datasets: [{
                        label: breakdownMetric.label, data: breakdownRows.map(row => row.value),
                        backgroundColor: breakdownRows.map((_row, index) => COLORS[index % COLORS.length]),
                        borderWidth: config.breakdown_type === "doughnut" ? 3 : 0,
                    }],
                },
                options: { ...breakdownOptions, plugins: {
                    ...breakdownOptions.plugins, tooltip: { callbacks: {
                        label: context => `${context.label}: ${this.chartValue(
                            config.breakdown_type === "bar" ? context.parsed.x : context.parsed, breakdownMetric.unit
                        )}`,
                    } },
                } },
            }));
        }
        if (this.comparisonRef.el && comparisons.length && comparisonMetric) {
            charts.push(new Chart(this.comparisonRef.el, {
                type: "bar",
                data: {
                    labels: comparisons.map(comparison => comparison.name),
                    datasets: [
                        { label: _t("Forecast"), data: comparisons.map(comparison => comparison.forecast[comparisonMetric.key]), backgroundColor: COLORS[0] },
                        { label: _t("Actual"), data: comparisons.map(comparison => comparison.actual?.[comparisonMetric.key] ?? null), backgroundColor: COLORS[1] },
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false, animation: false,
                    plugins: { legend: { position: "bottom" }, tooltip: { callbacks: {
                        label: context => `${context.dataset.label}: ${this.chartValue(context.parsed.y, comparisonMetric.unit)}`,
                    } } },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: value => this.chartValue(value, comparisonMetric.unit, true) } },
                        x: { grid: { display: false } },
                    },
                },
            }));
        }
        return () => charts.forEach(chart => chart.destroy());
    }
}

registry.category("actions").add("school_planning.dashboard", SchoolDashboard);
