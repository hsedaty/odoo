from odoo import api, fields, models
from odoo.exceptions import ValidationError


# Columns follow the supplied timetable: KG1, KG2, then Grades 1 through 10.
GRADES = ('KG1', 'KG2', *(f'GRADE{i}' for i in range(1, 11)))
WEEKLY_HOURS = {
    'ela': (10, 10, 9, 9, 9, 7, 7, 7, 6, 6, 4, 4),
    'math': (5, 5, 5, 5, 5, 5, 5, 5, 4, 4, 0, 0),
    'science': (2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 0, 0),
    'english_social_studies': (0, 0, 1, 1, 1, 1, 1, 2, 3, 3, 0, 0),
    'languages': (0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2),
    'cs': (1, 1, 2, 2, 2, 2, 2, 1, 2, 2, 1, 0),
    'pe': (2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1),
    'visual_arts': (1, 1, 2, 2, 2, 2, 1, 1, 0, 0, 0, 0),
    'music': (1, 1, 2, 2, 2, 1, 1, 1, 0, 0, 0, 0),
    'arabic': (5, 5, 5, 5, 5, 5, 5, 5, 3, 3, 3, 3),
    'religion': (1, 1, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2),
    'arabic_social_studies': (0, 0, 0, 0, 0, 2, 2, 2, 1, 1, 1, 1),
    'quran': (1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0),
    'creative_writing': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1),
    'math_1': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0),
    'math_2': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4),
    'biology': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0),
    'chemistry': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4),
    'world_history_1': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0),
    'world_history_2': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4),
    'ict': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
    'tw': (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
}


def american_grade_index(grade):
    key = ''.join(grade.name.upper().split()).replace('-', '')
    return GRADES.index(key) if key in GRADES else None


class School(models.Model):
    _inherit = 'school.schools'

    def _uses_american_timetable(self):
        self.ensure_one()
        return self.curriculum_ids.mapped('code') == ['US']

    def _american_timetable_values(self, grades, subjects):
        self.ensure_one()
        presets = {
            key: self.env.ref(f'school_planning.subject_us_{key}', raise_if_not_found=False)
            for key in WEEKLY_HOURS
        }
        offered = {}
        for key, preset in presets.items():
            if preset:
                offered[key] = subjects.filtered(
                    lambda subject: subject.preset_id == preset
                    or (not subject.preset_id and subject.name.casefold() == preset.name.casefold())
                )[:1]
        values = []
        for grade in grades:
            index = american_grade_index(grade)
            if index is None:
                continue
            for key, hours in WEEKLY_HOURS.items():
                subject = offered.get(key)
                if subject and hours[index]:
                    values.append({'grade_level_id': grade.id, 'subject_id': subject.id,
                                   'weekly_hours': hours[index], 'credits': 0})
            if index >= 8:
                choices = offered.get('visual_arts', self.env['school.subjects']) | offered.get('music', self.env['school.subjects'])
                if choices:
                    values.append({'grade_level_id': grade.id, 'subject_id': choices[0].id,
                                   'weekly_hours': 1, 'credits': 0,
                                   'choice_subject_ids': [fields.Command.set(choices.ids)]})
        return values


class AcademicYear(models.Model):
    _inherit = 'school.academic.years'

    uses_american_timetable = fields.Boolean(compute='_compute_uses_american_timetable')

    @api.depends('school_id.curriculum_ids', 'school_id.curriculum_ids.code')
    def _compute_uses_american_timetable(self):
        for year in self:
            year.uses_american_timetable = bool(year.school_id and year.school_id._uses_american_timetable())

    def _apply_american_timetable(self, grades, subjects):
        self.ensure_one()
        if self.baseline_locked:
            raise ValidationError(self.env._('An approved forecast cannot have its timetable replaced.'))
        supported = grades.filtered(lambda grade: american_grade_index(grade) is not None)
        self.subject_distribution_ids.filtered(lambda row: row.grade_level_id in supported).unlink()
        self.env['school.subject.distribution'].create([
            {**values, 'academic_year_id': self.id}
            for values in self.school_id._american_timetable_values(supported, subjects)
        ])

    def action_apply_american_timetable(self):
        self.ensure_one()
        if not self.uses_american_timetable or self.baseline_locked:
            raise ValidationError(self.env._('Select an unlocked year using only the American curriculum.'))
        curriculum = self.env.ref('school_planning.curriculum_us_standards')
        presets = self.env['school.subject.preset']
        for key in WEEKLY_HOURS:
            preset = self.env.ref(f'school_planning.subject_us_{key}', raise_if_not_found=False)
            if preset and preset.active:
                presets |= preset
        if not presets:
            raise ValidationError(self.env._('No American timetable subjects are available in the catalog.'))
        self.env['school.subject.setup.wizard'].create({
            'school_id': self.school_id.id, 'curriculum_id': curriculum.id,
            'subject_preset_ids': [fields.Command.set(presets.ids)],
        }).action_apply()
        grades = self.env['school.grade.levels'].search([('school_id', '=', self.school_id.id)])
        if not grades.filtered(lambda grade: american_grade_index(grade) is not None):
            raise ValidationError(self.env._('Configure grades KG1 through Grade 10 before applying this timetable.'))
        self._apply_american_timetable(grades, self.school_id.subject_ids)
        self._sync_efficiency_teaching()
        return self._workspace_action()


class SubjectDistribution(models.Model):
    _inherit = 'school.subject.distribution'

    choice_subject_ids = fields.Many2many(
        'school.subjects', string='Subject Choices',
        help='One shared weekly slot. Select the subject offered to this grade or class group; do not add both hours.',
    )
    choice_label = fields.Char(string='Choose One', compute='_compute_choice_label')

    @api.depends('choice_subject_ids.name')
    def _compute_choice_label(self):
        for row in self:
            row.choice_label = ' / '.join(row.choice_subject_ids.mapped('name'))

    @api.constrains('subject_id', 'choice_subject_ids', 'academic_year_id')
    def _check_subject_choices(self):
        for row in self:
            if row.choice_subject_ids and (row.subject_id not in row.choice_subject_ids
                    or any(subject.school_id != row.academic_year_id.school_id for subject in row.choice_subject_ids)):
                raise ValidationError(self.env._('Select one of this school\'s subjects from the displayed choices.'))
