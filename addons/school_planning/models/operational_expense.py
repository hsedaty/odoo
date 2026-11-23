import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    def action_school_edit_price_currency(self):
        self.ensure_one()
        self.check_access('write')
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Edit Price Currency'),
            'res_model': self._name,
            'res_id': self.id,
            'views': [(self.env.ref('base.view_currency_form').id, 'form')],
            'target': 'new',
        }

    def action_school_delete_price_currency(self):
        self.ensure_one()
        self.check_access('unlink')
        for model in ('res.company', 'school.schools', 'school.prediction.operational.seed'):
            if self.env[model].sudo().with_context(active_test=False).search_count([
                ('currency_id', '=', self.id),
            ], limit=1):
                raise ValidationError(self.env._('This currency is used by a company, school, or expense seed and cannot be deleted here.'))
        self.unlink()
        return False


class ResCurrencyRate(models.Model):
    _inherit = 'res.currency.rate'

    def _refresh_detailed_forecasts(self):
        if not self.env.registry.ready:
            return
        years = self.env['school.academic.years'].sudo().search([
            ('dataset_type', '=', 'forecast'), ('baseline_locked', '=', False),
            '|', ('expense_calculation_mode', '=', 'detailed'), ('detailed_incomes_created', '=', True),
        ])
        years._check_detailed_expense_calculation()
        years.invalidate_recordset(['grade_student_costs'])
        years.modified(['grade_student_costs'])
        self.env['school.financial.report']._refresh_for_academic_years(years.ids)

    @api.model_create_multi
    def create(self, vals_list):
        rates = super().create(vals_list)
        rates._refresh_detailed_forecasts()
        return rates

    def write(self, values):
        result = super().write(values)
        self._refresh_detailed_forecasts()
        return result

    def unlink(self):
        result = super().unlink()
        self._refresh_detailed_forecasts()
        return result


class School(models.Model):
    _inherit = 'school.schools'

    def write(self, values):
        result = super().write(values)
        if {'currency', 'currency_id'} & values.keys():
            years = self.env['school.academic.years'].sudo().search([
                ('school_id', 'in', self.ids), ('dataset_type', '=', 'forecast'),
                ('baseline_locked', '=', False),
                '|', ('expense_calculation_mode', '=', 'detailed'), ('detailed_incomes_created', '=', True),
            ])
            years._check_detailed_expense_calculation()
            self.env['school.financial.report']._refresh_for_academic_years(years.ids)
        return result


class OperationalExpenseFields(models.AbstractModel):
    _name = 'school.prediction.operational.fields'
    _description = 'Operational Expense Assumptions'

    name = fields.Char(required=True)
    category = fields.Selection([
        ('digital', 'Digital Resources'), ('management', 'Management Solutions'),
        ('accreditation', 'Accreditation'),
    ])
    curriculum = fields.Char()
    description = fields.Char()
    basis = fields.Selection([
        ('fixed', 'Fixed Amount'), ('student', 'Per Student'),
        ('student_percent', 'Per Student in %'),
        ('teacher', 'Per Teacher'), ('quantity', 'Per Other Unit'),
    ])
    price = fields.Float(string='Unit Price')
    price_set = fields.Boolean(string='Price Confirmed')
    currency_id = fields.Many2one('res.currency', string='Price Currency')
    grade_scope = fields.Selection([('all', 'All Grades'), ('selected', 'Selected Grades')], default='all')
    frequency = fields.Selection([('once', 'One Time'), ('annual', 'Annual'), ('interval', 'Every N Years')])
    start_year_index = fields.Integer(string='Start Year #', default=1)
    interval = fields.Integer(string='Every N Years', default=1)
    quantity = fields.Float(string='Units / Teachers')
    quantity_set = fields.Boolean(string='Quantity Confirmed')
    student_paid = fields.Boolean(string='Paid by Students')

    @api.constrains('price', 'quantity', 'start_year_index', 'interval')
    def _check_operational_values(self):
        for line in self:
            if line.price < 0 or line.quantity < 0 or line.start_year_index < 1 or line.interval < 1:
                raise ValidationError(self.env._('Prices and quantities cannot be negative; start year and interval must be positive.'))


