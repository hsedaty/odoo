# -*- coding: utf-8 -*-

import base64
import io
from unittest.mock import patch

from PIL import Image
from lxml import html as html_parser

from odoo.tests.common import TransactionCase, tagged
from reportlab.pdfbase.pdfmetrics import stringWidth

from ..models.report_branding import _BOLD_FONT, _REGULAR_FONT, _fit_text_font_size

try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        PdfReader = None


@tagged('post_install', '-at_install')
class TestReportBranding(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.school = cls.env['school.schools'].create({
            'name': 'Branding Test School',
            'currency': 'USD',
            'report_title': 'Annual School Finance',
            'report_footer': 'Prepared for school leadership',
            'report_show_grade_details': False,
        })
        cls.year = cls.env['school.academic.years'].create({
            'school_id': cls.school.id,
            'academic_year_name': '2098-2099',
            'start_date': '2098-09-01',
            'end_date': '2099-06-30',
            'dataset_type': 'actual',
        })

    @staticmethod
    def _logo(color):
        image_buffer = io.BytesIO()
        Image.new('RGB', (16, 16), color=color).save(image_buffer, format='PNG')
        return base64.b64encode(image_buffer.getvalue())

    def _add_real_financial_data(self, student_count=10, amount=1200):
        group = self.env['school.grade.groups'].create({
            'school_id': self.school.id, 'name': 'Primary', 'display_order': 1,
        })
        grade = self.env['school.grade.levels'].create({
            'school_id': self.school.id,
            'group_id': group.id,
            'name': 'Grade 1',
            'sort_order': 1,
        })
        self.env['school.grade.enrollment'].create({
            'academic_year_id': self.year.id,
            'grade_level_id': grade.id,
            'student_count': student_count,
        })
        fee_type = self.env['school.fee.types'].create({
            'school_id': self.school.id,
            'name': 'Tuition',
            'display_order': 1,
        })
        self.env['school.fee.values'].create({
            'academic_year_id': self.year.id,
            'grade_level_id': grade.id,
            'fee_type_id': fee_type.id,
            'amount': amount,
        })

    def test_school_branding_fields_and_safe_logo_helpers(self):
        self.school.write({'report_school_logo': self._logo('navy')})

        self.assertEqual(self.school.report_title, 'Annual School Finance')
        self.assertEqual(self.school.report_footer, 'Prepared for school leadership')
        self.assertFalse(self.school.report_show_grade_details)
        self.assertTrue(self.school._get_safe_report_logo_bytes('report_school_logo'))
        self.assertTrue(self.school.get_report_logo_data_uri('report_school_logo').startswith('data:image/'))
        self.assertFalse(self.school._get_safe_report_logo_bytes('untrusted_field'))
        self.assertFalse(self.school.get_report_logo_data_uri('report_company_logo'))

    def test_malformed_logo_logs_school_id(self):
        with patch.object(type(self.school), '__getitem__', return_value=b'not-an-image'):
            with self.assertLogs('odoo.addons.school_planning.models.report_branding', level='WARNING') as logs:
                self.assertFalse(self.school._get_safe_report_logo_bytes('report_school_logo'))
        self.assertIn(str(self.school.id), logs.output[0])

    def test_reportlab_pdf_uses_branding_and_grade_detail_setting(self):
        pdf_bytes = self.year._build_financial_summary_pdf_bytes()

        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
        if PdfReader:
            pdf_text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
            self.assertIn('Annual School Finance', pdf_text)
            self.assertIn('Prepared for school leadership', pdf_text)
            self.assertIn('Branding Test School', pdf_text)
            self.assertIn('Actuals are still in progress.', pdf_text)
            self.assertIn('Gross Revenue', pdf_text)
            self.assertIn('Operating Costs', pdf_text)
            self.assertIn('Net Budget', pdf_text)
            self.assertNotIn('Revenue and Cost by Grade Level', pdf_text)

            self.year.write({
                'enrollment_status': 'complete',
                'income_status': 'complete',
                'expenses_status': 'complete',
                'payroll_status': 'complete',
                'assets_status': 'complete',
                'teaching_status': 'complete',
            })
            complete_pdf = self.year._build_financial_summary_pdf_bytes()
            complete_text = '\n'.join(
                page.extract_text() or '' for page in PdfReader(io.BytesIO(complete_pdf)).pages
            )
            self.assertNotIn('Actuals are still in progress.', complete_text)

    def test_email_attachment_uses_branded_multi_year_report(self):
        if not PdfReader:
            self.skipTest('pypdf or PyPDF2 is required to inspect rendered PDF text')
        self._add_real_financial_data()
        next_year = self.env['school.academic.years'].create({
            'school_id': self.school.id,
            'academic_year_name': '2099-2100',
            'start_date': '2099-09-01',
            'end_date': '2100-06-30',
            'dataset_type': 'actual',
        })
        server = self.env['ir.mail_server'].create({
            'name': 'PDF Email Test Server', 'smtp_host': 'smtp.gmail.com',
        })
        wizard = self.env['school.financial.summary.email.wizard'].create({
            'school_id': self.school.id,
            'academic_year_ids': [(6, 0, (next_year | self.year).ids)],
            'mail_server_id': server.id,
            'email_to': 'recipient@example.com',
        })
        with patch.object(type(self.env['mail.mail']), 'send', autospec=True) as send_mock:
            wizard.action_send_email()

        send_mock.assert_called_once()
        attachment = send_mock.call_args.args[0].attachment_ids
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.name, 'financial_summary_multi_year.pdf')
        pdf_bytes = base64.b64decode(attachment.datas)
        pdf_text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
        self.assertIn('Annual School Finance', pdf_text)
        self.assertIn('Prepared for school leadership', pdf_text)
        self.assertIn('12,000.00', pdf_text)
        self.assertIn('Actuals are still in progress.', pdf_text)
        self.assertLess(pdf_text.index('2098-2099'), pdf_text.index('2099-2100'))
        self.assertNotIn('Revenue and Cost by Grade Level', pdf_text)

    def test_money_flow_signs_and_colors_in_both_report_renderers(self):
        if not PdfReader:
            self.skipTest('pypdf or PyPDF2 is required to inspect rendered PDF colors')
        self._add_real_financial_data()
        self.school.report_show_grade_details = True
        category = self.env['school.expense.categories'].create({
            'school_id': self.school.id, 'name': 'Operating', 'display_order': 1,
        })
        expense = self.env['school.expense.values'].create({
            'academic_year_id': self.year.id,
            'expense_category_id': category.id, 'amount': 5000,
        })
        green, red, neutral = '#187044', '#b42318', '#607487'
        for cost, budget, budget_color in [
            (5000, '7,000.00', green), (12000, '0.00', neutral), (15000, '-3,000.00', red),
        ]:
            with self.subTest(cost=cost):
                expense.amount = cost
                self.env.invalidate_all()
                cost_text = f'-{cost:,.2f}'
                self.assertEqual(self.year.expense_total, cost)
                self.assertEqual(self.year.net_budget, 12000 - cost)
                html, _ = self.env['ir.actions.report']._render_qweb_html(
                    'school_planning.report_school_financial_summary_pdf', self.year.ids,
                )
                document = html_parser.fromstring(html)
                for label, amount, color in [
                    ('Gross Revenue', '12,000.00', green),
                    ('Operating Expenses', cost_text, red),
                    ('Operating Profit', budget, budget_color),
                    ('Net Budget', budget, budget_color),
                    ('Tax Deductions', '0.00', neutral),
                    ('Average Cost Per Student', f'-{cost / 10:,.2f}', red),
                ]:
                    cell = document.xpath('//tr[td[1][normalize-space(.)=$label]]/td[2]', label=label)[0]
                    self.assertIn(amount, cell.text_content().replace('\ufeff', ''))
                    self.assertEqual(cell.xpath('.//span[@style]/@style'), [f'color: {color};'])
                margin = document.xpath('//tr[td[1][normalize-space(.)="Net Margin %"]]/td[2]')[0]
                self.assertEqual(margin.get('style'), f'color: {budget_color};')
                kpis = document.xpath('//div[@class="school-report-kpi-value"]')
                self.assertEqual([node.xpath('.//span[@style]/@style')[0] for node in kpis],
                                 [f'color: {color};' for color in (green, red, budget_color)])
                grade_cells = document.xpath('//tr[td[2]/span[normalize-space(.)="Grade 1"]]/td')
                self.assertIn('0.00', grade_cells[5].text_content().replace('\ufeff', ''))
                self.assertEqual(grade_cells[5].xpath('.//span[@style]/@style'), [f'color: {neutral};'])

                colored_text = []
                fill = (0, 0, 0)
                stack = []

                def capture_text(operator, operands, _cm, _tm):
                    nonlocal fill
                    if operator == b'q':
                        stack.append(fill)
                    elif operator == b'Q':
                        fill = stack.pop()
                    elif operator == b'rg':
                        fill = tuple(float(value) for value in operands)
                    elif operator == b'g':
                        fill = (float(operands[0]),) * 3
                    elif operator == b'Tj':
                        text = operands[0]
                        if isinstance(text, bytes):
                            text = text.decode('latin-1')
                        colored_text.append((str(text), fill))

                reader = PdfReader(io.BytesIO(self.year._build_financial_summary_pdf_bytes()))
                for page in reader.pages:
                    page.extract_text(visitor_operand_before=capture_text)
                for amount, color in [
                    ('USD 12,000.00', green), (f'USD {cost_text}', red),
                    (f'USD {budget}', budget_color), ('USD 0.00', neutral),
                    ('0.00', neutral),
                ]:
                    matching = [rgb for text, rgb in colored_text if text == amount]
                    self.assertTrue(matching, amount)
                    expected = tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
                    for rgb in matching:
                        for actual, component in zip(rgb, expected):
                            self.assertAlmostEqual(actual, component, places=5)

    def test_money_flow_refunds_and_rounded_zero(self):
        refund = self.year._get_report_money(-25, outflow=True)
        self.assertEqual(refund['amount'], 25)
        self.assertEqual(refund['color'], self.year._get_report_money(25)['color'])
        zero = self.year._get_report_money(0.001, outflow=True)
        self.assertEqual(zero['amount'], 0)
        self.assertEqual(str(zero['amount']), '0.0')
        self.assertEqual(zero['color'], self.year._get_report_money(0)['color'])

    def test_reportlab_uses_company_currency_when_school_currency_is_missing(self):
        if not PdfReader:
            self.skipTest('pypdf or PyPDF2 is required to inspect rendered PDF text')
        company_currency = self.env.company.currency_id
        self.school.write({'currency_id': False})

        pdf_bytes = self.year._build_financial_summary_pdf_bytes()

        reader = PdfReader(io.BytesIO(pdf_bytes))
        pdf_text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        self.assertIn(company_currency.name, pdf_text)

    def test_reportlab_paginates_embeds_both_logos_and_fits_large_grade_values(self):
        if not PdfReader:
            self.skipTest('pypdf or PyPDF2 is required to inspect rendered PDF pages')

        self.school.write({
            'report_show_grade_details': True,
            'report_school_logo': self._logo('navy'),
            'report_company_logo': self._logo('teal'),
            'report_title': 'École São Tomé — İstanbul Şişli',
            'report_footer': 'Préparé pour l’école — São Tomé',
        })
        group = self.env['school.grade.groups'].create({
            'school_id': self.school.id, 'name': 'Primary', 'display_order': 1,
        })
        grades = self.env['school.grade.levels'].create([{
            'school_id': self.school.id,
            'group_id': group.id,
            'name': f'Grade {index:02d}',
            'sort_order': index,
        } for index in range(60)])
        self.env['school.grade.enrollment'].create([{
            'academic_year_id': self.year.id,
            'grade_level_id': grade.id,
            'student_count': 1,
        } for grade in grades])
        fee_type = self.env['school.fee.types'].create({
            'school_id': self.school.id,
            'name': 'Tuition',
            'display_order': 1,
        })
        self.env['school.fee.values'].create([{
            'academic_year_id': self.year.id,
            'grade_level_id': grade.id,
            'fee_type_id': fee_type.id,
            'amount': 36300000,
        } for grade in grades])

        pdf_bytes = self.year._build_financial_summary_pdf_bytes()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pdf_text = '\n'.join(page.extract_text() or '' for page in reader.pages)

        self.assertGreater(len(reader.pages), 1)
        self.assertIn('École São Tomé — İstanbul Şişli', pdf_text)
        self.assertIn('Préparé pour l’école — São Tomé', pdf_text)
        self.assertIn('36,300,000.00', pdf_text)
        self.assertIn('2,178,000,000.00', pdf_text)
        self.assertIn('Currency: USD', pdf_text)
        self.assertIn('Gross Revenue', pdf_text)
        self.assertIn('Operating Costs', pdf_text)
        self.assertIn('Net Budget', pdf_text)
        first_page_text = reader.pages[0].extract_text() or ''
        if 'Grade Level' in first_page_text:
            self.assertIn('Grade 00', first_page_text)
        self.assertIn('Actuals are still in progress.', pdf_text)

        def resolve_pdf_object(value):
            if hasattr(value, 'get_object'):
                return value.get_object()
            if hasattr(value, 'getObject'):
                return value.getObject()
            return value

        for page in reader.pages:
            resources = resolve_pdf_object(page['/Resources'])
            xobjects = resolve_pdf_object(resources.get('/XObject', {}))
            image_count = 0
            for image in xobjects.values():
                image = resolve_pdf_object(image)
                image_count += image.get('/Subtype') == '/Image'
            self.assertGreaterEqual(image_count, 2)

        numeric_width = 43
        fitted_size = _fit_text_font_size('36,300,000.00', _REGULAR_FONT, numeric_width - 4, 7.5)
        self.assertLessEqual(stringWidth('36,300,000.00', _REGULAR_FONT, fitted_size), numeric_width - 4)
        header_width = 71
        header_size = _fit_text_font_size('Grade Level', _BOLD_FONT, header_width - 4, 7.5)
        self.assertLessEqual(stringWidth('Grade Level', _BOLD_FONT, header_size), header_width - 4)

    def test_qweb_html_renders_school_branding_and_safe_logos(self):
        self._add_real_financial_data()
        self.school.write({
            'report_school_logo': self._logo('navy'),
            'report_company_logo': self._logo('teal'),
        })
        report = self.env['ir.actions.report']

        html, _content_type = report._render_qweb_html(
            'school_planning.report_school_financial_summary_pdf', self.year.ids,
        )
        if isinstance(html, bytes):
            html = html.decode()

        self.assertIn('Annual School Finance', html)
        self.assertGreaterEqual(html.count('data:image/png;base64,'), 2)
        self.assertIn('Prepared for school leadership', html)
        self.assertIn('Actuals are still in progress.', html)
        self.assertIn('12,000.00', html)
        self.assertIn('school-report-kpi', html)
        self.assertIn('Gross Revenue', html)
        self.assertIn('Operating Costs', html)
        self.assertIn('Net Budget', html)

        self.year.write({
            'enrollment_status': 'complete',
            'income_status': 'complete',
            'expenses_status': 'complete',
            'payroll_status': 'complete',
            'assets_status': 'complete',
            'teaching_status': 'complete',
        })
        complete_html, _content_type = report._render_qweb_html(
            'school_planning.report_school_financial_summary_pdf', self.year.ids,
        )
        if isinstance(complete_html, bytes):
            complete_html = complete_html.decode()
        self.assertNotIn('Actuals are still in progress.', complete_html)
