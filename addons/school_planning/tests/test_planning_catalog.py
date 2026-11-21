from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPlanningCatalog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env.ref('school_planning.prediction_seed_configuration')
        cls.school = cls.env['school.schools'].create({'name': 'Catalog school', 'currency': 'EUR'})
        cls.years = cls.env['school.academic.years'].create([
            {'school_id': cls.school.id, 'academic_year_name': f'{start}-{start + 1}',
             'start_date': f'{start}-09-01', 'end_date': f'{start + 1}-06-30', 'dataset_type': 'forecast'}
            for start in (2041, 2042)
        ])

    def item(self, name, kind):
        return self.config.operational_seed_ids.filtered(
            lambda row: row.name == name and row.category_seed_id.catalog_type == kind
        ).ensure_one()

    def test_hierarchy_and_price_types(self):
        income_tax = self.item('Income Taxes', 'expense')
        self.assertEqual(income_tax.category_seed_id.name, 'Tax Payments')
        self.assertEqual(income_tax.category_seed_id.parent_id.name, 'Official Payments')
        self.assertEqual(income_tax.price_type, 'allocated')
        self.assertEqual(self.item('Internet Bills', 'expense').price_type, 'fixed')
        self.assertEqual(self.item('School License Renewal', 'expense').category_seed_id.price_type, 'fixed')
        self.assertEqual(self.item('Activity fees', 'income').category_seed_id.name, 'Other Incomes')
        self.assertEqual(self.item('Tuition Fees', 'income').price_type, 'fixed')
        self.assertFalse(self.env.ref('school_planning.operational_digital_ixl').active)
        with self.assertRaises(ValidationError):
            income_tax.category_seed_id.parent_id.parent_id = income_tax.category_seed_id

    def test_allocations_are_year_specific_and_fixed_is_not_overridable(self):
        first, second = self.years
        income = self.item('Admission Exam Fees', 'income')
        expense = self.item('Income Taxes', 'expense')
        fixed = self.item('Tuition Fees', 'income')
        fixed.write({'price': 100, 'price_set': True, 'currency_id': self.school.currency_id.id})
        baseline = (first.fee_gross_total, first.expense_total)
        for year in self.years:
            year.create_detailed_income_list()
            year.create_detailed_expense_list()
            year.set_detailed_income_selection(income.id, True)
            year.set_detailed_income_selection(fixed.id, True)
            year.set_detailed_expense_selection(expense.id, True)
        first.set_detailed_allocated_price('income', income.id, 25)
        first.set_detailed_allocated_price('expense', expense.id, 12)
        second.set_detailed_allocated_price('income', income.id, 40)
        self.assertEqual(first.get_detailed_income_list()['total'], 125)
        self.assertEqual(second.get_detailed_income_list()['total'], 140)
        self.assertEqual(first.get_detailed_expense_list()['total'], 12)
        self.assertEqual((first.fee_gross_total, first.expense_total), baseline)
        with self.assertRaises(ValidationError):
            first.set_detailed_allocated_price('income', fixed.id, 50)
        with self.assertRaises(ValidationError):
            fixed.write({'price': 101})
        with self.assertRaises(ValidationError):
            fixed.write({'price_type': 'allocated'})
        with self.assertRaises(ValidationError):
            fixed.unlink()
        with self.assertRaises(ValidationError):
            first.set_detailed_allocated_price('expense', expense.id, -1)
        with self.assertRaises(ValidationError):
            first.set_detailed_income_selection(expense.id, True)
        first.action_freeze_baseline()
        with self.assertRaises(ValidationError):
            first.set_detailed_allocated_price('income', income.id, 10)

    def test_archived_selected_item_remains_visible(self):
        year = self.years[0]
        old = self.env.ref('school_planning.operational_digital_ixl')
        self.school.curriculum_ids = [fields.Command.link(self.env.ref('school_planning.curriculum_us_standards').id)]
        old.write({'price': 20, 'price_set': True, 'basis': 'fixed', 'currency_id': self.school.currency_id.id})
        year.write({'detailed_expenses_created': True, 'detailed_expense_seed_ids': [fields.Command.link(old.id)]})
        data = year.get_detailed_expense_list()
        self.assertEqual(data['total'], 20)
        self.assertIn(old.id, [item['id'] for group in data['groups'] for category in group['categories'] for item in category['items']])

    def test_catalog_replacement_preserves_existing_selections(self):
        year = self.years[0]
        old = self.item('Income Taxes', 'expense')
        year.create_detailed_expense_list()
        year.set_detailed_expense_selection(old.id, True)
        year.set_detailed_allocated_price('expense', old.id, 75)
        self.config._install_planning_catalog()
        self.assertFalse(old.active)
        self.assertEqual(year.get_detailed_expense_list()['total'], 75)
        self.assertNotIn(old, self.years[1]._detailed_expense_catalog())

    def test_occurrence_overrides_and_revenue_percentage(self):
        first, second = self.years
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grade = self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        self.env['school.grade.enrollment'].create({
            'academic_year_id': first.id, 'grade_level_id': grade.id, 'student_count': 10,
        })
        fee_type = self.env['school.fee.types'].create({'school_id': self.school.id, 'name': 'Test fee', 'display_order': 1})
        fee = self.env['school.fee.values'].create({
            'academic_year_id': first.id, 'grade_level_id': grade.id, 'fee_type_id': fee_type.id, 'amount': 100,
        })
        first.prediction_income_tax_percent = 50
        self.assertEqual(first.fee_gross_total, 1000)
        self.assertEqual(first.fee_total, 500)

        fixed = self.item('Tuition Fees', 'income')
        fixed.write({'price': 100, 'price_set': True, 'currency_id': self.school.currency_id.id})
        expense = self.item('Income Taxes', 'expense')
        for year in self.years:
            year.create_detailed_income_list()
            year.create_detailed_expense_list()
            year.set_detailed_income_selection(fixed.id, True)
            year.set_detailed_expense_selection(expense.id, True)
        first.set_detailed_allocated_price('expense', expense.id, 12)
        first.set_detailed_occurrence_value('income', fixed.id, 'amount', 75)
        first.set_detailed_occurrence_value('expense', expense.id, 'amount', 40)
        self.assertEqual(first.get_detailed_income_list()['total'], 75)
        self.assertEqual(first.get_detailed_expense_list()['total'], 40)
        self.assertEqual(second.get_detailed_income_list()['total'], 100)
        self.assertEqual(fixed.price, 100)
        first.set_detailed_occurrence_value('income', fixed.id, 'revenue_percent', 5)
        first.set_detailed_occurrence_value('expense', expense.id, 'revenue_percent', 10)
        self.assertEqual(first.get_detailed_income_list()['total'], 50)
        self.assertEqual(first.get_detailed_expense_list()['total'], 100)
        self.assertEqual(self.school._chart_breakdowns(first)['expense_category_spend'], [
            {'label': 'Tax Payments', 'value': 100},
        ])
        fee.amount = 200
        self.assertEqual(first.get_detailed_expense_list()['total'], 200)
        self.assertEqual(first.get_detailed_income_list()['total'], 100)
        self.assertEqual(first.expense_total, 0)
        first.set_detailed_occurrence_value('expense', expense.id, 'seed', None)
        self.assertEqual(first.get_detailed_expense_list()['total'], 12)

    def test_occurrence_validation_and_frozen_forecasts(self):
        year = self.years[0]
        item = self.item('Tuition Fees', 'income')
        year.create_detailed_income_list()
        with self.assertRaises(ValidationError):
            year.set_detailed_occurrence_value('income', item.id, 'amount', 10)
        year.set_detailed_income_selection(item.id, True)
        for mode, value in [('amount', -1), ('revenue_percent', float('nan')), ('amount', True), ('other', 5)]:
            with self.subTest(mode=mode, value=value), self.assertRaises(ValidationError):
                year.set_detailed_occurrence_value('income', item.id, mode, value)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            year.write({'detailed_occurrence_values': {str(item.id): {'mode': 'amount', 'value': -1}}})
        self.assertEqual(year.set_detailed_occurrence_value('income', item.id, 'revenue_percent', 125)['total'], 0)
        year.action_freeze_baseline()
        with self.assertRaises(ValidationError):
            year.set_detailed_occurrence_value('income', item.id, 'amount', 20)

    def test_forecast_expense_tax_percentage_is_year_specific_and_not_double_counted(self):
        first, second = self.years
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grade = self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        fee_type = self.env['school.fee.types'].create({'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1})
        for year in self.years:
            self.env['school.grade.enrollment'].create({
                'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 10,
            })
            self.env['school.fee.values'].create({
                'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': fee_type.id, 'amount': 100,
            })
        first.prediction_income_tax_percent = 12
        self.assertEqual(first.tax_deductions_total, 120)
        self.assertEqual(first.fee_total, 880)
        self.assertEqual(first.expense_total, 0)
        self.assertEqual(first.net_budget, 880)
        self.assertEqual(second.tax_deductions_total, 0)
        for percentage in (-1, 101, float('nan'), float('inf')):
            with self.subTest(percentage=percentage), self.assertRaises(ValidationError), self.cr.savepoint():
                first.prediction_income_tax_percent = percentage
        first.action_freeze_baseline()
        with self.assertRaises(ValidationError):
            first.prediction_income_tax_percent = 15
