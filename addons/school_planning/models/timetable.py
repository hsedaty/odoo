import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError


# Columns follow the supplied timetable: KG1, KG2, then Grades 1 through 12.
GRADES = ('KG1', 'KG2', *(f'GRADE{i}' for i in range(1, 13)))
WEEKLY_HOURS = {
    'ela': (10, 10, 9, 9, 9, 7, 7, 7, 6, 6, 4, 4, 4, None),
    'math': (5, 5, 5, 5, 5, 5, 5, 5, 4, 4, None, None, None, None),
    'science': (2, 2, 3, 3, 3, 3, 3, 3, 4, 4, None, None, None, None),
    'english_social_studies': (0, 0, 1, 1, 1, 1, 1, 2, 3, 3, None, None, None, None),
    'languages': (0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 4, None),
    'cs': (1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 1, None, None, 4),
    'pe': (2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 2, None),
    'visual_arts': (1, 1, 2, 2, 2, 2, 1, 1, None, None, None, None, None, None),
    'music': (1, 1, 2, 2, 2, 1, 1, 1, None, None, None, None, None, None),
    'visual_arts/music': (None, None, None, None, None, None, None, None, 1, 1, 1, 1, None, None),
    'arabic': (5, 5, 5, 5, 5, 5, 5, 5, 3, 3, 3, 3, 3, 3),
    'religion': (2, 2, 3, 3, 3, 2, 3, 2, 2, 2, 2, 2, 2, 1),
    'arabic_social_studies': (0, 0, 0, 0, 0, 2, 2, 2, 1, 1, 1, 1, None, None),
    'creative_writing': (None, None, None, None, None, None, None, None, None, None, 2, 1, 1, None),
    'math_1': (None, None, None, None, None, None, None, None, None, None, 4, None, None, None),
    'math_2': (None, None, None, None, None, None, None, None, None, None, None, 4, None, None),
    'biology': (None, None, None, None, None, None, None, None, None, None, 4, None, None, None),
    'chemistry': (None, None, None, None, None, None, None, None, None, None, None, 4, None, None),
    'world_history_1': (None, None, None, None, None, None, None, None, None, None, 4, None, None, None),
    'world_history_2': (None, None, None, None, None, None, None, None, None, None, None, 4, None, None),
    'ict': (None, None, None, None, None, None, None, None, None, None, None, 1, None, None),
    'tw': (None, None, None, None, None, None, None, None, None, None, None, 1, 1, 1),
    'math_3': (None, None, None, None, None, None, None, None, None, None, None, None, 4, None),
    'physics': (None, None, None, None, None, None, None, None, None, None, None, None, 4, None),
    'advanced_chemistry/sociology': (None, None, None, None, None, None, None, None, None, None, None, None, 4, None),
    'literature': (None, None, None, None, None, None, None, None, None, None, None, None, None, 4),
    'advanced_math/psychology': (None, None, None, None, None, None, None, None, None, None, None, None, None, 4),
    'advanced_physics/business': (None, None, None, None, None, None, None, None, None, None, None, None, None, 4),
    'advanced_biology/political_science': (None, None, None, None, None, None, None, None, None, None, None, None, None, 4),
    'economics': (None, None, None, None, None, None, None, None, None, None, None, None, None, 4),
}


def grade_key(name):
    return ''.join(name.upper().split()).replace('-', '')


def counted_class_hours(rows, grade_field):
    hours, areas = {}, {}
    for row in rows:
        hours[row] = row.weekly_hours
        if row.elective_group:
            key = (row[grade_field].id, row.curriculum_id.id, row.elective_group)
            first = areas.setdefault(key, row)
            if first != row:
                hours[first] = max(hours[first], row.weekly_hours)
                hours[row] = 0
    return hours


class Curriculum(models.Model):
    _inherit = 'school.curriculum.preset'

    timetable_ids = fields.One2many('school.timetable', 'curriculum_id')