class OperationalExpenseSeed(models.Model):
    _name = 'school.prediction.operational.seed'
    _inherit = 'school.prediction.operational.fields'
    _description = 'Operational Expense Catalog'
    _order = 'name, id'

    configuration_id = fields.Many2one('school.prediction.seed.configuration', required=True, ondelete='cascade')
    category_seed_id = fields.Many2one(
        'school.prediction.seed.expense', string='Category', ondelete='restrict', index=True,
    )
    default_selected = fields.Boolean(string='Include in Detailed Forecast')
    price_type = fields.Selection([('fixed', 'Fixed'), ('allocated', 'Allocated')], required=True, default='allocated')
    active = fields.Boolean(default=True)
    replaces_tuition = fields.Boolean(
        string='Represents Tuition',
        help='Tuition is calculated from forecast tuition fee rows, not from this detailed income item.',
    )
    grade_ids = fields.Many2many('school.grade.level.preset', 'school_operational_seed_grade_rel', string='Grades')

    def write(self, values):
        tuition_changed = bool(self.filtered('replaces_tuition')) and bool(
            {'grade_scope', 'grade_ids', 'active', 'replaces_tuition'} & values.keys()
        )
        guarded = self.filtered(lambda seed: seed.price_type == 'fixed' and (
            ('price_type' in values and values['price_type'] != seed.price_type)
            or (seed.price_set and any(name in values and values[name] != (
                seed[name].id if name == 'currency_id' else seed[name]
            ) for name in ('price', 'price_set', 'currency_id')))
        ))
        if guarded and self.env['school.academic.years'].sudo().with_context(active_test=False).search_count([
            '|', ('detailed_expense_seed_ids', 'in', guarded.ids), ('detailed_income_seed_ids', 'in', guarded.ids),
        ], limit=1):
            raise ValidationError(self.env._('A confirmed fixed price used by a forecast cannot be changed.'))
        result = super().write(values)
        years = self.env['school.academic.years'].sudo().with_context(active_test=False).search([
            ('baseline_locked', '=', False),
            '|', '&', ('expense_calculation_mode', '=', 'detailed'), ('detailed_expense_seed_ids', 'in', self.ids),
            ('detailed_income_seed_ids', 'in', self.ids),
        ])
        if tuition_changed or ('replaces_tuition' in values and values['replaces_tuition']):
            years |= self.env['school.academic.years'].sudo().search([
                ('dataset_type', '=', 'forecast'), ('baseline_locked', '=', False),
            ])
            summary_fields = [name for name, field in years._fields.items() if field.compute == '_compute_financial_summary']
            years.invalidate_recordset(summary_fields + ['annual_fee_input'])
            years.mapped('enrollment_ids').invalidate_recordset(['revenue_total', 'revenue_per_student'])
        years._check_detailed_expense_calculation()
        self.env['school.financial.report']._refresh_for_academic_years(years.ids)
        return result

    def unlink(self):
        if self.env['school.academic.years'].sudo().with_context(active_test=False).search_count([
            '|', ('detailed_expense_seed_ids', 'in', self.ids), ('detailed_income_seed_ids', 'in', self.ids),
        ], limit=1):
            raise ValidationError(self.env._('Archive items used by forecasts instead of deleting them.'))
        return super().unlink()

    @api.model
    def _link_legacy_expense_categories(self):
        for code, name, order in (
            ('accreditation', 'Accreditation', 20),
            ('digital', 'Digital Resources', 30),
            ('management', 'Management Solutions', 40),
        ):
            items = self.with_context(active_test=False).search([
                ('category', '=', code), ('category_seed_id', '=', False),
            ])
            for config, details in items.grouped('configuration_id').items():
                categories = self.env['school.prediction.seed.expense'].with_context(active_test=False)
                category = categories.search([
                    ('configuration_id', '=', config.id), ('name', '=ilike', name),
                    ('cost_bucket', '=', 'operating'), '|',
                    ('is_detailed_category', '=', True), ('input_mode', '=', 'detail'),
                ], limit=1)
                if not category:
                    category = categories.create({
                        'configuration_id': config.id, 'name': name, 'display_order': order,
                        'is_detailed_category': True,
                    })
                elif not category.is_detailed_category:
                    category.is_detailed_category = True
                details.category_seed_id = category

    @api.constrains('configuration_id', 'category_seed_id', 'category')
    def _check_category_seed(self):
        for item in self:
            category = item.category_seed_id
            if not category and item.category:  # Existing XML seeds are linked after loading.
                continue
            if not category or not category.is_detailed_category or category.configuration_id != item.configuration_id:
                raise ValidationError(self.env._('Select a detailed expense category from the same seed configuration.'))


class PredictionSeedConfiguration(models.Model):
    _inherit = 'school.prediction.seed.configuration'

    operational_seed_ids = fields.One2many('school.prediction.operational.seed', 'configuration_id', string='Detailed Seeds')
    income_seed_ids = fields.One2many('school.prediction.seed.expense', 'configuration_id', domain=[('catalog_type', '=', 'income')])
    income_detail_seed_ids = fields.One2many('school.prediction.operational.seed', 'configuration_id',
                                           domain=[('category_seed_id.catalog_type', '=', 'income')])


