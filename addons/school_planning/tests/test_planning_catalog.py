import io

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase
from psycopg2.extras import Json

from .test_report_branding import PdfReader


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

    def test_per_student_income_grade_amounts_and_frozen_snapshot(self):
        year, other_year = self.years
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grades = self.env['school.grade.levels'].create([
            {'school_id': self.school.id, 'group_id': group.id, 'name': f'Grade {index}', 'sort_order': index}
            for index in (1, 2)
        ])
        enrollments = self.env['school.grade.enrollment'].create([
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': count}
            for grade, count in zip(grades, (10, 30))
        ])
        tuition = self.env['school.fee.types'].create({
            'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1, 'forecast_tuition': True,
        })
        fees = self.env['school.fee.values'].create([
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': tuition.id, 'amount': amount}
            for grade, amount in zip(grades, (100, 300))
        ])
        seed = self.item('Transportation Fees', 'income')
        seed.write({'basis': 'student', 'price_set': False, 'grade_scope': 'all'})
        year.create_detailed_income_list()
        year.set_detailed_income_selection(seed.id, True)
        self.assertEqual(year.detailed_income_pending, 1)
        year.set_detailed_student_grade(seed.id, grades[0].id, 50)
        self.assertEqual(year.detailed_income_pending, 1)
        year.set_detailed_student_grade(seed.id, False, 50)
        year.set_detailed_student_grade(seed.id, grades[1].id, 100)
        source = year._forecast_income_sources()[0][1]
        self.assertEqual(source['amount'], 3500)
        self.assertEqual([grade['rate'] for grade in source['grades']], [50, 100])
        self.assertEqual(year.fee_gross_total, 13500)
        self.assertEqual(enrollments.mapped('revenue_total'), [1500, 12000])
        self.assertFalse(other_year.detailed_occurrence_values)
        data = year.get_detailed_income_list()
        item = next(item for group_data in data['groups'] for category in group_data['categories']
                    for item in category['items'] if item['id'] == seed.id)
        self.assertEqual(item['grade_average'], 87.5)
        year.set_detailed_student_grade(seed.id, False, 80)
        self.assertEqual([grade['rate'] for grade in year._forecast_income_sources()[0][1]['grades']], [80, 80])
        self.assertEqual(year.fee_gross_total, 13200)
        year.set_detailed_occurrence_value('income', seed.id, 'seed', None)
        self.assertEqual(year.detailed_income_pending, 1)
        year.set_detailed_student_grade(seed.id, False, 80)
        enrollments.write({'student_count': 0})
        item = next(item for group_data in year.get_detailed_income_list()['groups']
                    for category in group_data['categories'] for item in category['items'] if item['id'] == seed.id)
        self.assertEqual(item['grade_average'], 80)
        self.assertEqual(year.fee_gross_total, 0)
        enrollments[0].student_count = 10
        enrollments[1].student_count = 30
        year.set_detailed_tuition_grade(grades[0].id, 200)
        self.assertEqual(year.get_detailed_income_list()['tuition_average'], 275)
        year.set_detailed_tuition_grade(False, 150)
        self.assertEqual(fees.mapped('amount'), [150, 150])
        year.action_freeze_baseline()
        before = enrollments.mapped('revenue_total')
        seed.grade_scope = 'selected'
        self.assertEqual(enrollments.mapped('revenue_total'), before)
        self.assertEqual(year.fee_gross_total, 9200)
        with self.assertRaises(ValidationError):
            year.set_detailed_student_grade(seed.id, False, 10)

    def test_income_grade_scope_and_tuition_scope(self):
        year = self.years[0]
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grades = self.env['school.grade.levels'].create([
            {'school_id': self.school.id, 'group_id': group.id, 'name': f'Grade {index}', 'sort_order': index}
            for index in (1, 2)
        ])
        self.env['school.grade.enrollment'].create([
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 10}
            for grade in grades
        ])
        tuition_type = self.env['school.fee.types'].create({
            'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1, 'forecast_tuition': True,
        })
        fees = self.env['school.fee.values'].create([
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': tuition_type.id, 'amount': 100}
            for grade in grades
        ])
        preset = self.env['school.grade.level.preset'].search([('name', '=', 'Grade 2')], limit=1)
        income = self.item('Activity fees', 'income')
        income.write({'basis': 'student', 'grade_scope': 'selected', 'grade_ids': [fields.Command.set(preset.ids)]})
        year.create_detailed_income_list()
        year.set_detailed_income_selection(income.id, True)
        with self.assertRaises(ValidationError):
            year.set_detailed_student_grade(income.id, grades[0].id, 50)
        year.set_detailed_student_grade(income.id, False, 50)
        fees[1].amount = 200
        self.assertEqual(year.annual_fee_input, 150)
        self.assertEqual(year.fee_gross_total, 3500)
        tuition_seed = self.item('Tuition Fees', 'income')
        tuition_seed.write({'grade_scope': 'selected', 'grade_ids': [fields.Command.set(preset.ids)]})
        self.assertEqual(year.annual_fee_input, 200)
        self.assertEqual(year.fee_gross_total, 2500)
        self.assertEqual([row['name'] for row in year.get_detailed_income_list()['tuition_grades']], ['Grade 2'])
        year.set_detailed_tuition_grade(False, 200)
        self.assertEqual(fees.mapped('amount'), [100, 200])
        self.assertEqual(year.fee_gross_total, 2500)
        with Form(year, view='school_planning.view_school_year_workspace') as form:
            form.annual_fee_input = 250
        self.assertEqual(fees.mapped('amount'), [100, 250])
        year.set_detailed_occurrence_value('income', income.id, 'revenue_percent', 10)
        self.assertEqual(year.fee_gross_total, 2750)

    def test_grade_metrics_use_gross_fees_and_grade_scoped_student_expenses(self):
        year = self.years[0]
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grades = self.env['school.grade.levels'].create([
            {'school_id': self.school.id, 'group_id': group.id, 'name': f'Grade {index}', 'sort_order': index}
            for index in (1, 2, 3)
        ])
        enrollments = self.env['school.grade.enrollment'].create([
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': students}
            for grade, students in zip(grades, (10, 20, 0))
        ])
        tuition = self.env['school.fee.types'].create({
            'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1, 'forecast_tuition': True,
        })
        self.env['school.fee.values'].create([
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': tuition.id, 'amount': price}
            for grade, price in zip(grades, (100, 200, 300))
        ])
        year.prediction_income_tax_percent = 10
        self.assertEqual(enrollments.mapped('revenue_total'), [1000, 4000, 0])
        self.assertEqual(enrollments.mapped('revenue_per_student'), [100, 200, 0])
        self.assertEqual(enrollments.mapped('cost_total'), [0, 0, 0])

        books = self.item('Hardcopy Books', 'expense')
        worksheets = self.item('Printed Worksheets and Booklets', 'expense')
        paid = self.item('Ministry Books', 'expense')
        shared = self.item('Marketing, Promotional Expenses', 'expense')
        participation = self.item('Annual Shows', 'expense')
        preset = self.env['school.grade.level.preset'].search([('name', '=', 'Grade 2')], limit=1)
        for seed, price, basis in (
            (books, 10, 'student'), (worksheets, 5, 'student'), (paid, 90, 'student'),
            (shared, 1000, 'fixed'), (participation, 0, 'student_percent'),
        ):
            seed.write({'price_type': 'allocated', 'price': price, 'price_set': True,
                        'currency_id': self.school.currency_id.id, 'basis': basis})
        worksheets.write({'grade_scope': 'selected', 'grade_ids': [fields.Command.set(preset.ids)]})
        participation.write({'grade_scope': 'selected', 'grade_ids': [fields.Command.set(preset.ids)]})
        year.create_detailed_expense_list()
        for seed in books | worksheets | paid | shared | participation:
            year.set_detailed_expense_selection(seed.id, True)
        paid.student_paid = True
        year.set_detailed_student_percentage('expense', participation.id, 6, 50)
        year.write({'expense_calculation_mode': 'detailed', 'payroll_summary_enabled': True,
                    'payroll_basis': 'amount', 'payroll_fixed_amount': 500})
        self.assertEqual(enrollments.mapped('cost_per_student'), [10, 18, 10])
        self.assertEqual(enrollments.mapped('cost_total'), [100, 360, 0])
        self.assertEqual(year.operating_cost_total, 1960)
        self.assertAlmostEqual(year.cost_per_student_grade_level_avg, 38 / 3)
        self.assertEqual(year.revenue_per_student_grade_level_avg, 100)
        dashboard = self.school.get_dashboard(self.school.id, year_id=year.id)
        self.assertEqual({row['id']: row['cost'] for row in dashboard['grades']},
                         {grade.id: cost for grade, cost in zip(grades, (100, 360, 0))})
        self.assertEqual([row['cost_per_student'] for row in dashboard['grades']], [10, 18, 10])

        year.set_detailed_occurrence_value('expense', books.id, 'amount', 90)
        self.assertEqual(enrollments.mapped('cost_per_student'), [3, 11, 3])
        enrollments[0].student_count = 20
        self.assertEqual(enrollments[0].revenue_total, 2000)
        self.assertEqual(enrollments[0].cost_total, 45)
        year.set_detailed_expense_selection(worksheets.id, False)
        self.assertEqual(enrollments[1].cost_per_student, 5.25)
        year.action_freeze_baseline()
        before = enrollments.read(['cost_total', 'cost_per_student'])
        participation.grade_scope = 'all'
        participation.price = 100
        self.assertEqual(enrollments.read(['cost_total', 'cost_per_student']), before)

    def test_actual_grade_revenue_is_gross_and_averaged_over_grade_enrollment(self):
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        self.env['school.fee.types'].create({'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1})
        actual = self.years[0]._ensure_actual_year()
        enrollment = actual.enrollment_ids[0]
        enrollment.student_count = 10
        fee = actual.fee_value_ids.filtered(lambda row: row.grade_level_id == enrollment.grade_level_id)[0]
        fee.write({'amount': 100, 'actual_applicability': 'selected',
                   'actual_selected_students': 2, 'actual_tax_percent': 25})
        self.assertEqual(fee.revenue_amount, 150)
        self.assertEqual(enrollment.revenue_total, 200)
        self.assertEqual(enrollment.revenue_per_student, 20)
        self.assertEqual(enrollment.cost_total, 0)

    def test_forecast_detailed_income_totals_and_sources(self):
        year = self.years[0]
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grade = self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        self.env['school.grade.enrollment'].create({
            'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 10,
        })
        tuition, activity = self.env['school.fee.types'].create([
            {'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1, 'forecast_tuition': True},
            {'school_id': self.school.id, 'name': 'Activity', 'display_order': 2},
        ])
        rows = self.env['school.fee.values'].create([
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': tuition.id, 'amount': 100},
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': activity.id, 'amount': 20},
        ])
        year.prediction_income_tax_percent = 10
        self.assertEqual(year.fee_gross_total, 1000)
        self.assertEqual(year.annual_fee_input, 100)
        income = self.item('Activity fees', 'income')
        year.create_detailed_income_list()
        year.set_detailed_income_selection(income.id, True)
        self.assertEqual(year.detailed_income_pending, 1)
        report = self.env['school.financial.report'].search([('academic_year_id', '=', year.id)])
        self.assertTrue(report.income_incomplete)
        with self.assertRaisesRegex(ValidationError, 'Complete the selected detailed income'):
            year.action_freeze_baseline()
        year.set_detailed_occurrence_value('income', income.id, 'amount', 400)
        self.assertEqual(year.detailed_income_pending, 0)
        self.assertFalse(report.income_incomplete)
        self.assertEqual(year.fee_gross_total, 1400)
        self.assertEqual(year.tax_deductions_total, 140)
        self.assertEqual(year.fee_total, 1260)
        self.assertEqual(year.annual_fee_input, 100)
        self.assertEqual(rows[1].amount, 20)
        report = self.env['school.financial.report'].search([('academic_year_id', '=', year.id)])
        self.assertEqual(report.gross_revenue, 1400)
        chart = self.school.get_dashboard(self.school.id, year_id=year.id)['breakdowns']['income_by_source']
        self.assertEqual({row['label']: row['value'] for row in chart}, {'Tuition': 1000, 'Activity fees': 400})
        actual = year._ensure_actual_year()
        with self.assertRaisesRegex(ValidationError, 'Detailed forecast income cannot be allocated'):
            actual.action_load_from_forecast()
        self.assertEqual(actual.income_status, 'not_started')
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'school_planning.report_school_financial_summary_pdf', year.ids,
        )
        self.assertIn(b'Detailed Income', html)
        self.assertIn(b'Activity fees', html)
        if PdfReader:
            text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(year._build_financial_summary_pdf_bytes())).pages)
            self.assertIn('Detailed Income', text)
            self.assertIn('Activity fees', text)
        income.basis = 'student_percent'
        year.set_detailed_student_percentage('income', income.id, 50, 30)
        self.assertEqual(year.fee_gross_total, 1150)
        year.set_detailed_occurrence_value('income', income.id, 'revenue_percent', 10)
        self.assertEqual(year.fee_gross_total, 1100)
        year.action_freeze_baseline()
        income.name = 'Renamed activity'
        income.replaces_tuition = True
        tuition.forecast_tuition = False
        self.assertEqual(year.fee_gross_total, 1100)
        self.assertEqual(year._forecast_income_sources()[0][1]['name'], 'Activity fees')
        self.assertEqual(year.get_detailed_income_list()['total'], 100)
        self.assertTrue(rows[0].included_in_forecast)
        self.assertEqual(report.gross_revenue, 1100)
        chart = self.school.get_dashboard(self.school.id, year_id=year.id)['breakdowns']['income_by_source']
        self.assertEqual({row['label']: row['value'] for row in chart}, {'Tuition': 1000, 'Activity fees': 100})

    def test_legacy_frozen_grade_metrics_keep_historical_fee_rows_and_costs(self):
        year = self.years[0]
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grade = self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        enrollment = self.env['school.grade.enrollment'].create({
            'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 10,
        })
        tuition, activity = self.env['school.fee.types'].create([
            {'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1, 'forecast_tuition': True},
            {'school_id': self.school.id, 'name': 'Activity', 'display_order': 2},
        ])
        self.env['school.fee.values'].create([
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': tuition.id, 'amount': 100},
            {'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': activity.id, 'amount': 20},
        ])
        year.prediction_income_tax_percent = 10
        year.action_freeze_baseline()
        year.flush_recordset(['baseline_totals', 'baseline_income_sources'])
        self.env.cr.execute(
            "UPDATE school_academic_years SET baseline_totals = baseline_totals - 'grade_student_costs', "
            "baseline_income_sources = NULL WHERE id = %s", [year.id],
        )
        self.env.invalidate_all()
        self.assertEqual(enrollment.revenue_total, 1080)
        self.assertEqual(enrollment.cost_total, 120)
        self.school.report_show_grade_details = True
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'school_planning.report_school_financial_summary_pdf', year.ids,
        )
        self.assertIn(b'Historical net fee revenue and previously allocated costs.', html)
        self.assertIn(b'Net Fee Revenue', html)
        if PdfReader:
            text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(year._build_financial_summary_pdf_bytes())).pages)
            self.assertIn('Historical net fee revenue and previously allocated costs.', text)
            self.assertIn('Net Fees', text)

    def test_tuition_is_automatically_included_from_fee_rows(self):
        year = self.years[0]
        tuition = self.item('Tuition Fees', 'income')
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grade = self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        enrollment = self.env['school.grade.enrollment'].create({
            'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 10,
        })
        fee_type = self.env['school.fee.types'].create({'school_id': self.school.id, 'name': 'Tuition', 'display_order': 1})
        self.env['school.fee.values'].create({
            'academic_year_id': year.id, 'grade_level_id': grade.id, 'fee_type_id': fee_type.id, 'amount': 100,
        })
        tuition.name = 'Custom Tuition'
        year.write({
            'detailed_incomes_created': True,
            'detailed_income_seed_ids': [fields.Command.link(tuition.id)],
            'detailed_occurrence_values': {str(tuition.id): {'mode': 'amount', 'value': 250}},
        })
        data = year.get_detailed_income_list()
        self.assertEqual((data['baseline'], data['total'], data['pending']), (1000, 0, 0))
        self.assertNotIn(tuition.id, [
            item['id'] for group in data['groups']
            for category in group['categories'] for item in category['items']
        ])
        self.assertEqual(year.fee_gross_total, 1000)
        self.assertEqual(year.detailed_occurrence_values[str(tuition.id)]['value'], 250)
        self.assertIn(tuition, year.detailed_income_seed_ids)
        with self.assertRaisesRegex(ValidationError, 'included automatically'):
            year.set_detailed_income_selection(tuition.id, True)

        other = self.item('Activity fees', 'income')
        year.set_detailed_income_selection(other.id, True)
        year.set_detailed_occurrence_value('income', other.id, 'amount', 50)
        enrollment.student_count = 20
        self.assertEqual(year.get_detailed_income_list()['baseline'], 2000)
        self.assertEqual(year.fee_gross_total, 2050)
        report = self.env['school.financial.report'].search([('academic_year_id', '=', year.id)])
        self.assertEqual(report.gross_revenue, 2050)
        chart = self.school.get_dashboard(self.school.id, year_id=year.id)['breakdowns']['income_by_source']
        self.assertEqual({row['label']: row['value'] for row in chart}, {'Tuition': 2000, 'Activity fees': 50})
        year.action_freeze_baseline()
        self.assertEqual(year.fee_gross_total, 2050)

    def test_previously_approved_manual_tuition_is_preserved(self):
        year = self.years[0]
        tuition = self.item('Tuition Fees', 'income')
        year.write({
            'detailed_incomes_created': True,
            'detailed_income_seed_ids': [fields.Command.link(tuition.id)],
            'detailed_occurrence_values': {str(tuition.id): {'mode': 'amount', 'value': 250}},
        })
        year.action_freeze_baseline()
        totals = dict(year.baseline_totals, fee_gross_total=250, fee_total=250, net_budget=250)
        sources = [
            {'name': 'Tuition', 'kind': 'tuition', 'row_ids': [], 'amount': 0},
            {'name': 'Tuition Fees', 'kind': 'detailed', 'seed_id': tuition.id, 'amount': 250},
        ]
        year.flush_recordset(['baseline_totals', 'baseline_income_sources'])
        self.env.cr.execute(
            'UPDATE school_academic_years SET baseline_totals = %s, baseline_income_sources = %s WHERE id = %s',
            [Json(totals), Json(sources), year.id],
        )
        self.env.invalidate_all()
        self.assertEqual(year.fee_gross_total, 250)
        self.assertEqual(year.get_detailed_income_list()['total'], 250)
        self.assertEqual(year._forecast_income_sources()[0], sources)
        report = self.env['school.financial.report']
        report._refresh_for_academic_years(year.ids)
        self.assertEqual(report.search([('academic_year_id', '=', year.id)]).gross_revenue, 250)

    def test_hierarchy_and_price_types(self):
        income_tax = self.item('Income Taxes', 'expense')
        self.assertEqual(income_tax.category_seed_id.name, 'Tax Payments')
        self.assertEqual(income_tax.category_seed_id.parent_id.name, 'Official Payments')
        self.assertEqual(income_tax.price_type, 'allocated')
        self.assertEqual(self.item('Internet Bills', 'expense').price_type, 'fixed')
        self.assertEqual(self.item('School License Renewal', 'expense').category_seed_id.price_type, 'fixed')
        self.assertEqual(self.item('Activity fees', 'income').category_seed_id.name, 'Other Incomes')
        self.assertEqual(self.item('Activity fees', 'income').price_type, 'fixed')
        self.assertFalse(self.env.ref('school_planning.operational_digital_ixl').active)
        with self.assertRaises(ValidationError):
            income_tax.category_seed_id.parent_id.parent_id = income_tax.category_seed_id

    def test_allocations_are_year_specific_and_fixed_is_not_overridable(self):
        first, second = self.years
        income = self.item('Admission Exam Fees', 'income')
        expense = self.item('Income Taxes', 'expense')
        fixed = self.item('Activity fees', 'income')
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
        self.assertEqual((first.fee_gross_total, first.expense_total), (baseline[0] + 125, baseline[1]))
        first.set_detailed_occurrence_value('income', income.id, 'amount', 60)
        self.assertEqual(first.get_detailed_income_list()['total'], 160)
        self.assertEqual(second.get_detailed_income_list()['total'], 140)
        first.set_detailed_occurrence_value('income', income.id, 'seed', None)
        self.assertEqual(first.get_detailed_income_list()['total'], 125)
        self.assertEqual(first.detailed_allocated_prices[str(income.id)], 25)
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

    def test_detailed_tuition_inputs_are_retained_without_being_counted(self):
        year = self.years[0]
        tuition = self.item('Tuition Fees', 'income')
        other = self.item('Activity fees', 'income')
        year.write({
            'detailed_incomes_created': True,
            'detailed_income_seed_ids': [fields.Command.link(tuition.id), fields.Command.link(other.id)],
            'detailed_occurrence_values': {
                str(tuition.id): {'mode': 'amount', 'value': 100},
                str(other.id): {'mode': 'amount', 'value': 25},
            },
        })
        for active in (True, False):
            tuition.active = active
            data = year.get_detailed_income_list()
            items = [item['id'] for group in data['groups'] for category in group['categories'] for item in category['items']]
            self.assertNotIn(tuition.id, items)
            self.assertIn(other.id, items)
            self.assertEqual(data['total'], 25)
            self.assertIn(tuition, year.with_context(active_test=False).detailed_income_seed_ids)
            self.assertEqual(year.detailed_occurrence_values[str(tuition.id)]['value'], 100)
        year.set_detailed_income_selection(tuition.id, False)
        self.assertEqual(year.get_detailed_income_list()['total'], 25)

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
        fee_type = self.env['school.fee.types'].create({'school_id': self.school.id, 'name': 'Test fee', 'display_order': 1, 'forecast_tuition': True})
        fee = self.env['school.fee.values'].create({
            'academic_year_id': first.id, 'grade_level_id': grade.id, 'fee_type_id': fee_type.id, 'amount': 100,
        })
        first.prediction_income_tax_percent = 50
        self.assertEqual(first.fee_gross_total, 1000)
        self.assertEqual(first.fee_total, 500)

        fixed = self.item('Activity fees', 'income')
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
        self.assertEqual(first.get_detailed_expense_list()['total'], 105)
        self.assertEqual(self.school._chart_breakdowns(first)['detailed_expense_category_spend'], [
            {'label': 'Tax Payments', 'value': 105},
        ])
        fee.amount = 200
        self.assertEqual(first.get_detailed_expense_list()['total'], 210)
        self.assertEqual(first.get_detailed_income_list()['total'], 100)
        self.assertEqual(first.expense_total, 0)
        first.set_detailed_occurrence_value('expense', expense.id, 'seed', None)
        self.assertEqual(first.get_detailed_expense_list()['total'], 12)

    def test_occurrence_validation_and_frozen_forecasts(self):
        year = self.years[0]
        item = self.item('Activity fees', 'income')
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

    def test_income_participation_percentage_is_year_specific(self):
        first, second = self.years
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grade = self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        for year in self.years:
            self.env['school.grade.enrollment'].create({
                'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 100,
            })
        item = self.item('Transportation Fees', 'income')
        with Form(item.with_context(catalog_type='income'), view='school_planning.view_operational_expense_seed_form') as form:
            form.basis = 'student_percent'
        for year in self.years:
            year.create_detailed_income_list()
            year.set_detailed_income_selection(item.id, True)
        first.set_detailed_student_percentage('income', item.id, 500, None)
        self.assertEqual(first.get_detailed_income_list()['pending'], 1)
        first.set_detailed_student_percentage('income', item.id, 500, 30)
        second.set_detailed_student_percentage('income', item.id, 250, 20)
        self.assertEqual(first.get_detailed_income_list()['total'], 15000)
        self.assertEqual(second.get_detailed_income_list()['total'], 5000)
        first.enrollment_ids.student_count = 80
        self.assertEqual(first.get_detailed_income_list()['total'], 12000)
        for percentage in (-1, 101, float('nan'), True):
            with self.subTest(percentage=percentage), self.assertRaises(ValidationError), self.cr.savepoint():
                first.set_detailed_student_percentage('income', item.id, 500, percentage)
        self.assertEqual(first.get_detailed_income_list()['total'], 12000)
        first.action_freeze_baseline()
        with self.assertRaises(ValidationError):
            first.set_detailed_student_percentage('income', item.id, 500, 50)

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

    def test_expense_calculation_source_and_deleting_detail_list(self):
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
        self.years.write({'prediction_income_tax_percent': 10})
        expense = self.item('Income Taxes', 'expense')
        income = self.item('Club Fees', 'income')
        first.create_detailed_income_list()
        first.set_detailed_income_selection(income.id, True)
        first.set_detailed_occurrence_value('income', income.id, 'amount', 20)
        self.assertEqual(first.tax_deductions_total, 102)

        first.create_detailed_expense_list()
        self.assertEqual(first.tax_deductions_total, 102)
        self.assertEqual(first.fee_total, 918)
        self.assertEqual(first.fee_value_ids.tax_amount, 100)
        report = self.env['school.financial.report'].search([('academic_year_id', '=', first.id)])
        self.assertEqual(report.tax_amount, 102)
        self.assertEqual(second.tax_deductions_total, 100)
        first.set_detailed_expense_selection(expense.id, True)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            first.expense_calculation_mode = 'detailed'
        first.set_detailed_allocated_price('expense', expense.id, 40)
        first.set_detailed_occurrence_value('expense', expense.id, 'amount', 50)
        first.write({'payroll_summary_enabled': True, 'payroll_basis': 'amount', 'payroll_fixed_amount': 200})
        first.expense_calculation_mode = 'detailed'
        self.assertEqual(first.tax_deductions_total, 0)
        self.assertEqual(first.fee_total, 1020)
        self.assertEqual(first.expense_total, 50)
        self.assertEqual(first.net_budget, 770)
        self.assertEqual(first.enrollment_ids.cost_total, 0)
        self.assertEqual(report.expense_total, 50)
        self.assertEqual(report.net_profit, 770)
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'school_planning.report_school_financial_summary_pdf', first.ids,
        )
        self.assertIn(b'Expenses used:', html)
        self.assertIn(b'Detailed', html)
        pdf = first._build_financial_summary_pdf_bytes()
        self.assertTrue(pdf.startswith(b'%PDF-'))
        if PdfReader:
            text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(pdf)).pages)
            self.assertIn('Expenses Used', text)
            self.assertIn('Detailed', text)
            self.assertIn('50.00', text)
        self.assertEqual(second.tax_deductions_total, 100)
        first.set_detailed_occurrence_value('expense', expense.id, 'revenue_percent', 10)
        self.assertEqual(first.expense_total, 102)
        self.assertEqual(report.expense_total, 102)
        first.expense_calculation_mode = 'no_details'
        self.assertEqual(first.tax_deductions_total, 102)
        self.assertEqual(first.expense_total, 0)
        self.assertEqual(report.expense_total, 0)
        first.expense_calculation_mode = 'detailed'

        self.assertFalse(first.delete_detailed_expense_list()['created'])
        self.assertEqual(first.expense_calculation_mode, 'no_details')
        self.assertEqual(first.tax_deductions_total, 102)
        self.assertEqual(first.fee_total, 918)
        self.assertEqual(report.tax_amount, 102)
        self.assertEqual(first.prediction_income_tax_percent, 10)
        self.assertEqual(first.get_detailed_income_list()['total'], 20)
        self.assertNotIn(str(expense.id), first.detailed_allocated_prices or {})
        self.assertNotIn(str(expense.id), first.detailed_occurrence_values or {})
        self.assertEqual(first.create_detailed_expense_list()['total'], 0)
        self.assertFalse(first.detailed_expense_seed_ids)
        first.action_freeze_baseline()
        with self.assertRaises(ValidationError):
            first.delete_detailed_expense_list()

    def test_expense_source_form_uses_saved_detailed_prices(self):
        year = self.years[0]
        expense = self.item('Income Taxes', 'expense')
        year.create_detailed_expense_list()
        year.set_detailed_expense_selection(expense.id, True)
        year.set_detailed_allocated_price('expense', expense.id, 100)
        for occurrence, amount in ((False, 100), (True, 150)):
            year.expense_calculation_mode = 'no_details'
            if occurrence:
                year.set_detailed_occurrence_value('expense', expense.id, 'amount', amount)
            for view in ('view_school_year_workspace', 'view_school_academic_years_financial_summary_form'):
                with self.subTest(view=view, occurrence=occurrence):
                    year.expense_calculation_mode = 'no_details'
                    with Form(year, view=f'school_planning.{view}') as form:
                        form.expense_calculation_mode = 'detailed'
                    self.assertEqual(year.expense_total, amount)

    def test_detailed_currency_rate_changes_refresh_report(self):
        year = self.years[0]
        item = self.item('Income Taxes', 'expense')
        group = self.env['school.grade.groups'].create({'school_id': self.school.id, 'name': 'Primary', 'display_order': 1})
        grade = self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': group.id, 'name': 'Grade 1', 'sort_order': 1,
        })
        enrollment = self.env['school.grade.enrollment'].create({
            'academic_year_id': year.id, 'grade_level_id': grade.id, 'student_count': 10,
        })
        currency = self.env.ref('base.GBP')
        currency.active = True
        rate = self.env['res.currency.rate'].create({
            'name': '2040-01-01', 'currency_id': currency.id, 'rate': 2,
            'company_id': self.env.company.root_id.id,
        })
        year.school_id.currency_id = self.env.company.currency_id
        item.write({'basis': 'student', 'price': 100, 'price_set': True, 'currency_id': currency.id})
        year.create_detailed_expense_list()
        year.set_detailed_expense_selection(item.id, True)
        year.expense_calculation_mode = 'detailed'
        report = self.env['school.financial.report'].search([('academic_year_id', '=', year.id)])
        before = year.expense_total
        self.assertEqual(report.expense_total, before)
        self.assertEqual(enrollment.cost_per_student, 50)
        self.assertEqual(enrollment.cost_total, 500)
        rate.write({'rate': 4})
        year.invalidate_recordset(['expense_total'])
        self.assertNotEqual(year.expense_total, before)
        self.assertEqual(report.expense_total, year.expense_total)
        self.assertEqual(enrollment.cost_per_student, 25)
        self.assertEqual(enrollment.cost_total, 250)
        frozen_total = year.expense_total
        year.action_freeze_baseline()
        item.price_set = False
        year.invalidate_recordset(['expense_total'])
        self.assertEqual(year.expense_total, frozen_total)
        self.assertEqual(report.expense_total, frozen_total)
