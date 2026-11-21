from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import formatLang


COMPLETION = [('not_started', 'Not Started'), ('in_progress', 'In Progress'), ('complete', 'Complete')]
ACTUAL_TOOLS = {
    'planning': [('grade_enrollment', 'Enrollment Dashboard'), ('subject_distribution', 'Teaching Load'), ('room_plan', 'Room Planning'),
                 ('expansion_projects', 'Expansion Projects'), ('expansion_project_rooms', 'Project Rooms')],
    'financial': [('fee_values', 'Revenue / Fees'), ('expense_values', 'Operating Expenses'), ('employment_salaries', 'Salaries Budget'),
                  ('fee_values_revenue_chart', 'Revenue Analysis'), ('expense_values_pie_chart', 'Expense Analysis')],
    'asset': [('asset_overview', 'Asset Overview'), ('asset_items', 'Asset Items'), ('asset_prices', 'Asset Prices'), ('asset_transactions', 'Asset Transactions')],
    'setup': [('academic_years', 'Academic Years'), ('grade_setup_wizard', 'Configure Grades'), ('grade_groups', 'Grade Groups'),
              ('grade_levels', 'Grade Levels'), ('subject_setup_wizard', 'Configure Subjects'), ('subjects', 'Subjects'), ('fee_types', 'Fee Types'),
              ('tax_rules', 'Tax Rules'), ('expense_categories', 'Expense Categories'), ('expense_items', 'Expense Items'),
              ('staff_categories', 'Staff Categories'), ('staff_positions', 'Staff Positions'), ('staffing_rules', 'Staffing Rules'),
              ('room_types', 'Room Types'), ('room_templates', 'Room Templates'), ('room_template_items', 'Room Template Items'),
              ('prediction_seed_configuration', 'Seed Configuration')],
}
METRICS = [
    ('total_enrolled_students', 'Students', 'enrollment', 'neutral'),
    ('fee_gross_total', 'Gross Revenue', 'income', 'higher'),
    ('tax_deductions_total', 'Tax Deductions', 'income', 'lower'),
    ('fee_total', 'Net Revenue', 'income', 'higher'),
    ('employee_cost_total', 'Total Payroll / Salaries', 'payroll', 'lower'),
    ('non_payroll_expense_total', 'Other Operating Expenses', 'expenses', 'lower'),
    ('new_rooms_expense_total', 'New Room Equipment', 'assets', 'lower'),
    ('operating_cost_total', 'Total Operating Costs', 'all', 'lower'),
    ('startup_cost_total', 'Startup Investment', 'assets', 'lower'),
    ('operating_profit', 'Operating Profit', 'all', 'higher'),
    ('net_budget', 'Net Budget', 'all', 'higher'),
]


