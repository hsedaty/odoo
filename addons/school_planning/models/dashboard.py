from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


FINANCIAL_METRICS = (
    'fee_gross_total', 'tax_deductions_total', 'fee_total',
    'employee_cost_total', 'non_payroll_expense_total', 'new_rooms_expense_total',
    'operating_cost_total', 'startup_cost_total', 'operating_profit', 'net_budget',
)

TREND_METRICS = (
    {'key': 'fee_gross_total', 'label': 'Gross revenue', 'unit': 'money'},
    {'key': 'fee_total', 'label': 'Net revenue', 'unit': 'money'},
    {'key': 'tax_deductions_total', 'label': 'Tax deductions', 'unit': 'money'},
    {'key': 'operating_cost_total', 'label': 'Operating costs', 'unit': 'money'},
    {'key': 'startup_cost_total', 'label': 'Startup investment', 'unit': 'money'},
    {'key': 'operating_profit', 'label': 'Operating profit', 'unit': 'money'},
    {'key': 'net_budget', 'label': 'Net budget', 'unit': 'money'},
    {'key': 'margin', 'label': 'Net margin', 'unit': 'percent'},
    {'key': 'students', 'label': 'Students', 'unit': 'count'},
    {'key': 'classes', 'label': 'Classes', 'unit': 'count'},
    {'key': 'teachers_required', 'label': 'Teachers required', 'unit': 'count'},
    {'key': 'staff_count', 'label': 'Staff headcount', 'unit': 'count'},
    {'key': 'payroll', 'label': 'Payroll', 'unit': 'money'},
    {'key': 'rooms_available', 'label': 'Rooms available', 'unit': 'count'},
    {'key': 'asset_purchases', 'label': 'Asset units to purchase', 'unit': 'count'},
)

BREAKDOWN_METRICS = (
    {'key': 'expense_category_spend', 'label': 'Expenses by category', 'unit': 'money', 'group': 'Category'},
    {'key': 'detailed_expense_category_spend', 'label': 'Detailed expense estimates by category (priced items)', 'unit': 'money', 'group': 'Category'},
    {'key': 'payroll_by_position', 'label': 'Payroll by staff position', 'unit': 'money', 'group': 'Staff position'},
    {'key': 'headcount_by_position', 'label': 'Headcount by staff position', 'unit': 'count', 'group': 'Staff position'},
    {'key': 'students_by_grade', 'label': 'Students by grade', 'unit': 'count', 'group': 'Grade'},
    {'key': 'revenue_by_grade', 'label': 'Net revenue by grade', 'unit': 'money', 'group': 'Grade'},
    {'key': 'rooms_by_type', 'label': 'Rooms by type', 'unit': 'count', 'group': 'Room type'},
    {'key': 'asset_purchases_by_item', 'label': 'Asset purchases by item', 'unit': 'count', 'group': 'Asset item'},
    {'key': 'asset_value_by_item', 'label': 'Startup investment by item', 'unit': 'money', 'group': 'Asset item'},
)

COMPARISON_SECTIONS = {
    'fee_gross_total': ('income',),
    'fee_total': ('income',),
    'tax_deductions_total': ('income',),
    'operating_cost_total': ('expenses', 'payroll', 'assets'),
    'startup_cost_total': ('assets',),
    'operating_profit': ('enrollment', 'income', 'expenses', 'payroll', 'assets'),
    'net_budget': ('enrollment', 'income', 'expenses', 'payroll', 'assets'),
    'margin': ('enrollment', 'income', 'expenses', 'payroll', 'assets'),
    'students': ('enrollment',),
    'classes': ('enrollment',),
    'teachers_required': ('enrollment', 'teaching'),
    'staff_count': ('payroll',),
    'payroll': ('payroll',),
    'rooms_available': ('assets',),
    'asset_purchases': ('assets',),
}

DEFAULT_CHART_PREFERENCES = {
    'trend_metric': 'net_budget',
    'trend_type': 'line',
    'breakdown_metric': 'expense_category_spend',
    'breakdown_type': 'doughnut',
    'comparison_metric': 'net_budget',
}

# Tuples, not sets: RPC input may be unhashable (lists/dicts) and must fail validation, not crash.
CHART_CHOICES = {
    'trend_metric': tuple(COMPARISON_SECTIONS),
    'trend_type': ('line', 'bar'),
    'breakdown_metric': tuple(item['key'] for item in BREAKDOWN_METRICS),
    'breakdown_type': ('bar', 'doughnut'),
    'comparison_metric': tuple(COMPARISON_SECTIONS),
}


