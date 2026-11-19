# -*- coding: utf-8 -*-

import base64
import io
import logging
import os

from PIL import Image
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont

from odoo import fields, models
from odoo.tools.image import image_data_uri


_logger = logging.getLogger(__name__)
_REGULAR_FONT = 'SchoolVera'
_BOLD_FONT = 'SchoolVera-Bold'
_FONT_DIRECTORY = os.path.join(os.path.dirname(reportlab.__file__), 'fonts')
if _REGULAR_FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(_REGULAR_FONT, os.path.join(_FONT_DIRECTORY, 'Vera.ttf')))
if _BOLD_FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(_BOLD_FONT, os.path.join(_FONT_DIRECTORY, 'VeraBd.ttf')))


def _fit_text_font_size(text, font_name, width, preferred_size):
    text_width = stringWidth(text, font_name, 1)
    if not text_width:
        return preferred_size
    return min(preferred_size, width / text_width)


class SchoolSchools(models.Model):
    _inherit = 'school.schools'

    report_school_logo = fields.Image(
        string='School Logo',
        max_width=1024,
        max_height=1024,
    )
    report_company_logo = fields.Image(
        string='Company Logo',
        max_width=1024,
        max_height=1024,
    )
    report_title = fields.Char(string='Financial Report Title', size=128)
    report_footer = fields.Char(string='Financial Report Footer', size=256)
    report_show_grade_details = fields.Boolean(
        string='Show Grade Details in Financial Reports',
        default=True,
    )

    def _get_safe_report_logo_bytes(self, field_name):
        self.ensure_one()
        if field_name not in ('report_school_logo', 'report_company_logo'):
            return False
        image = self[field_name]
        if not image:
            return False
        try:
            raw = base64.b64decode(image, validate=True)
            with Image.open(io.BytesIO(raw)) as decoded:
                decoded.verify()
            return raw
        except (ValueError, TypeError, OSError, SyntaxError, Image.DecompressionBombError) as error:
            _logger.warning(
                'Ignoring malformed financial report logo %s for school %s: %s',
                field_name, self.id, error,
            )
            return False

    def get_report_logo_data_uri(self, field_name):
        image = self._get_safe_report_logo_bytes(field_name)
        return image_data_uri(base64.b64encode(image)) if image else False


