import base64
import io
import math
import shutil
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


STAFF_ROLE_SELECTION = [
    ('teacher', 'Teacher'),
    ('principal', 'Principal'),
    ('assistant_principal', 'Assistant Principal'),
    ('it', 'IT'),
    ('janitor', 'Janitor'),
    ('admission_officer', 'Admission Officer'),
    ('front_desk', 'Front Desk'),
    ('student_affairs', 'Student Affairs'),
    ('nurse', 'Nurse'),
    ('hr', 'HR'),
    ('accountant', 'Accountant'),
    ('finance_officer', 'Finance Officer'),
]


def _extract_school_id_from_context(env):
    def _as_positive_int(value):
        if isinstance(value, int):
            return value if value > 0 else False
        if isinstance(value, dict):
            return _as_positive_int(value.get('id'))
        if isinstance(value, str) and value.isdigit():
            parsed = int(value)
            return parsed if parsed > 0 else False
        return False

    def _extract_singleton(value):
        if isinstance(value, (list, tuple)) and len(value) == 2:
            # many2one values can be serialized as [id, display_name]
            return _as_positive_int(value[0])
        if isinstance(value, (list, tuple)) and len(value) == 1:
            return _as_positive_int(value[0])
        return False

    def _normalize_domain(value):
        if isinstance(value, str):
            try:
                value = safe_eval(value)
            except Exception:
                return []
        return value if isinstance(value, (list, tuple)) else []

    context = env.context or {}
    for key in (
        'default_school_id',
        'searchpanel_default_school_id',
        'search_default_school_id',
        'searchpanel_school_id',
        'school_id',
    ):
        value = context.get(key)
        direct_match = _as_positive_int(value)
        if direct_match:
            return direct_match
        singleton_match = _extract_singleton(value)
        if singleton_match:
            return singleton_match

    for domain in (context.get('active_domain'), context.get('domain')):
        domain = _normalize_domain(domain)
        for clause in domain:
            if not isinstance(clause, (list, tuple)) or len(clause) < 3:
                continue
            field_name, operator, value = clause[0], clause[1], clause[2]
            if field_name != 'school_id':
                continue
            if operator == '=':
                match = _as_positive_int(value)
                if match:
                    return match
            if operator == 'in':
                match = _extract_singleton(value)
                if match:
                    return match

    return False

# --- MASTER DATA (Gold Band) ---
class SchoolSchools(models.Model):
    _name = 'school.schools'
    _description = 'Schools (Master Data)'

    name = fields.Char(string='Name', required=True, size=255)
    country = fields.Char(string='Country', size=100)
    currency = fields.Char(string='Currency', required=True, size=3)

    def action_open_grade_setup(self):
        self.ensure_one()
        action = self.env.ref('school_planning.action_school_grade_setup_wizard').read()[0]
        action['context'] = {'default_school_id': self.id}
        return action

    def action_open_subject_setup(self):
        self.ensure_one()
        action = self.env.ref('school_planning.action_school_subject_setup_wizard').read()[0]
        action['context'] = {'default_school_id': self.id}
        return action


class SchoolGradeGroupPreset(models.Model):
    _name = 'school.grade.group.preset'
    _description = 'Grade Group Preset'
    _order = 'display_order asc, id asc'

    name = fields.Char(required=True)
    display_order = fields.Integer(required=True)
    level_preset_ids = fields.One2many(
        'school.grade.level.preset',
        'group_preset_id',
        string='Grade Levels',
    )


class SchoolGradeLevelPreset(models.Model):
    _name = 'school.grade.level.preset'
    _description = 'Grade Level Preset'
    _order = 'sort_order asc, id asc'

    name = fields.Char(required=True)
    group_preset_id = fields.Many2one(
        'school.grade.group.preset',
        string='Grade Group',
        required=True,
        ondelete='cascade',
    )
    sort_order = fields.Integer(required=True)


class SchoolGradeSetupWizard(models.TransientModel):
    _name = 'school.grade.setup.wizard'
    _description = 'Configure School Grade Structure'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    group_preset_ids = fields.Many2many(
        'school.grade.group.preset',
        string='Grade Groups',
        required=True,
    )
    level_preset_ids = fields.Many2many(
        'school.grade.level.preset',
        string='Grade Levels',
        required=True,
    )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        groups = self.env['school.grade.group.preset'].search([])
        if 'group_preset_ids' in field_names:
            values['group_preset_ids'] = [fields.Command.set(groups.ids)]
        if 'level_preset_ids' in field_names:
            values['level_preset_ids'] = [fields.Command.set(groups.level_preset_ids.ids)]
        return values

    def action_apply(self):
        self.ensure_one()
        selected_groups = self.group_preset_ids.sorted('display_order')
        selected_levels = self.level_preset_ids.filtered(
            lambda preset: preset.group_preset_id in selected_groups
        ).sorted('sort_order')

        groups_by_preset = {}
        created_group_count = 0
        created_level_count = 0
        for preset in selected_groups:
            group = self.env['school.grade.groups'].search([
                ('school_id', '=', self.school_id.id),
                ('name', '=ilike', preset.name),
            ], limit=1)
            if not group:
                group = self.env['school.grade.groups'].create({
                    'school_id': self.school_id.id,
                    'name': preset.name,
                    'display_order': preset.display_order,
                })
                created_group_count += 1
            groups_by_preset[preset.id] = group

        for preset in selected_levels:
            group = groups_by_preset[preset.group_preset_id.id]
            level = self.env['school.grade.levels'].search([
                ('school_id', '=', self.school_id.id),
                ('group_id', '=', group.id),
                ('name', '=ilike', preset.name),
            ], limit=1)
            if not level:
                self.env['school.grade.levels'].create({
                    'school_id': self.school_id.id,
                    'group_id': group.id,
                    'name': preset.name,
                    'sort_order': preset.sort_order,
                })
                created_level_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Grade setup complete',
                'message': f'Added {created_group_count} grade groups and {created_level_count} grade levels.',
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SchoolCurriculumPreset(models.Model):
    _name = 'school.curriculum.preset'
    _description = 'Curriculum Preset'
    _order = 'display_order asc, id asc'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    description = fields.Text(required=True)
    source_url = fields.Char(string='Official Source', required=True)
    verified_on = fields.Date(string='Verified On', required=True)
    display_order = fields.Integer(required=True)
    subject_preset_ids = fields.One2many(
        'school.subject.preset',
        'curriculum_id',
        string='Subjects',
    )


class SchoolSubjectPreset(models.Model):
    _name = 'school.subject.preset'
    _description = 'Curriculum Subject Preset'
    _order = 'curriculum_id asc, display_order asc, id asc'

    name = fields.Char(required=True)
    category = fields.Char(required=True)
    curriculum_id = fields.Many2one(
        'school.curriculum.preset',
        string='Curriculum',
        required=True,
        ondelete='cascade',
    )
    display_order = fields.Integer(required=True)


class SchoolSubjectSetupWizard(models.TransientModel):
    _name = 'school.subject.setup.wizard'
    _description = 'Configure School Subjects'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    curriculum_id = fields.Many2one(
        'school.curriculum.preset',
        string='Curriculum',
        required=True,
    )
    curriculum_description = fields.Text(
        related='curriculum_id.description',
        string='Scope',
        readonly=True,
    )
    source_url = fields.Char(
        related='curriculum_id.source_url',
        string='Official Source',
        readonly=True,
    )
    verified_on = fields.Date(
        related='curriculum_id.verified_on',
        string='Verified On',
        readonly=True,
    )
    subject_preset_ids = fields.Many2many(
        'school.subject.preset',
        string='Subjects',
        required=True,
    )

    @api.onchange('curriculum_id')
    def _onchange_curriculum_id(self):
        self.subject_preset_ids = self.curriculum_id.subject_preset_ids

    def action_apply(self):
        self.ensure_one()
        selected_subjects = self.subject_preset_ids.filtered(
            lambda preset: preset.curriculum_id == self.curriculum_id
        ).sorted('display_order')

        created_count = 0
        for preset in selected_subjects:
            subject = self.env['school.subjects'].search([
                ('school_id', '=', self.school_id.id),
                ('name', '=ilike', preset.name),
            ], limit=1)
            if not subject:
                self.env['school.subjects'].create({
                    'school_id': self.school_id.id,
                    'name': preset.name,
                    'display_order': preset.display_order,
                })
                created_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Subject setup complete',
                'message': f'Added {created_count} subjects from {self.curriculum_id.name}.',
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SchoolPredictionScenarioPreset(models.Model):
    _name = 'school.prediction.scenario.preset'
    _description = 'Prediction Scenario Preset'
    _order = 'display_order asc, id asc'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    display_order = fields.Integer(required=True, default=10)
    annual_growth_rate = fields.Float(string='Annual Enrollment Growth %', required=True, default=4.0)
    operating_expense_ratio = fields.Float(string='Operating Expense Ratio %', required=True, default=25.0)
    salary_ratio = fields.Float(string='Salary Ratio %', required=True, default=35.0)
    tuition_share = fields.Float(string='Tuition Share', required=True, default=0.8)
    admission_share = fields.Float(string='Admission Share', required=True, default=0.1)
    activity_share = fields.Float(string='Activity Share', required=True, default=0.1)


class SchoolPredictionQuickSetupYearLine(models.TransientModel):
    _name = 'school.prediction.quick.setup.year.line'
    _description = 'Quick Prediction Setup Year Input'
    _order = 'year_index asc, id asc'

    wizard_id = fields.Many2one('school.prediction.quick.setup.wizard', required=True, ondelete='cascade')
    year_index = fields.Integer(string='Year #', required=True)
    year_label = fields.Char(string='Academic Year', required=True)
    student_count = fields.Integer(string='Students', required=True, default=600)
    annual_fee_per_student = fields.Float(string='Annual Fee Per Student', required=True, default=12000.0)
    teacher_count = fields.Integer(string='Teachers', required=True, default=0)
    principal_count = fields.Integer(string='Principals', required=True, default=0)
    assistant_principal_count = fields.Integer(string='Assistant Principals', required=True, default=0)
    it_count = fields.Integer(string='IT Staff', required=True, default=0)
    janitor_count = fields.Integer(string='Janitors', required=True, default=0)
    admission_officer_count = fields.Integer(string='Admission Officers', required=True, default=0)
    front_desk_count = fields.Integer(string='Front Desk Staff', required=True, default=0)
    student_affairs_count = fields.Integer(string='Student Affairs Staff', required=True, default=0)
    nurse_count = fields.Integer(string='Nurses', required=True, default=0)
    hr_count = fields.Integer(string='HR Staff', required=True, default=0)
    accountant_count = fields.Integer(string='Accountants', required=True, default=0)
    finance_officer_count = fields.Integer(string='Finance Officers', required=True, default=0)

    @api.onchange('student_count')
    def _onchange_student_count(self):
        for line in self:
            if not line.wizard_id:
                continue
            line.wizard_id._autofill_staff_counts_for_lines(line_ids=line)

    @api.model_create_multi
    def create(self, vals_list):
        staff_fields = {
            'teacher_count',
            'principal_count',
            'assistant_principal_count',
            'it_count',
            'janitor_count',
            'admission_officer_count',
            'front_desk_count',
            'student_affairs_count',
            'nurse_count',
            'hr_count',
            'accountant_count',
            'finance_officer_count',
        }

        next_index_without_wizard = 1
        wizard_next_indexes = {}
        for vals in vals_list:
            if not vals.get('year_index'):
                wizard_id = vals.get('wizard_id')
                if wizard_id:
                    if wizard_id not in wizard_next_indexes:
                        last_line = self.search([
                            ('wizard_id', '=', wizard_id),
                        ], order='year_index desc, id desc', limit=1)
                        wizard_next_indexes[wizard_id] = (last_line.year_index or 0) + 1
                    vals['year_index'] = wizard_next_indexes[wizard_id]
                    wizard_next_indexes[wizard_id] += 1
                else:
                    vals['year_index'] = next_index_without_wizard
                    next_index_without_wizard += 1
            elif not vals.get('wizard_id'):
                next_index_without_wizard = max(next_index_without_wizard, int(vals['year_index']) + 1)

            if not vals.get('year_label'):
                start_year = fields.Date.today().year + max(vals['year_index'] - 1, 0)
                vals['year_label'] = f'{start_year}-{start_year + 1}'

            missing_staff_fields = [field for field in staff_fields if field not in vals]
            wizard_id = vals.get('wizard_id')
            if missing_staff_fields and wizard_id:
                wizard = self.env['school.prediction.quick.setup.wizard'].browse(wizard_id)
                suggested_values = wizard._build_staff_values_from_students(vals.get('student_count') or 0)
                for field_name in missing_staff_fields:
                    vals[field_name] = suggested_values[field_name]
            elif missing_staff_fields:
                for field_name in missing_staff_fields:
                    vals[field_name] = 0

        return super().create(vals_list)

    def write(self, vals):
        # Ignore empty mandatory values from partial inline editor payloads.
        cleaned_vals = dict(vals)
        if cleaned_vals.get('year_index') in (False, None, 0):
            cleaned_vals.pop('year_index', None)
        if cleaned_vals.get('year_label') in (False, None, ''):
            cleaned_vals.pop('year_label', None)
        return super().write(cleaned_vals)


class SchoolPredictionQuickSetupSalaryLine(models.TransientModel):
    _name = 'school.prediction.quick.setup.salary.line'
    _description = 'Quick Prediction Setup Salary Input'
    _order = 'year_index asc, id asc'

    wizard_id = fields.Many2one('school.prediction.quick.setup.wizard', required=True, ondelete='cascade')
    year_index = fields.Integer(string='Year #', required=True)
    year_label = fields.Char(string='Academic Year', required=True)
    staff_role = fields.Selection(STAFF_ROLE_SELECTION, string='Staff Type', required=True)
    monthly_salary = fields.Float(string='Monthly Salary', required=True, default=0.0)
    months_paid = fields.Integer(string='Months Paid', required=True, default=12)
    bonus = fields.Float(string='Annual Bonus', default=0.0)


