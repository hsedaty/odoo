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
    active = fields.Boolean(default=True)
    grade_ids = fields.Many2many('school.grade.level.preset', 'school_operational_seed_grade_rel', string='Grades')

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

    operational_seed_ids = fields.One2many('school.prediction.operational.seed', 'configuration_id', string='Detailed Expense Seeds')


class AcademicYears(models.Model):
    _inherit = 'school.academic.years'

    operational_estimate_details = fields.Text(string='Expense Estimate Comparison', readonly=True, copy=False)
    detailed_expenses_created = fields.Boolean(copy=False)
    detailed_expense_seed_ids = fields.Many2many(
        'school.prediction.operational.seed', 'school_year_operational_seed_rel', copy=False,
    )

    def _detailed_expense_catalog(self):
        codes = set(self.school_id.curriculum_ids.mapped('code'))
        names = {name.casefold() for name in self.school_id.curriculum_ids.mapped('name')}
        names.update(label for code, label in (
            ('US', 'american'), ('IB_PYP', 'ib pyp'), ('IB_MYP', 'ib myp'), ('IB_DP', 'ib dp'),
        ) if code in codes)
        if any(code.startswith('IB_') for code in codes):
            names.add('ib')
        config = self.env.ref('school_planning.prediction_seed_configuration')
        return config.operational_seed_ids.filtered(
            lambda seed: seed.category_seed_id.active and seed.category_seed_id.is_detailed_category
            and (not seed.curriculum or seed.curriculum.strip().casefold() in names)
        )

    def _detailed_expense_amount(self, seed, currency, rate_ids, date):
        if seed.student_paid:
            return 0.0, self.env._('Paid by students')
        if not seed.price_set or not seed.basis or not seed.currency_id:
            return None, self.env._('Price needed in seed')
        if seed.basis in ('teacher', 'quantity') and not seed.quantity_set:
            return None, self.env._('Quantity needed in seed')
        quantity = seed.quantity if seed.basis in ('teacher', 'quantity') else 1
        if seed.grade_scope == 'selected' and not seed.grade_ids:
            return None, self.env._('Grades needed in seed')
        if seed.basis == 'student':
            grades = {name.strip().casefold() for name in seed.grade_ids.mapped('name')}
            quantity = sum(row.student_count for row in self.enrollment_ids
                           if seed.grade_scope == 'all' or row.grade_level_id.name.strip().casefold() in grades)
        amount = seed.price * quantity
        if amount and seed.currency_id != currency:
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
        self.ensure_one()
        self.check_access('read')
        if self.dataset_type != 'forecast':
            raise ValidationError(self.env._('Detailed expense estimates are available only for forecasts.'))
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
        result = {
            'created': self.detailed_expenses_created, 'locked': self.baseline_locked,
            'baseline': self.expense_total, 'currency': currency.id, 'groups': [], 'total': 0.0, 'pending': 0,
            'baseline_ratio': self.expense_total / revenue if revenue > 0 else None,
            'baseline_ratio_basis': self.env._('of revenue after tax') if basis == 'net' else self.env._('of revenue before tax'),
        }
        if not self.detailed_expenses_created:
            return result
        selected_ids = set(self.detailed_expense_seed_ids.ids)
        groups = {}
        catalog = self._detailed_expense_catalog().sorted(
            lambda seed: (seed.category_seed_id.display_order, seed.category_seed_id.id, seed.name)
        )
        for seed, amount, note in self._detailed_expense_amounts(catalog):
            name = seed.curriculum or self.env._('All Curricula')
            group = groups.setdefault(name, {'name': name, 'total': 0.0, 'categories': {}})
            category = group['categories'].setdefault(seed.category_seed_id.id, {
                'id': seed.category_seed_id.id, 'name': seed.category_seed_id.name, 'total': 0.0, 'items': [],
            })
            selected = seed.id in selected_ids
            category['items'].append({
                'id': seed.id, 'name': seed.name, 'amount': amount, 'note': note,
                'selected': selected, 'student_paid': seed.student_paid,
            })
            if selected and amount is None:
                result['pending'] += 1
            if selected and amount is not None:
                for subtotal in (category, group, result):
                    subtotal['total'] += amount
        result['groups'] = [
            {**group, 'categories': list(group['categories'].values())}
            for _, group in sorted(groups.items())
        ]
        return result

    def create_detailed_expense_list(self):
        self.ensure_one()
        self.check_access('write')
        if self.dataset_type != 'forecast':
            raise ValidationError(self.env._('Detailed expense estimates are available only for forecasts.'))
        if not self.detailed_expenses_created:
            self.write({'detailed_expenses_created': True})
        return self.get_detailed_expense_list()

    def set_detailed_expense_selection(self, seed_id, selected):
        self.ensure_one()
        self.check_access('write')
        if self.dataset_type != 'forecast' or not self.detailed_expenses_created:
            raise ValidationError(self.env._('Create the detailed expense list first.'))
        seed = self._detailed_expense_catalog().filtered(lambda row: row.id == seed_id and not row.student_paid)
        if not seed:
            raise ValidationError(self.env._('This expense is not available for this forecast.'))
        command = fields.Command.link if selected else fields.Command.unlink
        self.write({'detailed_expense_seed_ids': [command(seed.id)]})
        return self.get_detailed_expense_list()