class AcademicYears(models.Model):
    _inherit = 'school.academic.years'

    operational_estimate_details = fields.Text(string='Expense Estimate Comparison', readonly=True, copy=False)
    detailed_expenses_created = fields.Boolean(copy=False)
    expense_calculation_mode = fields.Selection(
        [('no_details', 'No Details'), ('detailed', 'Detailed')],
        string='Expenses Used in Reports', default='no_details', required=True, copy=False,
    )
    legacy_detailed_tax = fields.Boolean(copy=False, readonly=True)
    detailed_expense_seed_ids = fields.Many2many(
        'school.prediction.operational.seed', 'school_year_operational_seed_rel', copy=False,
    )
    detailed_incomes_created = fields.Boolean(copy=False)
    detailed_income_seed_ids = fields.Many2many(
        'school.prediction.operational.seed', 'school_year_income_seed_rel', copy=False,
    )
    detailed_allocated_prices = fields.Json(default=dict, copy=False)
    detailed_occurrence_values = fields.Json(default=dict, copy=False)
    baseline_income_sources = fields.Json(readonly=True, copy=False)
    grade_student_costs = fields.Json(
        compute='_compute_financial_summary',
        help='Per-student costs from selected detailed expenses, scoped to their assigned grades. Shared costs are excluded.',
    )
    grade_income_totals = fields.Json(compute='_compute_financial_summary')

    def _tuition_income_seed(self):
        return self.env.ref('school_planning.prediction_seed_configuration').income_detail_seed_ids.filtered(
            lambda seed: seed.active and seed.replaces_tuition
        )[:1]

    def _tuition_scope_enrollments(self):
        self.ensure_one()
        seed = self._tuition_income_seed()
        if seed and seed.grade_scope == 'selected' and not self.baseline_locked:
            names = {name.strip().casefold() for name in seed.grade_ids.mapped('name')}
            return self.enrollment_ids.filtered(lambda row: row.grade_level_id.name.strip().casefold() in names)
        return self.enrollment_ids

    def _tuition_scope_grades(self):
        self.ensure_one()
        seed = self._tuition_income_seed()
        if seed and not self.baseline_locked:
            return self._income_grade_levels(seed)
        return self.env['school.grade.levels'].search(
            [('school_id', '=', self.school_id.id)], order='sort_order, id',
        )

    def _forecast_tuition_rows(self):
        self.ensure_one()
        if self.baseline_locked:
            if not self.baseline_income_sources:
                return self.fee_value_ids
            tuition = next((source for source in self.baseline_income_sources if source['kind'] == 'tuition'), {})
            row_ids = set(tuition.get('row_ids', []))
            return self.fee_value_ids.filtered(lambda row: row.id in row_ids)
        grades = self._tuition_scope_grades()
        return self.fee_value_ids.filtered(
            lambda row: row.fee_type_id.forecast_tuition and row.grade_level_id in grades
        )

    def _forecast_income_sources(self):
        self.ensure_one()
        if self.baseline_locked:
            if self.baseline_income_sources:
                return self.baseline_income_sources, 0
            return [{'name': self.env._('Historical gross revenue'),
                     'kind': 'tuition', 'amount': (self.baseline_totals or {}).get('fee_gross_total', 0)}], 0
        tuition_rows = self._forecast_tuition_rows()
        sources = [{'name': self.env._('Tuition'), 'kind': 'tuition', 'row_ids': tuition_rows.ids,
                    'amount': sum(tuition_rows.mapped('gross_revenue_amount'))}]
        tuition_seed = self._tuition_income_seed()
        pending = int(bool(tuition_seed and tuition_seed.grade_scope == 'selected' and not tuition_seed.grade_ids))
        if self.detailed_incomes_created:
            selected = self.with_context(active_test=False).detailed_income_seed_ids.filtered(
                lambda seed: not seed.replaces_tuition
            )
            for seed, amount, _note in self._detailed_expense_amounts(selected):
                if amount is None:
                    pending += 1
                else:
                    source = {'name': seed.name, 'kind': 'detailed', 'seed_id': seed.id, 'amount': amount}
                    if seed.basis == 'student':
                        source['grades'] = self._student_income_grades(seed, amount)
                    sources.append(source)
        return sources, pending

    def _income_grade_levels(self, seed):
        names = {name.strip().casefold() for name in seed.grade_ids.mapped('name')}
        grades = self.env['school.grade.levels'].search(
            [('school_id', '=', self.school_id.id)], order='sort_order, id',
        )
        return grades.filtered(lambda grade: seed.grade_scope == 'all' or grade.name.strip().casefold() in names)

    def _student_income_grades(self, seed, amount=None):
        self.ensure_one()
        grades = self._income_grade_levels(seed)
        students = {row.grade_level_id.id: row.student_count for row in self.enrollment_ids}
        occurrence = (self.detailed_occurrence_values or {}).get(str(seed.id), {})
        if occurrence.get('mode') == 'student_grade':
            default = occurrence['value']
            rates = occurrence['grades']
        else:
            total_students = sum(students.get(grade.id, 0) for grade in grades)
            default = amount / total_students if amount is not None and total_students else None
            rates = {}
            if default is None and amount is not None and not occurrence:
                prices = self.detailed_allocated_prices or {}
                default = prices.get(str(seed.id)) if seed.price_type == 'allocated' else None
                if default is None and seed.price_set and seed.currency_id:
                    currency = self.school_id.currency_id or self.env.company.currency_id
                    default = seed.currency_id._convert(
                        seed.price, currency, self.env.company,
                        self.start_date or fields.Date.context_today(self), round=False,
                    )
        return [
            {'id': grade.id, 'name': grade.name, 'students': students.get(grade.id, 0),
             'rate': rates.get(str(grade.id), default)}
            for grade in grades
        ]

    def _detailed_grade_income_totals(self):
        totals = {}
        if self.dataset_type != 'forecast':
            return totals
        for source in self._forecast_income_sources()[0]:
            for grade in source.get('grades', []):
                if grade['rate'] is not None:
                    key = str(grade['id'])
                    totals[key] = totals.get(key, 0.0) + grade['rate'] * grade['students']
        return totals

    @api.constrains('expense_calculation_mode', 'detailed_expenses_created', 'detailed_expense_seed_ids',
                    'detailed_allocated_prices', 'detailed_occurrence_values')
    def _check_detailed_expense_calculation(self):
        for year in self.filtered(lambda row: row.dataset_type == 'forecast' and row.expense_calculation_mode == 'detailed'):
            if not year.detailed_expenses_created:
                raise ValidationError(self.env._('Create the detailed expense list before selecting Detailed.'))
            selected = year.with_context(active_test=False).detailed_expense_seed_ids
            missing = [seed.name for seed, amount, _note in year._detailed_expense_amounts(selected) if amount is None]
            if missing:
                raise ValidationError(self.env._(
                    'Select No Details and complete pricing for these expenses before using Detailed in reports: %s',
                    ', '.join(missing),
                ))

    def _selected_detailed_expense_total(self):
        self.ensure_one()
        selected = self.with_context(active_test=False).detailed_expense_seed_ids
        amounts = list(self._detailed_expense_amounts(selected))
        missing = [seed.name for seed, amount, _note in amounts if amount is None]
        if missing:
            raise ValidationError(self.env._('Detailed expenses need prices: %s', ', '.join(missing)))
        return sum(amount for _seed, amount, _note in amounts)

    def _per_student_expense_costs(self):
        self.ensure_one()
        if (self.dataset_type == 'forecast' and self.baseline_locked
                and 'grade_student_costs' not in (self.baseline_totals or {})):
            students = sum(self.enrollment_ids.mapped('student_count'))
            deductions = (
                sum(self.fee_value_ids.mapped('tax_amount'))
                + self.expense_value_ids._category_amount_total()
                + sum(self.employment_salary_ids.mapped('annual_cost'))
                + sum(self.room_plan_ids.mapped('new_rooms_asset_cost'))
            )
            unit_cost = deductions / students if students else 0.0
            return {str(row.grade_level_id.id): unit_cost for row in self.enrollment_ids}
        if self.expense_calculation_mode != 'detailed':
            return {}
        selected = self.with_context(active_test=False).detailed_expense_seed_ids.filtered(
            lambda seed: seed.basis in ('student', 'student_percent')
            or (self.detailed_occurrence_values or {}).get(str(seed.id), {}).get('mode') == 'student_percent'
        )
        costs = {}
        for seed, amount, _note in self._detailed_expense_amounts(selected):
            if amount is None:
                raise ValidationError(self.env._('Detailed expenses need prices: %s', seed.name))
            names = {name.strip().casefold() for name in seed.grade_ids.mapped('name')}
            enrollments = self.enrollment_ids.filtered(
                lambda row: seed.grade_scope == 'all' or row.grade_level_id.name.strip().casefold() in names
            )
            students = sum(enrollments.mapped('student_count'))
            unit_cost = amount / students if students else 0.0
            for row in enrollments:
                key = str(row.grade_level_id.id)
                costs[key] = costs.get(key, 0.0) + unit_cost
        return costs

    @api.constrains('detailed_allocated_prices')
    def _check_detailed_allocated_prices(self):
        for year in self:
            prices = year.detailed_allocated_prices or {}
            if not isinstance(prices, dict) or any(
                not isinstance(key, str) or not key.isdecimal() or isinstance(value, bool)
                or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
                for key, value in prices.items()
            ):
                raise ValidationError(self.env._('Allocated prices must be non-negative numbers.'))

    @api.constrains('detailed_occurrence_values')
    def _check_detailed_occurrence_values(self):
        for year in self:
            values = year.detailed_occurrence_values
            if values is False or values is None:
                continue
            def valid_number(value, maximum=None):
                return (value is None or (
                    not isinstance(value, bool) and isinstance(value, (int, float))
                    and math.isfinite(value) and value >= 0 and (maximum is None or value <= maximum)
                ))

            if not isinstance(values, dict) or any(
                not isinstance(key, str) or not key.isdecimal() or not isinstance(entry, dict)
                or not (
                    (set(entry) == {'mode', 'value'} and entry['mode'] in ('amount', 'revenue_percent')
                     and entry['value'] is not None and valid_number(entry['value']))
                    or (set(entry) == {'mode', 'value', 'percentage'} and entry['mode'] == 'student_percent'
                        and valid_number(entry['value']) and valid_number(entry['percentage'], 100))
                    or (set(entry) == {'mode', 'value', 'grades'} and entry['mode'] == 'student_grade'
                        and valid_number(entry['value'])
                        and isinstance(entry['grades'], dict)
                        and all(isinstance(grade, str) and grade.isdecimal() and rate is not None and valid_number(rate)
                                for grade, rate in entry['grades'].items()))
                ) for key, entry in values.items()
            ):
                raise ValidationError(self.env._('Detailed amounts must be non-negative and participation percentages must be between 0 and 100.'))

    def _detailed_catalog(self, kind):
        codes = set(self.school_id.curriculum_ids.mapped('code'))
        names = {name.casefold() for name in self.school_id.curriculum_ids.mapped('name')}
        names.update(label for code, label in (
            ('US', 'american'), ('IB_PYP', 'ib pyp'), ('IB_MYP', 'ib myp'), ('IB_DP', 'ib dp'),
        ) if code in codes)
        if any(code.startswith('IB_') for code in codes):
            names.add('ib')
        config = self.env.ref('school_planning.prediction_seed_configuration')
        year = self.with_context(active_test=False)
        selected = year.detailed_expense_seed_ids if kind == 'expense' else year.detailed_income_seed_ids
        seeds = config.with_context(active_test=False).operational_seed_ids
        return seeds.filtered(
            lambda seed: seed.category_seed_id.catalog_type == kind and seed.category_seed_id.is_detailed_category
            and ((seed.active and seed.category_seed_id.active) or seed in selected)
            and (seed in selected or not seed.curriculum or seed.curriculum.strip().casefold() in names)
        )

    def _detailed_expense_catalog(self):
        return self._detailed_catalog('expense')

    def _detailed_expense_amount(self, seed, currency, rate_ids, date):
        if seed.student_paid:
            return 0.0, self.env._('Paid by students')
        seed_key = str(seed._origin.id or seed.id)
        occurrence = (self.detailed_occurrence_values or {}).get(seed_key)
        if occurrence:
            amount = occurrence['value']
            if occurrence['mode'] == 'student_grade':
                if seed.grade_scope == 'selected' and not seed.grade_ids:
                    return None, self.env._('Grades needed in seed')
                grades = self._student_income_grades(seed)
                if any(grade['rate'] is None for grade in grades):
                    return None, self.env._('Enter an amount for each applicable grade')
                amount = sum(grade['rate'] * grade['students'] for grade in grades)
            elif occurrence['mode'] == 'student_percent':
                if amount is None or occurrence['percentage'] is None:
                    return None, self.env._('Enter an amount per student and participation percentage')
                grades = {name.strip().casefold() for name in seed.grade_ids.mapped('name')}
                if seed.grade_scope == 'selected' and not grades:
                    return None, self.env._('Grades needed in seed')
                students = sum(row.student_count for row in self.enrollment_ids
                               if seed.grade_scope == 'all' or row.grade_level_id.name.strip().casefold() in grades)
                amount *= students * occurrence['percentage'] / 100
            elif occurrence['mode'] == 'revenue_percent':
                if seed.category_seed_id.catalog_type == 'income':
                    revenue = sum(self._forecast_tuition_rows().mapped('gross_revenue_amount'))
                elif self.dataset_type == 'forecast':
                    revenue = sum(source['amount'] for source in self._forecast_income_sources()[0])
                else:
                    revenue = sum(self.fee_value_ids.mapped('gross_revenue_amount'))
                amount *= revenue / 100
            return currency.round(amount), ''
        prices = self.detailed_allocated_prices or {}
        override = prices.get(seed_key) if seed.price_type == 'allocated' else None
        if not seed.basis:
            return None, self.env._('Pricing basis needed in seed')
        if seed.basis == 'student_percent':
            return None, self.env._('Enter an amount per student and participation percentage')
        if override is None and not seed.price_set:
            return None, self.env._('Enter an allocated budget') if seed.price_type == 'allocated' else self.env._('Price needed in seed')
        if override is None and not seed.currency_id:
            return None, self.env._('Price currency needed in seed')
        if seed.basis in ('teacher', 'quantity') and not seed.quantity_set:
            return None, self.env._('Quantity needed in seed')
        quantity = seed.quantity if seed.basis in ('teacher', 'quantity') else 1
        if seed.grade_scope == 'selected' and not seed.grade_ids:
            return None, self.env._('Grades needed in seed')
        if seed.basis == 'student':
            grades = {name.strip().casefold() for name in seed.grade_ids.mapped('name')}
            quantity = sum(row.student_count for row in self.enrollment_ids
                           if seed.grade_scope == 'all' or row.grade_level_id.name.strip().casefold() in grades)
        amount = (override if override is not None else seed.price) * quantity
        if amount and seed.currency_id and seed.currency_id != currency:
            if not {seed.currency_id.id, currency.id}.issubset(rate_ids):
                return None, self.env._('Exchange rate unavailable for this year')
            amount = seed.currency_id._convert(amount, currency, self.env.company, date, round=False)
        return currency.round(amount), ''

    def _detailed_expense_amounts(self, catalog):
        if not catalog:
            return
        currency = self.school_id.currency_id or self.env.company.currency_id
        date = self.start_date or fields.Date.context_today(self)
        company = self.env.company
        rate_ids = set(self.env['res.currency.rate'].search([
            ('currency_id', 'in', (catalog.currency_id | currency).ids), ('name', '<=', date),
            ('company_id', 'in', [False, company.root_id.id]),
        ]).currency_id.ids) | {company.currency_id.id}
        for seed in catalog:
            yield seed, *self._detailed_expense_amount(seed, currency, rate_ids, date)

    def get_detailed_expense_list(self):
        return self._get_detailed_list('expense')

    def get_detailed_income_list(self):
        return self._get_detailed_list('income')

    def _get_detailed_list(self, kind):
        self.ensure_one()
        self.check_access('read')
        if self.dataset_type != 'forecast':
            raise ValidationError(self.env._('Detailed estimates are available only for forecasts.'))
        currency = self.school_id.currency_id or self.env.company.currency_id
        basis = self.prediction_expense_revenue_basis
        if not basis:
            # Older forecasts only retain the basis on linked expense seeds.
            rows = self.operating_expense_ids.filtered(
                lambda row: not row.expense_item_id and row.prediction_input_mode in ('normal', 'extreme')
            )
            basis = 'net' if rows and all(
                (row.expense_category_id.prediction_seed_id.trend or '').startswith('revenue_after_tax_') for row in rows
            ) else 'gross'
        revenue = self.fee_total if basis == 'net' else self.fee_gross_total
        baseline_rows = self.expense_value_ids
        if self.payroll_summary_enabled:
            baseline_rows = baseline_rows.filtered(lambda row: row.cost_bucket != 'employee')
        baseline = baseline_rows._category_amount_total()
        result = {
            'created': self.detailed_expenses_created if kind == 'expense' else self.detailed_incomes_created,
            'locked': self.baseline_locked, 'kind': kind,
            'baseline': baseline if kind == 'expense' else sum(self._forecast_tuition_rows().mapped('gross_revenue_amount')),
            'gross_revenue': self.fee_gross_total,
            'currency': currency.id, 'currency_name': currency.name, 'groups': [], 'total': 0.0, 'pending': 0,
            'baseline_ratio': baseline / revenue if kind == 'expense' and revenue > 0 else None,
            'baseline_ratio_basis': self.env._('of revenue after tax') if basis == 'net' else self.env._('of revenue before tax'),
            'historic_frozen': kind == 'income' and self.baseline_locked and not self.baseline_income_sources,
        }
        if kind == 'income':
            tuition_rows = self._forecast_tuition_rows()
            students = {row.grade_level_id.id: row.student_count for row in self.enrollment_ids}
            result['tuition_average'] = self.annual_fee_input
            result['tuition_grades'] = [
                {'id': grade.id, 'name': grade.name,
                 'students': students.get(grade.id, 0),
                 'rate': sum(tuition_rows.filtered(
                     lambda row: row.grade_level_id == grade
                 ).mapped('amount'))}
                for grade in self._tuition_scope_grades()
            ]
        if not result['created']:
            return result
        year = self.with_context(active_test=False)
        selected_ids = set((year.detailed_expense_seed_ids if kind == 'expense' else year.detailed_income_seed_ids).ids)
        frozen_amounts = {
            source['seed_id']: source['amount'] for source in (self.baseline_income_sources or [])
            if source['kind'] == 'detailed' and 'seed_id' in source
        } if kind == 'income' and self.baseline_locked else {}
        frozen_sources = {
            source['seed_id']: source for source in (self.baseline_income_sources or [])
            if source['kind'] == 'detailed' and 'seed_id' in source
        } if kind == 'income' and self.baseline_locked else {}
        groups = {}
        catalog = self._detailed_catalog(kind).sorted(
            lambda seed: ((seed.category_seed_id.parent_id or seed.category_seed_id).display_order,
                          seed.category_seed_id.display_order, seed.category_seed_id.id, seed.id)
        )
        if kind == 'income':
            catalog = catalog.filtered(lambda seed: not seed.replaces_tuition or seed.id in frozen_amounts)
        for seed, amount, note in self._detailed_expense_amounts(catalog):
            if seed.id in frozen_amounts:
                amount, note = frozen_amounts[seed.id], ''
            name = seed.curriculum or (seed.category_seed_id.parent_id or seed.category_seed_id).name
            group = groups.setdefault(name, {'name': name, 'total': 0.0, 'categories': {}})
            category = group['categories'].setdefault(seed.category_seed_id.id, {
                'id': seed.category_seed_id.id, 'name': seed.category_seed_id.name, 'total': 0.0, 'items': [],
                'price_type': seed.category_seed_id.price_type if seed.category_seed_id.parent_id else False,
            })
            selected = seed.id in selected_ids
            occurrence = (self.detailed_occurrence_values or {}).get(str(seed.id), {})
            item = {
                'id': seed.id, 'name': seed.name, 'amount': amount, 'note': note,
                'selected': selected, 'student_paid': seed.student_paid,
                'price_type': seed.price_type,
                'price': (self.detailed_allocated_prices or {}).get(str(seed.id), seed.price if seed.price_set else None),
                'price_currency': (seed.currency_id or currency).name,
                'occurrence_mode': occurrence.get('mode'),
                'occurrence_value': occurrence.get('value'),
                'occurrence_percentage': occurrence.get('percentage'),
                'basis': seed.basis,
            }
            if kind == 'income' and seed.basis == 'student':
                grades = (frozen_sources.get(seed.id, {}).get('grades', []) if self.baseline_locked
                          else self._student_income_grades(seed, amount))
                students = sum(grade['students'] for grade in grades)
                rates = [grade['rate'] for grade in grades if grade['rate'] is not None]
                item['grades'] = grades
                item['grade_average'] = None if len(rates) != len(grades) else (
                    sum(grade['rate'] * grade['students'] for grade in grades if grade['rate'] is not None) / students
                    if students else sum(rates) / len(rates) if rates else None
                )
            category['items'].append(item)
            if selected and amount is None:
                result['pending'] += 1
            if selected and amount is not None:
                for subtotal in (category, group, result):
                    subtotal['total'] += amount
        result['groups'] = [
            {**group, 'categories': list(group['categories'].values())}
            for group in groups.values()
        ]
        return result

    def create_detailed_expense_list(self):
        return self._create_detailed_list('expense')

    def create_detailed_income_list(self):
        return self._create_detailed_list('income')

    def delete_detailed_expense_list(self):
        self.ensure_one()
        self.check_access('write')
        if self.dataset_type != 'forecast' or not self.detailed_expenses_created or self.baseline_locked:
            raise ValidationError(self.env._('This detailed expense list cannot be deleted.'))
        prices = dict(self.detailed_allocated_prices or {})
        values = dict(self.detailed_occurrence_values or {})
        ids = {int(key) for key in prices.keys() | values.keys()}
        expense_ids = self.env['school.prediction.operational.seed'].with_context(active_test=False).search([
            ('id', 'in', list(ids)), ('category_seed_id.catalog_type', '=', 'expense'),
        ]).ids
        for seed_id in expense_ids:
            prices.pop(str(seed_id), None)
            values.pop(str(seed_id), None)
        self.write({
            'detailed_expenses_created': False,
            'expense_calculation_mode': 'no_details',
            'detailed_expense_seed_ids': [fields.Command.clear()],
            'detailed_allocated_prices': prices,
            'detailed_occurrence_values': values,
        })
        return self.get_detailed_expense_list()

    def _create_detailed_list(self, kind):
        self.ensure_one()
        self.check_access('write')
        if self.dataset_type != 'forecast':
            raise ValidationError(self.env._('Detailed estimates are available only for forecasts.'))
        field = 'detailed_expenses_created' if kind == 'expense' else 'detailed_incomes_created'
        if not self[field]:
            self.write({field: True})
        return self._get_detailed_list(kind)

    def set_detailed_expense_selection(self, seed_id, selected):
        return self._set_detailed_selection('expense', seed_id, selected)

    def set_detailed_income_selection(self, seed_id, selected):
        return self._set_detailed_selection('income', seed_id, selected)

    def _set_detailed_selection(self, kind, seed_id, selected):
        self.ensure_one()
        self.check_access('write')
        created = self.detailed_expenses_created if kind == 'expense' else self.detailed_incomes_created
        if self.dataset_type != 'forecast' or not created:
            raise ValidationError(self.env._('Create the detailed list first.'))
        seed = self._detailed_catalog(kind).filtered(lambda row: row.id == seed_id and not row.student_paid)
        if not seed:
            raise ValidationError(self.env._('This item is not available for this forecast.'))
        if kind == 'income' and selected and seed.replaces_tuition:
            raise ValidationError(self.env._('Tuition is included automatically from the forecast tuition fee rows.'))
        command = fields.Command.link if selected else fields.Command.unlink
        field = 'detailed_expense_seed_ids' if kind == 'expense' else 'detailed_income_seed_ids'
        self.write({field: [command(seed.id)]})
        return self._get_detailed_list(kind)

    def set_detailed_allocated_price(self, kind, seed_id, price):
        self.ensure_one()
        self.check_access('write')
        if kind not in ('income', 'expense') or self.dataset_type != 'forecast' or self.baseline_locked:
            raise ValidationError(self.env._('This forecast cannot be changed.'))
        seed = self._detailed_catalog(kind).filtered(lambda row: row.id == seed_id and row.price_type == 'allocated')
        if not seed or not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(price) or price < 0:
            raise ValidationError(self.env._('Enter a non-negative allocated price for an available item.'))
        prices = dict(self.detailed_allocated_prices or {})
        prices[str(seed.id)] = price
        self.write({'detailed_allocated_prices': prices})
        return self._get_detailed_list(kind)

    def set_detailed_occurrence_value(self, kind, seed_id, mode, value):
        self.ensure_one()
        self.check_access('write')
        if kind not in ('income', 'expense') or self.dataset_type != 'forecast' or self.baseline_locked:
            raise ValidationError(self.env._('This forecast cannot be changed.'))
        year = self.with_context(active_test=False)
        selected = year.detailed_income_seed_ids if kind == 'income' else year.detailed_expense_seed_ids
        seed = self._detailed_catalog(kind).filtered(lambda row: row.id == seed_id and row in selected and not row.student_paid)
        if not seed or mode not in ('seed', 'amount', 'revenue_percent'):
            raise ValidationError(self.env._('Select an available detailed item and amount type.'))
        values = dict(self.detailed_occurrence_values or {})
        if mode == 'seed':
            values.pop(str(seed.id), None)
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValidationError(self.env._('Enter a non-negative amount or revenue percentage.'))
            values[str(seed.id)] = {'mode': mode, 'value': value}
        self.write({'detailed_occurrence_values': values})
        return self._get_detailed_list(kind)

    def set_detailed_student_percentage(self, kind, seed_id, amount, percentage):
        self.ensure_one()
        self.check_access('write')
        if kind not in ('income', 'expense') or self.dataset_type != 'forecast' or self.baseline_locked:
            raise ValidationError(self.env._('This forecast cannot be changed.'))
        selected = self.with_context(active_test=False).detailed_income_seed_ids if kind == 'income' else self.with_context(active_test=False).detailed_expense_seed_ids
        values = dict(self.detailed_occurrence_values or {})
        seed = self._detailed_catalog(kind).filtered(
            lambda row: row.id == seed_id and row in selected and not row.student_paid
            and (row.basis == 'student_percent' or values.get(str(row.id), {}).get('mode') == 'student_percent')
        )
        if not seed:
            raise ValidationError(self.env._('Select an available item with the Per Student in % basis.'))
        values[str(seed.id)] = {'mode': 'student_percent', 'value': amount, 'percentage': percentage}
        self.write({'detailed_occurrence_values': values})
        return self._get_detailed_list(kind)

    def set_detailed_student_grade(self, seed_id, grade_id, amount):
        self.ensure_one()
        self.check_access('write')
        if self.dataset_type != 'forecast' or self.baseline_locked or not self.detailed_incomes_created:
            raise ValidationError(self.env._('This forecast cannot be changed.'))
        selected = self.with_context(active_test=False).detailed_income_seed_ids
        seed = self._detailed_catalog('income').filtered(
            lambda row: row.id == seed_id and row in selected and row.basis == 'student'
            and not row.replaces_tuition and not row.student_paid
        )
        if not seed or isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
            raise ValidationError(self.env._('Select a per-student income and enter a non-negative amount.'))
        grades = self._income_grade_levels(seed)
        if grade_id is not False and (type(grade_id) is not int or grade_id not in grades.ids):
            raise ValidationError(self.env._('This grade is outside the income seed grade scope.'))
        values = dict(self.detailed_occurrence_values or {})
        current = values.get(str(seed.id), {})
        if grade_id:
            if current.get('mode') == 'student_grade':
                default = current['value']
                rates = dict(current['grades'])
            else:
                total = next(self._detailed_expense_amounts(seed))[1]
                rows = self._student_income_grades(seed, total)
                default = next((row['rate'] for row in rows if row['rate'] is not None), None)
                rates = {}
            rates[str(grade_id)] = amount
        else:
            default, rates = amount, {}
        values[str(seed.id)] = {'mode': 'student_grade', 'value': default, 'grades': rates}
        self.write({'detailed_occurrence_values': values})
        return self._get_detailed_list('income')

    def set_detailed_tuition_grade(self, grade_id, amount):
        self.ensure_one()
        self.check_access('write')
        if self.dataset_type != 'forecast' or self.baseline_locked:
            raise ValidationError(self.env._('This forecast cannot be changed.'))
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
            raise ValidationError(self.env._('Enter a non-negative tuition amount.'))
        if grade_id is False:
            self.annual_fee_input = amount
        else:
            if type(grade_id) is not int or grade_id not in self._tuition_scope_grades().ids:
                raise ValidationError(self.env._('This grade is outside the tuition seed grade scope.'))
            rows = self._forecast_tuition_rows().filtered(lambda row: row.grade_level_id.id == grade_id)
            if not rows:
                fee_type = self.env['school.fee.types'].search([
                    ('school_id', '=', self.school_id.id), ('forecast_tuition', '=', True),
                ], order='display_order, id', limit=1)
                if not fee_type:
                    fee_type = self.env['school.fee.types'].create({
                        'school_id': self.school_id.id, 'name': 'Tuition Fee',
                        'display_order': 10, 'forecast_tuition': True,
                    })
                rows = self.env['school.fee.values'].create({
                    'academic_year_id': self.id, 'grade_level_id': grade_id,
                    'fee_type_id': fee_type.id, 'amount': 0,
                })
            previous = sum(rows.mapped('amount'))
            for row in rows:
                row.amount = amount * (row.amount / previous if previous else 1 / len(rows))
        return self._get_detailed_list('income')