class SchoolPredictionQuickSetupYearSalaryLine(models.TransientModel):
    _name = 'school.prediction.quick.setup.year.salary.line'
    _description = 'Quick Prediction Setup Year Salary Input'
    _order = 'year_index asc, id asc'

    wizard_id = fields.Many2one('school.prediction.quick.setup.wizard', required=True, ondelete='cascade')
    year_index = fields.Integer(string='Year #', required=True)
    year_label = fields.Char(string='Academic Year', required=True)
    teacher_monthly_salary = fields.Float(string='Teacher Salary', required=True, default=0.0)
    principal_monthly_salary = fields.Float(string='Principal Salary', required=True, default=0.0)
    assistant_principal_monthly_salary = fields.Float(string='Assistant Principal Salary', required=True, default=0.0)
    it_monthly_salary = fields.Float(string='IT Salary', required=True, default=0.0)
    janitor_monthly_salary = fields.Float(string='Janitor Salary', required=True, default=0.0)
    admission_officer_monthly_salary = fields.Float(string='Admission Officer Salary', required=True, default=0.0)
    front_desk_monthly_salary = fields.Float(string='Front Desk Salary', required=True, default=0.0)
    student_affairs_monthly_salary = fields.Float(string='Student Affairs Salary', required=True, default=0.0)
    nurse_monthly_salary = fields.Float(string='Nurse Salary', required=True, default=0.0)
    hr_monthly_salary = fields.Float(string='HR Salary', required=True, default=0.0)
    accountant_monthly_salary = fields.Float(string='Accountant Salary', required=True, default=0.0)
    finance_officer_monthly_salary = fields.Float(string='Finance Officer Salary', required=True, default=0.0)
    months_paid = fields.Integer(string='Months Paid', required=True, default=12)
    bonus = fields.Float(string='Annual Bonus', default=0.0)

    @api.model_create_multi
    def create(self, vals_list):
        next_index_without_wizard = 1
        wizard_next_indexes = {}
        for vals in vals_list:
            if not vals.get('year_index'):
                wizard_id = vals.get('wizard_id')
                if wizard_id:
                    if wizard_id not in wizard_next_indexes:
                        last_line = self.search([
                            ('wizard_id', '=', wizard_id),
                        ], order='year_index desc, id desc', limit=1)
                        wizard_next_indexes[wizard_id] = (last_line.year_index or 0) + 1
                    vals['year_index'] = wizard_next_indexes[wizard_id]
                    wizard_next_indexes[wizard_id] += 1
                else:
                    vals['year_index'] = next_index_without_wizard
                    next_index_without_wizard += 1
            elif not vals.get('wizard_id'):
                next_index_without_wizard = max(next_index_without_wizard, int(vals['year_index']) + 1)

            if not vals.get('year_label'):
                start_year = fields.Date.today().year + max(int(vals['year_index']) - 1, 0)
                vals['year_label'] = f'{start_year}-{start_year + 1}'

        return super().create(vals_list)

    def write(self, vals):
        # Ignore empty mandatory values from partial inline editor payloads.
        cleaned_vals = dict(vals)
        if cleaned_vals.get('year_index') in (False, None, 0):
            cleaned_vals.pop('year_index', None)
        if cleaned_vals.get('year_label') in (False, None, ''):
            cleaned_vals.pop('year_label', None)
        return super().write(cleaned_vals)