class AcademicYears(models.Model):
    _inherit = 'school.academic.years'

    forecast_year_id = fields.Many2one('school.academic.years', string='Forecast Baseline', ondelete='restrict', copy=False)
    actual_year_ids = fields.One2many('school.academic.years', 'forecast_year_id', string='Actual Years')
    period_key = fields.Char(compute='_compute_period_key', store=True)
    typed_year_name = fields.Char(compute='_compute_period_key', store=True)
    baseline_locked = fields.Boolean(string='Approved Baseline', readonly=True, copy=False)
    baseline_totals = fields.Json(readonly=True, copy=False)
    enrollment_status = fields.Selection(COMPLETION, default='not_started', required=True)
    income_status = fields.Selection(COMPLETION, default='not_started', required=True)
    expenses_status = fields.Selection(COMPLETION, default='not_started', required=True)
    payroll_status = fields.Selection(COMPLETION, default='not_started', required=True)
    assets_status = fields.Selection(COMPLETION, default='not_started', required=True)
    teaching_status = fields.Selection(COMPLETION, default='not_started', required=True)
    actual_status = fields.Selection(COMPLETION, compute='_compute_actual_status', string='Actual Progress')
    employee_cost_total = fields.Float(compute='_compute_financial_summary', string='Employee Costs')
    non_payroll_expense_total = fields.Float(compute='_compute_financial_summary', string='Other Operating Expenses')
    room_plan_ids = fields.One2many('school.room.plan', 'academic_year_id')
    asset_price_ids = fields.One2many('school.asset.prices', 'academic_year_id')
    subject_distribution_ids = fields.One2many('school.subject.distribution', 'academic_year_id')
    asset_transaction_ids = fields.One2many('school.asset.transactions', 'academic_year_id')
    expansion_project_ids = fields.One2many('school.expansion.projects', 'academic_year_id')
    staffing_override_ids = fields.One2many('school.staffing.overrides', 'academic_year_id')
    actual_planning_tool = fields.Selection(ACTUAL_TOOLS['planning'], default='grade_enrollment', string='Planning Workflows')
    actual_financial_tool = fields.Selection(ACTUAL_TOOLS['financial'], default='fee_values', string='Financial Operations')
    actual_asset_tool = fields.Selection(ACTUAL_TOOLS['asset'], default='asset_overview', string='Asset Management')
    actual_setup_tool = fields.Selection(ACTUAL_TOOLS['setup'], default='expense_items', string='Shared Setup',
                                         help='School setup is shared with Forecast. Tax types belong to this school; seed configuration is global.')
    actual_payroll_months = fields.Integer(string='Common Payroll Months', default=12)
    actual_fee_tax_percent = fields.Float(string='Common Fee Tax %', default=0)
    actual_fee_type_id = fields.Many2one('school.fee.types', string='Fee')
    actual_fee_amount = fields.Float(string='Fee / Student', default=0)
    actual_fee_grade_ids = fields.Many2many('school.grade.levels', 'school_actual_fee_grade_rel', 'year_id', 'grade_id', string='Grades')
    actual_fee_tax_rule_ids = fields.Many2many('school.tax.rules', 'school_actual_bulk_fee_tax_rel', 'year_id', 'tax_rule_id', string='Tax Types')
    actual_used_tax_rule_ids = fields.Many2many('school.tax.rules', compute='_compute_actual_used_taxes', string='Tax Types')
    actual_expense_category_id = fields.Many2one('school.expense.categories', string='Category')
    actual_expense_item_id = fields.Many2one('school.expense.items', string='Expense Item')
    actual_expense_amount = fields.Float(string='Annual Amount')
    total_students_input = fields.Integer(string='Total Students', compute='_compute_total_students_input', inverse='_inverse_total_students_input')
    annual_fee_input = fields.Float(string='Annual Fee / Student', compute='_compute_annual_fee_input', inverse='_inverse_annual_fee_input')
    payroll_summary_enabled = fields.Boolean(string='Use Total Payroll', default=False)
    payroll_basis = fields.Selection([('percent', 'Percentage of Revenue'), ('amount', 'Fixed Amount')], default='percent', required=True)
    payroll_rate = fields.Float(string='Payroll Rate')
    payroll_revenue_basis = fields.Selection([('gross', 'Before Tax'), ('net', 'After Tax')], string='Revenue Base', default='gross', required=True)
    payroll_fixed_amount = fields.Float(string='Fixed Payroll')
    payroll_percent_input = fields.Float(string='Salaries % of Revenue', compute='_compute_payroll_inputs', inverse='_inverse_payroll_percent')
    payroll_amount_input = fields.Float(string='Total Payroll / Salaries', compute='_compute_payroll_inputs', inverse='_inverse_payroll_amount')
    operating_expense_ids = fields.One2many('school.expense.values', 'academic_year_id', domain=[('cost_bucket', '=', 'operating')])
    payroll_expense_ids = fields.One2many('school.expense.values', 'academic_year_id', domain=[('cost_bucket', '=', 'employee')])

    @api.onchange('payroll_expense_ids')
    def _onchange_payroll_expense_amounts(self):
        for year in self.filtered('payroll_summary_enabled'):
            year.payroll_basis = 'amount'
            year.payroll_fixed_amount = year.payroll_expense_ids._category_amount_total()

    @api.depends('fee_gross_total', 'total_enrolled_students', 'fee_value_ids.amount')
    def _compute_annual_fee_input(self):
        for year in self:
            if year.total_enrolled_students:
                year.annual_fee_input = year.fee_gross_total / year.total_enrolled_students
            else:
                totals = {}
                for row in year.fee_value_ids:
                    totals[row.grade_level_id.id] = totals.get(row.grade_level_id.id, 0) + row.amount
                year.annual_fee_input = sum(totals.values()) / len(totals) if totals else 0

    def _inverse_annual_fee_input(self):
        for year in self:
            amount = year.annual_fee_input
            if amount < 0:
                raise ValidationError('Annual Fee / Student cannot be negative.')
            for enrollment in year.enrollment_ids:
                rows = year.fee_value_ids.filtered(lambda row: row.grade_level_id == enrollment.grade_level_id)
                if year.dataset_type == 'actual':
                    rows = rows.filtered(lambda row: row.actual_applicability == 'all')
                if not rows:
                    fee_type = self.env['school.fee.types'].search([('school_id', '=', year.school_id.id)], order='display_order, id', limit=1)
                    if not fee_type:
                        fee_type = self.env['school.fee.types'].create({'school_id': year.school_id.id, 'name': 'Tuition Fee', 'display_order': 10})
                    rows = self.env['school.fee.values'].create([{'academic_year_id': year.id, 'grade_level_id': enrollment.grade_level_id.id, 'fee_type_id': fee_type.id, 'amount': 0}])
                previous_total = sum(rows.mapped('amount'))
                for row in rows:
                    share = row.amount / previous_total if previous_total else 1 / len(rows)
                    row.with_context(defer_school_financial_refresh=True).amount = amount * share
            self.env['school.financial.report']._refresh_for_academic_years(year.ids)

    def _payroll_revenue_base(self):
        self.ensure_one()
        return max(self.fee_total if self.payroll_revenue_basis == 'net' else self.fee_gross_total, 0)

    @api.depends('employee_cost_total', 'fee_gross_total', 'payroll_summary_enabled', 'payroll_basis', 'payroll_revenue_basis', 'payroll_rate', 'payroll_fixed_amount')
    def _compute_payroll_inputs(self):
        for year in self:
            year.payroll_amount_input = year.employee_cost_total
            year.payroll_percent_input = year.payroll_rate if year.payroll_summary_enabled and year.payroll_basis == 'percent' else (
                year.employee_cost_total / year.fee_gross_total * 100 if year.fee_gross_total else 0
            )

    def _inverse_payroll_percent(self):
        for year in self:
            percent = year.payroll_percent_input
            if not 0 <= percent <= 100:
                raise ValidationError('Salaries % must be between 0 and 100.')
            revenue_basis = year.payroll_revenue_basis if year.payroll_summary_enabled and year.payroll_basis == 'percent' else 'gross'
            year.write({'payroll_summary_enabled': True, 'payroll_basis': 'percent', 'payroll_rate': percent, 'payroll_revenue_basis': revenue_basis,
                        **({'payroll_status': 'in_progress'} if year.dataset_type == 'actual' else {})})
            year.invalidate_recordset(['payroll_percent_input', 'payroll_amount_input'])

    def _inverse_payroll_amount(self):
        for year in self:
            amount = year.payroll_amount_input
            if amount < 0:
                raise ValidationError('Total Payroll cannot be negative.')
            year.write({'payroll_summary_enabled': True, 'payroll_basis': 'amount', 'payroll_fixed_amount': amount, 'payroll_revenue_basis': 'gross',
                        **({'payroll_status': 'in_progress'} if year.dataset_type == 'actual' else {})})
            year.invalidate_recordset(['payroll_percent_input', 'payroll_amount_input'])

    @api.depends('enrollment_ids.student_count')
    def _compute_total_students_input(self):
        for year in self:
            year.total_students_input = sum(year.enrollment_ids.mapped('student_count'))

    def _inverse_total_students_input(self):
        for year in self:
            total = year.total_students_input
            if total < 0:
                raise ValidationError('Total Students cannot be negative.')
            rows = year.enrollment_ids.sorted('id')
            if not rows:
                grades = self.env['school.grade.levels'].search([('school_id', '=', year.school_id.id)], order='sort_order, id')
                if not grades:
                    raise ValidationError('Configure this school\'s grades before entering Total Students.')
                rows = self.env['school.grade.enrollment'].create([
                    {'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 0} for grade in grades
                ])
            weights = [max(row.student_count, 0) for row in rows]
            if not sum(weights):
                weights = [1] * len(rows)
            weight_total = sum(weights)
            counts = [total * weight // weight_total for weight in weights]
            remainder_order = sorted(range(len(rows)), key=lambda index: (-(total * weights[index] % weight_total), index))
            for index in remainder_order[:total - sum(counts)]:
                counts[index] += 1
            for row, count in zip(rows, counts):
                row.with_context(defer_school_financial_refresh=True).student_count = count
            self.env['school.financial.report']._refresh_for_academic_years(year.ids)

    @api.onchange('total_students_input')
    def _onchange_total_students_input(self):
        for year in self:
            total = year.total_students_input
            if total < 0:
                raise ValidationError('Total Students cannot be negative.')
            rows = year.enrollment_ids
            if not rows:
                grades = self.env['school.grade.levels'].search([('school_id', '=', year.school_id.id)], order='sort_order, id')
                year.enrollment_ids = [fields.Command.create({'grade_level_id': grade.id, 'student_count': 0}) for grade in grades]
                rows = year.enrollment_ids
            if not rows or total == sum(rows.mapped('student_count')):
                continue
            weights = [max(row.student_count, 0) for row in rows]
            if not sum(weights):
                weights = [1] * len(rows)
            denominator = sum(weights)
            counts = [total * weight // denominator for weight in weights]
            order = sorted(range(len(rows)), key=lambda index: (-(total * weights[index] % denominator), index))
            for index in order[:total - sum(counts)]:
                counts[index] += 1
            for row, count in zip(rows, counts):
                row.student_count = count
            if year.dataset_type == 'actual':
                year.enrollment_status = 'in_progress'

    @api.onchange('annual_fee_input')
    def _onchange_annual_fee_input(self):
        for year in self.filtered(lambda record: record.dataset_type != 'actual'):
            amount = year.annual_fee_input
            if amount < 0:
                raise ValidationError('Annual Fee / Student cannot be negative.')
            students = sum(year.enrollment_ids.mapped('student_count'))
            totals = [sum(year.fee_value_ids.filtered(lambda row: row.grade_level_id == grade).mapped('amount')) for grade in year.fee_value_ids.mapped('grade_level_id')]
            current = sum(year.fee_value_ids.mapped('gross_revenue_amount')) / students if students else (sum(totals) / len(totals) if totals else 0)
            if abs(current - amount) < 0.000001:
                continue
            changed = False
            for grade in year.fee_value_ids.mapped('grade_level_id'):
                rows = year.fee_value_ids.filtered(lambda row: row.grade_level_id == grade)
                previous = sum(rows.mapped('amount'))
                if abs(previous - amount) < 0.000001:
                    continue
                shares = [row.amount / previous if previous else 1 / len(rows) for row in rows]
                for row, share in zip(rows, shares):
                    row.amount = amount * share
                changed = True
            if changed and year.dataset_type == 'actual':
                year.income_status = 'in_progress'

    _period_dataset_unique = models.Constraint(
        'unique(school_id, period_key, dataset_type)',
        'This school already has this reporting period in the selected dataset.',
    )
    _actual_baseline_unique = models.Constraint('unique(forecast_year_id)', 'This forecast already has an Actual year.')
    _named_dataset_unique = models.Constraint('unique(school_id, typed_year_name, dataset_type)', 'This school already has this year name in the selected dataset.')

    @api.depends('dataset_type', 'start_date', 'end_date', 'academic_year_name')
    def _compute_period_key(self):
        for year in self:
            year.period_key = f'{year.start_date}/{year.end_date}' if year.dataset_type != 'legacy' else False
            year.typed_year_name = year.academic_year_name if year.dataset_type != 'legacy' else False

    @api.depends('enrollment_status', 'income_status', 'expenses_status', 'payroll_status', 'assets_status', 'teaching_status')
    def _compute_actual_status(self):
        for year in self:
            statuses = [year[f'{section}_status'] for section in ('enrollment', 'income', 'expenses', 'payroll', 'assets', 'teaching')]
            year.actual_status = 'complete' if all(status == 'complete' for status in statuses) else (
                'not_started' if all(status == 'not_started' for status in statuses) else 'in_progress'
            )

    @api.constrains('dataset_type', 'school_id', 'start_date', 'end_date', 'academic_year_name', 'forecast_year_id')
    def _check_dataset_period(self):
        for year in self:
            if year.dataset_type != 'legacy' and (not year.start_date or not year.end_date or year.start_date >= year.end_date):
                raise ValidationError('Forecast and Actual years need a valid start and end date.')
            baseline = year.forecast_year_id
            if baseline and (year.dataset_type != 'actual' or baseline.dataset_type != 'forecast'
                             or baseline.school_id != year.school_id
                             or baseline.start_date != year.start_date or baseline.end_date != year.end_date
                             or baseline.academic_year_name != year.academic_year_name):
                raise ValidationError('Actual and Forecast must belong to the same school and exact reporting year.')
            for actual in year.actual_year_ids:
                if actual.school_id != year.school_id or actual.start_date != year.start_date or actual.end_date != year.end_date or actual.academic_year_name != year.academic_year_name or year.dataset_type != 'forecast':
                    raise ValidationError('A linked Forecast reporting year cannot be changed independently of its Actual year.')

    @api.depends('school_id', 'start_date', 'end_date', 'baseline_locked', 'baseline_totals',
                 'enrollment_ids.student_count', 'fee_value_ids.revenue_amount', 'expense_value_ids.amount',
                 'expense_value_ids.cost_bucket', 'expense_value_ids.expense_category_id', 'expense_value_ids.expense_item_id',
                 'employment_salary_ids.annual_cost',
                 'room_plan_ids.new_rooms_asset_cost', 'asset_price_ids.startup_cost', 'infrastructure_seeded', 'infrastructure_mode',
                 'payroll_summary_enabled', 'payroll_basis', 'payroll_revenue_basis', 'payroll_rate', 'payroll_fixed_amount')
    def _compute_financial_summary(self):
        super()._compute_financial_summary()
        for year in self:
            employee_expenses = 0 if year.payroll_summary_enabled else year.payroll_expense_ids._category_amount_total()
            year.employee_cost_total = year.salary_total + employee_expenses
            year.non_payroll_expense_total = year.expense_total - employee_expenses
            if year.baseline_locked:
                for name, amount in (year.baseline_totals or {}).items():
                    year[name] = amount

    @api.depends('academic_year_name', 'dataset_type', 'school_id')
    def _compute_display_name(self):
        labels = dict(self._fields['dataset_type'].selection)
        for year in self:
            year.display_name = f'{year.academic_year_name} | {labels.get(year.dataset_type)} | {year.school_id.name}'

    @api.model_create_multi
    def create(self, vals_list):
        if any(values.get('baseline_locked') or values.get('baseline_totals') for values in vals_list):
            raise ValidationError('Approve the forecast using Freeze Baseline.')
        prepared = []
        for values in vals_list:
            values = {'dataset_type': self.env.context.get('default_dataset_type', 'actual'), **values}
            if values['dataset_type'] == 'actual':
                for name in ('total_students_input', 'annual_fee_input', 'payroll_percent_input', 'payroll_amount_input'):
                    if values.get(name) == 0:
                        values.pop(name)
                enrollments = values.get('enrollment_ids', [])
                if enrollments and all(command[0] == fields.Command.CREATE and not command[2].get('student_count') for command in enrollments):
                    values.pop('enrollment_ids')
            prepared.append(values)
        records = super().create(prepared)
        records._ensure_forecast_expense_structure()
        records._prepare_actual_entry_rows()
        self.env['school.financial.report']._refresh_for_academic_years(records.ids)
        return records

    def write(self, values):
        if any(year.baseline_locked for year in self):
            raise ValidationError('This approved forecast is frozen. Its inputs and reporting period cannot be changed.')
        if 'dataset_type' in values and any(year.dataset_type != 'legacy' and year.dataset_type != values['dataset_type'] for year in self):
            raise ValidationError('Keep Forecast and Actual separate. Only unclassified historical years can change dataset.')
        if 'baseline_locked' in values or 'baseline_totals' in values:
            raise ValidationError('Approve the forecast using Freeze Baseline.')
        result = super().write(values)
        if {'forecast_year_id', 'dataset_type'} & values.keys():
            self._ensure_forecast_expense_structure()
        self.env['school.financial.report']._refresh_for_academic_years(self.ids)
        return result

    @api.constrains('prediction_income_tax_percent', 'dataset_type')
    def _check_prediction_income_tax_percent(self):
        if any(year.dataset_type == 'forecast' and not 0 <= year.prediction_income_tax_percent <= 100 for year in self):
            raise ValidationError(self.env._('Forecast tax deduction must be between 0 and 100%.'))

    def unlink(self):
        if any(year.baseline_locked for year in self):
            raise ValidationError('An approved forecast cannot be deleted.')
        return super().unlink()

    def action_freeze_baseline(self):
        for year in self:
            if year.dataset_type != 'forecast':
                raise ValidationError('Only a Forecast can be approved.')
            if year.baseline_locked:
                continue
            self.env['school.financial.report']._refresh_for_academic_years(year.ids)
            totals = {name: year[name] for name, field in year._fields.items() if field.compute == '_compute_financial_summary'}
            super(AcademicYears, year).write({'baseline_totals': totals, 'baseline_locked': True})
        return self._workspace_action()

    def _workspace_action(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.display_name, 'res_model': self._name,
                'res_id': self.id, 'view_mode': 'form', 'target': 'current',
                'views': [(self.env.ref('school_planning.view_school_year_workspace').id, 'form')]}

    def _ensure_actual_year(self):
        self.ensure_one()
        if self.dataset_type == 'actual':
            return self
        if self.dataset_type != 'forecast':
            raise ValidationError('Classify this historical year before creating a Forecast/Actual pair.')
        actual = self.actual_year_ids
        if not actual:
            actual = self.search([('school_id', '=', self.school_id.id), ('dataset_type', '=', 'actual'),
                                  ('start_date', '=', self.start_date), ('end_date', '=', self.end_date)], limit=1)
            if actual:
                actual.write({'forecast_year_id': self.id, 'academic_year_name': self.academic_year_name})
            else:
                actual = self.create({'school_id': self.school_id.id, 'academic_year_name': self.academic_year_name,
                                     'start_date': self.start_date, 'end_date': self.end_date,
                                     'dataset_type': 'actual', 'forecast_year_id': self.id})
        actual._ensure_forecast_expense_structure()
        actual._prepare_actual_entry_rows()
        return actual

    def _prepare_actual_entry_rows(self):
        for year in self.filtered(lambda record: record.dataset_type == 'actual'):
            year._ensure_forecast_expense_structure()
            context = {'actual_structure_only': True, 'defer_school_financial_refresh': True}
            grades = self.env['school.grade.levels'].search([('school_id', '=', year.school_id.id)], order='sort_order, id')
            missing_grades = grades - year.enrollment_ids.mapped('grade_level_id')
            self.env['school.grade.enrollment'].with_context(**context).create([
                {'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 0} for grade in missing_grades
            ])
            for seed in self.env.ref('school_planning.prediction_seed_configuration').fee_ids:
                fee_type = self.env['school.fee.types'].search([('school_id', '=', year.school_id.id), ('name', '=ilike', seed.name)], limit=1)
                if not fee_type:
                    self.env['school.fee.types'].create({'school_id': year.school_id.id, 'name': seed.name, 'display_order': seed.display_order,
                                                        'is_optional': seed.is_optional})
                elif seed.is_optional and not fee_type.is_optional:
                    fee_type.is_optional = True
            fee_types = self.env['school.fee.types'].search([('school_id', '=', year.school_id.id)], order='display_order, id')
            existing_fees = {(row.grade_level_id.id, row.fee_type_id.id) for row in year.fee_value_ids}
            self.env['school.fee.values'].with_context(**context).create([
                {'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': fee_type.id, 'amount': 0}
                for grade in grades for fee_type in fee_types if (grade.id, fee_type.id) not in existing_fees
            ])
            positions = self.env['school.staff.positions'].search([('school_id', '=', year.school_id.id)])
            if not positions:
                setup = self.env['school.prediction.quick.setup.wizard'].create({'school_id': year.school_id.id, 'forecast_years': 1,
                                                                                'teaching_load_hours': year.teacher_weekly_hours,
                                                                                'classroom_weekly_hours': year.classroom_weekly_hours})
                setup._ensure_operating_models()
                setup.unlink()
                positions = self.env['school.staff.positions'].search([('school_id', '=', year.school_id.id)])
            positions -= year.employment_salary_ids.mapped('staff_position_id')
            self.env['school.employment.salaries'].with_context(**context).create([
                {'academic_year_id': year.id, 'staff_position_id': position.id, 'actual_employee_count': 0,
                 'monthly_salary': 0, 'months_paid': year.actual_payroll_months, 'bonus': 0} for position in positions
            ])
            subjects = self.env['school.subjects'].search([('school_id', '=', year.school_id.id)])
            existing_load = {(row.grade_level_id.id, row.subject_id.id) for row in year.subject_distribution_ids}
            template_grades = grades
            load_values = []
            if year.uses_american_timetable:
                from .american_curriculum import american_grade_index
                template_grades = grades.filtered(lambda grade: american_grade_index(grade) is None)
                choice_grades = year.subject_distribution_ids.filtered('choice_subject_ids').grade_level_id.ids
                load_values += [
                    {**values, 'weekly_hours': 0}
                    for values in year.school_id._american_timetable_values(grades, subjects)
                    if not values.get('choice_subject_ids') or values['grade_level_id'] not in choice_grades
                ]
            load_values += [
                {'grade_level_id': grade.id, 'subject_id': subject.id, 'weekly_hours': 0, 'credits': 0}
                for grade in template_grades for subject in subjects
            ]
            self.env['school.subject.distribution'].with_context(**context).create([
                {**values, 'academic_year_id': year.id}
                for values in load_values if (values['grade_level_id'], values['subject_id']) not in existing_load
            ])

    def action_prepare_actual_entry(self):
        self.ensure_one()
        if self.dataset_type != 'actual':
            raise ValidationError('Entry templates are available for Actual years only.')
        self._ensure_forecast_expense_structure()
        self._prepare_actual_entry_rows()
        self.env['school.financial.report']._refresh_for_academic_years(self.ids)
        return self._workspace_action()

    def action_apply_actual_payroll_months(self):
        self.ensure_one()
        if self.dataset_type != 'actual' or not 0 <= self.actual_payroll_months <= 12:
            raise ValidationError('Select an Actual year and payroll months between 0 and 12.')
        self.employment_salary_ids.with_context(defer_school_financial_refresh=True).write({'months_paid': self.actual_payroll_months})
        self.env['school.financial.report']._refresh_for_academic_years(self.ids)
        return self._workspace_action()

    def action_apply_actual_fee_tax(self):
        self.ensure_one()
        if self.dataset_type != 'actual' or not 0 <= self.actual_fee_tax_percent <= 100:
            raise ValidationError('Select an Actual year and fee tax between 0 and 100.')
        self.fee_value_ids.with_context(defer_school_financial_refresh=True).write({'actual_tax_percent': self.actual_fee_tax_percent})
        self.env['school.financial.report']._refresh_for_academic_years(self.ids)
        return self._workspace_action()

    @api.depends('school_id.tax_rule_ids', 'school_id.tax_rule_ids.name', 'school_id.tax_rule_ids.percentage')
    def _compute_actual_used_taxes(self):
        for year in self:
            year.actual_used_tax_rule_ids = year.school_id.tax_rule_ids

    @api.constrains('school_id', 'actual_fee_tax_rule_ids')
    def _check_actual_fee_tax_school(self):
        for year in self:
            if any(tax.school_id != year.school_id for tax in year.actual_fee_tax_rule_ids):
                raise ValidationError('Fee tax types must belong to the current school.')

    @api.onchange('actual_fee_type_id', 'actual_fee_grade_ids')
    def _onchange_actual_fee_entry(self):
        for year in self:
            rows = year.fee_value_ids.filtered(lambda row: row.fee_type_id == year.actual_fee_type_id and (
                not year.actual_fee_grade_ids or row.grade_level_id in year.actual_fee_grade_ids))
            year.actual_fee_amount = rows[0].amount if rows and len(set(rows.mapped('amount'))) == 1 else 0
            year.actual_fee_tax_rule_ids = rows[0].actual_tax_rule_ids if rows and all(row.actual_tax_rule_ids == rows[0].actual_tax_rule_ids for row in rows) else self.env['school.tax.rules']

    def action_apply_actual_fee(self):
        self.ensure_one()
        if self.dataset_type != 'actual' or not self.actual_fee_type_id or self.actual_fee_type_id.school_id != self.school_id:
            raise ValidationError("Select a fee belonging to this Actual year's school.")
        if self.actual_fee_amount < 0 or any(grade.school_id != self.school_id for grade in self.actual_fee_grade_ids):
            raise ValidationError('Fee amounts cannot be negative and selected grades must belong to this school.')
        self._prepare_actual_entry_rows()
        rows = self.fee_value_ids.filtered(lambda row: row.fee_type_id == self.actual_fee_type_id and (
            not self.actual_fee_grade_ids or row.grade_level_id in self.actual_fee_grade_ids))
        rows.with_context(defer_school_financial_refresh=True).write({'amount': self.actual_fee_amount,
            'actual_tax_rule_ids': [fields.Command.set(self.actual_fee_tax_rule_ids.ids)]})
        self.env['school.financial.report']._refresh_for_academic_years(self.ids)
        return False

    @api.onchange('actual_expense_category_id')
    def _onchange_actual_expense_category(self):
        for year in self:
            if year.actual_expense_item_id.expense_category_id != year.actual_expense_category_id:
                year.actual_expense_item_id = False
            year._onchange_actual_expense_item()

    @api.onchange('actual_expense_item_id', 'operating_expense_ids')
    def _onchange_actual_expense_item(self):
        for year in self:
            if year.actual_expense_item_id:
                year.actual_expense_category_id = year.actual_expense_item_id.expense_category_id
            year.actual_expense_amount = sum(year.operating_expense_ids.filtered(
                lambda row: row.expense_category_id == year.actual_expense_category_id and row.expense_item_id == year.actual_expense_item_id).mapped('amount'))

    def action_apply_actual_expense(self):
        self.ensure_one()
        item = self.actual_expense_item_id
        category = self.actual_expense_category_id
        if not category or category.school_id != self.school_id or category.cost_bucket != 'operating':
            raise ValidationError('Select an expense category belonging to this school.')
        if item and category != item.expense_category_id:
            raise ValidationError('Select an expense item belonging to the selected category.')
        if self.actual_expense_amount < 0:
            raise ValidationError('Annual expense amounts cannot be negative.')
        rows = self.operating_expense_ids.filtered(lambda row: row.expense_category_id == category and row.expense_item_id == item)
        if len(rows) > 1:
            raise ValidationError('This item has multiple expense entries. Edit their amounts in Expense Details.')
        if rows:
            rows.amount = self.actual_expense_amount
        else:
            self.env['school.expense.values'].create({'academic_year_id': self.id, 'expense_category_id': category.id, 'expense_item_id': item.id,
                'amount': self.actual_expense_amount, 'cost_bucket': 'operating'})
        return False

    def _actual_expense_setup_action(self, setup):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(f'school_planning.action_school_{setup}')
        context = dict(self.env.context, default_school_id=self.school_id.id, default_display_order=10,
                       default_academic_year_id=self.id,
                       searchpanel_default_school_id=self.school_id.id)
        if setup == 'expense_items' and self.actual_expense_category_id:
            context.update(default_expense_category_id=self.actual_expense_category_id.id,
                           search_default_expense_category_id=self.actual_expense_category_id.id)
        action.update({'target': 'new', 'domain': [('school_id', '=', self.school_id.id)], 'context': context,
            'views': [(self.env.ref(f'school_planning.view_school_{setup}_tree').id, 'list'),
                      (self.env.ref(f'school_planning.view_school_{setup}_form').id, 'form')]})
        return action

    def action_open_actual_expense_categories(self):
        return self._actual_expense_setup_action('expense_categories')

    def action_open_actual_expense_items(self):
        return self._actual_expense_setup_action('expense_items')

    def action_open_actual_tax_types(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('school_planning.action_school_tax_rules')
        action.update({'target': 'new', 'context': dict(self.env.context, default_school_id=self.school_id.id),
                   'domain': [('school_id', '=', self.school_id.id)]})
        return action

    @api.onchange('employment_salary_ids')
    def _onchange_actual_payroll_detail(self):
        for year in self.filtered(lambda record: record.dataset_type == 'actual' and record.payroll_summary_enabled):
            if any(not row._origin or any(row[name] != row._origin[name] for name in (
                'actual_employee_count', 'monthly_salary', 'months_paid', 'bonus', 'staff_position_id')) for row in year.employment_salary_ids):
                year.payroll_summary_enabled = False
                year.payroll_status = 'in_progress'

    def _actual_tool_action(self, group):
        self.ensure_one()
        if self.dataset_type != 'actual':
            raise ValidationError('Select an Actual year to open Actual entry tools.')
        selected = self[f'actual_{group}_tool']
        if selected not in dict(ACTUAL_TOOLS[group]):
            raise ValidationError('Select an entry tool.')
        action = self.env['ir.actions.actions']._for_xml_id(f'school_planning.action_school_{selected}')
        model = self.env[action['res_model']]
        context = {'default_school_id': self.school_id.id, 'default_dataset_type': 'actual',
                   'default_academic_year_id': self.id, 'searchpanel_default_school_id': self.school_id.id,
                   'searchpanel_default_dataset_type': 'actual'}
        if model._name == 'school.academic.years':
            action['domain'] = [('school_id', '=', self.school_id.id), ('dataset_type', '=', 'actual')]
            action['views'] = [(self.env.ref('school_planning.view_school_actual_years_list').id, 'list'),
                               (self.env.ref('school_planning.view_school_year_workspace').id, 'form')]
        elif 'academic_year_id' in model._fields:
            action['domain'] = [('academic_year_id', '=', self.id)]
        elif model._name == 'school.room.template.items':
            action['domain'] = [('room_template_id.school_id', '=', self.school_id.id)]
        elif 'school_id' in model._fields:
            action['domain'] = [('school_id', '=', self.school_id.id)]
        action['context'] = context
        if group != 'setup' and selected not in ('fee_values_revenue_chart', 'expense_values_pie_chart'):
            view = self.env.ref(f'school_planning.view_school_{selected}_tree', raise_if_not_found=False)
            action['view_mode'] = 'list,form'
            action['views'] = [(view.id if view else False, 'list'), (False, 'form')]
        return action

    def action_actual_planning_tool(self):
        return self._actual_tool_action('planning')

    def action_actual_financial_tool(self):
        return self._actual_tool_action('financial')

    def action_actual_asset_tool(self):
        return self._actual_tool_action('asset')

    def action_actual_setup_tool(self):
        return self._actual_tool_action('setup')

    def _ensure_forecast_expense_structure(self):
        for actual in self.filtered(lambda year: year.dataset_type == 'actual' and year.forecast_year_id):
            existing = {(row.expense_category_id.id, row.expense_item_id.id, row.cost_bucket) for row in actual.expense_value_ids}
            values = []
            for row in actual.forecast_year_id.expense_value_ids:
                key = (row.expense_category_id.id, row.expense_item_id.id, row.cost_bucket)
                if key not in existing:
                    existing.add(key)
                    values.append({'academic_year_id': actual.id, 'expense_category_id': key[0],
                                   'expense_item_id': key[1], 'cost_bucket': key[2], 'amount': 0})
            if values:
                self.env['school.expense.values'].with_context(actual_structure_only=True, defer_school_financial_refresh=True).create(values)

    def action_open_actual(self):
        return self._ensure_actual_year()._workspace_action()

    def action_open_forecast(self):
        self.ensure_one()
        return self._workspace_action()

    def action_view_baseline(self):
        self.ensure_one()
        return (self.forecast_year_id or self)._workspace_action()

    def action_open_comparison(self):
        self.ensure_one()
        forecast = self.forecast_year_id if self.dataset_type == 'actual' else self
        if not forecast or forecast.dataset_type != 'forecast':
            raise ValidationError('Select a Forecast or an Actual year linked to a Forecast.')
        return self.env['school.forecast.comparison'].create({'school_id': self.school_id.id, 'forecast_year_id': forecast.id})._action()

    def action_classify_forecast(self):
        if any(year.dataset_type != 'legacy' for year in self):
            raise ValidationError('Only unclassified historical years can be adopted as Forecast.')
        self.write({'dataset_type': 'forecast'})
        return self._workspace_action()

    def action_classify_actual(self):
        if any(year.dataset_type != 'legacy' for year in self):
            raise ValidationError('Only unclassified historical years can be adopted as Actual.')
        for year in self:
            for salary in year.employment_salary_ids:
                salary.actual_employee_count = salary.employee_count
            for fee in year.fee_value_ids:
                fee.actual_tax_percent = fee.fee_type_id.tax_rule_id.percentage * 100 if fee.fee_type_id.is_taxable else 0
        self.write({'dataset_type': 'actual'})
        for year in self:
            for rows in (year.enrollment_ids, year.fee_value_ids, year.expense_value_ids,
                 year.employment_salary_ids, year.room_plan_ids, year.asset_price_ids):
                rows._update_actual_progress()
        return self._workspace_action()

    def action_complete_actual(self):
        self.ensure_one()
        if self.dataset_type != 'actual':
            raise ValidationError('Only Actual entry can be marked complete.')
        self.write({f'{section}_status': 'complete' for section in ('enrollment', 'income', 'expenses', 'payroll', 'assets', 'teaching')})
        return self._workspace_action()


class Schools(models.Model):
    _inherit = 'school.schools'

    def action_open_actuals(self):
        self.ensure_one()
        forecasts = self.env['school.academic.years'].search([('school_id', '=', self.id), ('dataset_type', '=', 'forecast')])
        for forecast in forecasts:
            forecast._ensure_actual_year()
        return {'type': 'ir.actions.act_window', 'name': f'{self.name} - Actuals', 'res_model': 'school.academic.years',
                'view_mode': 'list,form', 'domain': [('school_id', '=', self.id), ('dataset_type', '=', 'actual')],
                'context': {'default_school_id': self.id, 'default_dataset_type': 'actual'},
                'views': [(self.env.ref('school_planning.view_school_actual_years_list').id, 'list'),
                          (self.env.ref('school_planning.view_school_year_workspace').id, 'form')]}

    def action_open_comparison(self):
        self.ensure_one()
        forecast = self.env['school.academic.years'].search([('school_id', '=', self.id), ('dataset_type', '=', 'forecast')], order='start_date', limit=1)
        return self.env['school.forecast.comparison'].create({'school_id': self.id, 'forecast_year_id': forecast.id})._action()

    def action_open_quick_prediction(self):
        self.ensure_one()
        if not self.subject_ids:
            raise ValidationError('Configure subjects for this school before starting a prediction.')
        action = self.env['ir.actions.actions']._for_xml_id('school_planning.action_school_prediction_quick_setup_wizard')
        action['context'] = {'default_school_id': self.id}
        return action

    def action_open_financial_summary(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('school_planning.action_school_financial_summary')
        action['domain'] = [('school_id', '=', self.id)]
        action['context'] = {'default_school_id': self.id}
        action['view_mode'] = 'list,form'
        action['views'] = [(self.env.ref('school_planning.view_school_academic_years_financial_summary_tree').id, 'list'),
                           (self.env.ref('school_planning.view_school_year_workspace').id, 'form')]
        return action


class YearInputGuard(models.AbstractModel):
    _name = 'school.year.input.guard'
    _description = 'Approved Forecast Input Protection'

    def _check_unlocked_years(self, years):
        if any(year.baseline_locked for year in years):
            raise ValidationError('Inputs of an approved forecast cannot be changed. Enter actuals in the separate Actual year.')

    def _refresh_year_reports(self, years):
        if self._name in ('school.subject.distribution', 'school.grade.enrollment'):
            for year in years.filtered(lambda year: year.uses_american_timetable and year.dataset_type == 'forecast'):
                year._sync_efficiency_teaching()
        self.env['school.financial.report']._refresh_for_academic_years(years.ids)

    def _check_school_references(self):
        for record in self:
            year = record.academic_year_id
            for name in ('grade_level_id', 'fee_type_id', 'expense_category_id', 'expense_item_id', 'staff_position_id', 'subject_id', 'room_type_id', 'asset_item_id'):
                if name in record._fields and record[name] and record[name].school_id != year.school_id:
                    raise ValidationError('All inputs must belong to the same school as the selected year.')

    def _update_actual_progress(self, changed_fields=None):
        if self.env.context.get('actual_structure_only'):
            return
        inputs = {'school.grade.enrollment': {'student_count', 'grade_level_id'},
                  'school.fee.values': {'amount', 'actual_tax_percent', 'actual_tax_rule_ids', 'actual_applicability', 'actual_selected_students', 'fee_type_id', 'grade_level_id'},
                  'school.expense.values': {'amount', 'cost_bucket', 'expense_category_id', 'expense_item_id'},
                  'school.employment.salaries': {'actual_employee_count', 'monthly_salary', 'months_paid', 'bonus', 'staff_position_id'},
                  'school.room.plan': {'existing_rooms', 'manual_new_rooms', 'room_type_id'},
                  'school.asset.prices': {'unit_price', 'asset_item_id', 'planning_seed_quantity', 'planning_seed_basis'},
                  'school.asset.transactions': {'asset_item_id', 'transaction_type', 'quantity', 'transaction_date', 'notes'},
                  'school.expansion.projects': {'name', 'description', 'start_date', 'end_date', 'project_room_ids'},
                  'school.expansion.project.rooms': {'expansion_project_id', 'room_type_id', 'room_count'},
                  'school.staffing.overrides': {'staff_position_id', 'employee_count'},
                  'school.subject.distribution': {'grade_level_id', 'subject_id', 'weekly_hours', 'credits', 'choice_subject_ids'}}
        if changed_fields is not None and not inputs.get(self._name, set()).intersection(changed_fields):
            return
        sections = {'school.grade.enrollment': 'enrollment', 'school.fee.values': 'income',
                    'school.expense.values': 'expenses', 'school.employment.salaries': 'payroll',
                    'school.room.plan': 'assets', 'school.asset.prices': 'assets', 'school.asset.transactions': 'assets',
                    'school.expansion.projects': 'assets', 'school.expansion.project.rooms': 'assets',
                    'school.staffing.overrides': 'payroll', 'school.subject.distribution': 'teaching'}
        section = sections.get(self._name)
        if not section:
            return
        for year in self.mapped('academic_year_id').filtered(lambda year: year.dataset_type == 'actual'):
            touched = {section}
            if self._name == 'school.expense.values':
                touched = {'payroll' if row.cost_bucket == 'employee' else 'expenses' for row in self.filtered(lambda row: row.academic_year_id == year)}
            updates = {f'{name}_status': 'in_progress' for name in touched if year[f'{name}_status'] == 'not_started'}
            if self._name == 'school.employment.salaries' and year.payroll_summary_enabled:
                updates['payroll_summary_enabled'] = False
            if self._name == 'school.staffing.overrides':
                for override in self.filtered(lambda row: row.academic_year_id == year):
                    rows = year.employment_salary_ids.filtered(lambda row: row.staff_position_id == override.staff_position_id)
                    if not rows:
                        continue
                    weights = [max(row.actual_employee_count, 0) for row in rows]
                    if not sum(weights):
                        weights = [1] * len(rows)
                    denominator = sum(weights)
                    counts = [override.employee_count * weight // denominator for weight in weights]
                    order = sorted(range(len(rows)), key=lambda index: (-(override.employee_count * weights[index] % denominator), index))
                    for index in order[:override.employee_count - sum(counts)]:
                        counts[index] += 1
                    for row, count in zip(rows, counts):
                        row.with_context(defer_school_financial_refresh=True).actual_employee_count = count
            if updates:
                year.write(updates)

    @api.model_create_multi
    def create(self, vals_list):
        years = self.env['school.academic.years'].browse([values.get('academic_year_id') or self.env.context.get('default_academic_year_id') for values in vals_list if values.get('academic_year_id') or self.env.context.get('default_academic_year_id')])
        self._check_unlocked_years(years)
        records = super().create(vals_list)
        records._check_unlocked_years(records.mapped('academic_year_id'))
        records._check_school_references()
        if not self.env.context.get('actual_structure_only'):
            records._update_actual_progress()
        records._refresh_year_reports(records.mapped('academic_year_id'))
        return records

    def write(self, values):
        years = self.mapped('academic_year_id')
        self._check_unlocked_years(years)
        if values.get('academic_year_id'):
            self._check_unlocked_years(self.env['school.academic.years'].browse(values['academic_year_id']))
        result = super().write(values)
        self._check_school_references()
        self._update_actual_progress(values)
        self._refresh_year_reports(years | self.mapped('academic_year_id'))
        return result

    def unlink(self):
        self._check_unlocked_years(self.mapped('academic_year_id'))
        years = self.mapped('academic_year_id')
        result = super().unlink()
        self._refresh_year_reports(years)
        return result


class Enrollment(models.Model):
    _name = 'school.grade.enrollment'
    _inherit = ['school.grade.enrollment', 'school.year.input.guard']


class Fees(models.Model):
    _name = 'school.fee.values'
    _inherit = ['school.fee.values', 'school.year.input.guard']

    actual_tax_percent = fields.Float(string='Actual Tax %')
    dataset_type = fields.Selection(related='academic_year_id.dataset_type')
    school_id = fields.Many2one(related='academic_year_id.school_id')
    actual_tax_rule_ids = fields.Many2many('school.tax.rules', 'school_actual_fee_tax_rel', 'fee_value_id', 'tax_rule_id', string='Tax Types')
    actual_applicability = fields.Selection([('all', 'All Enrolled Students'), ('selected', 'Selected Students')], default='all', required=True, string='Fee Applies To')
    actual_selected_students = fields.Integer(string='Selected Students', default=0)
    actual_effective_tax_percent = fields.Float(string='Total Tax %', compute='_compute_effective_tax')

    @api.depends('actual_tax_rule_ids.percentage', 'actual_tax_percent')
    def _compute_effective_tax(self):
        for row in self:
            row.actual_effective_tax_percent = sum(row.actual_tax_rule_ids.mapped('percentage')) * 100 if row.actual_tax_rule_ids else row.actual_tax_percent

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            fee_type = self.env['school.fee.types'].browse(values.get('fee_type_id')).exists()
            if fee_type and fee_type.is_optional:
                values.setdefault('actual_applicability', 'selected')
        return super().create(vals_list)

    @api.onchange('fee_type_id')
    def _onchange_actual_fee_type(self):
        for row in self:
            row.actual_applicability = 'selected' if row.fee_type_id.is_optional else 'all'
            row.actual_selected_students = 0

    @api.onchange('actual_tax_rule_ids')
    def _onchange_tax_types(self):
        self.actual_tax_percent = 0

    def write(self, values):
        if 'actual_tax_rule_ids' in values:
            values = {**values, 'actual_tax_percent': 0}
        return super().write(values)

    @api.constrains('academic_year_id', 'actual_selected_students', 'actual_applicability', 'actual_tax_rule_ids', 'actual_tax_percent')
    def _check_actual_fee_inputs(self):
        for row in self:
            if any(tax.school_id != row.academic_year_id.school_id for tax in row.actual_tax_rule_ids):
                raise ValidationError('Fee tax types must belong to the current school.')
        for row in self.filtered(lambda record: record.dataset_type == 'actual'):
            if row.actual_selected_students < 0 or not 0 <= row.actual_effective_tax_percent <= 100:
                raise ValidationError('Participating students cannot be negative and combined fee tax must be between 0 and 100%.')

    @api.depends('academic_year_id.dataset_type', 'academic_year_id.enrollment_ids.student_count', 'grade_level_id', 'amount', 'actual_tax_percent',
                 'fee_type_id.is_taxable', 'fee_type_id.tax_rule_id.percentage', 'actual_tax_rule_ids.percentage', 'actual_applicability', 'actual_selected_students')
    def _compute_revenue_metrics(self):
        actuals = self.filtered(lambda row: row.academic_year_id.dataset_type == 'actual')
        super(Fees, self - actuals)._compute_revenue_metrics()
        for row in actuals:
            enrollment = row.academic_year_id.enrollment_ids.filtered(lambda enrollment: enrollment.grade_level_id == row.grade_level_id)[:1]
            row.enrolled_students = row.actual_selected_students if row.actual_applicability == 'selected' else (enrollment.student_count if enrollment else 0)
            row.gross_revenue_amount = row.amount * row.enrolled_students
            row.tax_amount = row.gross_revenue_amount * row.actual_effective_tax_percent / 100
            row.revenue_amount = row.gross_revenue_amount - row.tax_amount

    @api.constrains('actual_tax_percent')
    def _check_actual_tax(self):
        if any(not 0 <= row.actual_tax_percent <= 100 for row in self):
            raise ValidationError('Actual Tax % must be between 0 and 100.')


class Expenses(models.Model):
    _name = 'school.expense.values'
    _inherit = ['school.expense.values', 'school.year.input.guard']
    _order = 'expense_category_id, expense_item_id, id'

    cost_bucket = fields.Selection([('operating', 'Operating Expenses'), ('employee', 'Employee Costs')], required=True, default='operating')
    expense_category_id = fields.Many2one('school.expense.categories', string='Category', required=True, ondelete='cascade')
    total_contribution = fields.Float(string='Included in Total', compute='_compute_total_contribution', store=True)

    @api.depends('amount', 'expense_category_id', 'expense_item_id', 'cost_bucket',
                 'academic_year_id.expense_value_ids.amount', 'academic_year_id.expense_value_ids.expense_category_id',
                 'academic_year_id.expense_value_ids.expense_item_id', 'academic_year_id.expense_value_ids.cost_bucket')
    def _compute_total_contribution(self):
        category_totals = {}
        for row in self.mapped('academic_year_id.expense_value_ids').filtered(lambda record: not record.expense_item_id):
            key = (row.academic_year_id.id, row.expense_category_id.id, row.cost_bucket)
            category_totals[key] = category_totals.get(key, 0) + row.amount
        for row in self:
            key = (row.academic_year_id.id, row.expense_category_id.id, row.cost_bucket)
            row.total_contribution = 0 if row.expense_item_id and category_totals.get(key) else row.amount

    def _category_amount_total(self):
        totals = {}
        for row in self:
            key = (row.academic_year_id.id, row.expense_category_id.id, row.cost_bucket)
            amounts = totals.setdefault(key, {'category': 0, 'items': 0})
            amounts['items' if row.expense_item_id else 'category'] += row.amount
        return sum(amounts['category'] or amounts['items'] for amounts in totals.values())

    @api.model_create_multi
    def create(self, vals_list):
        values_list = []
        for values in vals_list:
            values = dict(values)
            if values.get('expense_item_id') and not values.get('expense_category_id'):
                values['expense_category_id'] = self.env['school.expense.items'].browse(values['expense_item_id']).expense_category_id.id
            if values.get('expense_category_id') and 'cost_bucket' not in values:
                values['cost_bucket'] = self.env['school.expense.categories'].browse(values['expense_category_id']).cost_bucket
            values_list.append(values)
        records = super().create(values_list)
        records._ensure_optional_expense_items()
        records._sync_actual_expense_structure()
        records._sync_payroll_expense_amounts()
        return records

    def write(self, values):
        values = dict(values)
        if values.get('expense_item_id') and 'expense_category_id' not in values:
            values['expense_category_id'] = self.env['school.expense.items'].browse(values['expense_item_id']).expense_category_id.id
        result = super().write(values)
        if {'academic_year_id', 'expense_category_id', 'expense_item_id', 'cost_bucket'} & values.keys():
            self._sync_actual_expense_structure()
        if {'amount', 'cost_bucket', 'expense_category_id', 'expense_item_id'} & values.keys():
            self._sync_payroll_expense_amounts()
        return result

    def unlink(self):
        years = self.filtered(lambda row: row.cost_bucket == 'employee').mapped('academic_year_id')
        result = super().unlink()
        if not self.env.context.get('defer_school_financial_refresh'):
            for year in years.filtered('payroll_summary_enabled'):
                year.write({'payroll_basis': 'amount', 'payroll_fixed_amount': year.payroll_expense_ids._category_amount_total()})
        return result

    def _sync_payroll_expense_amounts(self):
        if self.env.context.get('actual_structure_only') or self.env.context.get('defer_school_financial_refresh'):
            return
        years = self.filtered(lambda row: row.cost_bucket == 'employee').mapped('academic_year_id')
        for year in years.filtered('payroll_summary_enabled'):
            year.write({'payroll_basis': 'amount', 'payroll_fixed_amount': year.payroll_expense_ids._category_amount_total()})

    def _sync_actual_expense_structure(self):
        years = self.mapped('academic_year_id').filtered(lambda year: year.dataset_type == 'forecast')
        for year in years.filtered(lambda record: not record.actual_year_ids):
            actual = self.env['school.academic.years'].search([
                ('school_id', '=', year.school_id.id), ('dataset_type', '=', 'actual'), ('forecast_year_id', '=', False),
                ('start_date', '=', year.start_date), ('end_date', '=', year.end_date),
                ('academic_year_name', '=', year.academic_year_name),
            ], limit=1)
            if actual:
                actual.write({'forecast_year_id': year.id})
        years.mapped('actual_year_ids')._ensure_forecast_expense_structure()

    def _ensure_optional_expense_items(self):
        for row in self.filtered(lambda record: not record.expense_item_id):
            year = row.academic_year_id
            missing = row.expense_category_id.expense_item_ids - year.expense_value_ids.mapped('expense_item_id')
            if missing:
                self.with_context(actual_structure_only=True).create([
                    {'academic_year_id': year.id, 'expense_category_id': row.expense_category_id.id,
                     'expense_item_id': item.id, 'cost_bucket': row.cost_bucket, 'amount': 0,
                     'prediction_input_mode': row.prediction_input_mode} for item in missing
                ])

    @api.onchange('expense_item_id')
    def _onchange_expense_item_category(self):
        for row in self.filtered('expense_item_id'):
            row.expense_category_id = row.expense_item_id.expense_category_id

    @api.constrains('expense_category_id', 'expense_item_id')
    def _check_expense_category(self):
        if any(row.expense_item_id and row.expense_item_id.expense_category_id != row.expense_category_id for row in self):
            raise ValidationError('Expense items must belong to the selected category.')


class ActualFeeTypes(models.Model):
    _inherit = 'school.fee.types'

    is_optional = fields.Boolean(string='Optional / Participating Students Only', default=False)


class ActualTaxTypes(models.Model):
    _inherit = 'school.tax.rules'

    @api.constrains('school_id', 'percentage')
    def _check_tax_rates_and_assignments(self):
        if any(not 0 <= tax.percentage <= 1 for tax in self):
            raise ValidationError('Tax type rates must be between 0 and 100%.')
        self.env['school.fee.values'].search([('actual_tax_rule_ids', 'in', self.ids)])._check_actual_fee_inputs()
        self.env['school.fee.types'].search([('tax_rule_id', 'in', self.ids)])._check_tax_school()
        self.env['school.academic.years'].search([('actual_fee_tax_rule_ids', 'in', self.ids)])._check_actual_fee_tax_school()


class Salaries(models.Model):
    _name = 'school.employment.salaries'
    _inherit = ['school.employment.salaries', 'school.year.input.guard']

    actual_employee_count = fields.Integer(string='Actual Employees')
    dataset_type = fields.Selection(related='academic_year_id.dataset_type')

    @api.depends('academic_year_id.dataset_type', 'staff_position_id', 'actual_employee_count')
    def _compute_employee_count(self):
        actuals = self.filtered(lambda row: row.academic_year_id.dataset_type == 'actual')
        super(Salaries, self - actuals)._compute_employee_count()
        for row in actuals:
            row.employee_count = row.actual_employee_count

    @api.constrains('actual_employee_count', 'months_paid', 'monthly_salary', 'bonus')
    def _check_actual_payroll(self):
        if any(row.academic_year_id.dataset_type == 'actual' and (row.actual_employee_count < 0 or row.months_paid < 0 or row.monthly_salary < 0 or row.bonus < 0) for row in self):
            raise ValidationError('Actual payroll inputs cannot be negative.')


class Staffing(models.Model):
    _name = 'school.staffing.overrides'
    _inherit = ['school.staffing.overrides', 'school.year.input.guard']

    @api.constrains('employee_count')
    def _check_headcount(self):
        if any(row.employee_count < 0 for row in self):
            raise ValidationError('Employee count cannot be negative.')


class Subjects(models.Model):
    _name = 'school.subject.distribution'
    _inherit = ['school.subject.distribution', 'school.year.input.guard']


class Rooms(models.Model):
    _name = 'school.room.plan'
    _inherit = ['school.room.plan', 'school.year.input.guard']


class AssetPrices(models.Model):
    _name = 'school.asset.prices'
    _inherit = ['school.asset.prices', 'school.year.input.guard']


class AssetTransactions(models.Model):
    _name = 'school.asset.transactions'
    _inherit = ['school.asset.transactions', 'school.year.input.guard']


class ExpansionProjects(models.Model):
    _name = 'school.expansion.projects'
    _inherit = ['school.expansion.projects', 'school.year.input.guard']

    project_room_ids = fields.One2many('school.expansion.project.rooms', 'expansion_project_id')
    school_id = fields.Many2one(related='academic_year_id.school_id')


class ExpansionProjectRooms(models.Model):
    _name = 'school.expansion.project.rooms'
    _inherit = ['school.expansion.project.rooms', 'school.year.input.guard']

    academic_year_id = fields.Many2one(related='expansion_project_id.academic_year_id')


class FinancialReport(models.Model):
    _inherit = 'school.financial.report'

    dataset_type = fields.Selection(related='academic_year_id.dataset_type', store=True, index=True)


class QuickPrediction(models.TransientModel):
    _inherit = 'school.prediction.quick.setup.wizard'

    def action_apply(self):
        result = super(QuickPrediction, self.with_context(defer_school_financial_refresh=True)).action_apply()
        self.env['school.financial.report']._refresh_for_academic_years(self._existing_forecast_years().ids)
        return result


class ForecastComparison(models.TransientModel):
    _name = 'school.forecast.comparison'
    _description = 'Forecast Versus Actual'
    _rec_name = 'name'

    name = fields.Char(compute='_compute_name')
    school_id = fields.Many2one('school.schools', required=True)
    forecast_year_id = fields.Many2one('school.academic.years', string='Academic Year')
    actual_year_id = fields.Many2one('school.academic.years', compute='_compute_actual_year')
    baseline_locked = fields.Boolean(related='forecast_year_id.baseline_locked')
    actual_status = fields.Selection(related='actual_year_id.actual_status')
    currency_id = fields.Many2one(related='school_id.currency_id')
    line_ids = fields.One2many('school.forecast.comparison.line', 'wizard_id')

    @api.depends('school_id.name', 'forecast_year_id.academic_year_name')
    def _compute_name(self):
        for wizard in self:
            wizard.name = f'Forecast vs Actual | {wizard.forecast_year_id.academic_year_name or "Select Year"} | {wizard.school_id.name}'

    @api.depends('forecast_year_id', 'forecast_year_id.actual_year_ids')
    def _compute_actual_year(self):
        for wizard in self:
            wizard.actual_year_id = wizard.forecast_year_id.actual_year_ids[:1]

    @api.onchange('school_id')
    def _onchange_school(self):
        if self.forecast_year_id.school_id != self.school_id:
            self.forecast_year_id = self.env['school.academic.years'].search([('school_id', '=', self.school_id.id), ('dataset_type', '=', 'forecast')], order='start_date', limit=1)

    @api.constrains('school_id', 'forecast_year_id')
    def _check_forecast(self):
        for wizard in self:
            if wizard.forecast_year_id and (wizard.forecast_year_id.school_id != wizard.school_id or wizard.forecast_year_id.dataset_type != 'forecast'):
                raise ValidationError('Select a Forecast year belonging to this school.')

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values['line_ids'] = [fields.Command.create({'metric': metric, 'name': name, 'section': section, 'direction': direction, 'sequence': sequence})
                                  for sequence, (metric, name, section, direction) in enumerate(METRICS)]
        return super().create(vals_list)

    def _action(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Forecast vs Actual', 'res_model': self._name,
                'res_id': self.id, 'view_mode': 'form', 'target': 'current'}

    def action_enter_actual(self):
        self.ensure_one()
        if not self.forecast_year_id:
            raise ValidationError('Select a Forecast year first.')
        return self.forecast_year_id.action_open_actual()

    def _move_year(self, offset):
        self.ensure_one()
        years = self.env['school.academic.years'].search([('school_id', '=', self.school_id.id), ('dataset_type', '=', 'forecast')], order='start_date, id')
        if self.forecast_year_id in years:
            index = years.ids.index(self.forecast_year_id.id) + offset
            if 0 <= index < len(years):
                self.forecast_year_id = years[index]
        return self._action()

    def action_previous_year(self):
        return self._move_year(-1)

    def action_next_year(self):
        return self._move_year(1)


class ComparisonLine(models.TransientModel):
    _name = 'school.forecast.comparison.line'
    _description = 'Forecast Actual Variance'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('school.forecast.comparison', ondelete='cascade', required=True)
    sequence = fields.Integer()
    metric = fields.Selection([(metric, name) for metric, name, section, direction in METRICS], string='Metric Key', required=True)
    name = fields.Char(string='Metric')
    section = fields.Char()
    direction = fields.Char()
    forecast_amount = fields.Float(compute='_compute_variance', string='Forecast Numeric Value')
    actual_amount = fields.Float(compute='_compute_variance', string='Actual Numeric Value')
    difference = fields.Float(compute='_compute_variance', string='Variance Numeric Value')
    percentage = fields.Char(compute='_compute_variance', string='Variance %')
    result = fields.Char(compute='_compute_variance', string='Result')
    progress = fields.Char(compute='_compute_variance', string='Actual Status')
    actual_display = fields.Char(compute='_compute_variance', string='Actual Entered')
    difference_display = fields.Char(compute='_compute_variance', string='Actual - Forecast')
    forecast_display = fields.Char(compute='_compute_variance', string='Forecast')

    @api.depends('wizard_id.forecast_year_id', 'wizard_id.actual_year_id')
    def _compute_variance(self):
        for line in self:
            forecast = line.wizard_id.forecast_year_id
            actual = line.wizard_id.actual_year_id
            line.forecast_amount = forecast[line.metric] if forecast else 0
            line.actual_amount = actual[line.metric] if actual else 0
            line.difference = line.actual_amount - line.forecast_amount
            status = actual.actual_status if line.section == 'all' else (actual[f'{line.section}_status'] if actual else 'not_started')
            if line.section == 'income' and actual and actual.enrollment_status != 'complete':
                status = 'in_progress' if status != 'not_started' else status
            line.progress = dict(COMPLETION).get(status, 'Not Started')
            digits = 0 if line.metric == 'total_enrolled_students' else 2
            line.forecast_display = formatLang(self.env, line.forecast_amount, digits=digits)
            entered = actual and status != 'not_started'
            line.actual_display = formatLang(self.env, line.actual_amount, digits=digits) if entered else 'Not entered'
            line.difference_display = formatLang(self.env, line.difference, digits=digits) if entered else 'N/A'
            line.percentage = f'{line.difference / abs(line.forecast_amount) * 100:.1f}%' if line.forecast_amount and actual and status != 'not_started' else 'N/A'
            if not actual or status == 'not_started':
                line.result = 'Not entered'
            elif status != 'complete':
                line.result = 'Provisional'
            elif not line.difference:
                line.result = 'On target'
            elif line.direction == 'neutral':
                line.result = 'Difference'
            else:
                favorable = line.difference > 0 if line.direction == 'higher' else line.difference < 0
                line.result = 'Favorable' if favorable else 'Unfavorable'