class SchoolAcademicYears(models.Model):
    _inherit = 'school.academic.years'

    def _get_report_money(self, value, outflow=False):
        self.ensure_one()
        currency = self.school_id.currency_id or self.env.company.currency_id
        amount = currency.round(-value if outflow else value)
        return {
            'amount': amount or 0.0,
            'color': '#b42318' if amount < 0 else '#187044' if amount > 0 else '#607487',
        }

    def _build_financial_summary_pdf_bytes(self):
        years = self.sorted(key=lambda year: (
            year.start_date or '', year.academic_year_name or '', year.id,
        ))
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        pdf.setTitle('Financial Summary')
        page_width, page_height = A4

        navy = colors.HexColor('#17324D')
        teal = colors.HexColor('#167C80')
        muted = colors.HexColor('#607487')
        line_color = colors.HexColor('#DCE5EC')
        stripe = colors.HexColor('#F4F7FA')
        warning_background = colors.HexColor('#FFF3CD')
        warning_text = colors.HexColor('#705400')
        left, right = 40, page_width - 40

        def is_provisional(year):
            return year.dataset_type == 'actual' and year.actual_status != 'complete'

        def safe_text(value):
            return str(value or '').replace('\n', ' ')

        def truncate(value, width, font=_REGULAR_FONT, size=8):
            value = safe_text(value)
            if stringWidth(value, font, size) <= width:
                return value
            available_width = width - stringWidth('...', font, size)
            while value and stringWidth(value, font, size) > available_width:
                value = value[:-1]
            return value.rstrip() + '...'

        def draw_logo(school, field_name, x, y, width, height):
            image = school._get_safe_report_logo_bytes(field_name)
            if not image:
                return
            try:
                pdf.drawImage(
                    ImageReader(io.BytesIO(image)),
                    x, y, width=width, height=height,
                    preserveAspectRatio=True, anchor='c', mask='auto',
                )
            except (ValueError, TypeError, OSError) as error:
                _logger.warning(
                    'Unable to draw financial report logo %s for school %s: %s',
                    field_name, school.id, error,
                )
                return

        def draw_header(year, continued=False):
            school = year.school_id
            title = safe_text(school.report_title or 'Financial Summary')
            school_name = safe_text(school.name or '')
            year_name = safe_text(year.academic_year_name or '')
            draw_logo(school, 'report_school_logo', left, page_height - 82, 48, 42)
            draw_logo(school, 'report_company_logo', right - 48, page_height - 82, 48, 42)
            pdf.setFillColor(navy)
            pdf.setFont(_BOLD_FONT, 17)
            pdf.drawCentredString(page_width / 2, page_height - 52, truncate(title, 390, _BOLD_FONT, 17))
            pdf.setFillColor(muted)
            pdf.setFont(_REGULAR_FONT, 9)
            details = ' | '.join(part for part in (school_name, year_name) if part)
            if continued:
                details = f'{details} | Continued'
            pdf.drawCentredString(page_width / 2, page_height - 69, truncate(details, 400, size=9))
            pdf.setStrokeColor(teal)
            pdf.setLineWidth(2)
            pdf.line(left, page_height - 91, right, page_height - 91)
            if is_provisional(year):
                pdf.setFillColor(warning_background)
                pdf.roundRect(left, page_height - 140, right - left, 24, 3, fill=1, stroke=0)
                pdf.setFillColor(warning_text)
                pdf.setFont(_BOLD_FONT, 8)
                pdf.drawString(
                    left + 8, page_height - 131,
                    truncate(
                        'Actuals are still in progress. These figures are provisional; '
                        'unentered sections may show zero.',
                        right - left - 16, _BOLD_FONT, 8,
                    ),
                )

        def draw_footer(year):
            footer = safe_text(year.school_id.report_footer or 'School financial planning')
            pdf.setStrokeColor(line_color)
            pdf.setLineWidth(0.6)
            pdf.line(left, 34, right, 34)
            pdf.setFillColor(muted)
            pdf.setFont(_REGULAR_FONT, 8)
            pdf.drawString(left, 20, truncate(footer, 440, size=8))
            pdf.drawRightString(right, 20, f'{pdf.getPageNumber()}')

        def format_amount(value, currency):
            amount = currency.round(value or 0.0) if currency else float(value or 0.0)
            decimal_places = currency.decimal_places if currency else 2
            return f'{amount:,.{decimal_places}f}'

        def money(year, value, currency, outflow=False, show_currency=True):
            flow = year._get_report_money(value, outflow=outflow)
            code = currency.name if currency and show_currency else ''
            return f'{code} {format_amount(flow["amount"], currency)}'.strip(), colors.HexColor(flow['color'])

        def draw_section(title, y):
            pdf.setFillColor(navy)
            pdf.roundRect(left, y - 5, right - left, 20, 3, fill=1, stroke=0)
            pdf.setFillColor(colors.white)
            pdf.setFont(_BOLD_FONT, 9)
            pdf.drawString(left + 9, y + 1, safe_text(title))
            return y - 25

        def draw_executive_kpis(year, currency, y):
            gap = 8
            card_width = (right - left - 2 * gap) / 3
            card_height = 43
            kpis = (
                ('Gross Revenue', money(year, year.fee_gross_total, currency)),
                ('Operating Costs', money(year, year.operating_cost_total, currency, outflow=True)),
                ('Net Budget', money(year, year.net_budget, currency)),
            )
            for index, (label, (amount, color)) in enumerate(kpis):
                card_left = left + index * (card_width + gap)
                pdf.setFillColor(stripe)
                pdf.roundRect(card_left, y - card_height, card_width, card_height, 4, fill=1, stroke=0)
                pdf.setFillColor(muted)
                pdf.setFont(_BOLD_FONT, 7.5)
                pdf.drawString(card_left + 9, y - 14, safe_text(label))
                amount = safe_text(amount)
                font_size = _fit_text_font_size(amount, _BOLD_FONT, card_width - 18, 12)
                pdf.setFillColor(color)
                pdf.setFont(_BOLD_FONT, font_size)
                pdf.drawString(card_left + 9, y - 33, amount)
            return y - card_height - 25

        for year_idx, year in enumerate(years):
            school = year.school_id
            currency = school.currency_id or year.env.company.currency_id
            provisional = is_provisional(year)
            draw_header(year)
            y = page_height - (157 if provisional else 119)

            info = (
                ('Academic Year', year.academic_year_name or '-'),
                ('Dataset', dict(year._fields['dataset_type'].selection).get(year.dataset_type, '-')),
                ('Period', f'{year.start_date or "-"} to {year.end_date or "-"}'),
            )
            for label, value in info:
                pdf.setFillColor(muted)
                pdf.setFont(_BOLD_FONT, 8)
                pdf.drawString(left, y, safe_text(label))
                pdf.setFillColor(navy)
                pdf.setFont(_REGULAR_FONT, 9)
                pdf.drawString(left + 90, y, truncate(value, right - left - 90, size=9))
                y -= 15
            y -= 7
            pdf.setFillColor(muted)
            pdf.setFont(_REGULAR_FONT, 7)
            pdf.drawString(left, y, 'Green: inflow / surplus | Red (-): outflow / deficit | Zero: neutral')
            y -= 14
            y = draw_executive_kpis(year, currency, y)

            def draw_metric_rows(rows):
                nonlocal y
                for index, (label, (value, color)) in enumerate(rows):
                    if index % 2 == 0:
                        pdf.setFillColor(stripe)
                        pdf.rect(left, y - 5, right - left, 17, fill=1, stroke=0)
                    pdf.setFillColor(navy)
                    pdf.setFont(_REGULAR_FONT, 8.5)
                    pdf.drawString(left + 7, y, safe_text(label))
                    pdf.setFillColor(color)
                    pdf.setFont(_BOLD_FONT, 8.5)
                    pdf.drawRightString(right - 7, y, safe_text(value))
                    y -= 18

            y = draw_section('Core Financial Metrics', y)
            draw_metric_rows([
                ('Gross Revenue', money(year, year.fee_gross_total, currency)),
                ('Tax Deductions', money(year, year.tax_deductions_total, currency, outflow=True)),
                ('Net Revenue After Tax', money(year, year.fee_total, currency)),
                ('Operating Expenses', money(year, year.expense_total, currency, outflow=True)),
                ('Salaries', money(year, year.salary_total, currency, outflow=True)),
                ('New Rooms Equipment Expense', money(year, year.new_rooms_expense_total, currency, outflow=True)),
                ('Operating Cost Total', money(year, year.operating_cost_total, currency, outflow=True)),
                ('Startup Cost Total', money(year, year.startup_cost_total, currency, outflow=True)),
                ('Total Deductions', money(year, year.total_deductions, currency, outflow=True)),
                ('Operating Profit', money(year, year.operating_profit, currency)),
                ('Net Budget', money(year, year.net_budget, currency)),
                ('Net Margin %', (
                    f'{float(year.net_margin_pct or 0.0):.2f}%',
                    colors.HexColor('#b42318' if year.net_margin_pct < 0 else '#187044' if year.net_margin_pct > 0 else '#607487'),
                )),
            ])

            y -= 6
            y = draw_section('Enrollment and Unit Economics', y)
            draw_metric_rows([
                ('Total Enrolled Students', (str(int(year.total_enrolled_students or 0)), navy)),
                ('Average Revenue Per Student', money(year, year.revenue_per_student_avg, currency)),
                ('Average Cost Per Student', money(year, year.cost_per_student_avg, currency, outflow=True)),
                ('Revenue Per Student by Grade Level (Avg)', money(year, year.revenue_per_student_grade_level_avg, currency)),
                ('Cost Per Student by Grade Level (Avg)', money(year, year.cost_per_student_grade_level_avg, currency, outflow=True)),
                ('Revenue Per Student by Grade Group (Avg)', money(year, year.revenue_per_student_grade_group_avg, currency)),
                ('Cost Per Student by Grade Group (Avg)', money(year, year.cost_per_student_grade_group_avg, currency, outflow=True)),
            ])

            if school.report_show_grade_details:
                y -= 6
                if y < 130:
                    draw_footer(year)
                    pdf.showPage()
                    draw_header(year, continued=True)
                    y = page_height - (157 if provisional else 115)
                y = draw_section('Revenue and Cost by Grade Level', y)
                pdf.setFillColor(muted)
                pdf.setFont(_REGULAR_FONT, 7.5)
                pdf.drawRightString(right, y, f'Currency: {safe_text(currency.name)}')
                y -= 13
                headers = ('Group', 'Grade Level', 'Students', 'Revenue', 'Revenue/Student', 'Cost', 'Cost/Student')
                column_bounds = (
                    left, left + 66, left + 137, left + 180,
                    left + 256, left + 337, left + 413, right,
                )

                def draw_grade_headers():
                    for column_index, header in enumerate(headers):
                        cell_left, cell_right = column_bounds[column_index:column_index + 2]
                        header = safe_text(header)
                        font_size = _fit_text_font_size(
                            header, _BOLD_FONT, cell_right - cell_left - 4, 7.5,
                        )
                        pdf.setFillColor(muted)
                        pdf.setFont(_BOLD_FONT, font_size)
                        pdf.drawString(cell_left + 2, y, header)

                draw_grade_headers()
                y -= 14
                for index, enrollment in enumerate(year.enrollment_ids):
                    if y < 52:
                        draw_footer(year)
                        pdf.showPage()
                        draw_header(year, continued=True)
                        y = page_height - (157 if provisional else 115)
                        y = draw_section('Revenue and Cost by Grade Level (Continued)', y)
                        pdf.setFillColor(muted)
                        pdf.setFont(_REGULAR_FONT, 7.5)
                        pdf.drawRightString(right, y, f'Currency: {safe_text(currency.name)}')
                        y -= 13
                        draw_grade_headers()
                        y -= 14
                    if index % 2 == 0:
                        pdf.setFillColor(stripe)
                        pdf.rect(left, y - 4, right - left, 16, fill=1, stroke=0)
                    values = (
                        (truncate(enrollment.grade_group_id.name, 74), navy),
                        (truncate(enrollment.grade_level_id.name, 68), navy),
                        (str(int(enrollment.student_count or 0)), navy),
                        money(year, enrollment.revenue_total, currency, show_currency=False),
                        money(year, enrollment.revenue_per_student, currency, show_currency=False),
                        money(year, enrollment.cost_total, currency, outflow=True, show_currency=False),
                        money(year, enrollment.cost_per_student, currency, outflow=True, show_currency=False),
                    )
                    for column_index, (value, color) in enumerate(values):
                        pdf.setFillColor(color)
                        cell_left, cell_right = column_bounds[column_index:column_index + 2]
                        value = safe_text(value)
                        if column_index >= 2:
                            font_size = _fit_text_font_size(
                                value, _REGULAR_FONT, cell_right - cell_left - 4, 7.5,
                            )
                            pdf.setFont(_REGULAR_FONT, font_size)
                            pdf.drawRightString(cell_right - 2, y, value)
                        else:
                            value = truncate(value, cell_right - cell_left - 4)
                            font_size = _fit_text_font_size(
                                value, _REGULAR_FONT, cell_right - cell_left - 4, 7.5,
                            )
                            pdf.setFont(_REGULAR_FONT, font_size)
                            pdf.drawString(cell_left + 2, y, value)
                    y -= 17

            draw_footer(year)
            if year_idx < len(years) - 1:
                pdf.showPage()

        pdf.save()
        data = buffer.getvalue()
        buffer.close()
        return data