class SchoolPredictionQuickSetupWizard(models.TransientModel):
    _name = 'school.prediction.quick.setup.wizard'
    _description = 'Quick Prediction Setup Wizard'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    forecast_years = fields.Integer(string='Years Ahead to Predict', required=True, default=3)
    income_tax_percent = fields.Float(string='Income Tax %', required=True, default=12.0)
    fee_increase_percent = fields.Float(string='Annual Fee Increase %', required=True, default=5.0)
    salary_increase_percent = fields.Float(string='Annual Salary Increase %', required=True, default=5.0)
    max_students_per_class_input = fields.Integer(string='Max Students Per Class', required=True, default=25)
    subject_hours_per_class = fields.Float(string='Weekly Subject Hours Per Class', readonly=True)
    teaching_load_hours = fields.Float(string='Teaching Load Per Teacher', required=True, default=24.0)
    assistant_principal_per_students = fields.Float(string='Assistant Principal: 1 per N Students', required=True, default=250.0)
    janitor_per_students = fields.Float(string='Janitor: 1 per N Students', required=True, default=100.0)
    principal_fixed_count = fields.Integer(string='Principal Count', required=True, default=1)
    it_fixed_count = fields.Integer(string='IT Count', required=True, default=2)
    admission_officer_fixed_count = fields.Integer(string='Admission Officer Count', required=True, default=1)
    front_desk_fixed_count = fields.Integer(string='Front Desk Count', required=True, default=1)
    student_affairs_fixed_count = fields.Integer(string='Student Affairs Count', required=True, default=1)
    nurse_fixed_count = fields.Integer(string='Nurse Count', required=True, default=1)
    hr_fixed_count = fields.Integer(string='HR Count', required=True, default=1)
    accountant_fixed_count = fields.Integer(string='Accountant Count', required=True, default=1)
    finance_officer_fixed_count = fields.Integer(string='Finance Officer Count', required=True, default=1)
    line_ids = fields.One2many('school.prediction.quick.setup.year.line', 'wizard_id', string='Manual Year Inputs')
    salary_line_ids = fields.One2many('school.prediction.quick.setup.salary.line', 'wizard_id', string='Legacy Salary Inputs')
    year_salary_line_ids = fields.One2many('school.prediction.quick.setup.year.salary.line', 'wizard_id', string='Manual Salary Inputs')

    def _staff_role_specs(self):
        return STAFF_ROLE_SELECTION

    def _salary_role_field_map(self):
        return {
            'teacher': 'teacher_monthly_salary',
            'principal': 'principal_monthly_salary',
            'assistant_principal': 'assistant_principal_monthly_salary',
            'it': 'it_monthly_salary',
            'janitor': 'janitor_monthly_salary',
            'admission_officer': 'admission_officer_monthly_salary',
            'front_desk': 'front_desk_monthly_salary',
            'student_affairs': 'student_affairs_monthly_salary',
            'nurse': 'nurse_monthly_salary',
            'hr': 'hr_monthly_salary',
            'accountant': 'accountant_monthly_salary',
            'finance_officer': 'finance_officer_monthly_salary',
        }

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        forecast_years = int(values.get('forecast_years') or 3)
        fee_increase_percent = values.get('fee_increase_percent')
        salary_increase_percent = values.get('salary_increase_percent')
        school = False
        school_id = values.get('school_id')
        if school_id:
            school = self.env['school.schools'].browse(school_id)
        values['subject_hours_per_class'] = self._subject_hours_per_class_from_subjects(school=school)
        if 'line_ids' in field_names and not values.get('line_ids'):
            values['line_ids'] = self._build_default_line_commands(
                forecast_years,
                fee_increase_percent=fee_increase_percent,
            )
        if 'salary_line_ids' in field_names and not values.get('salary_line_ids'):
            values['salary_line_ids'] = self._build_salary_line_commands(
                line_values=values.get('line_ids') or [],
                fee_increase_percent=fee_increase_percent,
            )
        if 'year_salary_line_ids' in field_names and not values.get('year_salary_line_ids'):
            values['year_salary_line_ids'] = self._build_year_salary_line_commands(
                line_values=values.get('line_ids') or [],
                fee_increase_percent=fee_increase_percent,
                salary_increase_percent=salary_increase_percent,
            )
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            fee_increase_percent = vals.get('fee_increase_percent')
            salary_increase_percent = vals.get('salary_increase_percent')
            line_values = vals.get('line_ids') or []
            if line_values:
                normalized_line_values = self._line_dicts_from_command_values(
                    line_values,
                    fee_increase_percent=fee_increase_percent,
                )
                vals['line_ids'] = [(0, 0, line_value) for line_value in normalized_line_values]

            if vals.get('subject_hours_per_class'):
                school_id = vals.get('school_id')
            else:
                school_id = vals.get('school_id')
                if school_id:
                    school = self.env['school.schools'].browse(school_id)
                    vals['subject_hours_per_class'] = self._subject_hours_per_class_from_subjects(school=school)

            if not vals.get('salary_line_ids'):
                line_values = vals.get('line_ids') or []
                if line_values:
                    vals['salary_line_ids'] = self._build_salary_line_commands(
                        line_values=line_values,
                        fee_increase_percent=fee_increase_percent,
                    )
            if not vals.get('year_salary_line_ids'):
                line_values = vals.get('line_ids') or []
                if line_values:
                    vals['year_salary_line_ids'] = self._build_year_salary_line_commands(
                        line_values=line_values,
                        fee_increase_percent=fee_increase_percent,
                        salary_increase_percent=salary_increase_percent,
                    )
        return super().create(vals_list)

    def _academic_year_label(self, year_index):
        start_year = fields.Date.today().year + year_index
        return f'{start_year}-{start_year + 1}'

    def _growth_factor(self, percent_value):
        normalized = max(float(percent_value or 0.0), 0.0)
        return 1.0 + (normalized / 100.0)

    def _build_default_line_commands(self, forecast_years, fee_increase_percent=None):
        commands = []
        fee_growth = self._growth_factor(
            self.fee_increase_percent if fee_increase_percent is None else fee_increase_percent
        )
        for year_index in range(max(forecast_years, 1)):
            staff_values = self._build_staff_values_from_students(600)
            commands.append(fields.Command.create({
                'year_index': year_index + 1,
                'year_label': self._academic_year_label(year_index),
                'student_count': 600,
                'annual_fee_per_student': 12000.0 * (fee_growth ** year_index),
                **staff_values,
            }))
        return commands

    def _apply_fee_growth_to_lines(self):
        self.ensure_one()
        lines = self.line_ids.sorted('year_index')
        if not lines:
            return

        base_fee = float(lines[0].annual_fee_per_student or 0.0)
        growth = self._growth_factor(self.fee_increase_percent)
        for index, line in enumerate(lines):
            if index == 0:
                continue
            line.annual_fee_per_student = base_fee * (growth ** index)

    def _apply_salary_growth_to_lines(self):
        self.ensure_one()
        lines = self.year_salary_line_ids.sorted('year_index')
        if not lines:
            return

        role_field_map = self._salary_role_field_map()
        base_row = lines[0]
        growth = self._growth_factor(self.salary_increase_percent)
        base_values = {
            field_name: float(getattr(base_row, field_name) or 0.0)
            for field_name in role_field_map.values()
        }

        for index, line in enumerate(lines):
            if index == 0:
                continue
            updates = {}
            for field_name, base_value in base_values.items():
                updates[field_name] = base_value * (growth ** index)
            line.update(updates)

    def _default_monthly_salary_from_line(self, line_dict):
        scenario = self._default_scenario()
        salary_ratio = ((scenario.salary_ratio if scenario else 35.0) or 0.0) / 100.0
        gross_revenue = float(line_dict.get('student_count') or 0.0) * float(line_dict.get('annual_fee_per_student') or 0.0)
        salary_budget = gross_revenue * salary_ratio

        staff_total = 0
        for key in (
            'teacher_count', 'principal_count', 'assistant_principal_count', 'it_count', 'janitor_count',
            'admission_officer_count', 'front_desk_count', 'student_affairs_count', 'nurse_count',
            'hr_count', 'accountant_count', 'finance_officer_count',
        ):
            staff_total += max(int(line_dict.get(key) or 0), 0)
        staff_total = max(staff_total, 1)
        return salary_budget / (staff_total * 12.0) if salary_budget > 0 else 0.0

    def _line_dicts_from_year_lines(self):
        line_dicts = []
        for line in self.line_ids.sorted('year_index'):
            line_dicts.append({
                'year_index': line.year_index,
                'year_label': line.year_label,
                'student_count': line.student_count,
                'annual_fee_per_student': line.annual_fee_per_student,
                'teacher_count': line.teacher_count,
                'principal_count': line.principal_count,
                'assistant_principal_count': line.assistant_principal_count,
                'it_count': line.it_count,
                'janitor_count': line.janitor_count,
                'admission_officer_count': line.admission_officer_count,
                'front_desk_count': line.front_desk_count,
                'student_affairs_count': line.student_affairs_count,
                'nurse_count': line.nurse_count,
                'hr_count': line.hr_count,
                'accountant_count': line.accountant_count,
                'finance_officer_count': line.finance_officer_count,
            })
        return line_dicts

    def _line_dicts_from_command_values(self, line_values, fee_increase_percent=None):
        dicts = []
        fallback_year_index = 1
        last_fee_value = None
        fee_growth = self._growth_factor(
            self.fee_increase_percent if fee_increase_percent is None else fee_increase_percent
        )
        for command in line_values:
            if not isinstance(command, (list, tuple)) or len(command) < 3:
                continue
            if command[0] != 0:
                continue
            values = dict(command[2] or {})
            if not values.get('year_index'):
                values['year_index'] = fallback_year_index
                fallback_year_index += 1
            else:
                fallback_year_index = max(fallback_year_index, int(values['year_index']) + 1)
            if not values.get('year_label'):
                values['year_label'] = self._academic_year_label(max(int(values['year_index']) - 1, 0))
            values.setdefault('student_count', 0)
            raw_fee = values.get('annual_fee_per_student')
            if raw_fee in (False, None):
                if last_fee_value is None:
                    values['annual_fee_per_student'] = 12000.0
                else:
                    values['annual_fee_per_student'] = last_fee_value * fee_growth
            last_fee_value = float(values.get('annual_fee_per_student') or 0.0)
            for key in (
                'teacher_count', 'principal_count', 'assistant_principal_count', 'it_count', 'janitor_count',
                'admission_officer_count', 'front_desk_count', 'student_affairs_count', 'nurse_count',
                'hr_count', 'accountant_count', 'finance_officer_count',
            ):
                values.setdefault(key, 0)
            dicts.append(values)
        return dicts

    def _build_salary_line_commands(self, line_values=None, fee_increase_percent=None):
        existing_map = {
            (line.year_index, line.staff_role): line
            for line in self.salary_line_ids
        }

        year_lines = self._line_dicts_from_year_lines()
        if line_values is not None:
            year_lines = self._line_dicts_from_command_values(
                line_values,
                fee_increase_percent=fee_increase_percent,
            )

        commands = []
        for year_line in sorted(year_lines, key=lambda row: row.get('year_index') or 0):
            year_index = int(year_line.get('year_index') or 1)
            year_label = year_line.get('year_label') or self._academic_year_label(max(year_index - 1, 0))
            default_monthly = self._default_monthly_salary_from_line(year_line)

            for staff_role, _staff_title in self._staff_role_specs():
                existing = existing_map.get((year_index, staff_role))
                commands.append(fields.Command.create({
                    'year_index': year_index,
                    'year_label': year_label,
                    'staff_role': staff_role,
                    'monthly_salary': existing.monthly_salary if existing else default_monthly,
                    'months_paid': existing.months_paid if existing else 12,
                    'bonus': existing.bonus if existing else 0.0,
                }))
        return commands

    def _build_year_salary_line_commands(self, line_values=None, fee_increase_percent=None, salary_increase_percent=None):
        role_field_map = self._salary_role_field_map()
        existing_map = {
            line.year_index: line
            for line in self.year_salary_line_ids
        }
        salary_growth = self._growth_factor(
            self.salary_increase_percent if salary_increase_percent is None else salary_increase_percent
        )
        previous_generated_values = None

        year_lines = self._line_dicts_from_year_lines()
        if line_values is not None:
            year_lines = self._line_dicts_from_command_values(
                line_values,
                fee_increase_percent=fee_increase_percent,
            )

        commands = []
        for year_line in sorted(year_lines, key=lambda row: row.get('year_index') or 0):
            year_index = int(year_line.get('year_index') or 1)
            year_label = year_line.get('year_label') or self._academic_year_label(max(year_index - 1, 0))
            default_monthly = self._default_monthly_salary_from_line(year_line)
            existing = existing_map.get(year_index)

            values = {
                'year_index': year_index,
                'year_label': year_label,
                'months_paid': existing.months_paid if existing else 12,
                'bonus': existing.bonus if existing else 0.0,
            }
            for role_key, field_name in role_field_map.items():
                if existing:
                    values[field_name] = getattr(existing, field_name)
                elif previous_generated_values:
                    values[field_name] = previous_generated_values[field_name] * salary_growth
                else:
                    values[field_name] = default_monthly
            commands.append(fields.Command.create(values))
            previous_generated_values = values
        return commands

    def _sync_salary_lines(self):
        self.ensure_one()
        commands = self._build_year_salary_line_commands()
        self.year_salary_line_ids = [fields.Command.clear()] + commands

    def _safe_divisor(self, value, fallback):
        return float(value) if float(value or 0.0) > 0 else float(fallback)

    def _subject_count(self, school=None):
        target_school = school or self.school_id
        if not target_school:
            return 0
        return self.env['school.subjects'].search_count([
            ('school_id', '=', target_school.id),
        ])

    def _subject_hours_per_class_from_subjects(self, school=None):
        target_school = school or self.school_id
        if not target_school:
            return 0.0
        subject_count = self.env['school.subjects'].search_count([
            ('school_id', '=', target_school.id),
        ])
        return float(subject_count * 5.0)

    def _build_staff_values_from_students(self, student_count):
        student_count = max(int(student_count or 0), 0)
        max_students_per_class = max(int(self.max_students_per_class_input or 0), 1)
        class_count = math.ceil(student_count / max_students_per_class) if student_count > 0 else 0

        subject_count = self._subject_count()
        subject_hours_per_class = max(float(self.subject_hours_per_class or 0.0), 0.0)
        teaching_load_hours = self._safe_divisor(self.teaching_load_hours, 1.0)
        teacher_count = math.ceil((class_count * subject_hours_per_class) / teaching_load_hours) if class_count > 0 else 0
        teacher_count = max(int(teacher_count), int(subject_count))

        assistant_divisor = self._safe_divisor(self.assistant_principal_per_students, 250.0)
        janitor_divisor = self._safe_divisor(self.janitor_per_students, 100.0)

        return {
            'teacher_count': max(int(teacher_count), 0),
            'principal_count': max(int(self.principal_fixed_count or 0), 0),
            'assistant_principal_count': max(int(math.ceil(student_count / assistant_divisor)) if student_count > 0 else 0, 0),
            'it_count': max(int(self.it_fixed_count or 0), 0),
            'janitor_count': max(int(math.ceil(student_count / janitor_divisor)) if student_count > 0 else 0, 0),
            'admission_officer_count': max(int(self.admission_officer_fixed_count or 0), 0),
            'front_desk_count': max(int(self.front_desk_fixed_count or 0), 0),
            'student_affairs_count': max(int(self.student_affairs_fixed_count or 0), 0),
            'nurse_count': max(int(self.nurse_fixed_count or 0), 0),
            'hr_count': max(int(self.hr_fixed_count or 0), 0),
            'accountant_count': max(int(self.accountant_fixed_count or 0), 0),
            'finance_officer_count': max(int(self.finance_officer_fixed_count or 0), 0),
        }

    def _autofill_staff_counts_for_lines(self, line_ids=None):
        self.ensure_one()
        self.subject_hours_per_class = self._subject_hours_per_class_from_subjects()
        target_lines = line_ids or self.line_ids
        for line in target_lines:
            line_values = self._build_staff_values_from_students(line.student_count)
            line.update(line_values)
        self._sync_salary_lines()

    @api.onchange('school_id')
    def _onchange_school_id_staffing(self):
        for wizard in self:
            wizard.subject_hours_per_class = wizard._subject_hours_per_class_from_subjects()
            wizard._autofill_staff_counts_for_lines()

    @api.onchange('forecast_years')
    def _onchange_forecast_years(self):
        for wizard in self:
            target_years = max(int(wizard.forecast_years or 1), 1)
            existing_lines = wizard.line_ids.sorted('year_index')

            generated_values = []
            for index in range(target_years):
                if index < len(existing_lines):
                    line = existing_lines[index]
                    generated_values.append({
                        'year_index': index + 1,
                        'year_label': wizard._academic_year_label(index),
                        'student_count': line.student_count,
                        'annual_fee_per_student': line.annual_fee_per_student,
                        'teacher_count': line.teacher_count,
                        'principal_count': line.principal_count,
                        'assistant_principal_count': line.assistant_principal_count,
                        'it_count': line.it_count,
                        'janitor_count': line.janitor_count,
                        'admission_officer_count': line.admission_officer_count,
                        'front_desk_count': line.front_desk_count,
                        'student_affairs_count': line.student_affairs_count,
                        'nurse_count': line.nurse_count,
                        'hr_count': line.hr_count,
                        'accountant_count': line.accountant_count,
                        'finance_officer_count': line.finance_officer_count,
                    })
                else:
                    source = generated_values[-1] if generated_values else {
                        'student_count': 600,
                        'annual_fee_per_student': 12000.0,
                    }
                    source_staff_values = wizard._build_staff_values_from_students(source['student_count'])
                    generated_values.append({
                        'year_index': index + 1,
                        'year_label': wizard._academic_year_label(index),
                        'student_count': source['student_count'],
                        'annual_fee_per_student': source['annual_fee_per_student'] * wizard._growth_factor(
                            wizard.fee_increase_percent
                        ),
                        **source_staff_values,
                    })

            wizard.line_ids = [fields.Command.clear()] + [fields.Command.create(values) for values in generated_values]
            wizard._sync_salary_lines()

    @api.onchange(
        'max_students_per_class_input',
        'subject_hours_per_class',
        'teaching_load_hours',
        'assistant_principal_per_students',
        'janitor_per_students',
        'principal_fixed_count',
        'it_fixed_count',
        'admission_officer_fixed_count',
        'front_desk_fixed_count',
        'student_affairs_fixed_count',
        'nurse_fixed_count',
        'hr_fixed_count',
        'accountant_fixed_count',
        'finance_officer_fixed_count',
    )
    def _onchange_staffing_inputs(self):
        for wizard in self:
            wizard._autofill_staff_counts_for_lines()

    @api.onchange('line_ids')
    def _onchange_line_values_for_salary_defaults(self):
        for wizard in self:
            wizard._apply_fee_growth_to_lines()
            wizard._sync_salary_lines()
            wizard._apply_salary_growth_to_lines()

    @api.onchange('fee_increase_percent')
    def _onchange_fee_increase_percent(self):
        for wizard in self:
            wizard._apply_fee_growth_to_lines()
            wizard._sync_salary_lines()

    @api.onchange('salary_increase_percent')
    def _onchange_salary_increase_percent(self):
        for wizard in self:
            wizard._sync_salary_lines()
            wizard._apply_salary_growth_to_lines()

    @api.onchange('year_salary_line_ids')
    def _onchange_year_salary_line_ids(self):
        for wizard in self:
            wizard._apply_salary_growth_to_lines()

    def _upsert(self, model_name, domain, values):
        record = self.env[model_name].search(domain, limit=1)
        if record:
            record.write(values)
            return record
        return self.env[model_name].create(values)

    def _default_scenario(self):
        scenario = self.env['school.prediction.scenario.preset'].search([('code', '=', 'base')], limit=1)
        return scenario or self.env['school.prediction.scenario.preset'].search([], order='display_order asc, id asc', limit=1)

    def _ensure_income_tax_rule(self):
        self.ensure_one()
        normalized_percentage = max(float(self.income_tax_percent or 0.0), 0.0) / 100.0
        tax_name = f'Income Tax {float(self.income_tax_percent or 0.0):g}%'
        tax_rule = self.env['school.tax.rules'].search([
            ('name', '=', tax_name),
            ('percentage', '=', normalized_percentage),
        ], limit=1)
        if not tax_rule:
            tax_rule = self.env['school.tax.rules'].create({
                'name': tax_name,
                'percentage': normalized_percentage,
            })
        return tax_rule

    def _ensure_grade_structure(self):
        self.ensure_one()
        school = self.school_id
        selected_groups = self.env['school.grade.group.preset'].search([], order='display_order asc, id asc')
        selected_levels = self.env['school.grade.level.preset'].search([], order='sort_order asc, id asc')

        groups_by_preset = {}
        for preset in selected_groups:
            group = self.env['school.grade.groups'].search([
                ('school_id', '=', school.id),
                ('name', '=ilike', preset.name),
            ], limit=1)
            if not group:
                group = self.env['school.grade.groups'].create({
                    'school_id': school.id,
                    'name': preset.name,
                    'display_order': preset.display_order,
                })
            groups_by_preset[preset.id] = group

        for preset in selected_levels:
            group = groups_by_preset.get(preset.group_preset_id.id)
            if not group:
                continue
            level = self.env['school.grade.levels'].search([
                ('school_id', '=', school.id),
                ('group_id', '=', group.id),
                ('name', '=ilike', preset.name),
            ], limit=1)
            if not level:
                self.env['school.grade.levels'].create({
                    'school_id': school.id,
                    'group_id': group.id,
                    'name': preset.name,
                    'sort_order': preset.sort_order,
                })

        return self.env['school.grade.levels'].search([
            ('school_id', '=', school.id),
        ], order='sort_order asc, id asc')

    def _ensure_subjects(self):
        self.ensure_one()
        school = self.school_id
        curriculum = self.env['school.curriculum.preset'].search([], order='display_order asc, id asc', limit=1)
        if not curriculum:
            return

        presets = self.env['school.subject.preset'].search([
            ('curriculum_id', '=', curriculum.id),
        ], order='display_order asc, id asc')
        for preset in presets:
            subject = self.env['school.subjects'].search([
                ('school_id', '=', school.id),
                ('name', '=ilike', preset.name),
            ], limit=1)
            if not subject:
                self.env['school.subjects'].create({
                    'school_id': school.id,
                    'name': preset.name,
                    'display_order': preset.display_order,
                })
        return self.env['school.subjects'].search([
            ('school_id', '=', school.id),
        ], order='display_order asc, id asc')

    def _ensure_subject_distribution(self, academic_year, levels, subjects):
        self.ensure_one()
        for level in levels:
            for subject in subjects:
                self._upsert(
                    'school.subject.distribution',
                    [
                        ('academic_year_id', '=', academic_year.id),
                        ('grade_level_id', '=', level.id),
                        ('subject_id', '=', subject.id),
                    ],
                    {
                        'academic_year_id': academic_year.id,
                        'grade_level_id': level.id,
                        'subject_id': subject.id,
                        'weekly_hours': 5.0,
                        'credits': 0.0,
                    },
                )

    def _ensure_fee_types(self, tax_rule):
        self.ensure_one()
        school = self.school_id
        fee_specs = [
            ('Tuition Fee', 10),
            ('Admission Fee', 20),
            ('Activity Fee', 30),
        ]
        fee_types = []
        for name, display_order in fee_specs:
            fee_type = self.env['school.fee.types'].search([
                ('school_id', '=', school.id),
                ('name', '=ilike', name),
            ], limit=1)
            if not fee_type:
                fee_type = self.env['school.fee.types'].create({
                    'school_id': school.id,
                    'name': name,
                    'display_order': display_order,
                    'is_taxable': True,
                    'tax_rule_id': tax_rule.id,
                })
            else:
                fee_type.write({
                    'is_taxable': True,
                    'tax_rule_id': tax_rule.id,
                })
            fee_types.append(fee_type)
        return fee_types

    def _ensure_operating_models(self):
        self.ensure_one()
        school = self.school_id

        operating_category = self.env['school.expense.categories'].search([
            ('school_id', '=', school.id),
            ('name', '=ilike', 'Operating Costs'),
        ], limit=1)
        if not operating_category:
            operating_category = self.env['school.expense.categories'].create({
                'school_id': school.id,
                'name': 'Operating Costs',
                'display_order': 10,
            })

        expense_item = self.env['school.expense.items'].search([
            ('school_id', '=', school.id),
            ('name', '=ilike', 'General Operations'),
        ], limit=1)
        if not expense_item:
            expense_item = self.env['school.expense.items'].create({
                'school_id': school.id,
                'expense_category_id': operating_category.id,
                'name': 'General Operations',
                'display_order': 10,
            })

        teaching_staff_category = self.env['school.staff.categories'].search([
            ('school_id', '=', school.id),
            ('name', '=ilike', 'Teaching Staff'),
        ], limit=1)
        if not teaching_staff_category:
            teaching_staff_category = self.env['school.staff.categories'].create({
                'school_id': school.id,
                'name': 'Teaching Staff',
                'display_order': 10,
            })

        support_staff_category = self.env['school.staff.categories'].search([
            ('school_id', '=', school.id),
            ('name', '=ilike', 'Support Staff'),
        ], limit=1)
        if not support_staff_category:
            support_staff_category = self.env['school.staff.categories'].create({
                'school_id': school.id,
                'name': 'Support Staff',
                'display_order': 20,
            })

        staff_specs = [
            ('teacher', 'Teacher', teaching_staff_category, 10),
            ('principal', 'Principal', support_staff_category, 20),
            ('assistant_principal', 'Assistant Principal', support_staff_category, 30),
            ('it', 'IT', support_staff_category, 40),
            ('janitor', 'Janitor', support_staff_category, 50),
            ('admission_officer', 'Admission Officer', support_staff_category, 60),
            ('front_desk', 'Front Desk', support_staff_category, 70),
            ('student_affairs', 'Student Affairs', support_staff_category, 80),
            ('nurse', 'Nurse', support_staff_category, 90),
            ('hr', 'HR', support_staff_category, 100),
            ('accountant', 'Accountant', support_staff_category, 110),
            ('finance_officer', 'Finance Officer', support_staff_category, 120),
        ]

        positions = {}
        for key, title, category, display_order in staff_specs:
            position = self.env['school.staff.positions'].search([
                ('school_id', '=', school.id),
                ('title', '=ilike', title),
            ], limit=1)
            if not position:
                position = self.env['school.staff.positions'].create({
                    'school_id': school.id,
                    'staff_category_id': category.id,
                    'title': title,
                    'display_order': display_order,
                })
            else:
                position.write({'staff_category_id': category.id})
            positions[key] = position

        teacher_parameter = 1.0
        if self.subject_hours_per_class > 0 and self.teaching_load_hours > 0:
            teacher_parameter = self.teaching_load_hours / self.subject_hours_per_class
        teacher_parameter = max(float(teacher_parameter), 0.01)

        staffing_specs = [
            ('teacher', 'per_class', teacher_parameter, 10),
            ('principal', 'fixed', max(float(self.principal_fixed_count or 0), 0.0), 20),
            ('assistant_principal', 'per_student', self._safe_divisor(self.assistant_principal_per_students, 250.0), 30),
            ('it', 'fixed', max(float(self.it_fixed_count or 0), 0.0), 40),
            ('janitor', 'per_student', self._safe_divisor(self.janitor_per_students, 100.0), 50),
            ('admission_officer', 'fixed', max(float(self.admission_officer_fixed_count or 0), 0.0), 60),
            ('front_desk', 'fixed', max(float(self.front_desk_fixed_count or 0), 0.0), 70),
            ('student_affairs', 'fixed', max(float(self.student_affairs_fixed_count or 0), 0.0), 80),
            ('nurse', 'fixed', max(float(self.nurse_fixed_count or 0), 0.0), 90),
            ('hr', 'fixed', max(float(self.hr_fixed_count or 0), 0.0), 100),
            ('accountant', 'fixed', max(float(self.accountant_fixed_count or 0), 0.0), 110),
            ('finance_officer', 'fixed', max(float(self.finance_officer_fixed_count or 0), 0.0), 120),
        ]

        for key, method, parameter_value, display_order in staffing_specs:
            position = positions[key]
            staffing_rule = self.env['school.staffing.rules'].search([
                ('school_id', '=', school.id),
                ('staff_position_id', '=', position.id),
            ], order='display_order asc, id asc', limit=1)
            values = {
                'school_id': school.id,
                'staff_position_id': position.id,
                'display_order': display_order,
                'calculation_method': method,
                'parameter_value': parameter_value,
            }
            if staffing_rule:
                staffing_rule.write(values)
            else:
                self.env['school.staffing.rules'].create(values)
        return expense_item, positions

    def _line_staff_count_map(self, line):
        return {
            'teacher': max(int(line.teacher_count or 0), 0),
            'principal': max(int(line.principal_count or 0), 0),
            'assistant_principal': max(int(line.assistant_principal_count or 0), 0),
            'it': max(int(line.it_count or 0), 0),
            'janitor': max(int(line.janitor_count or 0), 0),
            'admission_officer': max(int(line.admission_officer_count or 0), 0),
            'front_desk': max(int(line.front_desk_count or 0), 0),
            'student_affairs': max(int(line.student_affairs_count or 0), 0),
            'nurse': max(int(line.nurse_count or 0), 0),
            'hr': max(int(line.hr_count or 0), 0),
            'accountant': max(int(line.accountant_count or 0), 0),
            'finance_officer': max(int(line.finance_officer_count or 0), 0),
        }

    def _ensure_academic_years(self, forecast_years=3):
        self.ensure_one()
        school = self.school_id
        existing_years = self.env['school.academic.years'].search([
            ('school_id', '=', school.id),
        ], order='academic_year_name asc, id asc')
        if len(existing_years) >= forecast_years:
            return existing_years[:forecast_years]

        current_year = fields.Date.today().year
        while len(existing_years) < forecast_years:
            year_start = current_year + len(existing_years)
            label = f'{year_start}-{year_start + 1}'
            year_record = self.env['school.academic.years'].search([
                ('school_id', '=', school.id),
                ('academic_year_name', '=', label),
            ], limit=1)
            if not year_record:
                year_record = self.env['school.academic.years'].create({
                    'school_id': school.id,
                    'academic_year_name': label,
                    'start_date': f'{year_start}-09-01',
                    'end_date': f'{year_start + 1}-06-30',
                })
            existing_years |= year_record
        return existing_years.sorted(key=lambda year: (year.academic_year_name or '', year.id))[:forecast_years]

    def _distribute_students(self, levels, total_students):
        total_students = max(int(total_students), 0)
        if not levels:
            return {}
        base_value = total_students // len(levels)
        remainder = total_students % len(levels)
        distribution = {}
        for index, level in enumerate(levels):
            distribution[level.id] = base_value + (1 if index < remainder else 0)
        return distribution

    def action_apply(self):
        self.ensure_one()
        if self.forecast_years <= 0:
            raise ValidationError('Years ahead to predict must be greater than zero.')
        if self.income_tax_percent < 0:
            raise ValidationError('Income tax percentage cannot be negative.')
        if self.max_students_per_class_input <= 0:
            raise ValidationError('Max students per class must be greater than zero.')
        if self.teaching_load_hours <= 0:
            raise ValidationError('Teaching load per teacher must be greater than zero.')

        manual_lines = self.line_ids.sorted('year_index')
        if len(manual_lines) < self.forecast_years:
            raise ValidationError('Please provide manual year rows for all forecast years.')

        selected_lines = manual_lines[:self.forecast_years]
        salary_lines = self.salary_line_ids
        year_salary_lines = self.year_salary_line_ids
        for line in selected_lines:
            if line.student_count <= 0:
                raise ValidationError('Each year must have student count greater than zero.')
            if line.annual_fee_per_student <= 0:
                raise ValidationError('Each year must have annual fee per student greater than zero.')

        for line in year_salary_lines:
            if line.months_paid < 0:
                raise ValidationError('Months paid cannot be negative.')
            if line.bonus < 0:
                raise ValidationError('Bonus cannot be negative.')
            for field_name in self._salary_role_field_map().values():
                if getattr(line, field_name) < 0:
                    raise ValidationError('Monthly salary cannot be negative.')

        scenario = self._default_scenario()
        if not scenario:
            raise ValidationError('No prediction scenario preset found. Please load prediction preset data first.')

        levels = self._ensure_grade_structure()
        if not levels:
            raise ValidationError('No grade levels available for this school after setup.')

        subjects = self._ensure_subjects()
        if not subjects:
            raise ValidationError('Please configure at least one subject from Subject Configuration first.')

        self.subject_hours_per_class = self._subject_hours_per_class_from_subjects()
        tax_rule = self._ensure_income_tax_rule()
        fee_types = self._ensure_fee_types(tax_rule)
        expense_item, staff_positions = self._ensure_operating_models()
        years = self._ensure_academic_years(forecast_years=self.forecast_years)

        levels.write({'max_students_per_class_override': self.max_students_per_class_input})

        shares = [scenario.tuition_share, scenario.admission_share, scenario.activity_share]
        share_total = sum(shares)
        if share_total <= 0:
            shares = [0.8, 0.1, 0.1]
            share_total = 1.0
        shares = [share / share_total for share in shares]

        operating_ratio = (scenario.operating_expense_ratio or 0.0) / 100.0
        salary_ratio = (scenario.salary_ratio or 0.0) / 100.0
        salary_line_map = {
            line.year_index: line
            for line in year_salary_lines
        }
        role_field_map = self._salary_role_field_map()

        for year_index, academic_year in enumerate(years):
            year_input = selected_lines[year_index]
            total_students = max(int(year_input.student_count), 1)
            annual_fee_per_student = float(year_input.annual_fee_per_student)
            students_by_level = self._distribute_students(levels, total_students)

            self._ensure_subject_distribution(academic_year, levels, subjects)

            for level in levels:
                student_count = students_by_level.get(level.id, 0)
                self._upsert(
                    'school.grade.enrollment',
                    [
                        ('academic_year_id', '=', academic_year.id),
                        ('grade_level_id', '=', level.id),
                    ],
                    {
                        'academic_year_id': academic_year.id,
                        'grade_level_id': level.id,
                        'student_count': student_count,
                    },
                )

                for fee_type, share in zip(fee_types, shares):
                    self._upsert(
                        'school.fee.values',
                        [
                            ('academic_year_id', '=', academic_year.id),
                            ('grade_level_id', '=', level.id),
                            ('fee_type_id', '=', fee_type.id),
                        ],
                        {
                            'academic_year_id': academic_year.id,
                            'grade_level_id': level.id,
                            'fee_type_id': fee_type.id,
                            'amount': annual_fee_per_student * share,
                        },
                    )

            gross_revenue = total_students * annual_fee_per_student
            operating_budget = gross_revenue * operating_ratio
            salary_budget = gross_revenue * salary_ratio

            self._upsert(
                'school.expense.values',
                [
                    ('academic_year_id', '=', academic_year.id),
                    ('expense_item_id', '=', expense_item.id),
                ],
                {
                    'academic_year_id': academic_year.id,
                    'expense_item_id': expense_item.id,
                    'amount': operating_budget,
                },
            )

            staff_counts = self._line_staff_count_map(year_input)
            total_staff_count = max(sum(staff_counts.values()), 1)
            fallback_monthly_salary = salary_budget / (total_staff_count * 12.0) if salary_budget > 0 else 0.0

            for position_key, count in staff_counts.items():
                staff_position = staff_positions[position_key]
                salary_line = salary_line_map.get(year_input.year_index)
                monthly_salary = fallback_monthly_salary
                if salary_line:
                    monthly_salary = getattr(salary_line, role_field_map[position_key])
                months_paid = salary_line.months_paid if salary_line else 12
                bonus = salary_line.bonus if salary_line else 0.0

                self._upsert(
                    'school.staffing.overrides',
                    [
                        ('academic_year_id', '=', academic_year.id),
                        ('staff_position_id', '=', staff_position.id),
                    ],
                    {
                        'academic_year_id': academic_year.id,
                        'staff_position_id': staff_position.id,
                        'employee_count': count,
                    },
                )

                self._upsert(
                    'school.employment.salaries',
                    [
                        ('academic_year_id', '=', academic_year.id),
                        ('staff_position_id', '=', staff_position.id),
                    ],
                    {
                        'academic_year_id': academic_year.id,
                        'staff_position_id': staff_position.id,
                        'monthly_salary': monthly_salary,
                        'months_paid': months_paid,
                        'bonus': bonus,
                    },
                )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Prediction setup complete',
                'message': f'School baseline was generated from manual Students and Fees for {self.forecast_years} academic years with income tax {self.income_tax_percent:g}%.',
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SchoolAcademicYears(models.Model):
    _name = 'school.academic.years'
    _description = 'Academic Years (Master Anchor)'
    _rec_name = 'academic_year_name'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    academic_year_name = fields.Char(string='Academic Year Name', required=True, size=50)
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    fee_gross_total = fields.Float(string='Gross Revenue', compute='_compute_financial_summary', readonly=True, store=False)
    tax_deductions_total = fields.Float(string='Tax Deductions', compute='_compute_financial_summary', readonly=True, store=False)
    fee_total = fields.Float(string='Fee Revenue', compute='_compute_financial_summary', readonly=True, store=False)
    expense_total = fields.Float(string='Expense Total', compute='_compute_financial_summary', readonly=True, store=False)
    salary_total = fields.Float(string='Salary Total', compute='_compute_financial_summary', readonly=True, store=False)
    new_rooms_expense_total = fields.Float(string='New Rooms Equipment Expense', compute='_compute_financial_summary', readonly=True, store=False)
    operating_cost_total = fields.Float(string='Operating Cost Total', compute='_compute_financial_summary', readonly=True, store=False)
    startup_cost_total = fields.Float(string='Startup Cost Total', compute='_compute_financial_summary', readonly=True, store=False)
    total_deductions = fields.Float(string='Total Deductions', compute='_compute_financial_summary', readonly=True, store=False)
    operating_profit = fields.Float(string='Operating Profit', compute='_compute_financial_summary', readonly=True, store=False)
    net_budget = fields.Float(string='Net Budget', compute='_compute_financial_summary', readonly=True, store=False)
    net_margin_pct = fields.Float(string='Net Margin %', compute='_compute_financial_summary', readonly=True, store=False)
    deductions_pct = fields.Float(string='Deductions %', compute='_compute_financial_summary', readonly=True, store=False)
    tax_pct = fields.Float(string='Tax %', compute='_compute_financial_summary', readonly=True, store=False)
    total_enrolled_students = fields.Integer(string='Total Enrolled Students', compute='_compute_financial_summary', readonly=True, store=False)
    revenue_per_student_avg = fields.Float(string='Average Revenue Per Student', compute='_compute_financial_summary', readonly=True, store=False)
    cost_per_student_avg = fields.Float(string='Average Cost Per Student', compute='_compute_financial_summary', readonly=True, store=False)
    revenue_per_student_grade_level_avg = fields.Float(string='Revenue Per Student by Grade Level', compute='_compute_financial_summary', readonly=True, store=False)
    cost_per_student_grade_level_avg = fields.Float(string='Cost Per Student by Grade Level', compute='_compute_financial_summary', readonly=True, store=False)
    revenue_per_student_grade_group_avg = fields.Float(string='Revenue Per Student by Grade Group', compute='_compute_financial_summary', readonly=True, store=False)
    cost_per_student_grade_group_avg = fields.Float(string='Cost Per Student by Grade Group', compute='_compute_financial_summary', readonly=True, store=False)
    enrollment_ids = fields.One2many('school.grade.enrollment', 'academic_year_id', string='Grade Metrics', readonly=True)

    @api.depends('school_id', 'start_date', 'end_date')
    def _compute_financial_summary(self):
        for record in self:
            enrollments = self.env['school.grade.enrollment'].search([('academic_year_id', '=', record.id)])
            fee_rows = self.env['school.fee.values'].search([('academic_year_id', '=', record.id)])
            expense_rows = self.env['school.expense.values'].search([('academic_year_id', '=', record.id)])
            salary_rows = self.env['school.employment.salaries'].search([('academic_year_id', '=', record.id)])
            room_plan_rows = self.env['school.room.plan'].search([('academic_year_id', '=', record.id)])
            asset_price_rows = self.env['school.asset.prices'].search([('academic_year_id', '=', record.id)])

            student_total = sum(row.student_count for row in enrollments)

            record.fee_gross_total = sum(row.gross_revenue_amount for row in fee_rows)
            record.tax_deductions_total = sum(row.tax_amount for row in fee_rows)
            record.fee_total = sum(row.revenue_amount for row in fee_rows)
            record.expense_total = sum(row.amount for row in expense_rows)
            record.salary_total = sum(row.annual_cost for row in salary_rows)
            record.new_rooms_expense_total = sum(row.new_rooms_asset_cost for row in room_plan_rows)
            record.operating_cost_total = record.expense_total + record.salary_total + record.new_rooms_expense_total
            record.startup_cost_total = sum(row.startup_cost for row in asset_price_rows)
            record.total_deductions = record.tax_deductions_total + record.operating_cost_total
            record.operating_profit = record.fee_total - record.operating_cost_total
            record.net_budget = record.operating_profit - record.startup_cost_total

            revenue_by_grade_level = {}
            students_by_grade_level = {}
            for enrollment in enrollments:
                level_id = enrollment.grade_level_id.id
                students_by_grade_level[level_id] = enrollment.student_count
                revenue_by_grade_level[level_id] = sum(
                    row.revenue_amount for row in fee_rows
                    if row.grade_level_id.id == level_id
                )

            grade_level_revenue_per_student = []
            grade_level_cost_per_student = []
            grade_group_revenue_per_student = {}
            grade_group_cost_per_student = {}
            cost_per_student_base = record.total_deductions / student_total if student_total else 0.0

            for enrollment in enrollments:
                level_id = enrollment.grade_level_id.id
                students = students_by_grade_level.get(level_id, 0)
                revenue_per_student = revenue_by_grade_level.get(level_id, 0.0) / students if students else 0.0

                grade_level_revenue_per_student.append(revenue_per_student)
                grade_level_cost_per_student.append(cost_per_student_base)

                group = enrollment.grade_level_id.group_id
                if group:
                    group_id = group.id
                    grade_group_revenue_per_student.setdefault(group_id, []).append(revenue_per_student)
                    grade_group_cost_per_student.setdefault(group_id, []).append(cost_per_student_base)

            record.total_enrolled_students = student_total
            record.revenue_per_student_avg = record.fee_total / student_total if student_total else 0.0
            record.cost_per_student_avg = record.total_deductions / student_total if student_total else 0.0
            record.revenue_per_student_grade_level_avg = sum(grade_level_revenue_per_student) / len(grade_level_revenue_per_student) if grade_level_revenue_per_student else 0.0
            record.cost_per_student_grade_level_avg = sum(grade_level_cost_per_student) / len(grade_level_cost_per_student) if grade_level_cost_per_student else 0.0
            record.revenue_per_student_grade_group_avg = (
                sum(sum(values) / len(values) for values in grade_group_revenue_per_student.values()) / len(grade_group_revenue_per_student)
                if grade_group_revenue_per_student else 0.0
            )
            record.cost_per_student_grade_group_avg = (
                sum(sum(values) / len(values) for values in grade_group_cost_per_student.values()) / len(grade_group_cost_per_student)
                if grade_group_cost_per_student else 0.0
            )

            if record.fee_gross_total:
                record.net_margin_pct = (record.net_budget / record.fee_gross_total) * 100.0
                record.deductions_pct = (record.total_deductions / record.fee_gross_total) * 100.0
                record.tax_pct = (record.tax_deductions_total / record.fee_gross_total) * 100.0
            else:
                record.net_margin_pct = 0.0
                record.deductions_pct = 0.0
                record.tax_pct = 0.0

    def action_open_deductions_pie(self):
        self.ensure_one()
        action = self.env.ref('school_planning.action_school_expense_values_pie_chart').read()[0]
        action['domain'] = [('academic_year_id', '=', self.id)]
        action['context'] = {'default_academic_year_id': self.id}
        return action

    def action_open_revenue_chart(self):
        self.ensure_one()
        action = self.env.ref('school_planning.action_school_fee_values_revenue_chart').read()[0]
        action['domain'] = [('academic_year_id', '=', self.id)]
        action['context'] = {'default_academic_year_id': self.id}
        return action

    def action_open_grade_metrics(self):
        self.ensure_one()
        action = self.env.ref('school_planning.action_school_grade_enrollment').read()[0]
        action['domain'] = [('academic_year_id', '=', self.id)]
        action['view_mode'] = 'list,pivot,graph,form'
        action['context'] = {'group_by': 'grade_group_id', 'default_academic_year_id': self.id}
        return action

    def action_print_financial_summary_pdf(self):
        records = self
        if not records:
            active_ids = self.env.context.get('active_ids') or []
            records = self.browse(active_ids)
        if not records:
            return False

        if shutil.which('wkhtmltopdf'):
            report = self.env.ref('school_planning.action_report_school_financial_summary_pdf')
            return report.with_context(discard_logo_check=True).report_action(records)

        ids_param = ','.join(str(record_id) for record_id in records.ids)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/school_planning/financial-summary/pdf?ids={ids_param}',
            'target': 'self',
        }

    def action_open_financial_summary_email_wizard(self):
        records = self
        if not records:
            active_ids = self.env.context.get('active_ids') or []
            records = self.browse(active_ids)
        records = records.exists()
        if not records:
            return False

        schools = records.mapped('school_id')
        if len(schools) > 1:
            raise ValidationError('Please select academic years from a single school.')

        school = schools[:1]
        records = records.filtered(lambda year: year.school_id == school)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Financial Summary PDF',
            'res_model': 'school.financial.summary.email.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_academic_year_ids': [fields.Command.set(records.ids)],
                'default_school_id': school.id,
                'default_subject': 'Financial Summary Report',
            },
        }

    def _build_financial_summary_pdf_bytes(self):
        years = self.sorted(key=lambda y: (y.start_date or '', y.academic_year_name or '', y.id))
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        page_width, page_height = A4

        for year_idx, year in enumerate(years):
            y = page_height - 50

            def draw_line(label, value):
                nonlocal y
                pdf.setFont('Helvetica-Bold', 10)
                pdf.drawString(40, y, label)
                pdf.setFont('Helvetica', 10)
                pdf.drawRightString(page_width - 40, y, value)
                y -= 16

            def fmt_money(amount, currency):
                return f"{currency} {float(amount or 0.0):,.2f}"

            school_name = year.school_id.name or '-'
            currency = year.school_id.currency or ''

            pdf.setFont('Helvetica-Bold', 16)
            pdf.drawString(40, y, 'Financial Summary')
            y -= 24

            pdf.setFont('Helvetica', 11)
            pdf.drawString(40, y, f'School: {school_name}')
            y -= 16
            pdf.drawString(40, y, f'Academic Year: {year.academic_year_name or "-"}')
            y -= 16
            pdf.drawString(40, y, f'Period: {year.start_date or "-"} - {year.end_date or "-"}')
            y -= 24

            pdf.setFont('Helvetica-Bold', 12)
            pdf.drawString(40, y, 'Core Financial Metrics')
            y -= 18

            draw_line('Gross Revenue', fmt_money(year.fee_gross_total, currency))
            draw_line('Tax Deductions', fmt_money(year.tax_deductions_total, currency))
            draw_line('Net Revenue After Tax', fmt_money(year.fee_total, currency))
            draw_line('Operating Expenses', fmt_money(year.expense_total, currency))
            draw_line('Salaries', fmt_money(year.salary_total, currency))
            draw_line('New Rooms Equipment Expense', fmt_money(year.new_rooms_expense_total, currency))
            draw_line('Operating Cost Total', fmt_money(year.operating_cost_total, currency))
            draw_line('Startup Cost Total', fmt_money(year.startup_cost_total, currency))
            draw_line('Total Deductions', fmt_money(year.total_deductions, currency))
            draw_line('Operating Profit', fmt_money(year.operating_profit, currency))
            draw_line('Net Budget', fmt_money(year.net_budget, currency))
            draw_line('Net Margin %', f"{float(year.net_margin_pct or 0.0):.2f}%")

            y -= 8
            pdf.setFont('Helvetica-Bold', 12)
            pdf.drawString(40, y, 'Enrollment and Unit Economics')
            y -= 18

            draw_line('Total Enrolled Students', f"{int(year.total_enrolled_students or 0)}")
            draw_line('Average Revenue Per Student', fmt_money(year.revenue_per_student_avg, currency))
            draw_line('Average Cost Per Student', fmt_money(year.cost_per_student_avg, currency))
            draw_line('Revenue Per Student by Grade Level (Avg)', fmt_money(year.revenue_per_student_grade_level_avg, currency))
            draw_line('Cost Per Student by Grade Level (Avg)', fmt_money(year.cost_per_student_grade_level_avg, currency))
            draw_line('Revenue Per Student by Grade Group (Avg)', fmt_money(year.revenue_per_student_grade_group_avg, currency))
            draw_line('Cost Per Student by Grade Group (Avg)', fmt_money(year.cost_per_student_grade_group_avg, currency))

            y -= 8
            pdf.setFont('Helvetica-Bold', 12)
            pdf.drawString(40, y, 'Revenue and Cost by Grade Level')
            y -= 18

            headers = ['Group', 'Level', 'Students', 'Revenue', 'Rev/Student', 'Cost', 'Cost/Student']
            x_positions = [40, 130, 230, 300, 390, 470, 545]
            pdf.setFont('Helvetica-Bold', 9)
            for idx, header in enumerate(headers):
                if idx >= 2:
                    pdf.drawRightString(x_positions[idx], y, header)
                else:
                    pdf.drawString(x_positions[idx], y, header)
            y -= 14

            pdf.setFont('Helvetica', 8)
            for line in year.enrollment_ids:
                if y < 60:
                    pdf.showPage()
                    y = page_height - 50
                    pdf.setFont('Helvetica-Bold', 10)
                    pdf.drawString(40, y, f'Continued: {year.academic_year_name or "-"}')
                    y -= 18
                    pdf.setFont('Helvetica-Bold', 9)
                    for idx, header in enumerate(headers):
                        if idx >= 2:
                            pdf.drawRightString(x_positions[idx], y, header)
                        else:
                            pdf.drawString(x_positions[idx], y, header)
                    y -= 14
                    pdf.setFont('Helvetica', 8)

                pdf.drawString(x_positions[0], y, line.grade_group_id.name or '')
                pdf.drawString(x_positions[1], y, line.grade_level_id.name or '')
                pdf.drawRightString(x_positions[2], y, str(int(line.student_count or 0)))
                pdf.drawRightString(x_positions[3], y, f"{float(line.revenue_total or 0.0):,.2f}")
                pdf.drawRightString(x_positions[4], y, f"{float(line.revenue_per_student or 0.0):,.2f}")
                pdf.drawRightString(x_positions[5], y, f"{float(line.cost_total or 0.0):,.2f}")
                pdf.drawRightString(x_positions[6], y, f"{float(line.cost_per_student or 0.0):,.2f}")
                y -= 12

            if year_idx < len(years) - 1:
                pdf.showPage()

        pdf.save()
        data = buffer.getvalue()
        buffer.close()
        return data


