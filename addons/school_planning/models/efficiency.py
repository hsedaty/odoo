import math
import uuid

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import formatLang


INFRASTRUCTURE = [('existing', 'Existing Classes'), ('new', 'No Existing Classes')]


class PredictionSeedConfiguration(models.Model):
    _name = 'school.prediction.seed.configuration'
    _description = 'Prediction Seed Configuration'

    name = fields.Char(default='Prediction Seeds', required=True)
    students_per_classroom = fields.Integer(default=25, required=True)
    classroom_weekly_hours = fields.Float(default=35, required=True)
    teacher_weekly_hours = fields.Float(default=20, required=True)
    infrastructure_mode = fields.Selection(INFRASTRUCTURE, default='existing', required=True)
    income_tax_percent = fields.Float(default=12)
    fee_increase_percent = fields.Float(default=5)
    salary_increase_percent = fields.Float(default=5)
    payroll_start_year_index = fields.Integer(default=1, required=True)
    payroll_trend = fields.Selection(selection=lambda self: self.env['school.prediction.quick.setup.repeating.expense.line']._fields['trend'].selection,
                                     default='revenue_decrease', required=True)
    payroll_base_annual_amount = fields.Float(default=50)
    payroll_annual_change_percent = fields.Float(default=3)
    assistant_principal_per_students = fields.Float(default=250, required=True)
    janitor_per_students = fields.Float(default=100, required=True)
    principal_fixed_count = fields.Integer(default=0)
    it_fixed_count = fields.Integer(default=0)
    admission_officer_fixed_count = fields.Integer(default=0)
    front_desk_fixed_count = fields.Integer(default=0)
    student_affairs_fixed_count = fields.Integer(default=0)
    nurse_fixed_count = fields.Integer(default=0)
    hr_fixed_count = fields.Integer(default=0)
    accountant_fixed_count = fields.Integer(default=0)
    finance_officer_fixed_count = fields.Integer(default=0)
    asset_ids = fields.One2many('school.prediction.seed.asset', 'configuration_id')
    fee_ids = fields.One2many('school.prediction.seed.fee', 'configuration_id')
    tax_ids = fields.One2many('school.prediction.seed.tax', 'configuration_id')
    staffing_seed_ids = fields.One2many('school.prediction.seed.staffing', 'configuration_id', string='Staffing Seeds')
    expense_category_ids = fields.One2many('school.prediction.seed.expense.category', 'configuration_id', string='Expense Categories')
    expense_ids = fields.One2many('school.prediction.seed.expense', 'configuration_id')
    expense_sources_merged = fields.Boolean(default=False, copy=False)

    def _default_staffing_seed_specs(self):
        self.ensure_one()
        return [
            ('principal', 'Principal', 'fixed', float(self.principal_fixed_count or 0), 20),
            ('assistant_principal', 'Assistant Principal', 'per_student', float(self.assistant_principal_per_students or 250.0), 30),
            ('it', 'IT', 'fixed', float(self.it_fixed_count or 0), 40),
            ('janitor', 'Janitor', 'per_student', float(self.janitor_per_students or 100.0), 50),
            ('admission_officer', 'Admission Officer', 'fixed', float(self.admission_officer_fixed_count or 0), 60),
            ('front_desk', 'Front Desk', 'fixed', float(self.front_desk_fixed_count or 0), 70),
            ('student_affairs', 'Student Affairs', 'fixed', float(self.student_affairs_fixed_count or 0), 80),
            ('nurse', 'Nurse', 'fixed', float(self.nurse_fixed_count or 0), 90),
            ('hr', 'HR', 'fixed', float(self.hr_fixed_count or 0), 100),
            ('accountant', 'Accountant', 'fixed', float(self.accountant_fixed_count or 0), 110),
            ('finance_officer', 'Finance Officer', 'fixed', float(self.finance_officer_fixed_count or 0), 120),
        ]

    def _ensure_staffing_seeds(self):
        for configuration in self:
            existing = {seed.code: seed for seed in configuration.staffing_seed_ids}
            for code, title, method, parameter_value, display_order in configuration._default_staffing_seed_specs():
                if code in existing:
                    continue
                self.env['school.prediction.seed.staffing'].create({
                    'configuration_id': configuration.id,
                    'code': code,
                    'title': title,
                    'calculation_method': method,
                    'parameter_value': parameter_value,
                    'display_order': display_order,
                })

    def _merge_legacy_expense_seeds(self):
        assumptions = ('cost_bucket', 'start_year_index', 'trend', 'base_annual_amount', 'annual_change_percent')
        for configuration in self.filtered(lambda record: not record.expense_sources_merged):
            groups = {}
            for seed in configuration.expense_ids:
                key = (seed.name.strip().casefold(), seed.cost_bucket)
                previous = groups.get(key)
                if previous:
                    if all(previous[name] == seed[name] for name in assumptions):
                        for item in seed.item_ids:
                            if item.name not in previous.item_ids.mapped('name'):
                                item.expense_seed_id = previous
                        seed.active = False
                    else:
                        suffix = 'Normal' if seed.input_mode == 'normal' else 'Extreme'
                        seed.name = f'{seed.name} ({suffix} {seed.id})'
                else:
                    groups[key] = seed
            for legacy in configuration.expense_category_ids:
                key = (legacy.name.strip().casefold(), 'operating')
                seed = groups.get(key)
                if not seed:
                    seed = self.env['school.prediction.seed.expense'].create({
                        'configuration_id': configuration.id, 'name': legacy.name,
                        'display_order': legacy.display_order, 'cost_bucket': 'operating', 'trend': 'stable',
                    })
                    groups[key] = seed
                for item in legacy.item_ids:
                    if not seed.item_ids.filtered(lambda row: row.name.strip().casefold() == item.name.strip().casefold()):
                        self.env['school.prediction.seed.expense.item'].create({
                            'expense_seed_id': seed.id, 'name': item.name, 'display_order': item.display_order,
                        })
            configuration.expense_sources_merged = True

    @api.constrains('students_per_classroom', 'classroom_weekly_hours', 'teacher_weekly_hours', 'income_tax_percent',
                    'assistant_principal_per_students', 'janitor_per_students',
                    'payroll_start_year_index', 'payroll_trend', 'payroll_base_annual_amount', 'payroll_annual_change_percent')
    def _check_seeds(self):
        for seed in self:
            if min(seed.students_per_classroom, seed.classroom_weekly_hours, seed.teacher_weekly_hours,
                   seed.assistant_principal_per_students, seed.janitor_per_students) <= 0 or not 0 <= seed.income_tax_percent <= 100:
                raise ValidationError('Capacities, hours, and staffing ratios must be positive; tax must be between 0 and 100.')
            if seed.payroll_start_year_index < 1 or seed.payroll_base_annual_amount < 0 or seed.payroll_annual_change_percent < 0:
                raise ValidationError('Payroll seed assumptions must be positive; annual change cannot be negative.')
            if seed.payroll_trend.startswith('revenue_') and seed.payroll_base_annual_amount > 100:
                raise ValidationError('Payroll revenue percentage must be between 0 and 100.')

    def _wizard_values(self):
        self.ensure_one()
        self._ensure_staffing_seeds()
        values = {name: self[name] for name in (
            'classroom_weekly_hours', 'infrastructure_mode', 'income_tax_percent', 'fee_increase_percent', 'salary_increase_percent',
            'assistant_principal_per_students', 'janitor_per_students', 'principal_fixed_count', 'it_fixed_count',
            'admission_officer_fixed_count', 'front_desk_fixed_count', 'student_affairs_fixed_count', 'nurse_fixed_count',
            'hr_fixed_count', 'accountant_fixed_count', 'finance_officer_fixed_count')}
        seed_map = {seed.code: seed for seed in self.staffing_seed_ids}
        for code, field_name in (
            ('assistant_principal', 'assistant_principal_per_students'),
            ('janitor', 'janitor_per_students'),
            ('principal', 'principal_fixed_count'),
            ('it', 'it_fixed_count'),
            ('admission_officer', 'admission_officer_fixed_count'),
            ('front_desk', 'front_desk_fixed_count'),
            ('student_affairs', 'student_affairs_fixed_count'),
            ('nurse', 'nurse_fixed_count'),
            ('hr', 'hr_fixed_count'),
            ('accountant', 'accountant_fixed_count'),
            ('finance_officer', 'finance_officer_fixed_count'),
        ):
            seed = seed_map.get(code)
            if seed:
                values[field_name] = seed.parameter_value
        return {**values, 'max_students_per_class_input': self.students_per_classroom, 'teaching_load_hours': self.teacher_weekly_hours}

    def _expense_commands(self, mode, bucket=None):
        self.ensure_one()
        rows = self.expense_ids.filtered(lambda row: (
            not row.is_detailed_category and row.input_mode != 'detail'
            and row.trend.startswith('revenue_') and (not bucket or row.cost_bucket == bucket)
        ))
        default_rule = self.env.ref('school_planning.prediction_seed_operations', raise_if_not_found=False)
        if default_rule and default_rule in rows and len((rows - default_rule).filtered(
            lambda row: row.cost_bucket == 'operating' and row.name.strip().casefold() == 'all expenses'
        )) == 1:
            rows -= default_rule
        return [fields.Command.create({**{name: row[name] for name in (
            'name', 'cost_bucket', 'start_year_index', 'trend', 'base_annual_amount', 'annual_change_percent')},
            'seed_id': row.id, 'input_mode': mode,
            'item_templates': [{'name': item.name, 'display_order': item.display_order} for item in row.item_ids]}) for row in rows]


