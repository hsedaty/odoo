import base64
from datetime import date
from pathlib import Path
from runpy import run_path
from unittest.mock import patch
from types import SimpleNamespace

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools.convert import convert_file

from ..models.forecast_actual import ACTUAL_TOOLS


@tagged('post_install', '-at_install')
class TestQuickPrediction(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.configuration = cls.env.ref('school_planning.prediction_seed_configuration')
        cls.configuration.write({'students_per_classroom': 25, 'classroom_weekly_hours': 35, 'teacher_weekly_hours': 20,
                     'infrastructure_mode': 'existing', 'payroll_start_year_index': 1,
                     'payroll_trend': 'revenue_decrease', 'payroll_base_annual_amount': 50,
                     'payroll_annual_change_percent': 3})
        cls.configuration.asset_ids.write({'unit_price': 0, 'quantity': 1})
        cls.configuration.expense_ids.filtered(lambda seed: not seed.is_detailed_category).unlink()
        cls.env['school.prediction.seed.expense'].create([
            {'configuration_id': cls.configuration.id, 'name': 'Manual Expenses', 'cost_bucket': 'operating',
             'trend': 'revenue_decrease', 'base_annual_amount': 30, 'annual_change_percent': 3},
        ])
        cls.school = cls.env['school.schools'].create({
            'name': 'Quick Prediction Test School', 'currency': 'EGP',
        })
        cls.env['school.subjects'].create({
            'name': 'Mathematics', 'school_id': cls.school.id, 'display_order': 1,
        })

    def _wizard(self, extreme=False):
        return self.env['school.prediction.quick.setup.wizard'].create({
            'school_id': self.school.id, 'extreme_efficiency': extreme,
        })

    def test_price_currency_picker_actions(self):
        currency = self.env['res.currency'].create({'name': 'XTS', 'symbol': 'T'})
        planner = new_test_user(self.env, login='currency_picker_planner', groups='base.group_user')
        with self.assertRaises(AccessError):
            currency.with_user(planner).action_school_edit_price_currency()
        with self.assertRaises(AccessError):
            currency.with_user(planner).action_school_delete_price_currency()
        self.assertEqual(currency.action_school_edit_price_currency()['res_id'], currency.id)
        seed = self.env.ref('school_planning.operational_digital_ixl')
        seed.currency_id = currency
        with self.assertRaisesRegex(ValidationError, 'expense seed'):
            currency.action_school_delete_price_currency()
        self.assertEqual(seed.currency_id, currency)
        seed.currency_id = False
        currency.action_school_delete_price_currency()
        self.assertFalse(currency.exists())

    def test_quick_prediction_only_forecasts_revenue_percentages(self):
        seed = self.configuration.expense_ids.filtered(lambda row: not row.is_detailed_category)
        seed.write({'name': 'All Expenses', 'trend': 'revenue_after_tax_decrease'})
        self.env['school.prediction.seed.expense'].create([
            {'configuration_id': self.configuration.id, 'name': 'Legacy fixed cost',
             'trend': 'stable', 'base_annual_amount': 900},
            {'configuration_id': self.configuration.id, 'name': 'Legacy breakdown',
             'input_mode': 'detail', 'trend': 'revenue_stable', 'base_annual_amount': 10},
        ])
        for extreme in (False, True):
            with self.subTest(extreme=extreme):
                wizard = self._wizard(extreme)
                wizard.line_ids.write({'student_count': 100, 'annual_fee_per_student': 100})
                wizard.income_tax_percent = 10
                self.assertEqual(wizard._active_repeating_expenses().seed_id, seed)
                self.env['school.prediction.quick.setup.one.time.expense.line'].create({
                    'wizard_id': wizard.id, 'name': seed.name, 'year_index': 2, 'amount': 500,
                })
                self.env['school.prediction.quick.setup.repeating.expense.line'].create({
                    'wizard_id': wizard.id, 'name': 'Legacy per-student cost',
                    'input_mode': 'extreme' if extreme else 'normal', 'trend': 'per_student',
                    'base_annual_amount': 5,
                })
                wizard.replace_existing_payroll = True
                wizard.action_apply()
                self.assertEqual(wizard._existing_forecast_years().mapped('expense_total'), [2700, 2430, 2160])
                for year, rate in zip(wizard._existing_forecast_years(), (0.30, 0.27, 0.24)):
                    self.assertAlmostEqual(year.get_detailed_expense_list()['baseline_ratio'], rate)
                    self.assertEqual(year.get_detailed_expense_list()['baseline_ratio_basis'], 'of revenue after tax')
                year.write({'prediction_expense_revenue_basis': False})
                self.assertAlmostEqual(year.get_detailed_expense_list()['baseline_ratio'], 0.24)

    def test_quick_predictions_are_independent_per_branch(self):
        branches = self.env['school.schools'].create([
            {'name': name, 'parent_school_id': self.school.id, 'currency': 'EGP'}
            for name in ('North', 'South')
        ])
        for branch, count in zip(branches, (100, 200)):
            self.env['school.subjects'].create({
                'name': 'Mathematics', 'school_id': branch.id, 'display_order': 1,
            })
            self.assertEqual(branch.action_open_quick_prediction()['context']['default_school_id'], branch.id)
            wizard = self.env['school.prediction.quick.setup.wizard'].create({'school_id': branch.id})
            wizard.line_ids.write({'student_count': count, 'annual_fee_per_student': 100})
            wizard.action_apply()
            self.assertEqual(wizard._existing_forecast_years().mapped('school_id'), branch)
            self.assertEqual(wizard._existing_forecast_years().mapped('total_enrolled_students'), [count] * 3)
        combined = self.school.get_dashboard(self.school.id)
        self.assertEqual(len(combined['rows']), 6)
        self.assertEqual(combined['totals']['students'], 300)
        for branch, count in zip(branches, (100, 200)):
            self.assertEqual(branch.get_dashboard(branch.id)['totals']['students'], count)

    def test_deleted_default_percentage_seed_stays_deleted(self):
        # setUpClass removed the installed default and set up a custom percentage instead.
        convert_file(self.env, 'school_planning', 'data/prediction_seed_configuration.xml', {}, mode='update')
        self.assertFalse(self.env.ref('school_planning.prediction_seed_operations', raise_if_not_found=False))
        self.assertEqual(self._wizard().repeating_expense_line_ids.seed_id,
                         self.configuration.expense_ids.filtered(lambda row: not row.is_detailed_category))

    def test_financial_summary_detailed_expenses_are_optional_and_year_specific(self):
        self.school.write({
            'currency_id': self.env.company.currency_id.id,
            'curriculum_ids': [fields.Command.link(self.env.ref('school_planning.curriculum_us_standards').id)],
        })
        wizard = self._wizard()
        wizard.line_ids.write({'student_count': 100, 'annual_fee_per_student': 100})
        wizard.action_apply()
        first, second = wizard._existing_forecast_years()[:2]
        self.assertFalse(first.get_detailed_expense_list()['created'])
        self.assertEqual(first.get_detailed_expense_list()['baseline'], 3000)
        self.assertAlmostEqual(first.get_detailed_expense_list()['baseline_ratio'], 0.30)
        self.assertEqual(first.get_detailed_expense_list()['baseline_ratio_basis'], 'of revenue before tax')

        accreditation = self.configuration.operational_seed_ids.filtered(lambda row: row.name == 'Cognia Candidacy Fee')
        accreditation.category_seed_id.detailed_schedule_required = True
        accreditation.write({'currency_id': self.school.currency_id.id, 'price': 2500, 'price_set': True,
                             'frequency': 'once', 'start_year_index': 2})
        digital = self.configuration.operational_seed_ids.filtered(lambda row: row.name == 'IXL')
        digital.write({'currency_id': self.school.currency_id.id, 'basis': 'student', 'price': 5, 'price_set': True})
        foreign = self.env.ref('school_planning.operational_digital_inthinking')
        missing = self.configuration.operational_seed_ids.filtered(lambda row: row.name == 'HMH')
        data = first.create_detailed_expense_list()
        self.assertIn('Official Payments', [group['name'] for group in data['groups']])
        self.assertEqual(data['total'], 0)
        with self.assertRaises(ValidationError):
            first.set_detailed_expense_selection(foreign.id, True)
        self.assertEqual(first.set_detailed_expense_selection(accreditation.id, True)['total'], 2500)
        self.assertEqual(first.set_detailed_expense_selection(digital.id, True)['total'], 3000)
        self.assertEqual(first.set_detailed_expense_selection(missing.id, True)['pending'], 1)
        self.assertEqual(first.create_detailed_expense_list()['total'], 3000)
        self.assertFalse(second.get_detailed_expense_list()['created'])
        accreditation.frequency = False
        self.assertEqual(second.create_detailed_expense_list()['total'], 0)
        self.assertEqual(second.set_detailed_expense_selection(accreditation.id, True)['total'], 2500)
        self.assertEqual(first.set_detailed_expense_selection(digital.id, False)['total'], 2500)
        self.assertEqual(first.set_detailed_expense_selection(accreditation.id, False)['total'], 0)
        self.assertEqual(second.get_detailed_expense_list()['total'], 2500)
        self.assertEqual(first.expense_total, 3000)
        self.assertEqual(second.expense_total, 2700)
        first.action_freeze_baseline()
        with self.assertRaises(ValidationError):
            first.set_detailed_expense_selection(digital.id, True)

    def test_detailed_expense_category_seeds_are_charted_without_posting(self):
        wizard = self._wizard()
        wizard.line_ids.write({'student_count': 100, 'annual_fee_per_student': 100})
        wizard.action_apply()
        year = wizard._existing_forecast_years()[0]
        self.assertEqual(self.env.ref('school_planning.operational_digital_ixl').category_seed_id.name, 'Digital Resources')
        with Form(self.configuration, view='school_planning.view_prediction_seed_configuration_form') as form:
            with form.expense_ids.new() as category_form:
                category_form.name = 'IT Support'
                category_form.is_detailed_category = True
        category = self.configuration.expense_ids.filtered(lambda row: row.name == 'IT Support')
        with Form(self.configuration, view='school_planning.view_prediction_seed_configuration_form') as form:
            with form.operational_seed_ids.new() as item_form:
                item_form.name = 'Support Retainer'
                item_form.category_seed_id = category
                item_form.basis = 'fixed'
                item_form.price = 880
                item_form.currency_id = self.school.currency_id or self.env.company.currency_id
                item_form.price_set = True
        item = self.configuration.operational_seed_ids.filtered(lambda row: row.name == 'Support Retainer')
        self.assertNotIn(category, self._wizard().repeating_expense_line_ids.seed_id)
        year.create_detailed_expense_list()
        data = year.set_detailed_expense_selection(item.id, True)
        self.assertIn('IT Support', [category['name'] for group in data['groups'] for category in group['categories']])
        dashboard = self.school.get_dashboard(school_id=self.school.id, year_id=year.id)
        self.assertIn('detailed_expense_category_spend', [metric['key'] for metric in dashboard['breakdown_metrics']])
        breakdowns = dashboard['breakdowns']
        self.assertEqual(breakdowns['detailed_expense_category_spend'], [{'label': 'IT Support', 'value': 880}])
        self.assertEqual(breakdowns['expense_category_spend'], [{'label': 'IT Support', 'value': 880}])
        year.set_detailed_expense_selection(item.id, False)
        self.assertFalse(self.school._chart_breakdowns(year)['detailed_expense_category_spend'])

    def test_expense_chart_switches_per_year_without_double_counting(self):
        self.school.write({
            'currency_id': self.env.company.currency_id.id,
            'curriculum_ids': [fields.Command.link(self.env.ref('school_planning.curriculum_us_standards').id)],
        })
        wizard = self._wizard()
        wizard.line_ids.write({'student_count': 100, 'annual_fee_per_student': 100})
        wizard.action_apply()
        first, second = wizard._existing_forecast_years()[:2]
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Other expenses', 'display_order': 20,
        })
        self.env['school.expense.values'].create({
            'academic_year_id': first.id, 'expense_category_id': category.id, 'amount': 100,
        })
        digital = self.configuration.operational_seed_ids.filtered(lambda row: row.name == 'IXL')
        digital.write({'currency_id': self.school.currency_id.id, 'basis': 'student', 'price': 5, 'price_set': True})
        accreditation = self.configuration.operational_seed_ids.filtered(lambda row: row.name == 'Cognia Candidacy Fee')
        accreditation.write({'currency_id': self.school.currency_id.id, 'price': 2500, 'price_set': True})
        missing = self.configuration.operational_seed_ids.filtered(lambda row: row.name == 'HMH')
        missing.price_set = False

        before = self.school.get_dashboard(school_id=self.school.id, year_id=first.id)
        self.assertFalse(before['expense_breakdown_uses_details'])
        self.assertEqual(before['breakdowns']['expense_category_spend'], [
            {'label': 'Manual Expenses', 'value': 3000},
            {'label': 'Other expenses', 'value': 100},
        ])
        first.create_detailed_expense_list()
        self.assertEqual(self.school._chart_breakdowns(first)['expense_category_spend'], [
            {'label': 'Other expenses', 'value': 100},
        ])
        first.set_detailed_expense_selection(digital.id, True)
        first.set_detailed_expense_selection(accreditation.id, True)
        first.set_detailed_expense_selection(missing.id, True)
        data = self.school.get_dashboard(school_id=self.school.id, year_id=first.id)
        self.assertTrue(data['expense_breakdown_uses_details'])
        self.assertEqual(data['breakdowns']['expense_category_spend'], [
            {'label': 'Accreditation Fees', 'value': 2500},
            {'label': 'Digital Resource Expenses', 'value': 500},
            {'label': 'Other expenses', 'value': 100},
        ])
        self.assertEqual(first.get_detailed_expense_list()['pending'], 1)
        self.assertEqual(self.school._chart_breakdowns(first | second)['expense_category_spend'], [
            {'label': 'Accreditation Fees', 'value': 2500},
            {'label': 'Digital Resource Expenses', 'value': 500},
            {'label': 'Other expenses', 'value': 100},
        ])
        first.set_detailed_expense_selection(digital.id, False)
        self.assertEqual(self.school._chart_breakdowns(first)['expense_category_spend'], [
            {'label': 'Accreditation Fees', 'value': 2500},
            {'label': 'Other expenses', 'value': 100},
        ])
        self.assertEqual(first.expense_total, 3100)

    def test_subject_setup_american_manual_selection(self):
        existing_subjects = self.school.subject_ids
        form = Form(self.env['school.subject.setup.wizard'].with_context(default_school_id=self.school.id))
        form.curriculum_id = self.env.ref('school_planning.curriculum_us_standards')
        self.assertFalse(form.subject_preset_ids)

        selected_subject = self.env.ref('school_planning.subject_us_ela')
        form.subject_preset_ids.add(selected_subject)
        wizard = form.save()
        self.assertEqual(self.school.subject_ids, existing_subjects)
        wizard.action_apply()

        self.assertEqual(existing_subjects.exists(), existing_subjects)
        self.assertEqual((self.school.subject_ids - existing_subjects).mapped('name'), [selected_subject.name])

    def test_subject_setup_other_curricula_auto_load(self):
        form = Form(self.env['school.subject.setup.wizard'].with_context(default_school_id=self.school.id))
        for xmlid in ('curriculum_england', 'curriculum_ib_pyp', 'curriculum_ib_myp', 'curriculum_ib_dp'):
            with self.subTest(curriculum=xmlid):
                curriculum = self.env.ref(f'school_planning.{xmlid}')
                form.curriculum_id = curriculum
                self.assertEqual(form.subject_preset_ids[:], curriculum.subject_preset_ids)

    def test_subject_setup_curriculum_switching(self):
        form = Form(self.env['school.subject.setup.wizard'].with_context(default_school_id=self.school.id))
        cambridge = self.env.ref('school_planning.curriculum_england')
        form.curriculum_id = cambridge
        self.assertTrue(form.subject_preset_ids)

        form.curriculum_id = self.env.ref('school_planning.curriculum_us_standards')
        self.assertFalse(form.subject_preset_ids)
        form.subject_preset_ids.add(self.env.ref('school_planning.subject_us_ela'))

        form.curriculum_id = cambridge
        self.assertEqual(form.subject_preset_ids[:], cambridge.subject_preset_ids)
        form.curriculum_id = self.env['school.curriculum.preset']
        self.assertFalse(form.subject_preset_ids)

    def test_subject_catalog_edits_are_reusable(self):
        env = self.env(context={**self.env.context, 'no_reset_password': True})
        manager = new_test_user(env, login='curriculum_catalog_admin', groups='base.group_system')
        planner = new_test_user(env, login='curriculum_catalog_planner', groups='base.group_user')
        american = self.env.ref('school_planning.curriculum_us_standards')
        catalog = self.env['school.subject.preset'].with_user(manager)
        subject = catalog.create({'name': 'Arabic Language', 'curriculum_id': american.id})
        subject.name = 'Arabic'
        with self.assertRaises(AccessError):
            subject.with_user(planner).name = 'Unauthorized edit'
        with self.assertRaises(AccessError):
            subject.with_user(planner).unlink()

        model = self.env['school.subject.setup.wizard'].with_user(planner).with_context(default_school_id=self.school.id)
        form = Form(model)
        form.curriculum_id = american
        self.assertFalse(form.subject_preset_ids)
        form.subject_preset_ids.add(subject.with_user(planner))
        wizard = form.save()
        wizard.action_apply()
        self.assertIn('Arabic', self.school.subject_ids.mapped('name'))

        subject.action_archive()
        self.assertNotIn(subject, american.subject_preset_ids)
        self.assertIn('Arabic', self.school.subject_ids.mapped('name'))
        with self.assertRaises(ValidationError):
            wizard.action_apply()

        subject.unlink()
        self.assertFalse(subject.exists())
        self.assertIn('Arabic', self.school.subject_ids.mapped('name'))

    def test_category_total_includes_items(self):
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Inclusive category total', 'display_order': 10,
        })
        item = self.env['school.expense.items'].create({
            'school_id': self.school.id, 'expense_category_id': category.id,
            'name': 'Included item', 'display_order': 10,
        })
        year = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': '2098-2099',
            'start_date': '2098-09-01', 'end_date': '2099-06-30', 'dataset_type': 'actual',
        })
        rows = self.env['school.expense.values'].create([
            {'academic_year_id': year.id, 'expense_category_id': category.id, 'amount': 1000},
            {'academic_year_id': year.id, 'expense_item_id': item.id, 'amount': 250},
        ])
        self.assertEqual(year.expense_total, 1000)
        self.assertEqual(year.operating_cost_total, 1000)
        self.assertEqual(sum(rows.mapped('total_contribution')), 1000)
        rows.filtered(lambda row: not row.expense_item_id).amount = 0
        self.assertEqual(year.expense_total, 250)
        self.assertEqual(sum(rows.mapped('total_contribution')), 250)
        rows.filtered('expense_item_id').amount = 400
        self.assertEqual(year.expense_total, 400)
        rows.filtered(lambda row: not row.expense_item_id).amount = 600
        self.assertEqual(year.expense_total, 600)
        self.assertEqual(self.env['school.expense.values']._read_group(
            [('academic_year_id', '=', year.id)], aggregates=['total_contribution:sum'])[0][0], 600)

    def test_payroll_category_total_includes_items(self):
        year = self._wizard()._ensure_academic_years(1)[0]
        year.write({'payroll_summary_enabled': True, 'payroll_basis': 'amount'})
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Payroll total', 'display_order': 10, 'cost_bucket': 'employee',
        })
        item = self.env['school.expense.items'].create({
            'school_id': self.school.id, 'expense_category_id': category.id,
            'name': 'Included benefits', 'display_order': 10,
        })
        rows = self.env['school.expense.values'].create([
            {'academic_year_id': year.id, 'expense_category_id': category.id, 'amount': 1000},
            {'academic_year_id': year.id, 'expense_item_id': item.id, 'amount': 250},
        ])
        self.assertEqual(year.payroll_fixed_amount, 1000)
        self.assertEqual(year.employee_cost_total, 1000)
        self.assertEqual(year.operating_cost_total, 1000)
        other_category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Other payroll', 'display_order': 20, 'cost_bucket': 'employee',
        })
        other_item = self.env['school.expense.items'].create({
            'school_id': self.school.id, 'expense_category_id': other_category.id,
            'name': 'Separate benefits', 'display_order': 10,
        })
        child = rows.filtered('expense_item_id')
        child.expense_item_id = other_item
        self.assertEqual(year.payroll_fixed_amount, 1250)
        child.expense_item_id = item
        self.assertEqual(year.payroll_fixed_amount, 1000)
        rows.filtered('expense_item_id').amount = 500
        self.assertEqual(year.payroll_fixed_amount, 1000)
        rows.filtered(lambda row: not row.expense_item_id).amount = 0
        self.assertEqual(year.payroll_fixed_amount, 500)
        year._onchange_payroll_expense_amounts()
        self.assertEqual(year.payroll_fixed_amount, 500)
        rows.filtered('expense_item_id').unlink()
        self.assertEqual(year.payroll_fixed_amount, 0)

    def test_category_total_upgrade_preserves_inputs(self):
        years = self._wizard()._ensure_academic_years(3)
        years.write({'payroll_summary_enabled': True, 'payroll_basis': 'amount'})
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Upgrade payroll total', 'display_order': 10, 'cost_bucket': 'employee',
        })
        item = self.env['school.expense.items'].create({
            'school_id': self.school.id, 'expense_category_id': category.id,
            'name': 'Upgrade breakdown', 'display_order': 10,
        })
        for year in years:
            self.env['school.expense.values'].create([
                {'academic_year_id': year.id, 'expense_category_id': category.id, 'amount': 1000},
                {'academic_year_id': year.id, 'expense_item_id': item.id, 'amount': 250},
            ])
        years[0].payroll_fixed_amount = 1250
        years[1].payroll_fixed_amount = 1777
        years[2].payroll_fixed_amount = 1250
        years[2].action_freeze_baseline()
        frozen_totals = dict(years[2].baseline_totals)
        values_before = years.expense_value_ids.mapped('amount')
        self.env.flush_all()
        self.cr.execute('UPDATE school_expense_values SET total_contribution = amount WHERE id IN %s',
                [tuple(years.expense_value_ids.ids)])
        years.expense_value_ids.invalidate_recordset(['total_contribution'])
        migration = run_path(str(Path(__file__).parents[1] / 'migrations' / '19.0.1.35.0' / 'post-migrate.py'))
        values = years.expense_value_ids
        year_search = type(years).search
        value_search = type(values).search

        def search_years(model, domain, *args, **kwargs):
            return year_search(model, domain or [('school_id', '=', self.school.id)], *args, **kwargs)

        def search_values(model, domain, *args, **kwargs):
            return value_search(model, domain or [('academic_year_id.school_id', '=', self.school.id)], *args, **kwargs)

        with patch.object(type(years), 'search', search_years), patch.object(type(values), 'search', search_values):
            for _iteration in range(2):
                migration['migrate'](self.cr, '19.0.1.34.0')
                self.assertEqual(years[0].payroll_fixed_amount, 1000)
                self.assertEqual(years[1].payroll_fixed_amount, 1777)
                self.assertEqual(years[2].payroll_fixed_amount, 1250)
                self.assertEqual(years[2].baseline_totals, frozen_totals)
                self.assertEqual(years.expense_value_ids.mapped('amount'), values_before)
                self.assertEqual(sum(years.expense_value_ids.mapped('total_contribution')), 3000)
                report = self.env['school.financial.report'].search([('academic_year_id', '=', years[0].id)])
                self.assertEqual(report.operating_cost_total, 1000)

    def test_direct_category_expense(self):
        year = self._wizard()._ensure_academic_years(1)[0]
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Direct Facilities', 'display_order': 10,
        })
        direct = self.env['school.expense.values'].create({
            'academic_year_id': year.id, 'expense_category_id': category.id, 'amount': 100,
        })
        self.assertFalse(category.expense_item_ids)
        self.assertFalse(direct.expense_item_id)
        item = self.env['school.expense.items'].create({
            'school_id': self.school.id, 'expense_category_id': category.id,
            'name': 'Repairs', 'display_order': 10,
        })
        child = self.env['school.expense.values'].create({
            'academic_year_id': year.id, 'expense_item_id': item.id, 'amount': 25,
        })
        self.assertEqual(child.expense_category_id, category)
        self.assertEqual(year.expense_total, 100)
        category.unlink()
        self.assertFalse((direct | child).exists())
        self.assertEqual(year.expense_total, 0)

    def test_expense_structure_flows_to_actual(self):
        forecast = self._wizard()._ensure_academic_years(1)[0]
        actual = forecast._ensure_actual_year()
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Later Expense', 'display_order': 10,
        })
        direct = self.env['school.expense.values'].create({
            'academic_year_id': forecast.id, 'expense_category_id': category.id, 'amount': 100,
        })
        actual_direct = actual.expense_value_ids.filtered(lambda row: row.expense_category_id == category)
        self.assertEqual(len(actual_direct), 1)
        self.assertEqual(actual_direct.amount, 0)
        self.assertEqual(actual.expenses_status, 'not_started')
        actual_direct.amount = 80
        actual.expenses_status = 'complete'
        item = self.env['school.expense.items'].create({
            'school_id': self.school.id, 'expense_category_id': category.id,
            'name': 'Optional Detail', 'display_order': 10,
        })
        self.env['school.expense.values'].create({
            'academic_year_id': forecast.id, 'expense_item_id': item.id, 'amount': 25,
        })
        actual._ensure_forecast_expense_structure()
        self.assertEqual(len(actual.expense_value_ids), 2)
        self.assertEqual(actual_direct.amount, 80)
        self.assertEqual(actual.expense_value_ids.filtered('expense_item_id').amount, 0)
        self.assertEqual(actual.expenses_status, 'complete')
        self.assertEqual(direct.amount, 100)
        actual.action_load_from_forecast()
        self.assertEqual(actual_direct.amount, 80)

    def test_expense_formulas(self):
        wizard = self._wizard()
        for trend, expected in (
            ('revenue_decrease', [300, 500, 600]),
            ('revenue_increase', [300, 700, 1200]),
            ('revenue_stable', [300, 600, 900]),
            ('per_student', [3000, 6000, 9000]),
            ('stable', [30, 30, 30]),
            ('increase', [30, 31.5, 33.075]),
            ('decrease', [30, 28.5, 27.075]),
        ):
            with self.subTest(trend=trend):
                rule = SimpleNamespace(base_annual_amount=30, start_year_index=1, trend=trend, annual_change_percent=5)
                for year, amount in enumerate(expected, start=1):
                    self.assertAlmostEqual(wizard._compute_repeating_expense_amount(rule, year, year * 1000, year * 100), amount)
        rule = SimpleNamespace(base_annual_amount=30, start_year_index=2, trend='revenue_decrease', annual_change_percent=5)
        self.assertEqual(wizard._compute_repeating_expense_amount(rule, 1, 1000, 100), 0)
        self.assertEqual(wizard._compute_repeating_expense_amount(rule, 2, 1000, 100), 300)
        self.assertEqual(wizard._compute_repeating_expense_amount(rule, 20, 1000, 100), 0)
        rule.trend = 'revenue_increase'
        self.assertEqual(wizard._compute_repeating_expense_amount(rule, 20, 1000, 100), 1000)

    def test_after_tax_expense_trends(self):
        wizard = self._wizard()
        for trend, expected in [('revenue_after_tax_increase', [240, 560, 960]),
                                ('revenue_after_tax_decrease', [240, 400, 480])]:
            rule = SimpleNamespace(base_annual_amount=30, start_year_index=1, trend=trend, annual_change_percent=5)
            for year, amount in enumerate(expected, start=1):
                self.assertAlmostEqual(wizard._compute_repeating_expense_amount(rule, year, year * 1000, year * 100, year * 800), amount)
            rule.start_year_index = 2
            self.assertEqual(wizard._compute_repeating_expense_amount(rule, 1, 1000, 100, 800), 0)
            self.assertEqual(wizard._compute_repeating_expense_amount(rule, 2, 1000, 100, 800), 240)
            self.assertEqual(wizard._compute_repeating_expense_amount(rule, 30, 1000, 100, 800), 800 if trend.endswith('_increase') else 0)
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        operations = wizard.extreme_expense_line_ids.filtered(lambda row: row.name == 'Manual Expenses')
        operations.write({'trend': 'revenue_after_tax_decrease', 'base_annual_amount': 30, 'annual_change_percent': 5})
        wizard.action_apply()
        for year, rate in zip(wizard._existing_forecast_years(), [30, 25, 20]):
            row = year.operating_expense_ids.filtered(lambda row: row.expense_category_id.name == 'Manual Expenses')
            self.assertAlmostEqual(row.amount, year.fee_total * rate / 100)
            self.assertLess(row.amount, year.fee_gross_total * rate / 100)

    def test_after_tax_payroll_trend(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        rule = wizard.payroll_rule_ids
        rule.write({'trend': 'revenue_after_tax_increase', 'base_annual_amount': 40, 'annual_change_percent': 5})
        gross = wizard.line_ids[0].student_count * wizard.line_ids[0].annual_fee_per_student
        net = gross * (1 - wizard.income_tax_percent / 100)
        self.assertAlmostEqual(rule.salary_base_amount, net * 0.4)
        rule.salary_base_amount = net * 0.3
        self.assertAlmostEqual(rule.base_annual_amount, 30)
        wizard.action_apply()
        for year, rate in zip(wizard._existing_forecast_years(), [30, 35, 40]):
            self.assertEqual(year.payroll_basis, 'amount')
            self.assertAlmostEqual(year.salary_total, year.fee_total * rate / 100)
        first = wizard._existing_forecast_years()[0]
        generated_payroll = first.salary_total
        first.fee_value_ids[0].fee_type_id.tax_rule_id.percentage = 0.2
        self.assertAlmostEqual(first.salary_total, generated_payroll)
        first.write({'payroll_basis': 'percent', 'payroll_revenue_basis': 'net'})
        with Form(first, view='school_planning.view_school_year_workspace') as form:
            form.payroll_percent_input = 25
            self.assertAlmostEqual(form.payroll_amount_input, first.fee_total * 0.25)
        self.assertEqual(first.payroll_revenue_basis, 'net')
        self.assertAlmostEqual(first.salary_total, first.fee_total * 0.25)
        wizard.income_tax_percent = 100
        wizard.action_apply()
        self.assertAlmostEqual(first.fee_total, 0)
        self.assertAlmostEqual(first.salary_total, 0)
        self.assertEqual(first.payroll_basis, 'amount')

    def test_mode_inputs_and_demo_preservation(self):
        wizard = self._wizard()
        self.assertEqual(set(wizard.repeating_expense_line_ids.mapped('name')), set(self.configuration.expense_ids.filtered(
            lambda row: row.cost_bucket == 'operating' and not row.is_detailed_category
        ).mapped('name')))
        self.assertFalse(wizard.extreme_expense_line_ids)
        wizard.extreme_efficiency = True
        wizard._onchange_extreme_efficiency()
        self.assertEqual(len(wizard.extreme_expense_line_ids), 1)
        salary_rule = wizard.payroll_rule_ids
        salary_rule.base_annual_amount = 42
        wizard.extreme_efficiency = False
        wizard._onchange_extreme_efficiency()
        wizard.action_load_demo_data()
        self.assertFalse(wizard.one_time_expense_line_ids)
        self.assertEqual(salary_rule.base_annual_amount, 42)
        self.assertEqual(len(wizard.extreme_expense_line_ids), 1)
        normal_ids = wizard.repeating_expense_line_ids.ids
        normal_salary_ids = wizard.year_salary_line_ids.ids
        wizard.extreme_efficiency = True
        wizard._onchange_extreme_efficiency()
        self.assertEqual(salary_rule.base_annual_amount, 42)
        wizard.action_load_demo_data()
        self.assertFalse(wizard.one_time_expense_line_ids)
        self.assertEqual(wizard.repeating_expense_line_ids.ids, normal_ids)
        self.assertEqual(wizard.year_salary_line_ids.ids, normal_salary_ids)
        self.assertEqual(len(wizard.extreme_expense_line_ids), 1)
        wizard.extreme_expense_line_ids.unlink()
        wizard.extreme_efficiency = False
        wizard._onchange_extreme_efficiency()
        wizard.extreme_efficiency = True
        wizard._onchange_extreme_efficiency()
        self.assertFalse(wizard.extreme_expense_line_ids)

    def test_revenue_validation(self):
        wizard = self._wizard()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['school.prediction.quick.setup.repeating.expense.line'].create({
                'wizard_id': wizard.id, 'trend': 'revenue_decrease', 'base_annual_amount': 101,
            })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['school.prediction.quick.setup.repeating.expense.line'].create({
                'wizard_id': wizard.id, 'trend': 'per_student', 'base_annual_amount': -1,
            })

    def test_generation_and_payroll_confirmation(self):
        wizard = self._wizard()
        wizard.action_load_demo_data()
        wizard.action_apply()
        years = wizard._existing_forecast_years()
        payroll = self.env['school.employment.salaries'].search([('academic_year_id', 'in', years.ids)])
        self.assertTrue(payroll)
        self.assertTrue(all(year.salary_total > 0 for year in years))
        teacher_salary = wizard.year_salary_line_ids.sorted('year_index')
        self.assertEqual(teacher_salary.mapped('months_paid'), [12, 12, 12])
        self.assertAlmostEqual(teacher_salary[1].teacher_monthly_salary, teacher_salary[0].teacher_monthly_salary * 1.1)
        wizard.extreme_efficiency = True
        wizard._onchange_extreme_efficiency()
        wizard.extreme_expense_line_ids.write({'trend': 'revenue_decrease', 'base_annual_amount': 30, 'annual_change_percent': 3})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.action_apply()
        self.assertTrue(payroll.exists())
        wizard.replace_existing_payroll = True
        wizard.action_apply()
        self.assertFalse(payroll.exists())
        for year, salary_amount, operations_amount in zip(years, [6000000, 12408000, 19166400], [3600000, 7128000, 10454400]):
            expenses = self.env['school.expense.values'].search([('academic_year_id', '=', year.id)])
            self.assertFalse(expenses.filtered(lambda row: row.cost_bucket == 'employee' and row.prediction_input_mode == 'extreme'))
            self.assertAlmostEqual(expenses.filtered(lambda row: row.expense_category_id.name == 'Manual Expenses').amount, operations_amount)
            self.assertAlmostEqual(year.salary_total, salary_amount)
            self.assertAlmostEqual(year.expense_total, sum(expenses.filtered(lambda row: row.cost_bucket == 'operating').mapped('amount')))
            report = self.env['school.financial.report'].search([('academic_year_id', '=', year.id)])
            self.assertAlmostEqual(report.net_profit, year.net_budget)
        count = self.env['school.expense.values'].search_count([('academic_year_id', 'in', years.ids)])
        wizard.action_apply()
        self.assertEqual(self.env['school.expense.values'].search_count([('academic_year_id', 'in', years.ids)]), count)
        wizard.extreme_efficiency = False
        wizard.action_apply()
        self.assertFalse(self.env['school.expense.values'].search([('academic_year_id', 'in', years.ids), ('prediction_input_mode', '=', 'extreme')]))
        self.assertTrue(all(year.salary_total > 0 for year in years))

    def test_manual_expense_conflict(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        years = wizard._ensure_academic_years(3)
        item = wizard._ensure_manual_expense_item(wizard._ensure_manual_expense_category(), 'Salaries')
        manual = self.env['school.expense.values'].create({
            'academic_year_id': years[0].id, 'expense_item_id': item.id, 'amount': 123,
        })
        wizard.action_apply()
        self.assertEqual(manual.amount, 123)
        item.name = 'Independent Expense'
        wizard.action_apply()
        self.assertEqual(manual.amount, 123)
        self.assertFalse(manual.prediction_input_mode)

    def test_forecast_and_actual_year_isolation(self):
        wizard = self._wizard(True)
        forecasts = wizard._ensure_academic_years(3)
        actual = self.env['school.academic.years'].create({
            'school_id': self.school.id,
            'academic_year_name': forecasts[0].academic_year_name,
            'start_date': forecasts[0].start_date,
            'end_date': forecasts[0].end_date,
            'dataset_type': 'actual',
        })
        self.assertEqual(wizard._ensure_academic_years(3), forecasts)
        navigation = self.env['school.room.plan']
        self.assertEqual(navigation._next_year(forecasts[0], self.school.id), forecasts[1])
        self.assertFalse(navigation._previous_year(actual, self.school.id))
        wizard.action_load_demo_data()
        wizard.action_apply()
        self.assertFalse(actual.enrollment_ids)
        self.assertTrue(actual.expense_value_ids)
        self.assertTrue(all(row.amount == 0 for row in actual.expense_value_ids))
        self.assertEqual(actual.expenses_status, 'not_started')

    def test_actual_pair_and_frozen_comparison(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        actual = forecast._ensure_actual_year()
        self.assertEqual(forecast._ensure_actual_year(), actual)
        self.assertEqual(actual.forecast_year_id, forecast)
        self.assertEqual(actual.total_enrolled_students, 0)
        self.assertEqual(actual.fee_gross_total, 0)
        self.assertEqual(actual.actual_status, 'not_started')
        frozen_revenue = forecast.fee_gross_total
        forecast.action_freeze_baseline()
        for operation in (
            lambda: forecast.write({'academic_year_name': 'Changed'}),
            lambda: forecast.fee_value_ids[:1].write({'amount': 1}),
            lambda: forecast.expense_value_ids[:1].unlink(),
            lambda: self.env['school.expense.values'].create({'academic_year_id': forecast.id, 'expense_item_id': forecast.expense_value_ids[0].expense_item_id.id, 'amount': 1}),
            lambda: wizard.action_apply(),
        ):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                operation()
        actual.enrollment_ids[0].student_count = 20
        self.assertEqual(actual.income_status, 'not_started')
        actual.fee_value_ids[0].amount = 100
        self.assertEqual(forecast.fee_gross_total, frozen_revenue)
        comparison = self.env['school.forecast.comparison'].create({'school_id': self.school.id, 'forecast_year_id': forecast.id})
        revenue = comparison.line_ids.filtered(lambda line: line.metric == 'fee_gross_total')
        self.assertEqual(revenue.result, 'Provisional')
        actual.write({'enrollment_status': 'complete', 'income_status': 'complete'})
        revenue.invalidate_recordset()
        self.assertEqual(revenue.result, 'Unfavorable')
        self.assertEqual(revenue.actual_amount, 2000)
        self.assertEqual(revenue.difference, 2000 - frozen_revenue)
        self.assertEqual(actual.actual_status, 'in_progress')

    def test_actual_payroll_and_employee_cost_alignment(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        actual = forecast._ensure_actual_year()
        position = wizard._ensure_operating_models()['teacher']
        salary = self.env['school.employment.salaries'].create({'academic_year_id': actual.id, 'staff_position_id': position.id,
                                                              'actual_employee_count': 3, 'monthly_salary': 1000, 'months_paid': 10, 'bonus': 100})
        self.assertEqual(salary.annual_cost, 30300)
        self.assertEqual(forecast.employee_cost_total, 6000000)
        self.assertEqual(actual.employee_cost_total, 30300)
        salary.actual_employee_count = 4
        self.assertEqual(actual.employee_cost_total, 40400)
        fee = actual.fee_value_ids[0]
        actual.enrollment_ids.filtered(lambda row: row.grade_level_id == fee.grade_level_id).student_count = 10
        fee.write({'amount': 100, 'actual_tax_percent': 10})
        self.assertEqual(fee.revenue_amount, 900)
        forecast.fee_value_ids[0].fee_type_id.tax_rule_id.percentage = 0.5
        self.assertEqual(fee.revenue_amount, 900)

    def test_editable_defaults_and_infrastructure(self):
        self.configuration.write({'students_per_classroom': 20, 'classroom_weekly_hours': 40,
                                  'teacher_weekly_hours': 10, 'infrastructure_mode': 'new'})
        projector_seed = self.configuration.asset_ids.filtered(lambda seed: seed.code == 'projector')
        projector_seed.unit_price = 1000
        assets = self.school._ensure_asset_seeds()
        projector = assets.filtered(lambda asset: asset.planning_seed_key == 'projector')
        projector.seed_unit_price = 1000
        wizard = self._wizard(True)
        self.assertEqual(wizard.teaching_load_hours, 10)
        self.assertEqual(wizard.classroom_weekly_hours, 40)
        wizard.action_load_demo_data()
        wizard.action_apply()
        first, second, third = wizard._existing_forecast_years()
        classes = sum(first.enrollment_ids.mapped('class_count'))
        self.assertEqual(first.required_classrooms, classes)
        self.assertEqual(first.required_teachers, classes * 4)
        self.assertEqual(first.students_per_classroom, 20)
        self.assertAlmostEqual(first.startup_cost_total, classes * 1000)
        self.assertAlmostEqual(first.new_rooms_expense_total, classes * 1000)
        self.assertAlmostEqual(first.net_budget, first.fee_total - first.salary_total - first.expense_total - first.startup_cost_total)
        self.assertEqual(second.room_plan_ids.existing_rooms, 0)
        self.assertAlmostEqual(second.startup_cost_total, second.required_classrooms * 1000)
        self.assertEqual(third.room_plan_ids.existing_rooms, 0)
        self.assertAlmostEqual(third.startup_cost_total, third.required_classrooms * 1000)
        first.total_students_input = 1000
        first.students_per_classroom = 50
        self.assertEqual(first.required_teachers, sum(first.enrollment_ids.mapped('class_count')) * 4)
        self.assertEqual(first.employment_salary_ids, self.env['school.employment.salaries'])
        investment = first.startup_cost_total
        projector_seed.quantity = 2
        self.assertEqual(first.asset_price_ids.filtered(lambda row: row.asset_item_id == projector).planning_seed_quantity, 1)
        self.assertEqual(first.startup_cost_total, investment)
        first.action_freeze_baseline()
        total = first.net_budget
        self.configuration.students_per_classroom = 10
        projector_seed.unit_price = 2000
        self.assertEqual(first.students_per_classroom, 50)
        self.assertEqual(first.asset_price_ids.filtered(lambda row: row.asset_item_id == projector).unit_price, 1000)
        self.assertEqual(first.net_budget, total)
        actual = first._ensure_actual_year()
        self.assertEqual(actual.students_per_classroom, 50)
        actual.action_load_from_forecast()
        self.assertEqual(actual.asset_price_ids.filtered(lambda row: row.asset_item_id == projector).planning_seed_quantity, 1)
        self.assertAlmostEqual(actual.startup_cost_total, investment)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            first.action_seed_asset_prices()

    def test_no_existing_classes_and_safe_forecast_load(self):
        self.configuration.infrastructure_mode = 'new'
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        self.assertTrue(forecast.room_plan_ids)
        self.assertTrue(forecast.asset_price_ids)
        self.assertEqual(forecast.room_plan_ids.calculated_new_rooms, forecast.required_classrooms)
        self.assertGreater(forecast.required_classrooms, 0)
        self.assertGreater(forecast.required_teachers, 0)
        actual = forecast._ensure_actual_year()
        self.assertTrue(actual.room_plan_ids)
        self.assertTrue(actual.asset_price_ids)
        self.assertEqual(actual.assets_status, 'not_started')
        actual.action_load_from_forecast()
        self.assertEqual(actual.total_students_input, forecast.total_students_input)
        self.assertAlmostEqual(actual.fee_gross_total, forecast.fee_gross_total)
        self.assertAlmostEqual(actual.fee_total, forecast.fee_total)
        self.assertAlmostEqual(actual.payroll_amount_input, forecast.employee_cost_total)
        self.assertAlmostEqual(actual.net_budget, forecast.net_budget)
        self.assertEqual(actual.actual_status, 'in_progress')
        actual.total_students_input = 80
        actual.payroll_amount_input = 1234
        actual.action_load_from_forecast()
        self.assertEqual(actual.total_students_input, 80)
        self.assertEqual(actual.payroll_amount_input, 1234)
        self.assertEqual(forecast.total_students_input, 100)

    def test_actual_teacher_requirement_uses_subject_hours_rules(self):
        self.env['school.subjects'].create({
            'name': 'Science', 'school_id': self.school.id, 'display_order': 2,
        })
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        actual = wizard._existing_forecast_years()[0]._ensure_actual_year()

        levels = actual.enrollment_ids.mapped('grade_level_id')[:2]
        subjects = actual.subject_distribution_ids.mapped('subject_id')[:2]
        self.assertEqual(len(levels), 2)
        self.assertEqual(len(subjects), 2)

        actual.enrollment_ids.write({'student_count': 0})
        actual.enrollment_ids.filtered(lambda row: row.grade_level_id in levels).write({'student_count': 50})
        self.assertEqual(sum(actual.enrollment_ids.filtered(lambda row: row.grade_level_id in levels).mapped('class_count')), 4)

        actual.subject_distribution_ids.write({'weekly_hours': 0})
        level_1, level_2 = levels
        subject_1, subject_2 = subjects

        actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == level_1 and row.subject_id == subject_1
        )[:1].weekly_hours = 30
        actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == level_1 and row.subject_id == subject_2
        )[:1].weekly_hours = 20
        actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == level_2 and row.subject_id == subject_1
        )[:1].weekly_hours = 20
        actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == level_2 and row.subject_id == subject_2
        )[:1].weekly_hours = 10

        # Grade-level cap: 35h/week per class.
        # Subject 1 hours: (30 * 0.7 * 2 classes) + (20 * 1.0 * 2 classes) = 82 -> ceil(82 / 20) = 5
        # Subject 2 hours: (20 * 0.7 * 2 classes) + (10 * 1.0 * 2 classes) = 48 -> ceil(48 / 20) = 3
        # Total teachers = 5 + 3 = 8
        self.assertEqual(actual.required_teachers, 8)

        actual.classroom_weekly_hours = 10
        self.assertEqual(actual.required_teachers, 8)

    def test_custom_staffing_seed_position_is_generated(self):
        self.configuration._ensure_staffing_seeds()
        self.configuration.staffing_seed_ids = [fields.Command.create({
            'title': 'Lab Assistant',
            'code': 'lab_assistant',
            'display_order': 130,
            'calculation_method': 'per_student',
            'parameter_value': 40,
        })]
        wizard = self._wizard()
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        position = self.env['school.staff.positions'].search([
            ('school_id', '=', self.school.id),
            ('title', '=', 'Lab Assistant'),
        ], limit=1)
        self.assertTrue(position)
        override = self.env['school.staffing.overrides'].search([
            ('academic_year_id', '=', forecast.id),
            ('staff_position_id', '=', position.id),
        ], limit=1)
        self.assertTrue(override)
        self.assertEqual(override.employee_count, 3)
        salary = self.env['school.employment.salaries'].search([
            ('academic_year_id', '=', forecast.id),
            ('staff_position_id', '=', position.id),
        ], limit=1)
        self.assertTrue(salary)

    def test_existing_classrooms_and_payroll_amount_seed(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        rule = wizard.payroll_rule_ids
        rule.salary_base_amount = 2400000
        self.assertAlmostEqual(rule.base_annual_amount, 20)
        self.assertAlmostEqual(rule.salary_base_amount, 2400000)
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        self.assertEqual(forecast.room_plan_ids.existing_rooms, forecast.required_classrooms)
        self.assertEqual(forecast.room_plan_ids.calculated_new_rooms, 0)
        self.assertEqual(forecast.room_plan_ids.calculated_required_rooms, sum(forecast.enrollment_ids.mapped('class_count')))
        self.assertEqual(forecast.startup_cost_total, 0)
        self.assertAlmostEqual(forecast.salary_total, 2400000)

    def test_period_selection_and_ordinary_user_actions(self):
        wizard = self._wizard(True)
        wizard.start_year = 2035
        years = wizard._ensure_academic_years(2)
        self.assertEqual(years.mapped('academic_year_name'), ['2035-2036', '2036-2037'])
        wizard.start_year = 2036
        self.assertEqual(wizard._ensure_academic_years(2)[0], years[1])
        comparison = self.env['school.forecast.comparison'].create({'school_id': self.school.id, 'forecast_year_id': years[0].id})
        comparison.action_next_year()
        self.assertEqual(comparison.forecast_year_id, years[1])
        comparison.action_previous_year()
        self.assertEqual(comparison.forecast_year_id, years[0])
        user = self.env['res.users'].with_context(no_reset_password=True).create({'name': 'Actual Entry User', 'login': 'school_actual_test_user',
                                             'email': 'sender@example.com',
                                             'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        school = self.school.with_user(user)
        self.assertEqual(school.action_open_quick_prediction()['res_model'], 'school.prediction.quick.setup.wizard')
        self.assertEqual(school.action_open_actuals()['res_model'], 'school.academic.years')
        self.assertEqual(school.action_open_comparison()['res_model'], 'school.forecast.comparison')
        self.assertEqual(school.action_open_financial_summary()['res_model'], 'school.academic.years')
        email_action = years[0].with_user(user).action_open_financial_summary_email_wizard()
        email_form = Form(self.env['school.financial.summary.email.wizard'].with_user(user).with_context(email_action['context']),
                  view='school_planning.view_school_financial_summary_email_wizard_form')
        self.assertEqual(len(email_form.academic_year_ids), 1)
        email_form.email_to = 'recipient@example.com'
        email_wizard = email_form.save()
        self.assertEqual(email_wizard.academic_year_ids, years[0].with_user(user))
        email_wizard.write({'subject': 'Updated Financial Summary'})
        self.assertEqual(email_wizard.subject, 'Updated Financial Summary')
        self.env['ir.mail_server'].create({'name': 'PDF Email Test Server', 'smtp_host': 'smtp.gmail.com', 'sequence': -100})
        with patch.object(type(self.env['mail.mail']), 'send', autospec=True) as send_mock:
            result = email_wizard.action_send_email()
        send_mock.assert_called_once()
        mail = send_mock.call_args.args[0]
        self.assertEqual(send_mock.call_args.kwargs, {'raise_exception': True})
        self.assertEqual(mail.email_to, 'recipient@example.com')
        self.assertIn('sender@example.com', mail.email_from)
        self.assertEqual(mail.subject, 'Updated Financial Summary')
        self.assertEqual(len(mail.attachment_ids), 1)
        self.assertTrue(base64.b64decode(mail.attachment_ids.datas).startswith(b'%PDF'))
        self.assertEqual(result['tag'], 'display_notification')
        seed_form = Form(self.configuration.with_user(user), view='school_planning.view_prediction_seed_configuration_form')
        self.assertEqual(seed_form.teacher_weekly_hours, 20)

    def test_actual_advanced_inputs(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        actual = forecast._ensure_actual_year()
        actual.payroll_amount_input = 10000
        position = wizard._ensure_operating_models()['teacher']
        salary = self.env['school.employment.salaries'].create({'academic_year_id': actual.id, 'staff_position_id': position.id,
                                                              'actual_employee_count': 2, 'monthly_salary': 1000, 'months_paid': 12})
        self.assertFalse(actual.payroll_summary_enabled)
        self.assertEqual(actual.salary_total, salary.annual_cost)
        asset = self.school._ensure_asset_seeds()[0]
        self.env['school.asset.transactions'].create({'academic_year_id': actual.id, 'asset_item_id': asset.id,
                                                      'transaction_type': 'Purchase', 'quantity': 10})
        self.assertEqual(actual.assets_status, 'in_progress')
        room_type = forecast.room_plan_ids.room_type_id
        project = self.env['school.expansion.projects'].create({'academic_year_id': actual.id, 'name': 'Actual Expansion',
                                                                'project_room_ids': [(0, 0, {'room_type_id': room_type.id, 'room_count': 2})]})
        self.assertEqual(project.project_room_ids.academic_year_id, actual)
        self.assertEqual(project.school_id, self.school)
        subject = self.school.subject_ids[0]
        self.env['school.subject.distribution'].create({'academic_year_id': actual.id, 'grade_level_id': actual.enrollment_ids[0].grade_level_id.id,
                                                        'subject_id': subject.id, 'weekly_hours': 5, 'credits': 2})
        self.assertEqual(actual.teaching_status, 'in_progress')
        actual.total_students_input = 70
        self.assertEqual(actual.subject_distribution_ids.filtered(lambda row: row.weekly_hours == 5).weekly_hours, 5)
        actual.infrastructure_mode = 'new'
        actual.asset_price_ids.filtered(lambda row: row.asset_item_id == asset).unit_price = 1000
        project.project_room_ids.room_count = 3
        self.assertGreater(actual.new_rooms_expense_total, 0)
        self.assertEqual(actual.new_rooms_expense_total, actual.startup_cost_total)
        self.assertEqual(forecast.employee_cost_total, 6000000)
        actual.action_complete_actual()
        self.assertEqual(actual.actual_status, 'complete')

    def test_actual_templates_bulk_controls_and_tools(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        actual = wizard._existing_forecast_years()[0]._ensure_actual_year()
        self.assertEqual(len(actual.enrollment_ids), len(actual.enrollment_ids.mapped('grade_level_id')))
        self.assertEqual(len(actual.fee_value_ids), len(actual.enrollment_ids) * len(actual.fee_value_ids.mapped('fee_type_id')))
        self.assertTrue(actual.employment_salary_ids)
        self.assertTrue(actual.subject_distribution_ids)
        self.assertEqual(actual.actual_status, 'not_started')
        actual.total_students_input = 80
        actual.annual_fee_input = 1000
        salary = actual.employment_salary_ids[0]
        salary.write({'actual_employee_count': 2, 'monthly_salary': 1000})
        actual.actual_payroll_months = 10
        actual.action_apply_actual_payroll_months()
        self.assertTrue(all(row.months_paid == 10 for row in actual.employment_salary_ids))
        self.assertEqual(salary.annual_cost, 20000)
        actual.actual_fee_tax_percent = 10
        actual.action_apply_actual_fee_tax()
        self.assertAlmostEqual(actual.fee_total, 72000)
        before = (len(actual.enrollment_ids), len(actual.fee_value_ids), len(actual.employment_salary_ids))
        actual.action_prepare_actual_entry()
        self.assertEqual(before, (len(actual.enrollment_ids), len(actual.fee_value_ids), len(actual.employment_salary_ids)))
        self.assertEqual(salary.actual_employee_count, 2)
        for group, tools in ACTUAL_TOOLS.items():
            for tool, label in tools:
                actual[f'actual_{group}_tool'] = tool
                action = actual._actual_tool_action(group)
                self.assertEqual(action['context']['default_academic_year_id'], actual.id)
                if tool == 'asset_prices':
                    self.assertEqual(action['views'][0], (self.env.ref('school_planning.view_school_asset_prices_tree').id, 'list'))
                if group != 'setup' and tool != 'asset_items':
                    self.assertEqual(action['domain'], [('academic_year_id', '=', actual.id)])
        self.assertEqual(actual.forecast_year_id.total_enrolled_students, 100)

    def test_actual_live_detail_payroll_and_staffing(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        actual = wizard._existing_forecast_years()[0]._ensure_actual_year()
        actual.payroll_amount_input = 50000
        with Form(actual, view='school_planning.view_school_year_workspace') as form:
            with form.employment_salary_ids.edit(0) as salary:
                salary.actual_employee_count = 2
                salary.monthly_salary = 1000
                salary.months_paid = 10
            self.assertFalse(form.payroll_summary_enabled)
            self.assertEqual(form.payroll_amount_input, 20000)
        row = actual.employment_salary_ids[0]
        self.assertEqual(actual.salary_total, 20000)
        self.env['school.staffing.overrides'].create({'academic_year_id': actual.id, 'staff_position_id': row.staff_position_id.id, 'employee_count': 3})
        self.assertEqual(row.actual_employee_count, 3)
        self.assertEqual(actual.salary_total, 30000)
        before = actual.assets_status
        foreign = self.env['school.schools'].create({'name': 'Different Actual School', 'currency': 'EGP'})
        foreign_asset = foreign._ensure_asset_seeds()[0]
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['school.asset.transactions'].create({'academic_year_id': actual.id, 'asset_item_id': foreign_asset.id,
                                                          'transaction_type': 'Purchase', 'quantity': 1})
        self.assertEqual(actual.assets_status, before)

    def test_new_manual_actual_form(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        model = self.env['school.academic.years'].with_context(default_school_id=self.school.id, default_dataset_type='actual')
        with Form(model, view='school_planning.view_school_year_workspace') as form:
            form.academic_year_name = '2055-2056'
            form.start_date = date(2055, 9, 1)
            form.end_date = date(2056, 6, 30)
            self.assertEqual(form.students_per_classroom, 25)
            self.assertEqual(form.teacher_weekly_hours, 20)
        year = form.record
        self.assertEqual(year.dataset_type, 'actual')
        self.assertTrue(year.employment_salary_ids)
        self.assertEqual(year.actual_status, 'not_started')

    def test_actual_expense_category_entry(self):
        category = self.env['school.expense.categories'].create({'school_id': self.school.id, 'name': 'Facilities', 'display_order': 10})
        other_category = self.env['school.expense.categories'].create({'school_id': self.school.id, 'name': 'Administration', 'display_order': 20})
        item = self.env['school.expense.items'].create({'school_id': self.school.id, 'expense_category_id': category.id, 'name': 'Rent', 'display_order': 10})
        actual = self.env['school.academic.years'].create({'school_id': self.school.id, 'academic_year_name': '2062-2063',
            'start_date': '2062-09-01', 'end_date': '2063-06-30', 'dataset_type': 'actual'})
        actual.write({'actual_expense_category_id': category.id, 'actual_expense_item_id': item.id, 'actual_expense_amount': 1250})
        self.assertFalse(actual.action_apply_actual_expense())
        rows = actual.operating_expense_ids.filtered(lambda row: row.expense_item_id == item)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.amount, 1250)
        self.assertEqual(rows.expense_category_id, category)
        self.assertEqual(actual.operating_cost_total, 1250)
        self.assertEqual(actual.expenses_status, 'in_progress')
        actual.actual_expense_amount = 1500
        actual.action_apply_actual_expense()
        self.assertEqual(rows.amount, 1500)
        self.assertEqual(len(actual.operating_expense_ids.filtered(lambda row: row.expense_item_id == item)), 1)
        actual.actual_expense_category_id = other_category
        actual._onchange_actual_expense_category()
        self.assertFalse(actual.actual_expense_item_id)
        self.assertEqual(actual.actual_expense_amount, 0)
        actual.write({'actual_expense_category_id': category.id, 'actual_expense_item_id': item.id})
        actual._onchange_actual_expense_item()
        self.assertEqual(actual.actual_expense_amount, 1500)
        categories_action = actual.action_open_actual_expense_categories()
        items_action = actual.action_open_actual_expense_items()
        self.assertEqual(categories_action['domain'], [('school_id', '=', self.school.id)])
        self.assertEqual(items_action['context']['default_expense_category_id'], category.id)
        self.assertEqual(items_action['context']['default_school_id'], self.school.id)
        self.assertEqual(category.action_open_expense_category()['res_id'], category.id)
        with Form(category.with_context(default_school_id=self.school.id, default_display_order=10),
                  view='school_planning.view_school_expense_categories_form') as form:
            with form.expense_item_ids.new() as line:
                line.name = 'Maintenance'
        maintenance = category.expense_item_ids.filtered(lambda record: record.name == 'Maintenance')
        self.assertEqual(maintenance.school_id, self.school)
        actual.actual_expense_item_id = maintenance
        actual.actual_expense_amount = 300
        actual.action_apply_actual_expense()
        self.assertEqual(actual.operating_cost_total, 1800)
        with Form(actual, view='school_planning.view_school_year_workspace') as form:
            rent_index = next(index for index, row in enumerate(actual.operating_expense_ids) if row.expense_item_id == item)
            with form.operating_expense_ids.edit(rent_index) as line:
                line.amount = 1600
        actual.actual_expense_item_id = item
        actual._onchange_actual_expense_item()
        self.assertEqual(actual.actual_expense_amount, 1600)
        self.assertEqual(actual.operating_cost_total, 1900)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            actual.actual_expense_amount = -1
            actual.action_apply_actual_expense()
        foreign = self.env['school.schools'].create({'name': 'Foreign Expense School', 'currency': 'EGP'})
        foreign_category = self.env['school.expense.categories'].create({'school_id': foreign.id, 'name': 'Foreign Category', 'display_order': 10})
        foreign_item = self.env['school.expense.items'].create({'school_id': foreign.id, 'expense_category_id': foreign_category.id, 'name': 'Foreign Item', 'display_order': 10})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['school.expense.values'].create({'academic_year_id': actual.id, 'expense_item_id': foreign_item.id, 'amount': 100})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            item.expense_category_id = foreign_category

    def test_delete_expense_category_with_items(self):
        categories = self.env['school.expense.categories'].create([
            {'school_id': self.school.id, 'name': 'Delete Facilities', 'display_order': 10},
            {'school_id': self.school.id, 'name': 'Keep Administration', 'display_order': 20},
        ])
        items = self.env['school.expense.items'].create([
            {'school_id': self.school.id, 'expense_category_id': categories[0].id, 'name': 'Rent', 'display_order': 10},
            {'school_id': self.school.id, 'expense_category_id': categories[0].id, 'name': 'Maintenance', 'display_order': 20},
            {'school_id': self.school.id, 'expense_category_id': categories[1].id, 'name': 'Office', 'display_order': 10},
        ])
        year = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': '2068-2069',
            'start_date': '2068-09-01', 'end_date': '2069-06-30', 'dataset_type': 'actual',
        })
        expenses = self.env['school.expense.values'].create([
            {'academic_year_id': year.id, 'expense_item_id': item.id, 'amount': amount}
            for item, amount in zip(items, (1000, 200, 300))
        ])
        self.assertEqual(year.operating_cost_total, 1500)
        self.assertFalse(categories[0].action_delete_expense_category())
        self.assertFalse(categories[0].exists())
        self.assertFalse(items[:2].exists())
        self.assertFalse(expenses[:2].exists())
        self.assertTrue(categories[1].exists())
        self.assertTrue(items[2].exists())
        self.assertTrue(expenses[2].exists())
        self.assertEqual(year.operating_cost_total, 300)
        arch = etree.fromstring(self.env.ref('school_planning.view_school_expense_categories_tree').get_combined_arch())
        buttons = arch.xpath("//button[@name='action_delete_expense_category']")
        self.assertEqual(len(buttons), 1)
        self.assertTrue(buttons[0].get('confirm'))
        forecast = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': '2069-2070',
            'start_date': '2069-09-01', 'end_date': '2070-06-30', 'dataset_type': 'forecast',
        })
        self.env['school.expense.values'].create({
            'academic_year_id': forecast.id, 'expense_item_id': items[2].id, 'amount': 500,
        })
        forecast.action_freeze_baseline()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            categories[1].action_delete_expense_category()
        self.assertTrue(categories[1].exists())
        self.assertTrue(items[2].exists())
        self.assertTrue(expenses[2].exists())

    def test_prediction_expenses_use_category_seeds(self):
        self.configuration.expense_ids.filtered(lambda row: row.cost_bucket == 'operating' and not row.is_detailed_category).unlink()
        categories = self.env['school.prediction.seed.expense'].create([
            {'configuration_id': self.configuration.id, 'name': 'Miscellaneous', 'trend': 'revenue_stable'},
            {'configuration_id': self.configuration.id, 'name': 'Facilities', 'trend': 'revenue_stable',
             'item_ids': [(0, 0, {'name': 'Rent'}), (0, 0, {'name': 'Maintenance'})]},
        ])
        for extreme in (False, True):
            with self.subTest(extreme=extreme):
                wizard = self._wizard(extreme)
                rows = wizard.extreme_expense_line_ids if extreme else wizard.repeating_expense_line_ids
                self.assertEqual(set(rows.mapped('name')), set(categories.mapped('name')))
                self.assertEqual(set(rows.mapped('cost_bucket')), {'operating'})
                wizard.action_load_demo_data()
                rows = wizard.extreme_expense_line_ids if extreme else wizard.repeating_expense_line_ids
                self.assertEqual(set(rows.mapped('seed_id').ids), set(categories.ids))
                rows.write({'base_annual_amount': 7})
                rows.filtered(lambda row: row.name == 'Miscellaneous').base_annual_amount = 3
                wizard.replace_existing_payroll = True
                wizard.action_apply()
                for year in wizard._existing_forecast_years():
                    for category, rate in [('Miscellaneous', 0.03), ('Facilities', 0.07)]:
                        expense = year.operating_expense_ids.filtered(lambda row: row.expense_category_id.name == category and not row.expense_item_id)
                        self.assertEqual(len(expense), 1)
                        self.assertFalse(expense.expense_item_id)
                        self.assertAlmostEqual(expense.amount, year.fee_gross_total * rate)
                wizard.action_apply()
                self.assertEqual(len(wizard._existing_forecast_years()[0].operating_expense_ids.filtered(
                    lambda row: row.expense_category_id.name in categories.mapped('name') and not row.expense_item_id)), 2)

    def test_configurable_expense_category_seeds(self):
        with Form(self.configuration, view='school_planning.view_prediction_seed_configuration_form') as form:
            with form.expense_ids.new() as category:
                category.name = 'Facilities Seeds'
                with category.item_ids.new() as item:
                    item.name = 'Rent Seed'
                with category.item_ids.new() as item:
                    item.name = 'Maintenance Seed'
        seed = self.configuration.expense_ids.filtered(lambda category: category.name == 'Facilities Seeds')
        wizard = self._wizard(True)
        wizard.line_ids.write({'student_count': 100, 'annual_fee_per_student': 1000})
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        category = forecast.operating_expense_ids.filtered(lambda row: row.expense_category_id.name == seed.name).expense_category_id
        self.assertEqual(set(category.expense_item_ids.mapped('name')), {'Rent Seed', 'Maintenance Seed'})
        actual = forecast._ensure_actual_year()
        direct = actual.operating_expense_ids.filtered(lambda row: row.expense_category_id == category and not row.expense_item_id)
        direct.amount = 900
        seed.name = 'Changed Global Seed'
        actual.action_prepare_actual_entry()
        self.assertEqual(direct.amount, 900)
        self.assertEqual(category.name, 'Facilities Seeds')
        actual.action_prepare_actual_entry()
        self.assertEqual(actual.operating_cost_total, 900)

    def test_unified_expense_seed_migration(self):
        configuration = self.env['school.prediction.seed.configuration'].create({'name': 'Migration Fixture'})
        seeds = self.env['school.prediction.seed.expense'].create([
            {'configuration_id': configuration.id, 'name': 'Shared Expense', 'input_mode': 'normal', 'trend': 'stable', 'base_annual_amount': 100},
            {'configuration_id': configuration.id, 'name': 'Shared Expense', 'input_mode': 'extreme', 'trend': 'stable', 'base_annual_amount': 200},
            {'configuration_id': configuration.id, 'name': 'Identical', 'trend': 'stable', 'base_annual_amount': 20},
            {'configuration_id': configuration.id, 'name': 'Identical', 'trend': 'stable', 'base_annual_amount': 20},
        ])
        self.env['school.prediction.seed.expense.category'].create({
            'configuration_id': configuration.id, 'name': 'Shared Expense',
            'item_ids': [(0, 0, {'name': 'Optional Item'})],
        })
        configuration._merge_legacy_expense_seeds()
        active = configuration.expense_ids.filtered('active')
        self.assertEqual(len(active), 3)
        self.assertEqual(set(active.mapped('base_annual_amount')), {20, 100, 200})
        self.assertEqual(seeds[0].item_ids.name, 'Optional Item')
        self.assertNotEqual(seeds[0].name, seeds[1].name)
        configuration._merge_legacy_expense_seeds()
        self.assertEqual(configuration.expense_ids.filtered('active'), active)
        before = configuration._expense_commands('normal', 'operating')
        after = configuration._expense_commands('extreme', 'operating')
        self.assertEqual([command[2]['name'] for command in before], [command[2]['name'] for command in after])

    def test_custom_wizard_expense_snapshot(self):
        seed = self.configuration.expense_ids.filtered(lambda row: row.cost_bucket == 'operating' and not row.is_detailed_category)[0]
        template = self.env['school.prediction.seed.expense.item'].create({'expense_seed_id': seed.id, 'name': 'Original Optional Item'})
        wizard = self._wizard(True)
        wizard.line_ids.write({'student_count': 100, 'annual_fee_per_student': 1000})
        rule = wizard.extreme_expense_line_ids[0]
        rule.write({'name': 'Edited Wizard Category', 'trend': 'revenue_stable', 'base_annual_amount': 0.25})
        self.env['school.prediction.quick.setup.repeating.expense.line'].create({
            'wizard_id': wizard.id, 'name': 'New Wizard Category', 'input_mode': 'extreme',
            'trend': 'revenue_stable', 'base_annual_amount': 0.075,
        })
        rule.seed_id.name = 'Later Seed Name'
        template.name = 'Later Template Name'
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        self.assertEqual(set(forecast.operating_expense_ids.expense_category_id.mapped('name')),
                         {'Edited Wizard Category', 'New Wizard Category'})
        self.assertEqual(forecast.operating_expense_ids.expense_item_id.name, 'Original Optional Item')
        actual = forecast._ensure_actual_year()
        self.assertEqual(set(actual.operating_expense_ids.expense_category_id.mapped('name')),
                         {'Edited Wizard Category', 'New Wizard Category'})
        self.assertTrue(all(row.amount == 0 for row in actual.expense_value_ids))
        forecast.payroll_expense_ids.amount = 400
        self.assertEqual(forecast.salary_total, 50000)
        self.assertEqual(forecast.expense_total, 325)

    def test_expense_placeholder_migration_preserves_inputs(self):
        self.env['school.prediction.seed.expense.category'].create({
            'configuration_id': self.configuration.id, 'name': 'Migration Placeholder',
        })
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Migration Placeholder', 'display_order': 10,
        })
        item = self.env['school.expense.items'].create({
            'school_id': self.school.id, 'expense_category_id': category.id,
            'name': category.name, 'display_order': 10,
        })
        years = self._wizard()._ensure_academic_years(2)
        generated, manual, frozen = self.env['school.expense.values'].create([
            {'academic_year_id': years[0].id, 'expense_item_id': item.id, 'amount': 100, 'prediction_input_mode': 'normal'},
            {'academic_year_id': years[0].id, 'expense_item_id': item.id, 'amount': 25},
            {'academic_year_id': years[1].id, 'expense_item_id': item.id, 'amount': 500, 'prediction_input_mode': 'normal'},
        ])
        years[1].action_freeze_baseline()
        baseline = dict(years[1].baseline_totals)
        self.env.flush_all()
        migration = run_path(str(Path(__file__).parents[1] / 'migrations' / '19.0.1.34.0' / 'post-migrate.py'))
        migration['migrate'](self.cr, '19.0.1.33.0')
        self.assertFalse(generated.expense_item_id)
        self.assertEqual(manual.expense_item_id, item)
        self.assertEqual(frozen.expense_item_id, item)
        self.assertEqual((generated | manual | frozen).mapped('amount'), [100, 25, 500])
        self.assertEqual(years[0].expense_total, 100)
        self.assertEqual(years[1].baseline_totals, baseline)
        migration['migrate'](self.cr, '19.0.1.33.0')
        self.assertEqual(years[0].expense_total, 100)

    def test_late_item_template_appears_once(self):
        forecast = self._wizard()._ensure_academic_years(1)[0]
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Later Item Category', 'display_order': 10,
        })
        self.env['school.expense.values'].create({'academic_year_id': forecast.id, 'expense_category_id': category.id, 'amount': 100})
        actual = forecast._ensure_actual_year()
        item = self.env['school.expense.items'].with_context(default_academic_year_id=forecast.id).create({
            'school_id': self.school.id, 'expense_category_id': category.id, 'name': 'Added in Category Setup', 'display_order': 10,
        })
        for year in forecast | actual:
            rows = year.expense_value_ids.filtered(lambda row: row.expense_item_id == item)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows.amount, 0)
        self.assertEqual(actual.expenses_status, 'not_started')

    def test_configurable_tax_seeds(self):
        self.assertEqual({seed.name: seed.percentage for seed in self.configuration.tax_ids},
                         {'Corporate Income Tax': 0.225, 'VAT': 0.14})
        existing_vat = self.school.tax_rule_ids.filtered(lambda tax: tax.name == 'VAT')
        vat_seed = self.configuration.tax_ids.filtered(lambda seed: seed.name == 'VAT')
        vat_seed.percentage = 0.12
        with Form(self.configuration, view='school_planning.view_prediction_seed_configuration_form') as form:
            with form.tax_ids.new() as seed:
                seed.name = 'Local Seed Tax'
                seed.percentage = 0.02
        school = self.env['school.schools'].create({'name': 'Configured Tax Seeds School', 'currency': 'EGP'})
        self.assertEqual({tax.name: tax.percentage for tax in school.tax_rule_ids},
                         {'Corporate Income Tax': 0.225, 'VAT': 0.12, 'Local Seed Tax': 0.02})
        self.assertEqual(existing_vat.percentage, 0.14)
        school.tax_rule_ids.filtered(lambda tax: tax.name == 'VAT').percentage = 0.1
        school._ensure_tax_types()
        self.assertEqual(school.tax_rule_ids.filtered(lambda tax: tax.name == 'VAT').percentage, 0.1)
        self.assertEqual(vat_seed.percentage, 0.12)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            vat_seed.percentage = 1.01
        with self.assertRaises(ValidationError), self.cr.savepoint():
            vat_seed.percentage = -0.01

    def test_school_owned_tax_types(self):
        other = self.env['school.schools'].create({'name': 'Independent Taxes School', 'currency': 'EGP'})
        taxes = self.env['school.tax.rules'].search([('school_id', '=', self.school.id)])
        other_taxes = self.env['school.tax.rules'].search([('school_id', '=', other.id)])
        self.assertEqual({tax.name: tax.percentage for tax in taxes}, {'Corporate Income Tax': 0.225, 'VAT': 0.14})
        self.assertEqual({tax.name: tax.percentage for tax in other_taxes}, {'Corporate Income Tax': 0.225, 'VAT': 0.14})
        self.assertFalse(taxes & other_taxes)
        actual = self.env['school.academic.years'].create({'school_id': self.school.id, 'academic_year_name': '2060-2061',
            'start_date': '2060-09-01', 'end_date': '2061-06-30', 'dataset_type': 'actual'})
        action = actual.action_open_actual_tax_types()
        self.assertEqual(self.env['school.tax.rules'].search(action['domain']), taxes)
        self.assertEqual(action['context']['default_school_id'], self.school.id)
        self.assertEqual(actual.actual_used_tax_rule_ids, taxes)
        self.assertEqual(self.env['school.tax.rules'].with_context(default_school_id=self.school.id).name_search(),
                         [(tax.id, tax.display_name) for tax in taxes])
        taxes.filtered(lambda tax: tax.name == 'VAT').percentage = 0.12
        self.assertEqual(other_taxes.filtered(lambda tax: tax.name == 'VAT').percentage, 0.14)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            actual.actual_fee_tax_rule_ids = other_taxes
        actual.actual_fee_tax_rule_ids = taxes
        with self.assertRaises(ValidationError), self.cr.savepoint():
            taxes[0].school_id = other
        fee_type = self.env['school.fee.types'].create({'school_id': self.school.id, 'name': 'Owned Tax Fee',
            'display_order': 1, 'is_taxable': True, 'tax_rule_id': taxes[0].id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            fee_type.tax_rule_id = other_taxes[0]
        self.school._ensure_tax_types()
        self.assertEqual(self.school.tax_rule_ids, taxes)

    def test_actual_fee_tax_types_and_transportation(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        actual = forecast._ensure_actual_year()
        actual.enrollment_ids[0].student_count = 20
        fee = actual.fee_value_ids.filtered(lambda row: row.grade_level_id == actual.enrollment_ids[0].grade_level_id)[:1]
        vat = self.env['school.tax.rules'].create({'school_id': self.school.id, 'name': 'Actual Fee VAT', 'percentage': 0.1})
        levy = self.env['school.tax.rules'].create({'school_id': self.school.id, 'name': 'Actual Fee Levy', 'percentage': 0.05})
        fee.write({'amount': 1000, 'actual_tax_rule_ids': [(6, 0, (vat | levy).ids)]})
        self.assertEqual(fee.gross_revenue_amount, 20000)
        self.assertAlmostEqual(fee.tax_amount, 3000)
        self.assertAlmostEqual(fee.revenue_amount, 17000)
        self.assertEqual(forecast.fee_gross_total, 12000000)
        self.assertEqual(set(actual.fee_value_ids.mapped('fee_type_id.name')), {'Tuition Fee', 'Activity Fee', 'Admission Fee', 'Transportation Fee'})
        transport = actual.fee_value_ids.filtered(lambda row: row.grade_level_id == actual.enrollment_ids[0].grade_level_id and row.fee_type_id.is_optional)
        transport.write({'amount': 500, 'actual_tax_rule_ids': [(6, 0, vat.ids)]})
        self.assertEqual(transport.actual_applicability, 'selected')
        self.assertEqual(transport.gross_revenue_amount, 0)
        transport.actual_selected_students = 6
        self.assertEqual(transport.gross_revenue_amount, 3000)
        self.assertEqual(transport.revenue_amount, 2700)
        fee.actual_tax_rule_ids = [(5, 0, 0)]
        self.assertEqual(fee.tax_amount, 0)
        actual.actual_fee_type_id = fee.fee_type_id
        actual.actual_fee_amount = 1200
        actual.actual_fee_tax_rule_ids = vat
        actual.action_apply_actual_fee()
        self.assertEqual(fee.amount, 1200)
        self.assertEqual(fee.tax_amount, 2400)
        self.assertEqual(transport.amount, 500)
        self.assertEqual(transport.actual_selected_students, 6)
        self.assertEqual(forecast.fee_gross_total, 12000000)
        self.assertEqual(actual.income_status, 'in_progress')
        with Form(actual, view='school_planning.view_school_year_workspace') as form:
            form.actual_fee_type_id = transport.fee_type_id
            self.assertEqual(form.actual_fee_amount, 0)
            self.assertFalse(form.actual_fee_tax_rule_ids)
        excessive = self.env['school.tax.rules'].create({'school_id': self.school.id, 'name': 'Actual Excess Tax', 'percentage': 0.95})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            fee.actual_tax_rule_ids = [(6, 0, (vat | excessive).ids)]
        with self.assertRaises(ValidationError), self.cr.savepoint():
            vat.percentage = 1.1

    def test_unclassified_data_is_preserved(self):
        year = self.env['school.academic.years'].create({'school_id': self.school.id, 'academic_year_name': '2030-2031',
                                                       'start_date': '2030-09-01', 'end_date': '2031-06-30', 'dataset_type': 'legacy'})
        wizard = self._wizard(True)
        wizard.start_year = 2030
        forecasts = wizard._ensure_academic_years(1)
        self.assertNotEqual(forecasts, year)
        self.assertEqual(year.dataset_type, 'legacy')
        self.assertEqual(year.total_enrolled_students, 0)
        grade = wizard._ensure_grade_structure()[0]
        self.env['school.grade.enrollment'].create({'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 10})
        fee_type = wizard._ensure_fee_types()[0]
        fee = self.env['school.fee.values'].create({'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': fee_type.id, 'amount': 100})
        revenue_before = fee.revenue_amount
        position = wizard._ensure_operating_models()['teacher']
        self.env['school.staffing.overrides'].create({'academic_year_id': year.id, 'staff_position_id': position.id, 'employee_count': 3})
        salary = self.env['school.employment.salaries'].create({'academic_year_id': year.id, 'staff_position_id': position.id, 'monthly_salary': 1000, 'months_paid': 12})
        salary_before = salary.annual_cost
        year.action_classify_actual()
        self.assertEqual(year.dataset_type, 'actual')
        self.assertEqual(fee.revenue_amount, revenue_before)
        self.assertEqual(salary.annual_cost, salary_before)
        self.assertEqual(year.income_status, 'in_progress')
        self.assertEqual(year.payroll_status, 'in_progress')
        self.assertEqual(forecasts._ensure_actual_year(), year)

    def test_missing_actual_and_zero_forecast(self):
        forecast = self._wizard(True)._ensure_academic_years(1)
        comparison = self.env['school.forecast.comparison'].create({'school_id': self.school.id, 'forecast_year_id': forecast.id})
        line = comparison.line_ids.filtered(lambda row: row.metric == 'net_budget')
        self.assertEqual(line.actual_display, 'Not entered')
        self.assertEqual(line.difference_display, 'N/A')
        self.assertEqual(line.percentage, 'N/A')
        actual = forecast._ensure_actual_year()
        actual.action_complete_actual()
        comparison.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(line.result, 'On target')
        self.assertNotEqual(line.actual_display, 'Not entered')
        self.assertEqual(line.percentage, 'N/A')

    def test_single_total_students_control(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        actual = forecast._ensure_actual_year()
        forecast.total_students_input = 203
        self.assertEqual(sum(forecast.enrollment_ids.mapped('student_count')), 203)
        self.assertEqual(forecast.total_enrolled_students, 203)
        self.assertEqual(actual.total_students_input, 0)
        actual.total_students_input = 117
        self.assertEqual(sum(actual.enrollment_ids.mapped('student_count')), 117)
        self.assertEqual(forecast.total_students_input, 203)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            actual.total_students_input = -1

    def test_single_fee_and_connected_payroll(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        actual = forecast._ensure_actual_year()
        actual.total_students_input = 100
        actual.annual_fee_input = 1000
        self.assertAlmostEqual(actual.fee_gross_total, 100000)
        actual.payroll_percent_input = 40
        self.assertAlmostEqual(actual.payroll_amount_input, 40000)
        actual.total_students_input = 200
        self.assertAlmostEqual(actual.payroll_amount_input, 80000)
        actual.payroll_amount_input = 50000
        self.assertAlmostEqual(actual.payroll_percent_input, 25)
        actual.total_students_input = 100
        self.assertAlmostEqual(actual.payroll_amount_input, 50000)
        self.assertAlmostEqual(actual.payroll_percent_input, 50)
        self.assertEqual(actual.expense_total, 0)
        self.assertEqual(actual.salary_total, 50000)
        self.assertEqual(forecast.total_students_input, 100)
        self.assertEqual(forecast.employee_cost_total, 6000000)

    def test_form_payroll_controls(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        forecast.total_students_input = 100
        forecast.annual_fee_input = 1000
        with Form(forecast, view='school_planning.view_school_year_workspace') as form:
            form.payroll_percent_input = 40
            self.assertAlmostEqual(form.payroll_amount_input, 40000)
            self.assertEqual(form.total_enrolled_students, 100)
        self.assertEqual(forecast.payroll_basis, 'percent')
        self.assertAlmostEqual(forecast.salary_total, 40000)
        with Form(forecast, view='school_planning.view_school_year_workspace') as form:
            form.payroll_amount_input = 50000
            self.assertAlmostEqual(form.payroll_percent_input, 50)
        self.assertEqual(forecast.payroll_basis, 'amount')
        self.assertAlmostEqual(forecast.salary_total, 50000)

    def test_form_student_fee_and_normal_forecast_load(self):
        wizard = self._wizard()
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        actual = forecast._ensure_actual_year()
        actual.action_load_from_forecast()
        self.assertFalse(actual.payroll_summary_enabled)
        self.assertTrue(actual.employment_salary_ids)
        self.assertAlmostEqual(actual.salary_total, forecast.salary_total)
        self.assertEqual(actual.subject_distribution_ids.mapped('weekly_hours'), forecast.subject_distribution_ids.mapped('weekly_hours'))
        self.assertEqual(actual.teaching_status, 'in_progress')
        for fee_type in actual.fee_value_ids.mapped('fee_type_id'):
            actual.fee_value_ids.filtered(lambda row: row.fee_type_id == fee_type).with_context(defer_school_financial_refresh=True).write({
                'amount': 1000 if fee_type.name == 'Tuition Fee' else 0})
        with Form(actual, view='school_planning.view_school_year_workspace') as form:
            form.total_students_input = 90
            self.assertEqual(sum(form.enrollment_ids.edit(index).student_count for index in range(len(form.enrollment_ids))), 90)
            self.assertGreater(form.required_classrooms, 0)
            self.assertAlmostEqual(form.fee_gross_total, 90000)
        self.assertEqual(actual.total_enrolled_students, 90)
        self.assertAlmostEqual(actual.fee_gross_total, 90000)
        self.assertEqual(forecast.total_enrolled_students, 100)

    def test_blank_actual_expense_structure(self):
        wizard = self._wizard(True)
        wizard.action_load_demo_data()
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        actual = forecast._ensure_actual_year()
        self.assertTrue(forecast.operating_expense_ids.mapped('expense_item_id') <= actual.operating_expense_ids.mapped('expense_item_id'))
        self.assertTrue(all(row.amount == 0 for row in actual.operating_expense_ids))
        self.assertEqual(actual.expenses_status, 'not_started')
        actual.operating_expense_ids[:1].amount = 123
        forecast._ensure_actual_year()
        self.assertEqual(actual.operating_expense_ids[:1].amount, 123)

    def test_quick_prediction_form_defaults(self):
        self.configuration.classroom_weekly_hours = 36
        model = self.env['school.prediction.quick.setup.wizard'].with_context(default_school_id=self.school.id, default_extreme_efficiency=True)
        with Form(model, view='school_planning.view_school_prediction_quick_setup_wizard_form') as form:
            self.assertEqual(form.classroom_weekly_hours, 36)
            self.assertEqual(form.teaching_load_hours, 20)
            self.assertEqual(len(form.extreme_expense_line_ids), 1)
            self.assertEqual(len(form.payroll_rule_ids), 1)

    def test_global_seeds_without_demo_and_pdf_actions(self):
        self.configuration.write({'students_per_classroom': 18, 'classroom_weekly_hours': 30, 'teacher_weekly_hours': 15})
        self.configuration.payroll_base_annual_amount = 42
        projector = self.configuration.asset_ids.filtered(lambda seed: seed.code == 'projector')
        projector.unit_price = 900
        self.configuration.infrastructure_mode = 'new'
        wizard = self._wizard(True)
        self.assertTrue(all(line.student_count == 0 and line.annual_fee_per_student == 0 for line in wizard.line_ids))
        self.assertEqual(wizard.payroll_rule_ids.base_annual_amount, 42)
        wizard.line_ids.write({'student_count': 100, 'annual_fee_per_student': 1000})
        wizard.action_apply()
        forecast = wizard._existing_forecast_years()[0]
        self.assertEqual(forecast.students_per_classroom, 18)
        self.assertEqual(forecast.asset_price_ids.filtered(lambda row: row.asset_item_id.planning_seed_key == 'projector').unit_price, 900)
        self.assertAlmostEqual(forecast.salary_total, 42000)
        other = self.env['school.schools'].create({'name': 'Second Seed School', 'currency': 'EGP'})
        second = self.env['school.prediction.quick.setup.wizard'].create({'school_id': other.id, 'extreme_efficiency': True})
        self.assertEqual(second.classroom_weekly_hours, 30)
        self.assertEqual(second.payroll_rule_ids.base_annual_amount, 42)
        self.configuration.classroom_weekly_hours = 40
        self.assertEqual(forecast.classroom_weekly_hours, 30)
        self.assertIn(forecast.action_print_financial_summary_pdf()['type'], ('ir.actions.act_url', 'ir.actions.report'))
        self.assertEqual(forecast.action_open_financial_summary_email_wizard()['res_model'], 'school.financial.summary.email.wizard')
        self.assertTrue(forecast._build_financial_summary_pdf_bytes().startswith(b'%PDF'))
        projector.unit_price = 1000
        wizard.action_apply()
        self.assertEqual(forecast.asset_price_ids.filtered(lambda row: row.asset_item_id.planning_seed_key == 'projector').unit_price, 1000)
        self.assertGreater(forecast.startup_cost_total, 0)
        wizard.infrastructure_mode = 'existing'
        wizard.action_apply()
        self.assertTrue(forecast.room_plan_ids)
        self.assertTrue(forecast.asset_price_ids)
        self.assertEqual(forecast.startup_cost_total, 0)
        self.assertEqual(forecast.new_rooms_expense_total, 0)
        forecast.total_students_input = 10000
        forecast.room_plan_ids.write({'existing_rooms': 0, 'manual_new_rooms': 10})
        self.assertGreater(forecast.required_classrooms, 0)
        self.assertEqual(forecast.startup_cost_total, 0)
        self.assertEqual(forecast.new_rooms_expense_total, 0)
        self.assertTrue(all(price.startup_cost == 0 for price in forecast.asset_price_ids))
        projector.unit_price = 1200
        desk = self.configuration.asset_ids.filtered(lambda seed: seed.code == 'student_desk')
        desk.write({'unit_price': 5, 'quantity': 2})
        forecast.infrastructure_mode = 'new'
        cost_per_room = 1200 + forecast.students_per_classroom * 5 * 2
        self.assertEqual(forecast.room_plan_ids.existing_rooms, 0)
        self.assertEqual(forecast.room_plan_ids.calculated_new_rooms, forecast.required_classrooms)
        self.assertAlmostEqual(forecast.new_rooms_expense_total, (forecast.required_classrooms + 10) * cost_per_room)
        self.assertAlmostEqual(forecast.startup_cost_total, forecast.new_rooms_expense_total)
        forecast.infrastructure_mode = 'existing'
        self.assertEqual(forecast.startup_cost_total, 0)
        self.assertEqual(forecast.new_rooms_expense_total, 0)