class SchoolFinancialSummaryEmailWizard(models.TransientModel):
    _name = 'school.financial.summary.email.wizard'
    _description = 'Send Financial Summary PDF by Email'

    school_id = fields.Many2one('school.schools', string='School', readonly=True)
    academic_year_ids = fields.Many2many(
        'school.academic.years',
        string='Academic Years',
        required=True,
        domain="[('school_id', '=', school_id)]",
    )
    mail_server_id = fields.Many2one(
        'ir.mail_server',
        string='Gmail Outgoing Server',
        required=True,
        domain=['|', ('smtp_authentication', '=', 'gmail'), ('smtp_host', 'ilike', 'smtp.gmail.com')],
        default=lambda self: self.env['ir.mail_server'].search([
            '|', ('smtp_authentication', '=', 'gmail'), ('smtp_host', 'ilike', 'smtp.gmail.com')
        ], limit=1),
        help='Select an outgoing Gmail mail server (OAuth or SMTP login).',
    )
    email_to = fields.Char(string='Recipient Emails', required=True, help='Comma-separated email addresses.')
    subject = fields.Char(string='Subject', required=True, default='Financial Summary Report')
    body_html = fields.Html(
        string='Email Body',
        required=True,
        default='<p>Hello,</p><p>Please find attached the Financial Summary PDF.</p><p>Best regards,</p>',
    )

    @api.constrains('school_id', 'academic_year_ids')
    def _check_academic_years_same_school(self):
        for wizard in self:
            if wizard.school_id and any(year.school_id != wizard.school_id for year in wizard.academic_year_ids):
                raise ValidationError('Selected academic years must belong to the same school as this report.')

    def action_send_email(self):
        self.ensure_one()
        years = self.academic_year_ids.sorted(key=lambda y: (y.start_date or '', y.academic_year_name or '', y.id))
        if not years:
            raise ValidationError('Please select at least one academic year.')
        if not self.mail_server_id:
            raise ValidationError('Please configure and select a Gmail outgoing server with a valid token.')

        pdf_bytes = years._build_financial_summary_pdf_bytes()
        filename = 'financial_summary_multi_year.pdf' if len(years) > 1 else f'financial_summary_{years[0].academic_year_name}.pdf'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(pdf_bytes),
            'mimetype': 'application/pdf',
            'res_model': 'school.academic.years',
            'res_id': years[0].id,
        })

        mail_values = {
            'subject': self.subject,
            'body_html': self.body_html,
            'email_to': self.email_to,
            'mail_server_id': self.mail_server_id.id,
            'attachment_ids': [(6, 0, [attachment.id])],
        }
        mail = self.env['mail.mail'].create(mail_values)
        mail.send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Email sent',
                'message': 'Financial summary PDF has been emailed successfully.',
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.constrains('school_id', 'academic_year_name')
    def _check_unique_academic_year(self):
        for record in self:
            domain = [
                ('school_id', '=', record.school_id.id),
                ('academic_year_name', '=', record.academic_year_name),
                ('id', '!=', record.id)
            ]
            if self.search_count(domain) > 0:
                raise ValidationError('The academic year name must be unique per school.')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env['school.financial.report']._refresh_for_academic_years(records.ids)
        return records

    def write(self, vals):
        result = super().write(vals)
        self.env['school.financial.report']._refresh_for_academic_years(self.ids)
        return result


