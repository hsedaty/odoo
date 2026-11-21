from odoo import http
from odoo.http import content_disposition, request


class SchoolFinancialSummaryPdfController(http.Controller):
    @http.route('/school_planning/financial-summary/pdf', type='http', auth='user', website=False)
    def financial_summary_pdf(self, ids=None, **kwargs):
        year_ids = []
        if ids:
            for token in ids.split(','):
                token = token.strip()
                if token.isdigit():
                    year_ids.append(int(token))

        years = request.env['school.academic.years'].browse(year_ids).exists().sorted(
            key=lambda y: (y.start_date or '', y.academic_year_name or '', y.id)
        )

        if not years:
            return request.not_found()

        pdf_data = years._build_financial_summary_pdf_bytes()
        filename = 'financial_summary_multi_year.pdf' if len(years) > 1 else f'financial_summary_{years[0].academic_year_name}.pdf'
        return request.make_response(
            pdf_data,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Length', str(len(pdf_data))),
                ('Content-Disposition', content_disposition(filename)),
            ],
        )