class SchoolDashboard(models.Model):
    _inherit = 'school.schools'

    # groups= makes Odoo reject writes from non-administrators.
    dashboard_chart_preferences = fields.Json(string='Shared Dashboard Charts', groups='base.group_system')

    @api.model
    def _normalized_chart_preferences(self, preferences):
        if not isinstance(preferences, dict) or set(preferences) - set(DEFAULT_CHART_PREFERENCES):
            raise ValidationError(_('Invalid shared dashboard chart preferences.'))
        normalized = {**DEFAULT_CHART_PREFERENCES, **preferences}
        if any(normalized[key] not in choices for key, choices in CHART_CHOICES.items()):
            raise ValidationError(_('Select a supported dashboard chart.'))
        return normalized

    @api.model
    def _chart_values(self, year):
        return {
            'fee_gross_total': year.fee_gross_total,
            'fee_total': year.fee_total,
            'tax_deductions_total': year.tax_deductions_total,
            'operating_cost_total': year.operating_cost_total,
            'startup_cost_total': year.startup_cost_total,
            'operating_profit': year.operating_profit,
            'net_budget': year.net_budget,
            'margin': year.net_margin_pct,
            'students': year.total_enrolled_students,
            'classes': sum(year.enrollment_ids.mapped('class_count')),
            'teachers_required': year.required_teachers,
            'staff_count': sum(year.employment_salary_ids.mapped('employee_count')),
            'payroll': year.salary_total,
            'rooms_available': sum(year.room_plan_ids.mapped('effective_room_count')),
            'asset_purchases': sum(year.asset_price_ids.mapped('purchase_quantity')),
        }

    @api.model
    def _chart_breakdowns(self, years):
        values = {item['key']: {} for item in BREAKDOWN_METRICS}

        def add(metric, label, amount):
            label = label or _('Uncategorized')
            values[metric][label] = values[metric].get(label, 0) + amount

        for year in years:
            for enrollment in year.enrollment_ids:
                add('students_by_grade', enrollment.grade_level_id.name, enrollment.student_count)
                add('revenue_by_grade', enrollment.grade_level_id.name, enrollment.revenue_total)
            use_details = year.dataset_type == 'forecast' and year.detailed_expenses_created
            for category, expenses in year.expense_value_ids.grouped('expense_category_id').items():
                if use_details:
                    expenses = expenses.filtered(
                        lambda row: row.cost_bucket != 'operating' or not row.prediction_input_mode
                    )
                if expenses:
                    add('expense_category_spend', category.name, expenses._category_amount_total())
            if use_details and year.detailed_expense_seed_ids:
                selected = year._detailed_expense_catalog() & year.detailed_expense_seed_ids
                for seed, amount, _note in year._detailed_expense_amounts(selected):
                    if amount:
                        add('expense_category_spend', seed.category_seed_id.name, amount)
                        add('detailed_expense_category_spend', seed.category_seed_id.name, amount)
            for salary in year.employment_salary_ids:
                position = salary.staff_position_id.title
                add('payroll_by_position', position, salary.annual_cost)
                add('headcount_by_position', position, salary.employee_count)
            for room in year.room_plan_ids:
                add('rooms_by_type', room.room_type_id.name, room.effective_room_count)
            for asset in year.asset_price_ids:
                add('asset_purchases_by_item', asset.asset_item_id.name, asset.purchase_quantity)
                add('asset_value_by_item', asset.asset_item_id.name, asset.startup_cost)

        return {
            key: [
                {'label': label, 'value': amount}
                for label, amount in sorted(groups.items(), key=lambda item: (-item[1], item[0]))
            ]
            for key, groups in values.items()
        }

    @api.model
    def _comparison_data(self, years, dataset):
        if dataset == 'forecast':
            forecasts = years
        elif dataset == 'actual':
            forecasts = years.mapped('forecast_year_id')
        else:
            forecasts = years.browse()
        forecasts = forecasts.sorted(key=lambda year: (year.start_date or date.min, year.academic_year_name or '', year.id))
        result = []
        for forecast in forecasts:
            actual = forecast.actual_year_ids[:1]
            actual_values = None
            if actual:
                values = self._chart_values(actual)
                # None means "not entered yet", which the UI must not show as a real zero.
                actual_values = {
                    metric: values[metric]
                    if all(actual[f'{section}_status'] != 'not_started' for section in sections) else None
                    for metric, sections in COMPARISON_SECTIONS.items()
                }
            result.append({
                'id': forecast.id,
                'name': forecast.academic_year_name,
                'approved': forecast.baseline_locked,
                'forecast': self._chart_values(forecast),
                'actual': actual_values,
                'actual_exists': bool(actual),
                'actual_provisional': bool(actual and actual.actual_status != 'complete'),
            })
        return result

    @api.model
    def get_dashboard(self, school_id=False, dataset='forecast', year_id=False, year_ids=None):
        if dataset not in ('forecast', 'actual', 'legacy'):
            raise ValidationError(_('Select Forecast, Actual or Unclassified data.'))
        if year_ids is not None and (
            year_id or not isinstance(year_ids, list)
            or any(type(value) is not int or value <= 0 for value in year_ids)
        ):
            raise ValidationError(_('Select valid academic years.'))
        schools = self.search([], order='name, id')
        school = schools.filtered(lambda record: record.id == school_id) if school_id else schools[:1]
        if school_id and not school:
            raise ValidationError(_('The selected school is unavailable.'))
        years = self.env['school.academic.years'].search([
            ('school_id', '=', school.id), ('dataset_type', '=', dataset),
        ], order='start_date, academic_year_name, id') if school else self.env['school.academic.years']
        selected_ids = set(year_ids) if year_ids is not None else {year_id} if year_id else set(years.ids)
        selected = years.filtered(lambda year: year.id in selected_ids)
        if selected_ids - set(selected.ids):
            raise ValidationError(_('The selected year is unavailable for this school and dataset.'))

        rows = []
        grades = {}
        for year in selected:
            rows.append({
                'id': year.id, 'name': year.academic_year_name,
                'status': year.actual_status if dataset == 'actual' else (
                    'unclassified' if dataset == 'legacy' else (
                        'approved' if year.baseline_locked else 'draft')),
                **{name: year[name] for name in FINANCIAL_METRICS},
                **self._chart_values(year),
            })
            for enrollment in year.enrollment_ids.sorted(
                key=lambda line: (line.grade_level_id.sort_order, line.grade_level_id.id)
            ):
                level = enrollment.grade_level_id
                grade = grades.setdefault(level.id, {
                    'id': level.id, 'name': level.name, 'group': level.group_id.name or '',
                    'students': 0, 'revenue': 0.0, 'cost': 0.0,
                })
                grade['students'] += enrollment.student_count
                grade['revenue'] += enrollment.revenue_total
                grade['cost'] += enrollment.cost_total

        totals = {name: sum(row[name] for row in rows) for name in FINANCIAL_METRICS}
        totals['student_years'] = sum(row['students'] for row in rows)
        totals['students'] = rows[-1]['students'] if rows else 0
        totals['margin'] = totals['net_budget'] / totals['fee_gross_total'] * 100 if totals['fee_gross_total'] else 0
        currency = school.currency_id or self.env.company.currency_id
        return {
            'schools': [{'id': item.id, 'name': item.name} for item in schools],
            'school_id': school.id or False,
            'years': [{'id': year.id, 'name': year.academic_year_name} for year in years],
            'currency': currency.name, 'currency_digits': currency.decimal_places,
            'rows': rows, 'grades': list(grades.values()), 'totals': totals,
            'trend_metrics': [{**metric, 'label': _(metric['label'])} for metric in TREND_METRICS],
            'breakdown_metrics': [
                {**metric, 'label': _(metric['label']), 'group': _(metric['group'])}
                for metric in BREAKDOWN_METRICS
            ],
            'breakdowns': self._chart_breakdowns(selected),
            'expense_breakdown_uses_details': any(
                year.dataset_type == 'forecast' and year.detailed_expenses_created for year in selected
            ),
            'comparisons': self._comparison_data(selected, dataset),
            'chart_preferences': self._normalized_chart_preferences(school.sudo().dashboard_chart_preferences or {}),
            'can_save_chart_preferences': self.env.user.has_group('base.group_system'),
        }

    def save_dashboard_chart_preferences(self, preferences):
        """Save school-wide chart defaults; an empty dict restores the built-in defaults."""
        self.ensure_one()
        self.dashboard_chart_preferences = self._normalized_chart_preferences(preferences)
        return self.dashboard_chart_preferences

    def action_open_dashboard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client', 'tag': 'school_planning.dashboard',
            'name': _('School Dashboard'), 'params': {'school_id': self.id},
        }