class SchoolGradeGroups(models.Model):
    _name = 'school.grade.groups'
    _description = 'Grade Groups (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    name = fields.Char(string='Name', required=True, size=100)
    display_order = fields.Integer(string='Display Order', required=True)


class SchoolGradeLevels(models.Model):
    _name = 'school.grade.levels'
    _description = 'Grade Levels (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    group_id = fields.Many2one('school.grade.groups', string='Grade Group', required=True, ondelete='cascade')
    max_students_per_class_override = fields.Integer(
        string='Max Students Override',
        help='Optional per-grade-level override. When set (> 0), it overrides the classroom default only for this grade level.',
    )
    max_students_per_class = fields.Integer(
        string='Max Students Per Class',
        compute='_compute_max_students_per_class',
        store=True,
    )
    name = fields.Char(string='Name', required=True, size=100)
    sort_order = fields.Integer(string='Sort Order', required=True)

    @api.depends('max_students_per_class_override', 'school_id')
    def _compute_max_students_per_class(self):
        for record in self:
            classroom_default = 0
            if record.school_id:
                classroom_room_type = self.env['school.room.types'].search([
                    ('school_id', '=', record.school_id.id),
                    ('name', 'ilike', 'Classroom'),
                ], order='display_order asc, id asc', limit=1)
                classroom_default = int(classroom_room_type.max_students_per_class_default or 0)
            record.max_students_per_class = (
                record.max_students_per_class_override
                or classroom_default
            )


