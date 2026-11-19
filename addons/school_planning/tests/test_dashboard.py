from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSchoolDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.school = cls.env['school.schools'].create({
            'name': 'Dashboard School', 'currency': 'EUR',
        })
        cls.group = cls.env['school.grade.groups'].create({
            'school_id': cls.school.id, 'name': 'Primary', 'display_order': 1,
        })
        cls.grade = cls.env['school.grade.levels'].create({
            'school_id': cls.school.id, 'group_id': cls.group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        cls.years = cls.env['school.academic.years'].create([
            {'school_id': cls.school.id, 'academic_year_name': f'{start}-{start + 1}',
             'start_date': f'{start}-09-01', 'end_date': f'{start + 1}-06-30',
             'dataset_type': dataset}
            for start, dataset in [(2096, 'forecast'), (2097, 'forecast'), (2096, 'actual')]
        ])
        for index, year in enumerate(cls.years):
            cls.env['school.grade.enrollment'].create({
                'academic_year_id': year.id, 'grade_level_id': cls.grade.id,
                'student_count': (index + 1) * 10,
            })

    def test_dataset_isolation_and_live_totals(self):
        data = self.school.get_dashboard(self.school.id)
        forecasts = self.years.filtered(lambda year: year.dataset_type == 'forecast')
        self.assertEqual([row['id'] for row in data['rows']], forecasts.ids)
        self.assertEqual(data['totals']['students'], 20)
        self.assertEqual(data['totals']['student_years'], 30)
        self.assertEqual(data['grades'][0]['students'], 30)
        self.assertEqual(data['currency'], 'EUR')
        self.assertEqual(data['totals']['net_budget'], sum(forecasts.mapped('net_budget')))
        forecasts[-1].enrollment_ids.student_count = 45
        self.assertEqual(self.school.get_dashboard(self.school.id)['totals']['students'], 45)

    def test_year_filter_and_provisional_actuals(self):
        year = self.years[-1]
        data = self.school.get_dashboard(self.school.id, 'actual', year.id)
        self.assertEqual([row['id'] for row in data['rows']], year.ids)
        self.assertEqual(data['rows'][0]['status'], year.actual_status)
        self.assertEqual(data['totals']['students'], year.total_enrolled_students)
        grade = next(item for item in data['grades'] if item['id'] == self.grade.id)
        self.assertEqual(grade['revenue'], sum(year.enrollment_ids.filtered(
            lambda line: line.grade_level_id == self.grade
        ).mapped('revenue_total')))

    def test_multiple_year_selection_filters_comparison_and_totals(self):
        forecasts = self.years.filtered(lambda year: year.dataset_type == 'forecast')
        third = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': '2098-2099',
            'start_date': '2098-09-01', 'end_date': '2099-06-30', 'dataset_type': 'forecast',
        })
        actual = forecasts[0]._ensure_actual_year()
        selected = forecasts[0] | third
        data = self.school.get_dashboard(self.school.id, year_ids=selected.ids)
        self.assertEqual([row['id'] for row in data['rows']], selected.ids)
        self.assertEqual([row['id'] for row in data['comparisons']], selected.ids)
        self.assertEqual(data['totals']['net_budget'], sum(selected.mapped('net_budget')))
        self.assertTrue(data['comparisons'][0]['actual_exists'])
        self.assertFalse(data['comparisons'][1]['actual_exists'])
        self.assertEqual(len(self.school.get_dashboard(self.school.id)['comparisons']), 3)
        self.assertEqual(self.school.get_dashboard(self.school.id, year_ids=[])['rows'], [])
        self.assertEqual(self.school.get_dashboard(self.school.id, year_ids=[])['comparisons'], [])
        actual_data = self.school.get_dashboard(self.school.id, dataset='actual', year_ids=actual.ids)
        self.assertEqual([row['id'] for row in actual_data['comparisons']], forecasts[0].ids)
        for invalid in ([forecasts[0].id, self.years[-1].id], [False], 'bad', [99999999]):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.school.get_dashboard(self.school.id, year_ids=invalid)
        with self.assertRaises(ValidationError):
            self.school.get_dashboard(self.school.id, year_id=forecasts[0].id, year_ids=selected.ids)

    def test_financial_values_and_cost_reconciliation(self):
        year = self.years[0]
        fee = self.env['school.fee.types'].create({
            'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1,
        })
        self.env['school.fee.values'].create({
            'academic_year_id': year.id, 'grade_level_id': self.grade.id,
            'fee_type_id': fee.id, 'amount': 2000,
        })
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Operating', 'display_order': 1,
        })
        self.env['school.expense.values'].create({
            'academic_year_id': year.id, 'expense_category_id': category.id, 'amount': 200,
        })
        year.write({'payroll_summary_enabled': True, 'payroll_basis': 'amount', 'payroll_fixed_amount': 500})
        data = self.school.get_dashboard(self.school.id, year_id=year.id)
        totals = data['totals']
        self.assertEqual(totals['fee_gross_total'], 20000)
        self.assertEqual(totals['operating_cost_total'], 700)
        self.assertEqual(totals['net_budget'], 19300)
        self.assertAlmostEqual(totals['margin'], 96.5)
        self.assertEqual(totals['employee_cost_total'] + totals['non_payroll_expense_total'], 700)
        self.assertEqual(data['grades'][0]['revenue'], 20000)
        year.payroll_fixed_amount = 25000
        negative = self.school.get_dashboard(self.school.id, year_id=year.id)['totals']
        self.assertEqual(negative['net_budget'], -5200)
        self.assertEqual(negative['margin'], -26)
        year.action_freeze_baseline()
        frozen = self.school.get_dashboard(self.school.id, year_id=year.id)
        self.assertEqual(frozen['rows'][0]['status'], 'approved')
        self.assertEqual(frozen['totals']['net_budget'], year.baseline_totals['net_budget'])

    def test_invalid_filters_rejected(self):
        with self.assertRaises(ValidationError):
            self.school.get_dashboard(self.school.id, 'all')
        with self.assertRaises(ValidationError):
            self.school.get_dashboard(self.school.id, 'forecast', self.years[-1].id)
        other = self.env['school.schools'].create({'name': 'Other school', 'currency': 'USD'})
        with self.assertRaises(ValidationError):
            other.get_dashboard(other.id, 'forecast', self.years[0].id)
        with self.assertRaises(ValidationError):
            self.school.get_dashboard(-1)

    def test_empty_dataset_and_action(self):
        data = self.school.get_dashboard(self.school.id, 'legacy')
        self.assertFalse(data['rows'])
        self.assertFalse(data['years'])
        self.assertEqual(data['totals']['margin'], 0)
        self.assertEqual(data['totals']['students'], 0)
        action = self.school.action_open_dashboard()
        self.assertEqual(action['params']['school_id'], self.school.id)

    def test_dashboard_respects_school_record_rules(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Dashboard Reader', 'login': 'dashboard_reader',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.env['ir.rule'].create({
            'name': 'Dashboard selected school only',
            'model_id': self.env['ir.model']._get_id('school.schools'),
            'domain_force': f"[('id', '=', {self.school.id})]",
        })
        data = self.env['school.schools'].with_user(user).get_dashboard()
        self.assertEqual(data['school_id'], self.school.id)
        self.assertEqual([school['id'] for school in data['schools']], self.school.ids)

    def test_chart_metrics_and_breakdowns_use_existing_calculations(self):
        year = self.years[0]
        fee_type = self.env['school.fee.types'].create({
            'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1,
        })
        self.env['school.fee.values'].create({
            'academic_year_id': year.id, 'grade_level_id': self.grade.id,
            'fee_type_id': fee_type.id, 'amount': 2000,
        })
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Learning materials', 'display_order': 1,
        })
        item = self.env['school.expense.items'].create({
            'school_id': self.school.id, 'expense_category_id': category.id,
            'name': 'Books', 'display_order': 1,
        })
        self.env['school.expense.values'].create({
            'academic_year_id': year.id, 'expense_category_id': category.id, 'amount': 350,
        })
        self.env['school.expense.values'].create({
            'academic_year_id': year.id, 'expense_category_id': category.id,
            'expense_item_id': item.id, 'amount': 100,
        })
        staff_category = self.env['school.staff.categories'].create({
            'school_id': self.school.id, 'name': 'Teaching', 'display_order': 1,
        })
        position = self.env['school.staff.positions'].create({
            'school_id': self.school.id, 'staff_category_id': staff_category.id,
            'title': 'Teacher', 'display_order': 1,
        })
        self.env['school.staffing.rules'].create({
            'school_id': self.school.id, 'staff_position_id': position.id,
            'display_order': 1, 'calculation_method': 'fixed', 'parameter_value': 2,
        })
        self.env['school.employment.salaries'].create({
            'academic_year_id': year.id, 'staff_position_id': position.id,
            'monthly_salary': 1000, 'months_paid': 10,
        })

        data = self.school.get_dashboard(self.school.id, year_id=year.id)
        row = data['rows'][0]
        self.assertEqual(row['fee_gross_total'], year.fee_gross_total)
        self.assertEqual(row['payroll'], year.salary_total)
        self.assertEqual(row['staff_count'], 2)
        self.assertEqual(row['teachers_required'], year.required_teachers)
        self.assertEqual(data['breakdowns']['students_by_grade'], [{'label': 'Grade 1', 'value': 10}])
        self.assertEqual(data['breakdowns']['expense_category_spend'], [
            {'label': 'Learning materials', 'value': 350},
        ])
        self.assertEqual(data['breakdowns']['payroll_by_position'], [
            {'label': 'Teacher', 'value': 20000},
        ])

    def test_forecast_comparison_uses_linked_actual_and_keeps_unentered_null(self):
        forecast = self.years.filtered(lambda year: year.dataset_type == 'forecast')[0]
        actual = forecast._ensure_actual_year()
        data = self.school.get_dashboard(self.school.id)
        pairs = {row['id']: row for row in data['comparisons']}
        self.assertTrue(pairs[forecast.id]['actual_exists'])
        self.assertIsNone(pairs[forecast.id]['actual']['net_budget'])
        self.assertEqual(pairs[forecast.id]['actual']['students'], actual.total_enrolled_students)
        other_forecast = self.years.filtered(
            lambda year: year.dataset_type == 'forecast' and year != forecast
        )
        self.assertFalse(pairs[other_forecast.id]['actual_exists'])
        self.assertIsNone(pairs[other_forecast.id]['actual'])

        actual.write({
            'enrollment_status': 'complete', 'income_status': 'complete',
            'expenses_status': 'complete', 'payroll_status': 'complete',
            'assets_status': 'complete', 'teaching_status': 'complete',
        })
        complete = {row['id']: row for row in self.school.get_dashboard(self.school.id)['comparisons']}
        self.assertEqual(complete[forecast.id]['actual']['net_budget'], actual.net_budget)
        self.assertEqual(complete[forecast.id]['actual']['students'], actual.total_enrolled_students)
        self.assertFalse(complete[forecast.id]['actual_provisional'])

    def test_shared_chart_preferences_are_admin_only_and_school_scoped(self):
        model = self.env['school.schools']
        preferences = {
            'trend_metric': 'students', 'trend_type': 'bar',
            'breakdown_metric': 'students_by_grade', 'breakdown_type': 'bar',
            'comparison_metric': 'payroll',
        }
        saved = self.school.save_dashboard_chart_preferences(preferences)
        self.assertEqual(saved, preferences)

        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Dashboard Reader', 'login': 'dashboard_preferences_reader',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        data = model.with_user(user).get_dashboard(self.school.id)
        self.assertEqual(data['chart_preferences'], preferences)
        self.assertFalse(data['can_save_chart_preferences'])
        with self.assertRaises(AccessError):
            self.school.with_user(user).save_dashboard_chart_preferences({})

        other = model.create({'name': 'Other dashboard school', 'currency': 'USD'})
        other_data = model.get_dashboard(other.id)
        self.assertEqual(other_data['chart_preferences']['trend_metric'], 'net_budget')

        for invalid in ({'trend_metric': 'arbitrary_database_field'}, {'trend_metric': []}, {'unknown': 1}, []):
            with self.assertRaises(ValidationError):
                self.school.save_dashboard_chart_preferences(invalid)
        defaults = self.school.save_dashboard_chart_preferences({})
        self.assertEqual(defaults['trend_metric'], 'net_budget')