class PredictionFeeSeed(models.Model):
    _name = 'school.prediction.seed.fee'
    _description = 'Prediction Fee Type Seed'
    _order = 'display_order, id'

    configuration_id = fields.Many2one('school.prediction.seed.configuration', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    display_order = fields.Integer(default=10, required=True)
    is_optional = fields.Boolean(string='Participating Students Only', default=False)


class PredictionTaxSeed(models.Model):
    _name = 'school.prediction.seed.tax'
    _description = 'Prediction Tax Type Seed'
    _order = 'display_order, id'

    configuration_id = fields.Many2one('school.prediction.seed.configuration', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    display_order = fields.Integer(default=10, required=True)
    percentage = fields.Float(string='Percentage', required=True)

    _unique_name = models.Constraint('UNIQUE(configuration_id, name)', 'Tax seed names must be unique within the configuration.')

    @api.constrains('percentage')
    def _check_percentage(self):
        if any(not 0 <= seed.percentage <= 1 for seed in self):
            raise ValidationError('Tax seed rates must be between 0 and 100%.')


class PredictionStaffingSeed(models.Model):
    _name = 'school.prediction.seed.staffing'
    _description = 'Prediction Staffing Seed'
    _order = 'display_order, id'

    configuration_id = fields.Many2one('school.prediction.seed.configuration', required=True, ondelete='cascade')
    code = fields.Char(required=True)
    title = fields.Char(required=True)
    display_order = fields.Integer(default=10, required=True)
    calculation_method = fields.Selection([('fixed', 'Fixed Count'), ('per_student', '1 per N Students')], required=True, default='fixed')
    parameter_value = fields.Float(required=True, default=0.0)

    _unique_code = models.Constraint('UNIQUE(configuration_id, code)', 'Staffing seed codes must be unique within the configuration.')

    @api.constrains('code', 'parameter_value', 'calculation_method')
    def _check_values(self):
        for seed in self:
            if not (seed.code or '').strip():
                raise ValidationError('Staffing seed code is required.')
            if seed.parameter_value < 0:
                raise ValidationError('Staffing seed value cannot be negative.')
            if seed.calculation_method == 'per_student' and seed.parameter_value <= 0:
                raise ValidationError('Per-student staffing seeds must be greater than zero.')


class PredictionExpenseCategorySeed(models.Model):
    _name = 'school.prediction.seed.expense.category'
    _description = 'Expense Category Seed'
    _order = 'display_order, id'

    configuration_id = fields.Many2one('school.prediction.seed.configuration', required=True, ondelete='cascade')
    name = fields.Char(string='Category', required=True)
    display_order = fields.Integer(default=10, required=True)
    item_ids = fields.One2many('school.prediction.seed.expense.item', 'category_id', string='Expense Items')
    item_summary = fields.Char(string='Expense Items', compute='_compute_item_summary')
    item_count = fields.Integer(string='Items', compute='_compute_item_summary')

    _unique_name = models.Constraint('UNIQUE(configuration_id, name)', 'Expense category seed names must be unique within the configuration.')

    @api.depends('item_ids.name', 'item_ids.display_order')
    def _compute_item_summary(self):
        for category in self:
            category.item_count = len(category.item_ids)
            category.item_summary = ', '.join(category.item_ids.sorted('display_order').mapped('name'))


class PredictionExpenseItemSeed(models.Model):
    _name = 'school.prediction.seed.expense.item'
    _description = 'Expense Item Seed'
    _order = 'display_order, id'

    category_id = fields.Many2one('school.prediction.seed.expense.category', ondelete='cascade')
    expense_seed_id = fields.Many2one('school.prediction.seed.expense', ondelete='cascade')
    name = fields.Char(string='Expense Item', required=True)
    display_order = fields.Integer(default=10, required=True)

    _unique_name = models.Constraint('UNIQUE(category_id, name)', 'Expense item seed names must be unique within their category.')
    _unique_expense_seed_name = models.Constraint('UNIQUE(expense_seed_id, name)', 'Item seed names must be unique within their expense seed.')


class PredictionAssetSeed(models.Model):
    _name = 'school.prediction.seed.asset'
    _description = 'Prediction Asset Seed'

    configuration_id = fields.Many2one('school.prediction.seed.configuration', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    code = fields.Char()
    unit_price = fields.Float(default=0)
    quantity = fields.Integer(default=1)
    basis = fields.Selection([('student', 'Per Student'), ('classroom', 'Per Classroom')], required=True, default='classroom')

    @api.constrains('unit_price', 'quantity')
    def _check_values(self):
        if any(row.unit_price < 0 or row.quantity < 0 for row in self):
            raise ValidationError('Asset seed price and quantity cannot be negative.')


class PredictionExpenseSeed(models.Model):
    _name = 'school.prediction.seed.expense'
    _description = 'Prediction Expense Seed'
    _order = 'display_order, id'

    configuration_id = fields.Many2one('school.prediction.seed.configuration', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    display_order = fields.Integer(default=10)
    item_ids = fields.One2many('school.prediction.seed.expense.item', 'expense_seed_id', string='Optional Items')
    input_mode = fields.Selection([
        ('normal', 'Normal'), ('extreme', 'Extreme Efficiency'), ('detail', 'Comparison only'),
    ], default='extreme', required=True)
    cost_bucket = fields.Selection([('operating', 'Expenses'), ('employee', 'Payroll')], default='operating', required=True)
    is_detailed_category = fields.Boolean(string='Detailed Expense Category')
    catalog_type = fields.Selection([('expense', 'Expense'), ('income', 'Income')], required=True, default='expense')
    price_type = fields.Selection([('fixed', 'Fixed'), ('allocated', 'Allocated')], required=True, default='allocated')
    parent_id = fields.Many2one('school.prediction.seed.expense', string='Parent Category', ondelete='restrict')
    detailed_schedule_required = fields.Boolean(string='Require Payment Schedule')
    start_year_index = fields.Integer(default=1, required=True)
    end_year_index = fields.Integer(string='Last Year (0 = ongoing)')
    trend = fields.Selection(selection=lambda self: self.env['school.prediction.quick.setup.repeating.expense.line']._fields['trend'].selection,
                             default='revenue_stable', required=True)
    base_annual_amount = fields.Float()
    annual_change_percent = fields.Float()

    @api.constrains('parent_id', 'configuration_id', 'catalog_type')
    def _check_catalog_parent(self):
        if self._has_cycle():
            raise ValidationError(self.env._('Categories cannot contain a cycle.'))
        for category in self.filtered('parent_id'):
            if (category.parent_id.configuration_id != category.configuration_id
                    or category.parent_id.catalog_type != category.catalog_type
                    or not category.parent_id.is_detailed_category):
                raise ValidationError(self.env._('The parent must be a detailed category of the same type and configuration.'))

    @api.constrains('is_detailed_category', 'cost_bucket')
    def _check_detailed_category_bucket(self):
        if any(seed.is_detailed_category and seed.cost_bucket != 'operating' for seed in self):
            raise ValidationError(self.env._('Detailed expense categories must use the Expenses cost bucket.'))
        regular_seeds = self.filtered(lambda seed: not seed.is_detailed_category)
        if regular_seeds and self.env['school.prediction.operational.seed'].with_context(active_test=False).search_count([
            ('category_seed_id', 'in', regular_seeds.ids),
        ], limit=1):
            raise ValidationError(self.env._('Move the linked detailed expenses before changing this category to a regular seed.'))

    @api.constrains('base_annual_amount', 'annual_change_percent', 'start_year_index', 'end_year_index', 'trend')
    def _check_values(self):
        for row in self:
            if row.base_annual_amount < 0 or row.annual_change_percent < 0 or row.start_year_index < 1 or (row.trend.startswith('revenue_') and row.base_annual_amount > 100):
                raise ValidationError('Seed amounts and changes cannot be negative; revenue rates cannot exceed 100 and start year must be positive.')
            if row.end_year_index and row.end_year_index < row.start_year_index:
                raise ValidationError(self.env._('Last year must be at least the start year, or zero for an ongoing expense.'))


class SchoolDefaults(models.Model):
    _inherit = 'school.schools'

    default_students_per_classroom = fields.Integer(string='Students / Classroom', default=25, required=True)
    default_classroom_weekly_hours = fields.Float(string='Hours / Week / Classroom', default=35, required=True)
    default_teacher_weekly_hours = fields.Float(string='Hours / Week / Teacher', default=20, required=True)
    default_infrastructure = fields.Selection(INFRASTRUCTURE, default='existing', required=True)
    asset_seed_ids = fields.One2many('school.asset.items', 'school_id', string='Asset Defaults')

    @api.constrains('default_students_per_classroom', 'default_classroom_weekly_hours', 'default_teacher_weekly_hours')
    def _check_planning_defaults(self):
        if any(school.default_students_per_classroom <= 0 or school.default_classroom_weekly_hours <= 0 or school.default_teacher_weekly_hours <= 0 for school in self):
            raise ValidationError('Classroom capacity and weekly teaching hours must be greater than zero.')

    def _ensure_asset_seeds(self):
        self.ensure_one()
        assets = self.env['school.asset.items']
        seeded = assets
        configuration = self.env.ref('school_planning.prediction_seed_configuration')
        for sequence, seed in enumerate(configuration.asset_ids, start=1):
            key, name, basis = seed.code or f'configuration-asset-{seed.id}', seed.name, seed.basis
            asset = assets.search([('school_id', '=', self.id), ('planning_seed_key', '=', key)], limit=1)
            if not asset:
                asset = assets.search([('school_id', '=', self.id), ('name', '=ilike', name)], limit=1)
                if asset:
                    asset.write({'planning_seed_key': key, 'seed_quantity': asset.seed_quantity or 1, 'seed_basis': basis})
                else:
                    asset = assets.create({'school_id': self.id, 'name': name, 'asset_type': 'fixed',
                                           'display_order': sequence * 10, 'planning_seed_key': key,
                                           'seed_quantity': 1, 'seed_basis': basis, 'seed_unit_price': 0})
            asset.write({'seed_quantity': seed.quantity, 'seed_unit_price': seed.unit_price, 'seed_basis': seed.basis})
            seeded |= asset
        return seeded.filtered(lambda asset: asset.seed_quantity > 0)

    def action_seed_asset_defaults(self):
        self._ensure_asset_seeds()
        return self.env['ir.actions.actions']._for_xml_id('school_planning.action_school_prediction_seed_configuration')


class AssetDefaults(models.Model):
    _inherit = 'school.asset.items'

    planning_seed_key = fields.Char(copy=False)
    seed_unit_price = fields.Float(string='Default Unit Price', default=0)
    seed_quantity = fields.Integer(string='Default Quantity', default=0)
    seed_basis = fields.Selection([('student', 'Per Student'), ('classroom', 'Per Classroom')], default='classroom', required=True)

    @api.constrains('seed_unit_price', 'seed_quantity')
    def _check_asset_defaults(self):
        if any(asset.seed_unit_price < 0 or asset.seed_quantity < 0 for asset in self):
            raise ValidationError('Default asset prices and quantities cannot be negative.')


class EfficientYear(models.Model):
    _inherit = 'school.academic.years'

    students_per_classroom = fields.Integer(string='No. of Students per Classroom', default=0)
    classroom_weekly_hours = fields.Float(string='Hours / Week / Classroom', default=0)
    teacher_weekly_hours = fields.Float(string='Hours / Week / Teacher', default=0)
    infrastructure_mode = fields.Selection(INFRASTRUCTURE, default='existing', required=True)
    infrastructure_seeded = fields.Boolean(copy=False)
    required_classrooms = fields.Integer(compute='_compute_teaching_requirements', string='Calculated Classrooms')
    required_teachers = fields.Integer(compute='_compute_teaching_requirements', string='Calculated Teachers')
    teacher_requirement_details = fields.Html(
        string='Teachers by Subject', compute='_compute_teaching_requirements',
    )
    forecast_loaded = fields.Boolean(string='Forecast Inputs Loaded', readonly=True, copy=False)

    @api.onchange('school_id', 'forecast_year_id')
    def _onchange_new_year_defaults(self):
        for year in self.filtered(lambda record: not record._origin and record.school_id):
            source = year.forecast_year_id or self.env.ref('school_planning.prediction_seed_configuration')
            for name in ('students_per_classroom', 'classroom_weekly_hours', 'teacher_weekly_hours', 'infrastructure_mode'):
                year[name] = source[name]

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            school = self.env['school.schools'].browse(values.get('school_id') or self.env.context.get('default_school_id')).exists()
            baseline = self.browse(values.get('forecast_year_id')).exists()
            if school:
                seed = self.env.ref('school_planning.prediction_seed_configuration')
                for name in ('students_per_classroom', 'classroom_weekly_hours', 'teacher_weekly_hours', 'infrastructure_mode'):
                    values.setdefault(name, baseline[name] if baseline else seed[name])
        records = super().create(vals_list)
        for year in records.filtered(lambda record: record.infrastructure_mode == 'new'):
            year.with_context(actual_structure_only=True, defer_school_financial_refresh=True)._seed_infrastructure()
        self.env['school.financial.report']._refresh_for_academic_years(records.ids)
        return records

    @api.constrains('students_per_classroom', 'classroom_weekly_hours', 'teacher_weekly_hours')
    def _check_year_teaching_settings(self):
        if any(year.students_per_classroom <= 0 or year.classroom_weekly_hours <= 0 or year.teacher_weekly_hours <= 0 for year in self):
            raise ValidationError('Classroom capacity and teaching hours must be greater than zero.')

    @api.depends('dataset_type', 'uses_timetables',
                 'enrollment_ids.student_count', 'enrollment_ids.class_count', 'students_per_classroom',
                 'classroom_weekly_hours', 'teacher_weekly_hours', 'infrastructure_mode',
                 'subject_distribution_ids.weekly_hours', 'subject_distribution_ids.grade_level_id', 'subject_distribution_ids.subject_id',
                 'subject_distribution_ids.class_weekly_hours',
                 'subject_distribution_ids.subject_id.name', 'subject_distribution_ids.subject_id.display_order')
    def _compute_teaching_requirements(self):
        for year in self:
            classes = sum(year.enrollment_ids.mapped('class_count'))
            year.required_classrooms = classes
            timetable = year.uses_timetables
            year.teacher_requirement_details = False
            if (year.dataset_type != 'actual' and not timetable) or not any(year.subject_distribution_ids.mapped('weekly_hours')):
                hours = classes * year.classroom_weekly_hours
                year.required_teachers = math.ceil(hours / year.teacher_weekly_hours) if year.teacher_weekly_hours else 0
                if timetable:
                    year.teacher_requirement_details = Markup('<p>{}</p>').format(year.env._(
                        'Subject hours have not been entered. The total currently uses a classroom-hours estimate; '
                        'load the curriculum timetables to see teachers needed by subject.'
                    ))
                continue

            # Seeded timetables retain their hours and configured teacher load.
            # Other Actual curricula keep the existing 35-hour class / 20-hour teacher caps.
            class_count_by_level = {
                enrollment.grade_level_id.id: max(int(enrollment.class_count or 0), 0)
                for enrollment in year.enrollment_ids
            }
            weekly_by_level = {}
            for row in year.subject_distribution_ids:
                level_id = row.grade_level_id.id
                weekly_by_level[level_id] = weekly_by_level.get(level_id, 0.0) + max(float(row.class_weekly_hours or 0.0), 0.0)

            subject_hours = {}
            for row in year.subject_distribution_ids:
                weekly_hours = max(float(row.weekly_hours or 0.0), 0.0)
                if weekly_hours <= 0:
                    continue
                level_id = row.grade_level_id.id
                subject_id = row.subject_id.id
                classes_for_level = class_count_by_level.get(level_id, 0)
                if classes_for_level <= 0:
                    continue
                level_total = weekly_by_level.get(level_id, 0.0)
                cap_factor = 1.0 if timetable else (min(1.0, 35.0 / level_total) if level_total > 0 else 0.0)
                effective_weekly = weekly_hours * cap_factor
                subject_hours[subject_id] = subject_hours.get(subject_id, 0.0) + (effective_weekly * classes_for_level)

            teacher_load = year.teacher_weekly_hours if timetable else 20.0
            teachers_by_subject = {
                subject_id: math.ceil(hours / teacher_load)
                for subject_id, hours in subject_hours.items()
                if hours > 0
            }
            year.required_teachers = sum(teachers_by_subject.values())
            if timetable:
                year.teacher_requirement_details = year._render_teacher_requirements(subject_hours, teachers_by_subject)

    def _render_teacher_requirements(self, subject_hours, teachers_by_subject):
        self.ensure_one()
        subjects = self.subject_distribution_ids.subject_id.sorted('display_order')
        names = subjects.mapped('name')
        rows = Markup('').join(
            Markup('<tr><td>{}</td><td class="text-end">{}</td><td class="text-end">{}</td></tr>').format(
                f'{subject.name} ({subject.preset_id.curriculum_id.name})'
                if names.count(subject.name) > 1 and subject.preset_id else subject.name,
                formatLang(self.env, subject_hours.get(subject.id, 0), digits=2),
                teachers_by_subject.get(subject.id, 0),
            )
            for subject in subjects
        )
        return Markup(
            '<div class="table-responsive"><table class="table table-sm table-striped">'
            '<thead><tr><th>{}</th><th class="text-end">{}</th><th class="text-end">{}</th></tr></thead>'
            '<tbody>{}</tbody><tfoot><tr class="fw-bold"><td>{}</td>'
            '<td class="text-end">{}</td><td class="text-end">{}</td></tr></tfoot></table></div>'
        ).format(
            self.env._('Subject'), self.env._('Weekly Teaching Hours'), self.env._('Teachers Needed'),
            rows, self.env._('Total'), formatLang(self.env, sum(subject_hours.values()), digits=2),
            sum(teachers_by_subject.values()),
        )

    @api.constrains('payroll_rate', 'payroll_fixed_amount')
    def _check_summary_payroll(self):
        if any(not 0 <= year.payroll_rate <= 100 or year.payroll_fixed_amount < 0 for year in self):
            raise ValidationError('Payroll rate must be between 0 and 100, and fixed payroll cannot be negative.')

    @api.onchange('payroll_percent_input')
    def _onchange_payroll_percent(self):
        for year in self:
            percent = year.payroll_percent_input
            expected = (year.employee_cost_total / year.fee_gross_total * 100 if year.fee_gross_total else 0) if not year.payroll_summary_enabled else (
                year.payroll_rate if year.payroll_basis == 'percent' else (year.payroll_fixed_amount / year.fee_gross_total * 100 if year.fee_gross_total else 0))
            if abs(percent - expected) > 0.000001:
                if not year.payroll_summary_enabled or year.payroll_basis != 'percent':
                    year.payroll_revenue_basis = 'gross'
                year.payroll_rate = percent
                year.payroll_basis = 'percent'
                year.payroll_summary_enabled = True

    @api.onchange('payroll_amount_input')
    def _onchange_payroll_amount(self):
        for year in self:
            expected = year.employee_cost_total if not year.payroll_summary_enabled else (year._payroll_revenue_base() * year.payroll_rate / 100 if year.payroll_basis == 'percent' else year.payroll_fixed_amount)
            if abs(year.payroll_amount_input - expected) > 0.000001:
                year.payroll_fixed_amount = year.payroll_amount_input
                year.payroll_revenue_basis = 'gross'
                year.payroll_basis = 'amount'
                year.payroll_summary_enabled = True

    def write(self, values):
        child_inputs = {'enrollment_ids', 'fee_value_ids', 'employment_salary_ids', 'expense_value_ids', 'operating_expense_ids', 'payroll_expense_ids'}
        controls = ('total_students_input', 'annual_fee_input', 'payroll_percent_input', 'payroll_amount_input') if child_inputs.intersection(values) else (
            ('payroll_percent_input', 'payroll_amount_input') if {'total_students_input', 'annual_fee_input'}.intersection(values) else ())
        submitted = {name: values[name] for name in controls if name in values}
        if submitted:
            result = self.write({name: value for name, value in values.items() if name not in submitted})
            self.invalidate_recordset(list(submitted))
            for year in self:
                changes = {name: value for name, value in submitted.items() if abs(value - year[name]) > 0.000001}
                if changes:
                    year.write(changes)
            return result
        if 'payroll_percent_input' in values and 'payroll_amount_input' in values:
            values = dict(values)
            values.pop('payroll_amount_input' if values.get('payroll_basis', self[:1].payroll_basis) == 'percent' else 'payroll_percent_input')
        if {'students_per_classroom', 'infrastructure_mode'}.intersection(values) and self and all(year.dataset_type == 'actual' for year in self):
            values = {**values, 'assets_status': values.get('assets_status', 'in_progress')}
        changing_to_new = self.filtered(lambda year: year.infrastructure_mode != 'new') if values.get('infrastructure_mode') == 'new' else self.browse()
        result = super(EfficientYear, self.with_context(defer_school_financial_refresh=True)).write(values)
        if {'students_per_classroom', 'classroom_weekly_hours', 'teacher_weekly_hours', 'total_students_input'}.intersection(values):
            for year in self:
                year._sync_efficiency_teaching()
        if values.get('infrastructure_mode') == 'new':
            for year in self:
                year.with_context(defer_school_financial_refresh=True,
                                  reapply_prediction_seeds=year in changing_to_new and not values.get('asset_price_ids'))._seed_infrastructure()
        report_years = self
        if {'annual_fee_input', 'fee_value_ids'}.intersection(values):
            batches = self.filtered(lambda year: year.dataset_type == 'forecast' and year.forecast_fee_growth_batch).mapped('forecast_fee_growth_batch')
            if batches:
                report_years |= self.env['school.academic.years'].search([
                    ('dataset_type', '=', 'forecast'),
                    ('forecast_fee_growth_batch', 'in', batches),
                ])
        self.env['school.financial.report']._refresh_for_academic_years(report_years.ids)
        return result

    def _sync_efficiency_teaching(self):
        self.ensure_one()
        if self.baseline_locked or not self.students_per_classroom or not self.classroom_weekly_hours or not self.teacher_weekly_hours:
            return
        if self.dataset_type == 'forecast' and self.subject_distribution_ids and not self.uses_timetables:
            for grade in self.subject_distribution_ids.mapped('grade_level_id'):
                rows = self.subject_distribution_ids.filtered(lambda row: row.grade_level_id == grade)
                total = sum(rows.mapped('weekly_hours'))
                for row in rows:
                    row.weekly_hours = self.classroom_weekly_hours * (row.weekly_hours / total if total else 1 / len(rows))
        if self.dataset_type == 'forecast':
            positions = self.env['school.staff.positions'].search([('school_id', '=', self.school_id.id), ('planning_role', '=', 'teacher')])
            for position in positions:
                override = self.env['school.staffing.overrides'].search([('academic_year_id', '=', self.id), ('staff_position_id', '=', position.id)], limit=1)
                count = (self.required_teachers if self.uses_timetables else
                         max(self.required_teachers, len(self.school_id.subject_ids))) if self.total_enrolled_students else 0
                if override:
                    override.employee_count = count
                elif self.employment_salary_ids.filtered(lambda row: row.staff_position_id == position):
                    self.env['school.staffing.overrides'].create({'academic_year_id': self.id, 'staff_position_id': position.id, 'employee_count': count})

    def action_seed_asset_prices(self):
        self.ensure_one()
        self.with_context(reapply_prediction_seeds=True)._seed_infrastructure()
        self.env['school.financial.report']._refresh_for_academic_years(self.ids)
        return self._workspace_action()

    def _seed_infrastructure(self):
        self.ensure_one()
        if self.baseline_locked:
            raise ValidationError('An approved forecast cannot be reseeded.')
        reset_seeds = self.env.context.get('reapply_prediction_seeds')
        assets = self.school_id._ensure_asset_seeds()
        if reset_seeds:
            self.asset_price_ids.filtered(lambda row: row.planning_seed_quantity > 0 and row.asset_item_id not in assets).unlink()
        room_type = self.env['school.room.types'].search([('school_id', '=', self.school_id.id), ('planning_classroom', '=', True)], limit=1)
        if not room_type:
            room_type = self.env['school.room.types'].search([('school_id', '=', self.school_id.id), ('name', '=ilike', 'Classroom')], limit=1)
            if room_type:
                room_type.planning_classroom = True
        if not room_type:
            room_type = self.env['school.room.types'].create({'school_id': self.school_id.id, 'name': 'Classroom', 'display_order': 10, 'planning_classroom': True})
        template = self.env['school.room.templates'].search([('school_id', '=', self.school_id.id), ('room_type_id', '=', room_type.id)], limit=1)
        if not template:
            template = self.env['school.room.templates'].create({'school_id': self.school_id.id, 'room_type_id': room_type.id, 'name': 'Classroom Equipment', 'display_order': 10})
        for asset in assets:
            line = self.env['school.room.template.items'].search([('room_template_id', '=', template.id), ('asset_item_id', '=', asset.id)], limit=1)
            if not line:
                self.env['school.room.template.items'].create({'room_template_id': template.id, 'asset_item_id': asset.id, 'quantity': asset.seed_quantity})
            price = self.asset_price_ids.filtered(lambda row: row.asset_item_id == asset)
            if not price:
                self.env['school.asset.prices'].with_context(defer_school_financial_refresh=True).create({'academic_year_id': self.id, 'asset_item_id': asset.id, 'unit_price': asset.seed_unit_price,
                                                                                                      'planning_seed_quantity': asset.seed_quantity, 'planning_seed_basis': asset.seed_basis})
            elif reset_seeds or not self.infrastructure_seeded:
                values = {'planning_seed_quantity': asset.seed_quantity, 'planning_seed_basis': asset.seed_basis}
                if reset_seeds:
                    values['unit_price'] = asset.seed_unit_price
                price.with_context(defer_school_financial_refresh=True).write(values)
        plan = self.room_plan_ids.filtered(lambda row: row.room_type_id == room_type)
        if not plan or reset_seeds:
            existing = self.required_classrooms if self.infrastructure_mode == 'existing' else 0
            if plan:
                plan.with_context(defer_school_financial_refresh=True).write({'existing_rooms': existing, 'existing_rooms_manual_override': True})
            else:
                self.env['school.room.plan'].with_context(defer_school_financial_refresh=True).create({'academic_year_id': self.id, 'room_type_id': room_type.id,
                                                                                                    'existing_rooms': existing, 'existing_rooms_manual_override': True})
        self.with_context(defer_school_financial_refresh=True).write({'infrastructure_seeded': True})

    def action_load_from_forecast(self):
        self.ensure_one()
        baseline = self.forecast_year_id
        if self.dataset_type != 'actual' or not baseline:
            raise ValidationError('Load from Forecast requires an Actual year linked to a Forecast.')
        sources, pending = baseline._forecast_income_sources()
        if self.income_status == 'not_started' and (pending or any(source['kind'] == 'detailed' for source in sources)):
            raise ValidationError(self.env._(
                'Detailed forecast income cannot be allocated to Actual fee rows automatically. '
                'Enter Actual income first, then load the remaining sections from the forecast.'
            ))
        sections = [('enrollment', 'enrollment_ids', ('grade_level_id', 'student_count')),
                    ('income', 'fee_value_ids', ('grade_level_id', 'fee_type_id', 'amount')),
                    ('expenses', 'operating_expense_ids', ('expense_category_id', 'expense_item_id', 'amount', 'cost_bucket')),
                    ('assets', 'room_plan_ids', ('room_type_id', 'existing_rooms', 'manual_new_rooms', 'existing_rooms_manual_override'))]
        target = self.with_context(defer_school_financial_refresh=True)
        for section, relation, names in sections:
            if self[f'{section}_status'] != 'not_started':
                continue
            rows = baseline[relation]
            if relation == 'fee_value_ids':
                rows = baseline._forecast_tuition_rows()
            commands = [fields.Command.clear()]
            for row in rows:
                values = {name: row[name].id if row._fields[name].type == 'many2one' else row[name] for name in names}
                if relation == 'fee_value_ids':
                    values['actual_tax_percent'] = row.tax_amount / row.gross_revenue_amount * 100 if row.gross_revenue_amount else (
                        row.fee_type_id.tax_rule_id.percentage * 100 if row.fee_type_id.is_taxable else 0)
                commands.append(fields.Command.create(values))
            target.write({relation: commands, f'{section}_status': 'in_progress'})
            if section == 'assets':
                target.write({'asset_price_ids': [fields.Command.clear()] + [fields.Command.create({'asset_item_id': row.asset_item_id.id, 'unit_price': row.unit_price,
                                                                                                 'planning_seed_quantity': row.planning_seed_quantity, 'planning_seed_basis': row.planning_seed_basis}) for row in baseline.asset_price_ids],
                              'infrastructure_mode': baseline.infrastructure_mode, 'infrastructure_seeded': baseline.infrastructure_seeded})
        if self.payroll_status == 'not_started':
            salaries = [fields.Command.create({'staff_position_id': row.staff_position_id.id, 'actual_employee_count': row.employee_count,
                                               'monthly_salary': row.monthly_salary, 'months_paid': row.months_paid, 'bonus': row.bonus}) for row in baseline.employment_salary_ids]
            payroll_categories = [fields.Command.create({'expense_category_id': row.expense_category_id.id,
                'expense_item_id': row.expense_item_id.id, 'cost_bucket': 'employee', 'amount': row.amount}) for row in baseline.payroll_expense_ids]
            target.write({'employment_salary_ids': [fields.Command.clear()] + salaries,
                          'payroll_expense_ids': [fields.Command.clear()] + payroll_categories,
                          'payroll_summary_enabled': baseline.payroll_summary_enabled or baseline.employee_cost_total != baseline.salary_total,
                          'payroll_basis': 'amount', 'payroll_fixed_amount': baseline.employee_cost_total, 'payroll_status': 'in_progress'})
        if self.teaching_status == 'not_started' and baseline.subject_distribution_ids:
            target.write({'subject_distribution_ids': [fields.Command.clear()] + [fields.Command.create({'grade_level_id': row.grade_level_id.id, 'subject_id': row.subject_id.id,
                                                                             'weekly_hours': row.weekly_hours, 'credits': row.credits,
                                                                             'timetable_id': row.timetable_id.id,
                                                                             'elective_group': row.elective_group}) for row in baseline.subject_distribution_ids],
                          'teaching_status': 'in_progress'})
            target._prepare_actual_entry_rows()
        target.write({'forecast_loaded': True})
        self.env['school.financial.report']._refresh_for_academic_years(self.ids)
        return self._workspace_action()


class EfficientEnrollment(models.Model):
    _inherit = 'school.grade.enrollment'

    @api.depends('student_count', 'max_students_per_class', 'academic_year_id.students_per_classroom')
    def _compute_class_count(self):
        for row in self:
            capacity = row.academic_year_id.students_per_classroom or row.max_students_per_class
            row.class_count = math.ceil(row.student_count / capacity) if capacity and row.student_count > 0 else 0


class TeacherPosition(models.Model):
    _inherit = 'school.staff.positions'

    planning_role = fields.Selection([('teacher', 'Teacher')])


class ClassroomType(models.Model):
    _inherit = 'school.room.types'

    planning_classroom = fields.Boolean()


class EfficientRooms(models.Model):
    _inherit = 'school.room.plan'

    calculated_required_rooms = fields.Integer(string='Calculated Rooms (Total)', compute='_compute_required_rooms')

    @api.depends('academic_year_id.enrollment_ids.class_count', 'academic_year_id.infrastructure_mode', 'room_type_id', 'effective_room_count')
    def _compute_required_rooms(self):
        for row in self:
            row.calculated_required_rooms = sum(row.academic_year_id.enrollment_ids.mapped('class_count')) if row.room_type_id.planning_classroom else row.effective_room_count

    @api.depends('academic_year_id.infrastructure_mode', 'academic_year_id.enrollment_ids.class_count', 'room_type_id', 'existing_rooms')
    def _compute_calculated_new_rooms(self):
        super(EfficientRooms, self.filtered(lambda row: not row.room_type_id.planning_classroom))._compute_calculated_new_rooms()
        for row in self:
            if row.academic_year_id.infrastructure_mode == 'existing':
                row.calculated_new_rooms = 0
            elif row.room_type_id.planning_classroom:
                row.calculated_new_rooms = sum(row.academic_year_id.enrollment_ids.mapped('class_count'))

    @api.depends('academic_year_id.students_per_classroom', 'academic_year_id.infrastructure_seeded', 'academic_year_id.infrastructure_mode', 'room_type_id', 'calculated_new_rooms', 'manual_new_rooms',
                 'academic_year_id.asset_price_ids.unit_price', 'academic_year_id.expansion_project_ids.project_room_ids.room_count',
                 'academic_year_id.expansion_project_ids.project_room_ids.room_type_id')
    def _compute_new_rooms_asset_cost(self):
        super(EfficientRooms, self.filtered(lambda row: not row.room_type_id.planning_classroom))._compute_new_rooms_asset_cost()
        for row in self.filtered(lambda row: row.room_type_id.planning_classroom):
            project_rooms = row.academic_year_id.expansion_project_ids.mapped('project_room_ids').filtered(lambda room: room.room_type_id == row.room_type_id)
            row.total_new_rooms = max(row.calculated_new_rooms, 0) + max(row.manual_new_rooms, 0) + sum(project_rooms.mapped('room_count')) if row.academic_year_id.infrastructure_mode == 'new' else 0
            assets = row.academic_year_id.asset_price_ids.filtered(lambda price: price.planning_seed_quantity > 0)
            row.new_rooms_asset_cost = row.total_new_rooms * sum(price.unit_price * price.planning_seed_quantity * (
                row.academic_year_id.students_per_classroom if price.planning_seed_basis == 'student' else 1
            ) for price in assets)
        for row in self.filtered(lambda row: row.academic_year_id.infrastructure_mode == 'existing'):
            row.total_new_rooms = 0
            row.new_rooms_asset_cost = 0


class EfficientAssetPrices(models.Model):
    _inherit = 'school.asset.prices'

    planning_seed_quantity = fields.Integer(string='Quantity per Unit', default=0)
    planning_seed_basis = fields.Selection([('student', 'Per Student'), ('classroom', 'Per Classroom')], string='Allocation', default='classroom', required=True)

    @api.depends('academic_year_id.students_per_classroom', 'academic_year_id.room_plan_ids.effective_room_count', 'academic_year_id.room_plan_ids.existing_rooms',
                 'academic_year_id.infrastructure_mode', 'planning_seed_quantity', 'planning_seed_basis', 'unit_price',
                 'academic_year_id.expansion_project_ids.project_room_ids.room_count', 'academic_year_id.expansion_project_ids.project_room_ids.room_type_id',
                 'academic_year_id.asset_transaction_ids.quantity')
    def _compute_asset_requirements(self):
        super(EfficientAssetPrices, self.filtered(lambda row: row.planning_seed_quantity <= 0))._compute_asset_requirements()
        for row in self.filtered(lambda row: row.planning_seed_quantity > 0):
            year = row.academic_year_id
            plans = year.room_plan_ids.filtered(lambda plan: plan.room_type_id.planning_classroom)
            per_room = row.planning_seed_quantity * (year.students_per_classroom if row.planning_seed_basis == 'student' else 1)
            room_count = sum(plans.mapped('total_new_rooms')) if year.infrastructure_mode == 'new' else year.required_classrooms
            transactions = self.env['school.asset.transactions'].search([('academic_year_id', 'in', year._origin.ids), ('asset_item_id', '=', row.asset_item_id.id)])
            row.required_quantity = room_count * per_room
            row.owned_quantity = sum(transactions.mapped('quantity')) if year.infrastructure_mode == 'new' else row.required_quantity
            row.purchase_quantity = row.required_quantity if year.infrastructure_mode == 'new' else 0
            row.asset_total_value = row.owned_quantity * row.unit_price
            row.startup_cost = row.purchase_quantity * row.unit_price
        for row in self.filtered(lambda row: row.academic_year_id.infrastructure_mode == 'existing'):
            row.purchase_quantity = 0
            row.startup_cost = 0


class EfficientQuickPrediction(models.TransientModel):
    _inherit = 'school.prediction.quick.setup.wizard'

    classroom_weekly_hours = fields.Float(string='Hours / Week / Classroom', default=35, required=True)
    infrastructure_mode = fields.Selection(INFRASTRUCTURE, default='existing', required=True)
    payroll_rules_initialized = fields.Boolean(default=False)
    extreme_expense_line_ids = fields.One2many(domain=[('input_mode', '=', 'extreme'), ('cost_bucket', '=', 'operating')])
    payroll_rule_ids = fields.One2many('school.prediction.quick.setup.repeating.expense.line', 'wizard_id', domain=[('input_mode', '=', 'extreme'), ('cost_bucket', '=', 'employee')])

    def _extreme_expense_commands(self):
        return self.env.ref('school_planning.prediction_seed_configuration')._expense_commands('extreme', 'operating')

    def _payroll_commands(self):
        seed = self.env.ref('school_planning.prediction_seed_configuration')
        return [fields.Command.create({
            'name': 'Payroll',
            'cost_bucket': 'employee',
            'start_year_index': seed.payroll_start_year_index,
            'trend': seed.payroll_trend,
            'base_annual_amount': seed.payroll_base_annual_amount,
            'annual_change_percent': seed.payroll_annual_change_percent,
            'input_mode': 'extreme',
        })]

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        seed = self.env.ref('school_planning.prediction_seed_configuration')
        values.update({name: value for name, value in seed._wizard_values().items() if name in field_names and f'default_{name}' not in self.env.context})
        if 'repeating_expense_line_ids' in field_names and not values.get('repeating_expense_line_ids'):
            values['repeating_expense_line_ids'] = seed._expense_commands('normal', 'operating')
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            seed = self.env.ref('school_planning.prediction_seed_configuration')
            for name, value in seed._wizard_values().items():
                values.setdefault(name, value)
            values.setdefault('repeating_expense_line_ids', seed._expense_commands('normal', 'operating'))
            if values.get('extreme_efficiency') and not values.get('payroll_rules_initialized'):
                values.setdefault('payroll_rule_ids', self._payroll_commands())
                values['payroll_rules_initialized'] = True
        return super().create(vals_list)

    @api.onchange('extreme_efficiency', 'school_id', 'forecast_years', 'start_year')
    def _onchange_extreme_efficiency(self):
        super()._onchange_extreme_efficiency()
        for wizard in self:
            if wizard.extreme_efficiency and not wizard.payroll_rules_initialized:
                expenses = wizard.extreme_expense_line_ids
                wizard.payroll_rule_ids = wizard._payroll_commands()
                wizard.extreme_expense_line_ids = expenses
                wizard.payroll_rules_initialized = True

    @api.onchange('school_id')
    def _onchange_efficiency_defaults(self):
        for wizard in self.filtered('school_id'):
            wizard.update(self.env.ref('school_planning.prediction_seed_configuration')._wizard_values())

    def _subject_hours_per_class_from_subjects(self, school=None):
        return self.classroom_weekly_hours if len(self) == 1 else self.env.ref('school_planning.prediction_seed_configuration').classroom_weekly_hours

    @api.onchange('classroom_weekly_hours')
    def _onchange_classroom_hours(self):
        for wizard in self:
            wizard.subject_hours_per_class = wizard.classroom_weekly_hours
            wizard._autofill_staff_counts_for_lines()

    def _ensure_subject_distribution(self, academic_year, levels, subjects):
        if academic_year.school_id._matching_timetables():
            academic_year._apply_timetables(levels, subjects)
        seeded = academic_year.subject_distribution_ids.filtered('timetable_id')
        for grade in levels:
            curricula = seeded.filtered(lambda row: row.grade_level_id == grade).timetable_id.curriculum_id
            remaining = subjects.filtered(
                lambda subject: subject.preset_id.curriculum_id in (self.school_id.curriculum_ids - curricula)
            ) if curricula else subjects
            super()._ensure_subject_distribution(academic_year, grade, remaining)
            academic_year.subject_distribution_ids.filtered(
                lambda row: row.grade_level_id == grade and row.subject_id in remaining
            ).write({'weekly_hours': self.classroom_weekly_hours / len(remaining) if remaining else 0})

    def _ensure_subjects(self):
        self.school_id._ensure_timetable_subjects()
        return super()._ensure_subjects()

    def _ensure_operating_models(self):
        positions = super()._ensure_operating_models()
        positions['teacher'].planning_role = 'teacher'
        return positions

    def _active_repeating_expenses(self):
        return super()._active_repeating_expenses()

    def _ensure_academic_years(self, forecast_years=3):
        years = super()._ensure_academic_years(forecast_years)
        years.with_context(defer_school_financial_refresh=True).write({'students_per_classroom': self.max_students_per_class_input,
                                                                     'classroom_weekly_hours': self.classroom_weekly_hours,
                                                                     'teacher_weekly_hours': self.teaching_load_hours, 'infrastructure_mode': self.infrastructure_mode})
        return years

    def action_load_demo_data(self):
        settings = {name: self[name] for name in ('teaching_load_hours', 'classroom_weekly_hours', 'max_students_per_class_input', 'infrastructure_mode')}
        action = super().action_load_demo_data()
        self.update(settings)
        if self.extreme_efficiency:
            self.payroll_rule_ids = [fields.Command.clear()] + self._payroll_commands()
            self.payroll_rules_initialized = True
        else:
            self.repeating_expense_line_ids = [fields.Command.clear()] + self.env.ref(
                'school_planning.prediction_seed_configuration')._expense_commands('normal', 'operating')
        return action

    def _original_forecast_settings(self):
        self.ensure_one()

        def values(record, names):
            metadata = record.fields_get(names, attributes=['string', 'selection', 'type'])
            result = []
            for name in names:
                field = metadata[name]
                value = record[name]
                if field['type'] == 'selection':
                    value = dict(field['selection']).get(value, value)
                elif field['type'] == 'boolean':
                    value = self.env._('Yes') if value else self.env._('No')
                result.append([field['string'], value])
            return result

        common = [
            'start_year', 'forecast_years', 'extreme_efficiency', 'income_tax_percent',
            'fee_increase_percent', 'infrastructure_mode', 'max_students_per_class_input',
            'classroom_weekly_hours', 'teaching_load_hours',
        ]
        if not self.extreme_efficiency:
            common += [
                'salary_increase_percent', 'assistant_principal_per_students', 'janitor_per_students',
                'principal_fixed_count', 'it_fixed_count', 'admission_officer_fixed_count',
                'front_desk_fixed_count', 'student_affairs_fixed_count', 'nurse_fixed_count',
                'hr_fixed_count', 'accountant_fixed_count', 'finance_officer_fixed_count',
            ]
        else:
            common += ['replace_existing_payroll']
        sections = [{'title': self.env._('Forecast settings'), 'values': values(self, common)}]
        year_fields = ['student_count', 'annual_fee_per_student']
        if not self.extreme_efficiency:
            year_fields += [name for name in self.line_ids._fields if name.endswith('_count') and name != 'student_count']
        for line in self.line_ids.sorted('year_index')[:self.forecast_years]:
            sections.append({'title': self.env._('Year %(year)s', year=line.year_label),
                             'values': values(line, year_fields)})
        if not self.extreme_efficiency:
            salary_fields = list(self._salary_role_field_map().values()) + ['months_paid', 'bonus']
            for line in self.year_salary_line_ids.sorted('year_index').filtered(
                lambda line: line.year_index in self.line_ids.sorted('year_index')[:self.forecast_years].mapped('year_index')
            ):
                sections.append({'title': self.env._('Salaries: %(year)s', year=line.year_label),
                                 'values': values(line, salary_fields)})
        rule_fields = ['start_year_index', 'trend', 'base_annual_amount', 'annual_change_percent']
        for line in self._active_repeating_expenses() | (self.payroll_rule_ids if self.extreme_efficiency else self.payroll_rule_ids.browse()):
            rule_values = values(line, rule_fields)
            if line.trend.startswith('revenue_'):
                rule_values[2][0] = self.env._('Base Revenue %')
                rule_values[3][0] = self.env._('Annual Change (percentage points)')
            sections.append({'title': self.env._('Expense rule: %(name)s', name=line.name),
                             'values': rule_values})
        return sections

    def action_apply(self):
        result = super(EfficientQuickPrediction, self.with_context(
            defer_school_financial_refresh=True, skip_forecast_fee_growth=True,
        )).action_apply()
        self.ensure_one()
        years = self._existing_forecast_years()
        for year_index, year in enumerate(years, start=1):
            target = year.with_context(defer_school_financial_refresh=True)
            if self.extreme_efficiency:
                gross_revenue = year.fee_gross_total
                student_count = year.total_enrolled_students
                net_revenue = year.fee_total
                amount = sum(self._compute_repeating_expense_amount(rule, year_index, gross_revenue, student_count, net_revenue)
                             for rule in self.payroll_rule_ids)
                target.write({'payroll_summary_enabled': True, 'payroll_basis': 'amount',
                              'payroll_rate': 0, 'payroll_fixed_amount': amount})
            else:
                target.write({'payroll_summary_enabled': False})
            target.with_context(reapply_prediction_seeds=True)._seed_infrastructure()
            target._sync_efficiency_teaching()
        self.env['school.financial.report']._refresh_for_academic_years(years.ids)
        settings = self._original_forecast_settings()
        fee_growth_batch = uuid.uuid4().hex
        for year in years:
            grades = year.enrollment_ids.sorted(key=lambda row: (row.grade_level_id.sort_order, row.grade_level_id.id))
            year.write({'forecast_fee_growth_batch': fee_growth_batch,
                        'forecast_fee_growth_percent': max(self.fee_increase_percent, 0),
                        'original_forecast_settings': settings + [{
                'title': self.env._('Generated enrollment: %(year)s', year=year.academic_year_name),
                'values': [[row.grade_level_id.name, row.student_count] for row in grades],
            }]})
        return result


class PayrollRule(models.TransientModel):
    _inherit = 'school.prediction.quick.setup.repeating.expense.line'

    salary_base_amount = fields.Float(string='Annual Salaries', compute='_compute_salary_base_amount', inverse='_inverse_salary_base_amount')

    def _salary_revenue_base(self):
        self.ensure_one()
        year = self.wizard_id.line_ids.filtered(lambda line: line.year_index == self.start_year_index)[:1]
        revenue = year.student_count * year.annual_fee_per_student if year else 0
        if self.trend.startswith('revenue_after_tax_'):
            revenue *= 1 - min(max(self.wizard_id.income_tax_percent, 0), 100) / 100
        return revenue

    @api.depends('base_annual_amount', 'trend', 'start_year_index', 'wizard_id.income_tax_percent', 'wizard_id.line_ids.student_count', 'wizard_id.line_ids.annual_fee_per_student')
    def _compute_salary_base_amount(self):
        for rule in self:
            revenue = rule._salary_revenue_base()
            rule.salary_base_amount = revenue * rule.base_annual_amount / 100 if rule.trend.startswith('revenue_') else rule.base_annual_amount

    def _inverse_salary_base_amount(self):
        for rule in self:
            revenue = rule._salary_revenue_base()
            if rule.trend.startswith('revenue_') and not revenue and rule.salary_base_amount:
                raise ValidationError('The selected revenue base must be positive before entering a salaries amount.')
            rule.base_annual_amount = rule.salary_base_amount / revenue * 100 if rule.trend.startswith('revenue_') and revenue else rule.salary_base_amount

    @api.onchange('salary_base_amount')
    def _onchange_salary_base_amount(self):
        for rule in self:
            revenue = rule._salary_revenue_base()
            if rule.trend.startswith('revenue_') and revenue:
                rule.base_annual_amount = rule.salary_base_amount / revenue * 100
            elif not rule.trend.startswith('revenue_'):
                rule.base_annual_amount = rule.salary_base_amount