class Timetable(models.Model):
    _name = 'school.timetable'
    _description = 'Curriculum Timetable Seed'
    _order = 'name, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    curriculum_id = fields.Many2one('school.curriculum.preset', required=True, ondelete='restrict')
    line_ids = fields.One2many('school.timetable.line', 'timetable_id', string='Weekly Subject Hours', copy=True)

    _curriculum_unique = models.Constraint('UNIQUE(curriculum_id)', 'Each curriculum can have only one timetable.')

    @api.model
    def _install_american_timetable(self, replace=False):
        timetable = self.env.ref('school_planning.timetable_american', raise_if_not_found=False)
        if timetable and not replace:
            return
        subjects = {
            key: self.env.ref(f'school_planning.subject_us_{key}', raise_if_not_found=False) or self.env['school.subject.preset']
            for slot in WEEKLY_HOURS for key in slot.split('/')
        }
        grades = {grade_key(grade.name): grade for grade in self.env['school.grade.level.preset'].search([])}
        lines = []
        for index, name in enumerate(GRADES):
            grade = grades.get(name)
            if not grade:
                continue
            elective = 0
            for key, hours in WEEKLY_HOURS.items():
                options = key.split('/')
                if hours[index] is None or any(not subjects[option] for option in options):
                    continue
                if len(options) > 1:
                    elective += 1
                for option in options:
                    lines.append(fields.Command.create({
                        'grade_id': grade.id, 'subject_id': subjects[option].id, 'weekly_hours': hours[index],
                        'elective_group': f'ELCT{elective}' if len(options) > 1 else False,
                    }))
        values = {
            'name': 'American Timetable', 'curriculum_id': self.env.ref('school_planning.curriculum_us_standards').id,
            'line_ids': [fields.Command.clear()] + lines,
        }
        if not timetable and replace:
            timetable = self.with_context(active_test=False).search([('curriculum_id', '=', values['curriculum_id'])], limit=1)
        if timetable:
            timetable.write(values)
        else:
            timetable = self.create(values)
        if not self.env.ref('school_planning.timetable_american', raise_if_not_found=False):
            self.env['ir.model.data'].create({
                'module': 'school_planning', 'name': 'timetable_american',
                'model': self._name, 'res_id': timetable.id, 'noupdate': True,
            })

    @api.constrains('curriculum_id')
    def _check_curriculum(self):
        self.line_ids._check_subjects()


class TimetableLine(models.Model):
    _name = 'school.timetable.line'
    _description = 'Timetable Subject Hours'
    _order = 'grade_id, id'

    timetable_id = fields.Many2one('school.timetable', required=True, ondelete='cascade')
    curriculum_id = fields.Many2one(related='timetable_id.curriculum_id')
    grade_id = fields.Many2one('school.grade.level.preset', required=True, ondelete='restrict')
    subject_id = fields.Many2one('school.subject.preset', required=True, ondelete='cascade')
    choice_subject_ids = fields.Many2many('school.subject.preset', readonly=True,
                                        help='Legacy slot subjects retained for upgrade conversion.')
    elective_group = fields.Char(string='Elective Area', help='Use the same label, such as ELCT1, for subjects sharing one class slot.')
    weekly_hours = fields.Float(required=True, default=1)
    class_weekly_hours = fields.Float(string='Counted Class Hours', compute='_compute_class_hours',
                                     help='Each elective area counts once per grade, using its largest subject duration.')

    @api.depends('timetable_id.line_ids.weekly_hours', 'timetable_id.line_ids.elective_group',
                 'timetable_id.line_ids.grade_id', 'timetable_id.curriculum_id')
    def _compute_class_hours(self):
        for timetable in self.timetable_id:
            for line, hours in counted_class_hours(timetable.line_ids, 'grade_id').items():
                line.class_weekly_hours = hours

    @api.constrains('weekly_hours')
    def _check_hours(self):
        if any(not math.isfinite(line.weekly_hours) or line.weekly_hours < 0 for line in self):
            raise ValidationError(self.env._('Weekly subject hours must be non-negative.'))

    @api.constrains('subject_id', 'choice_subject_ids', 'timetable_id')
    def _check_subjects(self):
        for line in self:
            subjects = line.subject_id | line.choice_subject_ids
            if any(subject.curriculum_id != line.curriculum_id for subject in subjects):
                raise ValidationError(self.env._('Timetable subjects must belong to its curriculum.'))
            if line.choice_subject_ids and line.subject_id not in line.choice_subject_ids:
                raise ValidationError(self.env._('The default subject must be one of the alternatives.'))

    @api.constrains('grade_id', 'subject_id', 'timetable_id')
    def _check_duplicate_slots(self):
        for line in self:
            others = line.timetable_id.line_ids.filtered(lambda other: other != line and other.grade_id == line.grade_id)
            if line.subject_id in others.subject_id:
                raise ValidationError(self.env._('A subject can appear only once per grade in a timetable.'))


class School(models.Model):
    _inherit = 'school.schools'

    def _matching_timetables(self):
        self.ensure_one()
        return self.env['school.timetable'].search([
            ('curriculum_id', 'in', self.curriculum_ids.ids), ('active', '=', True),
        ])

    def _timetable_values(self, grades, subjects):
        self.ensure_one()
        offered = {subject.preset_id.id: subject for subject in subjects if subject.preset_id}
        values = []
        for timetable in self._matching_timetables():
            for line in timetable.line_ids:
                matching = grades.filtered(lambda grade: grade_key(grade.name) == grade_key(line.grade_id.name))
                subject = offered.get(line.subject_id.id)
                if not matching:
                    continue
                if not subject:
                    raise ValidationError(self.env._('Add the subjects for timetable "%s" before loading it.', timetable.name))
                if not line.subject_id.active:
                    raise ValidationError(self.env._('Remove archived subjects from timetable "%s" before loading it.', timetable.name))
                for grade in matching:
                    values.append({
                        'grade_level_id': grade.id, 'subject_id': subject.id,
                        'weekly_hours': line.weekly_hours, 'credits': 0, 'timetable_id': timetable.id,
                        'elective_group': line.elective_group,
                    })
        return values

    def _ensure_timetable_subjects(self):
        self.ensure_one()
        lines = self._matching_timetables().line_ids
        presets = lines.subject_id
        for preset in presets:
            subject = self.subject_ids.filtered(lambda subject: subject.preset_id == preset)[:1]
            if not subject:
                subject = self.subject_ids.filtered(
                    lambda subject: not subject.preset_id and subject.name.casefold() == preset.name.casefold()
                )[:1]
                if subject:
                    subject.preset_id = preset
                else:
                    self.env['school.subjects'].create({
                        'school_id': self.id, 'name': preset.name, 'display_order': preset.display_order,
                        'preset_id': preset.id,
                    })