class SchoolSubjects(models.Model):
    _name = 'school.subjects'
    _description = 'Subjects (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    name = fields.Char(string='Name', required=True, size=100)
    display_order = fields.Integer(string='Display Order', required=True)


class SchoolTaxRules(models.Model):
    _name = 'school.tax.rules'
    _description = 'Shared Tax Rules (Master Data)'
    _order = 'name asc, percentage asc, id asc'

    school_id = fields.Many2one(
        'school.schools',
        string='Legacy School',
        ondelete='set null',
        help='Deprecated compatibility field. Tax rules are shared by all schools.',
    )
    name = fields.Char(string='Name', required=True, size=100)
    percentage = fields.Float(string='Percentage', required=True)

    @api.depends('name', 'percentage')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.name} ({record.percentage * 100:g}%)'

    @api.constrains('name', 'percentage')
    def _check_unique_shared_rule(self):
        for record in self:
            normalized_name = (record.name or '').strip()
            duplicate = self.search([
                ('id', '!=', record.id),
                ('name', '=ilike', normalized_name),
                ('percentage', '=', record.percentage),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    f'The shared tax rule {record.display_name} already exists.'
                )


class SchoolFeeTypes(models.Model):
    _name = 'school.fee.types'
    _description = 'Fee Types (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    name = fields.Char(string='Name', required=True, size=100)
    display_order = fields.Integer(string='Display Order', required=True)
    is_taxable = fields.Boolean(string='Is Taxable', default=False, required=True)
    tax_rule_id = fields.Many2one(
        'school.tax.rules',
        string='Tax Rule',
        ondelete='set null',
        domain=[('school_id', '=', False)],
    )


class SchoolExpenseCategories(models.Model):
    _name = 'school.expense.categories'
    _description = 'Expense Categories (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    name = fields.Char(string='Name', required=True, size=100)
    display_order = fields.Integer(string='Display Order', required=True)

    @api.model
    def _school_domain_from_context(self):
        school_id = _extract_school_id_from_context(self.env)
        return [('school_id', '=', school_id)] if school_id else []

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        def _coerce_id(value):
            if isinstance(value, int):
                return value if value > 0 else False
            if isinstance(value, str) and value.isdigit():
                parsed = int(value)
                return parsed if parsed > 0 else False
            if isinstance(value, dict):
                return _coerce_id(value.get('id'))
            if isinstance(value, (list, tuple)) and value:
                return _coerce_id(value[0])
            return False

        domain = list(domain or [])
        has_school_clause = False
        normalized_domain = []
        for token in domain:
            if not isinstance(token, (list, tuple)) or len(token) < 3:
                normalized_domain.append(token)
                continue
            field_name, op, value = token[0], token[1], token[2]
            if field_name != 'school_id':
                normalized_domain.append(token)
                continue
            has_school_clause = True
            if op == '=':
                coerced = _coerce_id(value)
                normalized_domain.append((field_name, op, coerced or 0))
            elif op == 'in' and isinstance(value, (list, tuple)):
                coerced_values = [coerced for coerced in (_coerce_id(v) for v in value) if coerced]
                normalized_domain.append((field_name, op, coerced_values or [0]))
            else:
                normalized_domain.append(token)

        if not has_school_clause:
            normalized_domain += self._school_domain_from_context()

        domain = normalized_domain
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)


class SchoolExpenseItems(models.Model):
    _name = 'school.expense.items'
    _description = 'Expense Items (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    expense_category_id = fields.Many2one(
        'school.expense.categories',
        string='Expense Category',
        required=True,
        ondelete='cascade',
        domain="[('school_id', '=', school_id.id)]",
    )
    name = fields.Char(string='Name', required=True, size=100)
    display_order = fields.Integer(string='Display Order', required=True)

    @api.onchange('school_id')
    def _onchange_school_id(self):
        domain = [('school_id', '=', self.school_id.id)] if self.school_id else []
        if self.expense_category_id and self.expense_category_id.school_id != self.school_id:
            self.expense_category_id = False
        return {'domain': {'expense_category_id': domain}}


class SchoolStaffCategories(models.Model):
    _name = 'school.staff.categories'
    _description = 'Staff Categories (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    name = fields.Char(string='Name', size=100)
    display_order = fields.Integer(string='Display Order', required=True)


class SchoolStaffPositions(models.Model):
    _name = 'school.staff.positions'
    _description = 'Staff Positions (Master Data)'
    _rec_name = 'title'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    staff_category_id = fields.Many2one('school.staff.categories', string='Staff Category', required=True, ondelete='cascade')
    title = fields.Char(string='Title', required=True, size=100)
    display_order = fields.Integer(string='Display Order', required=True)


class SchoolStaffingRules(models.Model):
    _name = 'school.staffing.rules'
    _description = 'Staffing Rules (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    staff_position_id = fields.Many2one('school.staff.positions', string='Staff Position', required=True, ondelete='cascade')
    display_order = fields.Integer(string='Display Order', required=True, default=10)
    calculation_method = fields.Selection([
        ('fixed', 'Fixed'),
        ('per_grade', 'Per Grade'),
        ('per_class', 'Per Class'),
        ('per_student', 'Per Student'),
        ('per_room', 'Per Room'),
        ('per_subject_hours', 'Per Subject Hours')
    ], string='Calculation Method', required=True, default='fixed')
    parameter_value = fields.Float(string='Parameter Value', required=True, default=1.0)


class SchoolStaffingOverrides(models.Model):
    _name = 'school.staffing.overrides'
    _description = 'Staffing Overrides (Year Data)'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    staff_position_id = fields.Many2one('school.staff.positions', string='Staff Position', required=True, ondelete='cascade')
    employee_count = fields.Integer(string='Employee Count (Override)', required=True, default=0)

    @api.constrains('academic_year_id', 'staff_position_id')
    def _check_unique_year_position(self):
        for record in self:
            duplicate = self.search([
                ('id', '!=', record.id),
                ('academic_year_id', '=', record.academic_year_id.id),
                ('staff_position_id', '=', record.staff_position_id.id),
            ], limit=1)
            if duplicate:
                raise ValidationError('Only one staffing override is allowed per academic year and staff position.')


class SchoolRoomTypes(models.Model):
    _name = 'school.room.types'
    _description = 'Room Types (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    name = fields.Char(string='Name', required=True, size=100)
    max_students_per_class_default = fields.Integer(
        string='Default Max Students Per Class',
        required=True,
        default=25,
    )
    display_order = fields.Integer(string='Display Order', required=True)


class SchoolAssetItems(models.Model):
    _name = 'school.asset.items'
    _description = 'Asset Items (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    name = fields.Char(string='Name', required=True, size=150)
    asset_type = fields.Selection([
        ('fixed', 'Fixed'),
        ('consumable', 'Consumable'),
    ], string='Asset Type', required=True, default='fixed')
    unit_of_measure = fields.Char(string='Unit of Measure', size=30)
    display_order = fields.Integer(string='Display Order', required=True)


class SchoolRoomTemplates(models.Model):
    _name = 'school.room.templates'
    _description = 'Room Templates (Master Data)'

    school_id = fields.Many2one(
        'school.schools',
        string='School',
        required=True,
        ondelete='cascade',
        default=lambda self: _extract_school_id_from_context(self.env),
    )
    room_type_id = fields.Many2one('school.room.types', string='Room Type', required=True, ondelete='cascade')
    name = fields.Char(string='Name', required=True, size=150)
    display_order = fields.Integer(string='Display Order', required=True)


class SchoolRoomTemplateItems(models.Model):
    _name = 'school.room.template.items'
    _description = 'Room Template Items (Master Data)'

    room_template_id = fields.Many2one('school.room.templates', string='Room Template', required=True, ondelete='cascade')
    asset_item_id = fields.Many2one('school.asset.items', string='Asset Item', required=True, ondelete='cascade')
    quantity = fields.Integer(string='Quantity', required=True)


# --- YEAR DATA (Blue Band) & CALCULATED RESULTS (Green Band) ---

class SchoolGradeEnrollment(models.Model):
    _name = 'school.grade.enrollment'
    _description = 'Grade Enrollment & Class Count'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    grade_level_id = fields.Many2one('school.grade.levels', string='Grade Level', required=True, ondelete='cascade')
    grade_group_id = fields.Many2one('school.grade.groups', string='Grade Group', related='grade_level_id.group_id', store=True, readonly=True)
    
    # BLUE TEXT (Inputs)
    student_count = fields.Integer(string='Student Count (Input)', required=True)
    max_students_per_class = fields.Integer(
        string='Max Students Per Class',
        related='grade_level_id.max_students_per_class',
        store=True,
        readonly=True,
    )
    
    # GREEN TEXT (Calculated Result)
    class_count = fields.Integer(string='Class Count (Calculated)', compute='_compute_class_count', store=True)
    revenue_total = fields.Float(string='Revenue Total', compute='_compute_financial_metrics', store=False)
    cost_total = fields.Float(string='Cost Total', compute='_compute_financial_metrics', store=False)
    revenue_per_student = fields.Float(string='Revenue Per Student', compute='_compute_financial_metrics', store=False)
    cost_per_student = fields.Float(string='Cost Per Student', compute='_compute_financial_metrics', store=False)

    @api.depends('student_count', 'max_students_per_class')
    def _compute_class_count(self):
        for record in self:
            if record.max_students_per_class > 0 and record.student_count > 0:
                record.class_count = math.ceil(record.student_count / record.max_students_per_class)
            else:
                record.class_count = 0

        # Recompute room plans affected by the changed enrollments
        academic_year_ids = self.mapped('academic_year_id').ids
        if academic_year_ids:
            room_plans = self.env['school.room.plan'].search([('academic_year_id', 'in', academic_year_ids)])
            room_plans._compute_calculated_new_rooms()
            room_plans._sync_next_year_existing_rooms()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._trigger_downstream_recompute()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._trigger_downstream_recompute()
        return result

    def unlink(self):
        academic_year_ids = self.mapped('academic_year_id').ids
        result = super().unlink()
        if academic_year_ids:
            room_plans = self.env['school.room.plan'].search([('academic_year_id', 'in', academic_year_ids)])
            room_plans._compute_calculated_new_rooms()
            room_plans._sync_next_year_existing_rooms()
            subject_rows = self.env['school.subject.distribution'].search([('academic_year_id', 'in', academic_year_ids)])
            if subject_rows:
                subject_rows._compute_teaching_hours()
            fee_rows = self.env['school.fee.values'].search([('academic_year_id', 'in', academic_year_ids)])
            if fee_rows:
                fee_rows._compute_revenue_metrics()
            self.env['school.financial.report']._refresh_for_academic_years(academic_year_ids)
        return result

    def _trigger_downstream_recompute(self):
        academic_year_ids = self.mapped('academic_year_id').ids
        if not academic_year_ids:
            return
        room_plans = self.env['school.room.plan'].search([('academic_year_id', 'in', academic_year_ids)])
        room_plans._compute_calculated_new_rooms()
        room_plans._sync_next_year_existing_rooms()

        subject_rows = self.env['school.subject.distribution'].search([
            ('academic_year_id', 'in', academic_year_ids)
        ])
        if subject_rows:
            subject_rows._compute_teaching_hours()

        fee_rows = self.env['school.fee.values'].search([
            ('academic_year_id', 'in', academic_year_ids)
        ])
        if fee_rows:
            fee_rows._compute_revenue_metrics()

        self.env['school.financial.report']._refresh_for_academic_years(academic_year_ids)

    @api.depends('academic_year_id', 'grade_level_id', 'student_count')
    def _compute_financial_metrics(self):
        for record in self:
            fee_rows = self.env['school.fee.values'].search([
                ('academic_year_id', '=', record.academic_year_id.id),
                ('grade_level_id', '=', record.grade_level_id.id),
            ])
            revenue_total = sum(fee_rows.mapped('revenue_amount'))

            year_fee_rows = self.env['school.fee.values'].search([
                ('academic_year_id', '=', record.academic_year_id.id)
            ])
            year_expense_rows = self.env['school.expense.values'].search([
                ('academic_year_id', '=', record.academic_year_id.id)
            ])
            year_salary_rows = self.env['school.employment.salaries'].search([
                ('academic_year_id', '=', record.academic_year_id.id)
            ])
            year_room_rows = self.env['school.room.plan'].search([
                ('academic_year_id', '=', record.academic_year_id.id)
            ])
            year_enrollments = self.env['school.grade.enrollment'].search([
                ('academic_year_id', '=', record.academic_year_id.id)
            ])

            year_total_students = sum(year_enrollments.mapped('student_count'))
            total_deductions = (
                sum(year_fee_rows.mapped('tax_amount'))
                + sum(year_expense_rows.mapped('amount'))
                + sum(year_salary_rows.mapped('annual_cost'))
                + sum(year_room_rows.mapped('new_rooms_asset_cost'))
            )
            cost_per_student = (total_deductions / year_total_students) if year_total_students else 0.0

            record.revenue_total = revenue_total
            record.revenue_per_student = (revenue_total / record.student_count) if record.student_count else 0.0
            record.cost_per_student = cost_per_student
            record.cost_total = cost_per_student * record.student_count


class SchoolSubjectDistribution(models.Model):
    _name = 'school.subject.distribution'
    _description = 'Subject Distribution & Teaching Load'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    grade_level_id = fields.Many2one('school.grade.levels', string='Grade Level', required=True, ondelete='cascade')
    subject_id = fields.Many2one('school.subjects', string='Subject', required=True, ondelete='cascade')
    
    # BLUE TEXT (Input)
    weekly_hours = fields.Float(string='Weekly Hours (Input)', required=True)
    credits = fields.Float(string='Credits')

    # GREEN TEXT (Calculated Result)
    total_teaching_hours = fields.Float(
        string='Total Teaching Hours (Calculated)',
        compute='_compute_teaching_hours',
        store=True,
        aggregator='sum',
    )

    @api.depends('weekly_hours', 'grade_level_id', 'academic_year_id')
    def _compute_teaching_hours(self):
        for record in self:
            enrollment = self.env['school.grade.enrollment'].search([
                ('academic_year_id', '=', record.academic_year_id.id),
                ('grade_level_id', '=', record.grade_level_id.id)
            ], limit=1)
            classes = enrollment.class_count if enrollment else 0
            record.total_teaching_hours = record.weekly_hours * classes


class SchoolFeeValues(models.Model):
    _name = 'school.fee.values'
    _description = 'Fee Values (Year Data)'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    grade_level_id = fields.Many2one('school.grade.levels', string='Grade Level', required=True, ondelete='cascade')
    fee_type_id = fields.Many2one('school.fee.types', string='Fee Type', required=True, ondelete='cascade')
    amount = fields.Float(string='Amount (Input)', required=True)
    enrolled_students = fields.Integer(string='Enrolled Students', compute='_compute_revenue_metrics', store=True)
    gross_revenue_amount = fields.Float(string='Gross Revenue', compute='_compute_revenue_metrics', store=True, aggregator='sum')
    tax_amount = fields.Float(string='Tax Deduction', compute='_compute_revenue_metrics', store=True, aggregator='sum')
    revenue_amount = fields.Float(string='Revenue (Calculated)', compute='_compute_revenue_metrics', store=True, aggregator='sum')

    @api.depends('academic_year_id', 'grade_level_id', 'amount', 'fee_type_id', 'fee_type_id.is_taxable', 'fee_type_id.tax_rule_id', 'fee_type_id.tax_rule_id.percentage')
    def _compute_revenue_metrics(self):
        for record in self:
            enrollment = self.env['school.grade.enrollment'].search([
                ('academic_year_id', '=', record.academic_year_id.id),
                ('grade_level_id', '=', record.grade_level_id.id)
            ], limit=1)
            students = enrollment.student_count if enrollment else 0
            gross = record.amount * students
            tax_rate = 0.0
            if record.fee_type_id.is_taxable and record.fee_type_id.tax_rule_id:
                tax_rate = (record.fee_type_id.tax_rule_id.percentage or 0.0)
            tax_amount = gross * tax_rate

            record.enrolled_students = students
            record.gross_revenue_amount = gross
            record.tax_amount = tax_amount
            record.revenue_amount = gross - tax_amount

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env['school.financial.report']._refresh_for_academic_years(records.mapped('academic_year_id').ids)
        return records

    def write(self, vals):
        old_year_ids = self.mapped('academic_year_id').ids
        result = super().write(vals)
        self.env['school.financial.report']._refresh_for_academic_years(list(set(old_year_ids) | set(self.mapped('academic_year_id').ids)))
        return result

    def unlink(self):
        academic_year_ids = self.mapped('academic_year_id').ids
        result = super().unlink()
        self.env['school.financial.report']._refresh_for_academic_years(academic_year_ids)
        return result