class AcademicYear(models.Model):
    _inherit = 'school.academic.years'

    timetable_ids = fields.Many2many('school.timetable', compute='_compute_timetables', string='Matching Timetables')
    uses_timetables = fields.Boolean(compute='_compute_timetables')

    @api.depends('school_id.curriculum_ids', 'school_id.curriculum_ids.code', 'school_id.curriculum_ids.timetable_ids.active',
                 'subject_distribution_ids.timetable_id')
    def _compute_timetables(self):
        for year in self:
            year.timetable_ids = year.school_id._matching_timetables() if year.school_id else self.env['school.timetable']
            # Existing American-only years predate timetable source links.
            year.uses_timetables = bool(year.subject_distribution_ids.timetable_id) or year.school_id.curriculum_ids.mapped('code') == ['US']

    def _apply_timetables(self, grades, subjects):
        self.ensure_one()
        if self.baseline_locked:
            raise ValidationError(self.env._('An approved forecast cannot have its timetable replaced.'))
        values = self.school_id._timetable_values(grades, subjects)
        timetables = self.school_id._matching_timetables()
        curricula = {timetable.id: timetable.curriculum_id.id for timetable in timetables}
        scopes = {(value['grade_level_id'], curricula[value['timetable_id']]) for value in values}
        self.subject_distribution_ids.filtered(lambda row: (
            row.timetable_id in timetables and row.grade_level_id in grades
        ) or (row.grade_level_id.id, row.subject_id.preset_id.curriculum_id.id) in scopes).unlink()
        self.env['school.subject.distribution'].create([
            {**value, 'academic_year_id': self.id} for value in values
        ])

    def action_apply_timetables(self):
        self.ensure_one()
        if not self.school_id._matching_timetables() or self.baseline_locked:
            raise ValidationError(self.env._('Select an unlocked year with a timetable matching the school curricula.'))
        self.school_id._ensure_timetable_subjects()
        grades = self.env['school.grade.levels'].search([('school_id', '=', self.school_id.id)])
        if not self.school_id._timetable_values(grades, self.school_id.subject_ids):
            raise ValidationError(self.env._('No timetable rows match the school grades. Configure timetable subjects and grades first.'))
        self._apply_timetables(grades, self.school_id.subject_ids)
        self._sync_efficiency_teaching()
        return self._workspace_action()


class SubjectDistribution(models.Model):
    _inherit = 'school.subject.distribution'

    timetable_id = fields.Many2one('school.timetable', string='Timetable Seed', ondelete='restrict', readonly=True,
                                   help='Source seed. Archive a used timetable instead of deleting it; loaded hours remain independent.')
    curriculum_id = fields.Many2one(related='subject_id.preset_id.curriculum_id', string='Curriculum')
    choice_subject_ids = fields.Many2many(
        'school.subjects', readonly=True, help='Legacy slot subjects retained for upgrade conversion.',
    )
    elective_group = fields.Char(string='Elective Area', help='Subjects sharing ELCT1, ELCT2, etc. occupy one class slot per grade and curriculum.')
    class_weekly_hours = fields.Float(string='Counted Class Hours', compute='_compute_class_hours',
                                     help='Each elective area counts once, using its largest subject duration; other rows in that area contribute zero.')

    @api.depends('academic_year_id.subject_distribution_ids.weekly_hours',
                 'academic_year_id.subject_distribution_ids.elective_group',
                 'academic_year_id.subject_distribution_ids.grade_level_id',
                 'academic_year_id.subject_distribution_ids.subject_id.preset_id.curriculum_id')
    def _compute_class_hours(self):
        for year in self.academic_year_id:
            for row, hours in counted_class_hours(year.subject_distribution_ids, 'grade_level_id').items():
                row.class_weekly_hours = hours

    @api.constrains('subject_id', 'choice_subject_ids', 'academic_year_id')
    def _check_subject_choices(self):
        for row in self:
            if row.choice_subject_ids and (row.subject_id not in row.choice_subject_ids
                    or any(subject.school_id != row.academic_year_id.school_id for subject in row.choice_subject_ids)):
                raise ValidationError(self.env._('The elective slot and all its alternatives must belong to this school.'))