class SchoolExpenseValues(models.Model):
    _name = 'school.expense.values'
    _description = 'Expense Values (Year Data)'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    expense_item_id = fields.Many2one('school.expense.items', string='Expense Item', required=True, ondelete='cascade')
    amount = fields.Float(string='Amount (Input)', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env['school.financial.report']._refresh_for_academic_years(records.mapped('academic_year_id').ids)
        return records

    def write(self, vals):
        old_year_ids = self.mapped('academic_year_id').ids
        result = super().write(vals)
        self.env['school.financial.report']._refresh_for_academic_years(list(set(old_year_ids) | set(self.mapped('academic_year_id').ids)))
        return result

    def unlink(self):
        academic_year_ids = self.mapped('academic_year_id').ids
        result = super().unlink()
        self.env['school.financial.report']._refresh_for_academic_years(academic_year_ids)
        return result


class SchoolEmploymentSalaries(models.Model):
    _name = 'school.employment.salaries'
    _description = 'Employment Salaries (Year Data)'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    staff_position_id = fields.Many2one('school.staff.positions', string='Staff Position', required=True, ondelete='cascade')
    employee_count = fields.Integer(string='Employee Count', compute='_compute_employee_count', store=False)
    monthly_salary = fields.Float(string='Monthly Salary (Input)', required=True)
    months_paid = fields.Integer(string='Months Paid', default=12)
    bonus = fields.Float(string='Bonus (Input)', default=0)
    annual_cost = fields.Float(string='Annual Cost (Calculated)', compute='_compute_annual_cost', store=False)

    @api.depends('academic_year_id', 'staff_position_id')
    def _compute_employee_count(self):
        for record in self:
            if not record.staff_position_id:
                record.employee_count = 0
                continue

            override = self.env['school.staffing.overrides'].search([
                ('academic_year_id', '=', record.academic_year_id.id),
                ('staff_position_id', '=', record.staff_position_id.id),
            ], limit=1)
            if override:
                record.employee_count = max(int(override.employee_count), 0)
                continue

            school_id = record.staff_position_id.school_id.id
            rule = self.env['school.staffing.rules'].search([
                ('school_id', '=', school_id),
                ('staff_position_id', '=', record.staff_position_id.id),
            ], order='display_order asc, id asc', limit=1)

            if not rule:
                record.employee_count = 0
                continue

            if rule.calculation_method == 'fixed':
                value = rule.parameter_value
            elif rule.calculation_method == 'per_grade':
                value = rule.parameter_value * self.env['school.grade.levels'].search_count([('school_id', '=', school_id)])
            elif rule.calculation_method == 'per_class':
                total_classes = sum(
                    row.class_count for row in self.env['school.grade.enrollment'].search([
                        ('academic_year_id', '=', record.academic_year_id.id)
                    ])
                )
                value = math.ceil(total_classes / rule.parameter_value) if rule.parameter_value else 0
            elif rule.calculation_method == 'per_student':
                total_students = sum(
                    row.student_count for row in self.env['school.grade.enrollment'].search([
                        ('academic_year_id', '=', record.academic_year_id.id)
                    ])
                )
                value = math.ceil(total_students / rule.parameter_value) if rule.parameter_value else 0
            elif rule.calculation_method == 'per_room':
                room_plans = self.env['school.room.plan'].search([('academic_year_id', '=', record.academic_year_id.id)])
                total_rooms = sum(room_plans.mapped('effective_room_count'))
                value = math.ceil(total_rooms / rule.parameter_value) if rule.parameter_value else 0
            elif rule.calculation_method == 'per_subject_hours':
                total_hours = sum(
                    row.total_teaching_hours for row in self.env['school.subject.distribution'].search([
                        ('academic_year_id', '=', record.academic_year_id.id)
                    ])
                )
                value = math.ceil(total_hours / rule.parameter_value) if rule.parameter_value else 0
            else:
                value = 0

            record.employee_count = max(int(value), 0)

    @api.depends('employee_count', 'monthly_salary', 'months_paid', 'bonus')
    def _compute_annual_cost(self):
        for record in self:
            record.annual_cost = record.employee_count * ((record.monthly_salary * record.months_paid) + record.bonus)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env['school.financial.report']._refresh_for_academic_years(records.mapped('academic_year_id').ids)
        return records

    def write(self, vals):
        old_year_ids = self.mapped('academic_year_id').ids
        result = super().write(vals)
        self.env['school.financial.report']._refresh_for_academic_years(list(set(old_year_ids) | set(self.mapped('academic_year_id').ids)))
        return result

    def unlink(self):
        academic_year_ids = self.mapped('academic_year_id').ids
        result = super().unlink()
        self.env['school.financial.report']._refresh_for_academic_years(academic_year_ids)
        return result


class SchoolAssetPrices(models.Model):
    _name = 'school.asset.prices'
    _description = 'Asset Prices (Year Data)'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    asset_item_id = fields.Many2one('school.asset.items', string='Asset Item', required=True, ondelete='cascade')
    unit_price = fields.Float(string='Unit Price (Input)', required=True)
    required_quantity = fields.Integer(string='Required Quantity', compute='_compute_asset_requirements', store=False)
    owned_quantity = fields.Integer(string='Owned Quantity', compute='_compute_asset_requirements', store=False)
    purchase_quantity = fields.Integer(string='Purchase Quantity', compute='_compute_asset_requirements', store=False)
    asset_total_value = fields.Float(string='Asset Total Value', compute='_compute_asset_requirements', store=False)
    startup_cost = fields.Float(string='Startup Cost', compute='_compute_asset_requirements', store=False)

    @api.depends('academic_year_id', 'asset_item_id', 'unit_price')
    def _compute_asset_requirements(self):
        for record in self:
            if not record.academic_year_id or not record.asset_item_id:
                record.required_quantity = 0
                record.owned_quantity = 0
                record.purchase_quantity = 0
                record.asset_total_value = 0
                record.startup_cost = 0
                continue

            year_id = record.academic_year_id.id
            school_id = record.asset_item_id.school_id.id

            room_plan_rows = self.env['school.room.plan'].search([('academic_year_id', '=', year_id)])
            expansion_rows = self.env['school.expansion.project.rooms'].search([
                ('expansion_project_id.academic_year_id', '=', year_id)
            ])

            expansion_by_room_type = {}
            for expansion in expansion_rows:
                key = expansion.room_type_id.id
                expansion_by_room_type[key] = expansion_by_room_type.get(key, 0) + expansion.room_count

            effective_by_room_type = {}
            for plan in room_plan_rows:
                effective_by_room_type[plan.room_type_id.id] = (
                    plan.existing_rooms + plan.calculated_new_rooms + plan.manual_new_rooms +
                    expansion_by_room_type.get(plan.room_type_id.id, 0)
                )

            bom_rows = self.env['school.room.template.items'].search([
                ('asset_item_id', '=', record.asset_item_id.id),
                ('room_template_id.school_id', '=', school_id)
            ])
            required_qty = 0
            for bom in bom_rows:
                room_type_id = bom.room_template_id.room_type_id.id
                required_qty += bom.quantity * effective_by_room_type.get(room_type_id, 0)

            owned_qty = sum(
                self.env['school.asset.transactions'].search([
                    ('academic_year_id', '=', year_id),
                    ('asset_item_id', '=', record.asset_item_id.id)
                ]).mapped('quantity')
            )

            purchase_qty = max(required_qty - owned_qty, 0)

            record.required_quantity = required_qty
            record.owned_quantity = owned_qty
            record.purchase_quantity = purchase_qty
            record.asset_total_value = owned_qty * record.unit_price
            record.startup_cost = purchase_qty * record.unit_price

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env['school.financial.report']._refresh_for_academic_years(records.mapped('academic_year_id').ids)
        return records

    def write(self, vals):
        old_year_ids = self.mapped('academic_year_id').ids
        result = super().write(vals)
        self.env['school.financial.report']._refresh_for_academic_years(list(set(old_year_ids) | set(self.mapped('academic_year_id').ids)))
        return result

    def unlink(self):
        academic_year_ids = self.mapped('academic_year_id').ids
        result = super().unlink()
        self.env['school.financial.report']._refresh_for_academic_years(academic_year_ids)
        return result


class SchoolAssetTransactions(models.Model):
    _name = 'school.asset.transactions'
    _description = 'Asset Transactions (Year Data)'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    asset_item_id = fields.Many2one('school.asset.items', string='Asset Item', required=True, ondelete='cascade')
    transaction_type = fields.Char(string='Transaction Type', required=True, size=20)
    quantity = fields.Integer(string='Quantity (Input)', required=True)
    transaction_date = fields.Date(string='Transaction Date', required=True, default=fields.Date.context_today)
    notes = fields.Char(string='Notes', size=255)


class SchoolRoomPlan(models.Model):
    _name = 'school.room.plan'
    _description = 'Room Plan (Year Data & Calculated)'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    room_type_id = fields.Many2one('school.room.types', string='Room Type', required=True, ondelete='cascade')
    existing_rooms = fields.Integer(string='Existing Rooms (Input)', default=0, required=True)
    existing_rooms_manual_override = fields.Boolean(
        string='Manual Existing Rooms Override',
        default=False,
        help='When enabled, this row will not auto-fill Existing Rooms from the previous academic year.',
    )
    calculated_new_rooms = fields.Integer(string='Calculated New Rooms', compute='_compute_calculated_new_rooms', store=True)
    manual_new_rooms = fields.Integer(string='Manual New Rooms (Input)', default=0, required=True)
    total_new_rooms = fields.Integer(string='Total New Rooms', compute='_compute_new_rooms_asset_cost', store=False)
    new_rooms_asset_cost = fields.Float(string='New Rooms Asset Expense', compute='_compute_new_rooms_asset_cost', store=False)
    effective_room_count = fields.Integer(string='Effective Rooms (Calculated)', compute='_compute_effective_room_count', store=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_room_plan_sync'):
            records._sync_existing_rooms_from_previous_year()
            records._sync_next_year_existing_rooms()
        self.env['school.financial.report']._refresh_for_academic_years(records.mapped('academic_year_id').ids)
        return records

    def write(self, vals):
        vals_to_write = dict(vals)
        if (
            not self.env.context.get('skip_room_plan_sync')
            and not self.env.context.get('skip_existing_rooms_override_flag')
            and 'existing_rooms' in vals_to_write
            and 'existing_rooms_manual_override' not in vals_to_write
        ):
            vals_to_write['existing_rooms_manual_override'] = True

        old_year_ids = self.mapped('academic_year_id').ids
        result = super().write(vals_to_write)
        if not self.env.context.get('skip_room_plan_sync'):
            self._sync_existing_rooms_from_previous_year()
            self._sync_next_year_existing_rooms()
        self.env['school.financial.report']._refresh_for_academic_years(list(set(old_year_ids) | set(self.mapped('academic_year_id').ids)))
        return result

    def unlink(self):
        academic_year_ids = self.mapped('academic_year_id').ids
        result = super().unlink()
        self.env['school.financial.report']._refresh_for_academic_years(academic_year_ids)
        return result

    def _ordered_school_years(self, school_id):
        return self.env['school.academic.years'].search([
            ('school_id', '=', school_id),
        ], order='start_date asc, academic_year_name asc, id asc')

    def _previous_year(self, academic_year, school_id):
        years = self._ordered_school_years(school_id)
        year_ids = years.ids
        if academic_year.id not in year_ids:
            return False
        idx = year_ids.index(academic_year.id)
        if idx <= 0:
            return False
        return years[idx - 1]

    def _next_year(self, academic_year, school_id):
        years = self._ordered_school_years(school_id)
        year_ids = years.ids
        if academic_year.id not in year_ids:
            return False
        idx = year_ids.index(academic_year.id)
        if idx >= len(years) - 1:
            return False
        return years[idx + 1]

    def _expected_existing_rooms_from_previous_year(self, record):
        previous_year = self._previous_year(record.academic_year_id, record.room_type_id.school_id.id)
        if not previous_year:
            return None
        previous_plan = self.search([
            ('academic_year_id', '=', previous_year.id),
            ('room_type_id', '=', record.room_type_id.id),
        ], limit=1)
        if not previous_plan:
            return None
        return max(previous_plan.calculated_new_rooms, 0) + max(previous_plan.manual_new_rooms, 0)

    def _sync_existing_rooms_from_previous_year(self):
        for record in self:
            if record.existing_rooms_manual_override:
                continue
            expected = record._expected_existing_rooms_from_previous_year(record)
            if expected is None:
                continue
            if int(record.existing_rooms or 0) == int(expected):
                continue
            record.with_context(
                skip_room_plan_sync=True,
                skip_existing_rooms_override_flag=True,
            ).write({'existing_rooms': int(expected)})

    def _sync_next_year_existing_rooms(self):
        next_plans = self.env['school.room.plan']
        for record in self:
            if not record.academic_year_id or not record.room_type_id:
                continue
            next_year = self._next_year(record.academic_year_id, record.room_type_id.school_id.id)
            if not next_year:
                continue
            next_plan = self.search([
                ('academic_year_id', '=', next_year.id),
                ('room_type_id', '=', record.room_type_id.id),
            ], limit=1)
            if not next_plan or next_plan.existing_rooms_manual_override:
                continue
            next_plans |= next_plan
        if next_plans:
            next_plans._sync_existing_rooms_from_previous_year()

    @api.depends('academic_year_id', 'room_type_id', 'existing_rooms')
    def _compute_calculated_new_rooms(self):
        for record in self:
            room_type_name = (record.room_type_id.name or '').strip().lower()
            if 'classroom' not in room_type_name:
                record.calculated_new_rooms = 0
                continue

            academic_year = record.academic_year_id
            if not academic_year:
                record.calculated_new_rooms = 0
                continue

            enrollments = self.env['school.grade.enrollment'].search([
                ('academic_year_id', '=', academic_year.id)
            ])
            total_classes = sum(int(e.class_count or 0) for e in enrollments)
            existing_rooms = max(int(record.existing_rooms or 0), 0)

            # A classroom row should only reflect the year-level classroom shortfall;
            # stale carry-over values or duplicate room-type rows must not inflate the
            # calculation beyond the actual current year need.
            record.calculated_new_rooms = max(0, total_classes - existing_rooms)

    @api.depends('academic_year_id', 'room_type_id', 'existing_rooms', 'calculated_new_rooms', 'manual_new_rooms')
    def _compute_effective_room_count(self):
        for record in self:
            expansion_count = sum(
                self.env['school.expansion.project.rooms'].search([
                    ('expansion_project_id.academic_year_id', '=', record.academic_year_id.id),
                    ('room_type_id', '=', record.room_type_id.id)
                ]).mapped('room_count')
            )
            record.effective_room_count = record.existing_rooms + record.calculated_new_rooms + record.manual_new_rooms + expansion_count

    @api.depends('academic_year_id', 'room_type_id', 'calculated_new_rooms', 'manual_new_rooms')
    def _compute_new_rooms_asset_cost(self):
        for record in self:
            total_new_rooms = max(record.calculated_new_rooms, 0) + max(record.manual_new_rooms, 0)
            record.total_new_rooms = total_new_rooms

            if not total_new_rooms or not record.academic_year_id or not record.room_type_id:
                record.new_rooms_asset_cost = 0
                continue

            template = self.env['school.room.templates'].search([
                ('school_id', '=', record.room_type_id.school_id.id),
                ('room_type_id', '=', record.room_type_id.id),
            ], order='display_order asc, id asc', limit=1)
            if not template:
                record.new_rooms_asset_cost = 0
                continue

            template_items = self.env['school.room.template.items'].search([
                ('room_template_id', '=', template.id)
            ])
            if not template_items:
                record.new_rooms_asset_cost = 0
                continue

            prices = self.env['school.asset.prices'].search([
                ('academic_year_id', '=', record.academic_year_id.id),
                ('asset_item_id', 'in', template_items.mapped('asset_item_id').ids)
            ])
            price_map = {price.asset_item_id.id: price.unit_price for price in prices}

            # If current-year asset prices are missing, reuse the latest known
            # price for each missing asset item so later academic years still
            # produce a meaningful room expansion cost.
            missing_asset_ids = [
                asset_id
                for asset_id in template_items.mapped('asset_item_id').ids
                if asset_id not in price_map
            ]
            if missing_asset_ids:
                fallback_prices = self.env['school.asset.prices'].search([
                    ('asset_item_id', 'in', missing_asset_ids),
                ], order='academic_year_id desc, id desc')
                for fallback in fallback_prices:
                    if fallback.asset_item_id.id not in price_map:
                        price_map[fallback.asset_item_id.id] = fallback.unit_price

            cost_per_room = sum(item.quantity * price_map.get(item.asset_item_id.id, 0.0) for item in template_items)
            record.new_rooms_asset_cost = total_new_rooms * cost_per_room

        if not self.env.context.get('skip_room_plan_sync'):
            self._sync_next_year_existing_rooms()


class SchoolExpansionProjects(models.Model):
    _name = 'school.expansion.projects'
    _description = 'Expansion Projects (Year Data)'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year', required=True, ondelete='cascade')
    name = fields.Char(string='Project Name (Input)', required=True, size=150)
    description = fields.Text(string='Description')
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')


class SchoolExpansionProjectRooms(models.Model):
    _name = 'school.expansion.project.rooms'
    _description = 'Expansion Project Rooms (Year Data)'

    expansion_project_id = fields.Many2one('school.expansion.projects', string='Expansion Project', required=True, ondelete='cascade')
    room_type_id = fields.Many2one('school.room.types', string='Room Type', required=True, ondelete='cascade')
    room_count = fields.Integer(string='Room Count (Input)', required=True)


# --- REPORTING (Stored Snapshot for Native Pivot/Graph/Dashboard Analytics) ---
#
# The Green Band figures above are intentionally "live, never stored" so the
# budgeting screens behave like a spreadsheet. Native Odoo pivot/graph views
# and Spreadsheet Dashboards need stored, groupable measures to aggregate
# efficiently, so this model keeps a materialized snapshot per academic year,
# refreshed by the write/create/unlink hooks on the input models above.
class SchoolFinancialReport(models.Model):
    _name = 'school.financial.report'
    _description = 'Budget & Prediction Financial Report (Stored Analytics Snapshot)'
    _rec_name = 'academic_year_name'
    _order = 'start_date asc, id asc'

    academic_year_id = fields.Many2one('school.academic.years', string='Academic Year Record', required=True, ondelete='cascade', index=True)
    school_id = fields.Many2one('school.schools', string='School', required=True, ondelete='cascade', index=True)
    academic_year_name = fields.Char(string='Academic Year', required=True)
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')

    total_enrolled_students = fields.Integer(string='Enrolled Students')

    gross_revenue = fields.Float(string='Gross Revenue')
    tax_amount = fields.Float(string='Tax Deductions')
    net_revenue = fields.Float(string='Net Revenue')

    expense_total = fields.Float(string='Operating Expenses')
    salary_total = fields.Float(string='Salary Cost')
    room_equipment_total = fields.Float(string='New Rooms Equipment Cost')
    operating_cost_total = fields.Float(string='Operating Cost Total')
    startup_cost_total = fields.Float(string='Startup Cost Total')
    total_cost = fields.Float(string='Total Cost (incl. Tax & Startup)')

    operating_profit = fields.Float(string='Operating Profit')
    net_profit = fields.Float(string='Net Profit (Budget)')
    net_margin_pct = fields.Float(string='Net Margin %')

    prior_year_gross_revenue = fields.Float(string='Prior Year Gross Revenue')
    prior_year_net_revenue = fields.Float(string='Prior Year Net Revenue')
    prior_year_net_profit = fields.Float(string='Prior Year Net Profit')
    revenue_yoy_pct = fields.Float(string='Revenue YoY %')
    profit_yoy_pct = fields.Float(string='Net Profit YoY %')

    _academic_year_unique = models.Constraint(
        'unique(academic_year_id)',
        'A financial report row already exists for this academic year.',
    )

    @api.model
    def _refresh_all(self):
        self._refresh_for_academic_years(self.env['school.academic.years'].search([]).ids)

    @api.model
    def _refresh_for_academic_years(self, academic_year_ids):
        academic_year_ids = {year_id for year_id in (academic_year_ids or []) if year_id}
        if not academic_year_ids:
            return

        self = self.sudo()
        room_plan_model = self.env['school.room.plan']
        years = self.env['school.academic.years'].browse(list(academic_year_ids)).exists()

        # A changed year can shift the "previous year" baseline used by the
        # following year's YoY comparison, so refresh that one too.
        for year in years:
            next_year = room_plan_model._next_year(year, year.school_id.id)
            if next_year:
                academic_year_ids.add(next_year.id)
        years = self.env['school.academic.years'].browse(list(academic_year_ids)).exists()

        for year in years:
            previous_year = room_plan_model._previous_year(year, year.school_id.id)

            vals = {
                'school_id': year.school_id.id,
                'academic_year_name': year.academic_year_name,
                'start_date': year.start_date,
                'end_date': year.end_date,
                'total_enrolled_students': year.total_enrolled_students,
                'gross_revenue': year.fee_gross_total,
                'tax_amount': year.tax_deductions_total,
                'net_revenue': year.fee_total,
                'expense_total': year.expense_total,
                'salary_total': year.salary_total,
                'room_equipment_total': year.new_rooms_expense_total,
                'operating_cost_total': year.operating_cost_total,
                'startup_cost_total': year.startup_cost_total,
                'total_cost': year.total_deductions,
                'operating_profit': year.operating_profit,
                'net_profit': year.net_budget,
                'net_margin_pct': year.net_margin_pct,
                'prior_year_gross_revenue': previous_year.fee_gross_total if previous_year else 0.0,
                'prior_year_net_revenue': previous_year.fee_total if previous_year else 0.0,
                'prior_year_net_profit': previous_year.net_budget if previous_year else 0.0,
            }
            vals['revenue_yoy_pct'] = (
                (vals['net_revenue'] - vals['prior_year_net_revenue']) / abs(vals['prior_year_net_revenue']) * 100.0
                if vals['prior_year_net_revenue'] else 0.0
            )
            vals['profit_yoy_pct'] = (
                (vals['net_profit'] - vals['prior_year_net_profit']) / abs(vals['prior_year_net_profit']) * 100.0
                if vals['prior_year_net_profit'] else 0.0
            )

            report = self.search([('academic_year_id', '=', year.id)], limit=1)
            if report:
                report.write(vals)
            else:
                vals['academic_year_id'] = year.id
                self.create(vals)