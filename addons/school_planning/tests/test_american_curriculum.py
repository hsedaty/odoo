from lxml import html

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.convert import convert_file


@tagged('post_install', '-at_install')
class TestAmericanTimetable(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.curriculum = cls.env.ref('school_planning.curriculum_us_standards')
        cls.school = cls.env['school.schools'].create({'name': 'American timetable school', 'currency': 'EUR'})
        cls.env['school.subject.setup.wizard'].create({
            'school_id': cls.school.id, 'curriculum_id': cls.curriculum.id,
            'subject_preset_ids': [fields.Command.set(cls.curriculum.subject_preset_ids.ids)],
        }).action_apply()
        cls.wizard = cls.env['school.prediction.quick.setup.wizard'].create({'school_id': cls.school.id})
        cls.grades = cls.wizard._ensure_grade_structure()
        cls.year = cls.env['school.academic.years'].create({
            'school_id': cls.school.id, 'academic_year_name': '2047-2048',
            'start_date': '2047-09-01', 'end_date': '2048-06-30', 'dataset_type': 'forecast',
        })

    def grade(self, name):
        return self.grades.filtered(lambda grade: grade.name == name).ensure_one()

    def rows(self, name):
        return self.year.subject_distribution_ids.filtered(lambda row: row.grade_level_id == self.grade(name))

    def seed(self):
        self.wizard._ensure_subject_distribution(self.year, self.grades, self.school.subject_ids)

    def test_supplied_grade_hours_and_subjects(self):
        self.seed()
        for grade, total in [('KG1', 29), ('KG2', 29)] + [
                (f'Grade {i}', 34 if i <= 6 else 29) for i in range(1, 11)]:
            with self.subTest(grade=grade):
                self.assertEqual(sum(self.rows(grade).mapped('weekly_hours')), total)
                self.assertTrue(all(row.weekly_hours > 0 for row in self.rows(grade)))
        kg = {row.subject_id.name: row.weekly_hours for row in self.rows('KG1')}
        self.assertEqual(kg, {'English Language Arts': 10, 'Mathematics': 5, 'Science': 2,
                             'Computer Science': 1, 'Physical Education': 2, 'Visual Arts': 1,
                             'Music': 1, 'Arabic': 5, 'Religion': 1, 'Quran': 1})
        for grade, expected in {
            'Grade 4': {'English Language Arts': 7, 'World Languages': 2, 'Religion': 1, 'Arabic Social Studies': 2},
            'Grade 6': {'English Social Studies': 2, 'Computer Science': 1, 'Quran': 1},
            'Grade 9': {'Creative Writing': 2, 'Math 1': 4, 'Biology': 4, 'World History 1': 4},
            'Grade 10': {'Creative Writing': 1, 'Math 2': 4, 'Chemistry': 4, 'World History 2': 4, 'ICT': 1, 'TW': 1},
        }.items():
            actual = {row.subject_id.name: row.weekly_hours for row in self.rows(grade)}
            for subject, hours in expected.items():
                self.assertEqual(actual[subject], hours)
        self.assertNotIn('Science', self.rows('Grade 9').subject_id.mapped('name'))
        self.assertNotIn('Computer Science', self.rows('Grade 10').subject_id.mapped('name'))

    def test_new_prediction_keeps_supplied_hours(self):
        self.wizard.line_ids.write({'student_count': 350, 'annual_fee_per_student': 100})
        self.wizard.action_apply()
        for year in self.wizard._existing_forecast_years():
            for name, expected in (('KG1', 29), ('Grade 1', 34), ('Grade 7', 29), ('Grade 10', 29)):
                rows = year.subject_distribution_ids.filtered(lambda row: row.grade_level_id == self.grade(name))
                self.assertEqual(sum(rows.mapped('weekly_hours')), expected)
            teacher = year.employment_salary_ids.filtered(lambda row: row.staff_position_id.planning_role == 'teacher')
            self.assertEqual(teacher.employee_count, year.required_teachers)

    def test_choice_is_one_slot_and_survives_copy(self):
        self.seed()
        choice = self.rows('Grade 7').filtered('choice_subject_ids').ensure_one()
        self.assertEqual(set(choice.choice_subject_ids.mapped('name')), {'Visual Arts', 'Music'})
        choice.subject_id = self.school.subject_ids.filtered(lambda subject: subject.name == 'Music')
        self.assertEqual(sum(self.rows('Grade 7').mapped('weekly_hours')), 29)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            choice.subject_id = self.school.subject_ids.filtered(lambda subject: subject.name == 'Mathematics')
        actual = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': self.year.academic_year_name,
            'start_date': self.year.start_date, 'end_date': self.year.end_date,
            'dataset_type': 'actual', 'forecast_year_id': self.year.id,
        })
        actual.action_load_from_forecast()
        copied = actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == choice.grade_level_id and row.choice_subject_ids
        ).ensure_one()
        self.assertEqual(copied.subject_id, choice.subject_id)
        self.assertEqual(copied.choice_subject_ids, choice.choice_subject_ids)
        self.assertEqual(sum(actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == choice.grade_level_id).mapped('weekly_hours')), 29)
        self.year.action_freeze_baseline()
        with self.assertRaises(ValidationError):
            self.year.action_apply_american_timetable()

    def test_preserves_hours_and_uses_real_teaching_load(self):
        self.seed()
        positions = self.wizard._ensure_operating_models()
        salary = self.env['school.employment.salaries'].create({
            'academic_year_id': self.year.id, 'staff_position_id': positions['teacher'].id,
            'monthly_salary': 100,
        })
        self.env['school.grade.enrollment'].create([
            {'academic_year_id': self.year.id, 'grade_level_id': self.grade(name).id, 'student_count': 25}
            for name in ('KG1', 'Grade 1')
        ])
        self.year.write({'teacher_weekly_hours': 1, 'classroom_weekly_hours': 40})
        self.assertEqual(self.year.required_teachers, 63)
        self.assertEqual(salary.employee_count, 63)
        english = self.rows('Grade 1').filtered(lambda row: row.subject_id.name == 'English Language Arts')
        english.weekly_hours = 8
        self.assertEqual(salary.employee_count, 62)
        self.year.write({'classroom_weekly_hours': 35})
        self.assertEqual(english.weekly_hours, 8)
        self.assertEqual(self.year.required_teachers, 62)

    def test_teacher_breakdown_aggregates_grades_and_rounds_each_subject(self):
        english = self.school.subject_ids.filtered(lambda subject: subject.name == 'English Language Arts')
        math = self.school.subject_ids.filtered(lambda subject: subject.name == 'Mathematics')
        self.env['school.subject.distribution'].create([
            {'academic_year_id': self.year.id, 'grade_level_id': self.grade(grade).id,
             'subject_id': subject.id, 'weekly_hours': hours}
            for grade, subject, hours in [('KG1', english, 10), ('Grade 1', english, 9),
                                          ('KG1', math, 5), ('Grade 1', math, 5)]
        ])
        self.env['school.grade.enrollment'].create([
            {'academic_year_id': self.year.id, 'grade_level_id': self.grade(grade).id, 'student_count': students}
            for grade, students in [('KG1', 30), ('Grade 1', 51)]
        ])
        self.year.teacher_weekly_hours = 20

        def breakdown():
            tree = html.fromstring(self.year.teacher_requirement_details)
            return [[cell.text_content() for cell in row] for row in tree.xpath('//tbody/tr')]

        self.assertEqual(breakdown(), [['English Language Arts', '47.00', '3'], ['Mathematics', '25.00', '2']])
        self.assertEqual(self.year.required_teachers, 5)
        self.year.teacher_weekly_hours = 25
        self.assertEqual(breakdown(), [['English Language Arts', '47.00', '2'], ['Mathematics', '25.00', '1']])
        self.assertEqual(self.year.required_teachers, 3)
        english.name = '<English & Writing>'
        self.assertIn('<English & Writing>', breakdown()[0])
        self.assertNotIn('<English & Writing>', self.year.teacher_requirement_details)

    def test_teacher_breakdown_counts_only_selected_elective(self):
        self.seed()
        self.env['school.grade.enrollment'].create({
            'academic_year_id': self.year.id, 'grade_level_id': self.grade('Grade 7').id, 'student_count': 25,
        })
        choice = self.rows('Grade 7').filtered('choice_subject_ids')
        music = choice.choice_subject_ids.filtered(lambda subject: subject.name == 'Music')
        choice.subject_id = music
        tree = html.fromstring(self.year.teacher_requirement_details)
        rows = {row[0].text_content(): int(row[2].text_content()) for row in tree.xpath('//tbody/tr')}
        self.assertEqual(rows['Music'], 1)
        self.assertEqual(rows['Visual Arts'], 0)
        self.assertEqual(sum(rows.values()), self.year.required_teachers)
        self.assertEqual(int(tree.xpath('//tfoot/tr/td[last()]')[0].text_content()), self.year.required_teachers)

    def test_explicit_apply_preserves_unsupported_grades_and_other_years(self):
        other = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': '2048-2049',
            'start_date': '2048-09-01', 'end_date': '2049-06-30', 'dataset_type': 'forecast',
        })
        subject = self.school.subject_ids[0]
        keep = self.env['school.subject.distribution'].create([
            {'academic_year_id': year.id, 'grade_level_id': self.grade('Grade 11').id,
             'subject_id': subject.id, 'weekly_hours': 7}
            for year in (self.year, other)
        ])
        self.year.action_apply_american_timetable()
        self.assertEqual(keep.mapped('weekly_hours'), [7, 7])
        self.assertEqual(other.subject_distribution_ids, keep.filtered(lambda row: row.academic_year_id == other))
        self.assertEqual(sum(self.rows('KG1').mapped('weekly_hours')), 29)

    def test_non_american_and_mixed_curricula_keep_existing_distribution(self):
        for xmlid in ('curriculum_england', 'curriculum_ib_pyp', 'curriculum_ib_myp', 'curriculum_ib_dp'):
            curriculum = self.env.ref(f'school_planning.{xmlid}')
            self.school.curriculum_ids = [fields.Command.set(curriculum.ids)]
            self.wizard._ensure_subject_distribution(self.year, self.grades, self.school.subject_ids)
            self.assertFalse(self.year.uses_american_timetable)
            self.assertAlmostEqual(sum(self.rows('Grade 1').mapped('weekly_hours')), self.wizard.classroom_weekly_hours)
            self.assertEqual(len(self.rows('Grade 1')), len(self.school.subject_ids))
        self.school.curriculum_ids = [fields.Command.set((self.curriculum | curriculum).ids)]
        self.assertFalse(self.year.uses_american_timetable)
        with self.assertRaises(ValidationError):
            self.year.action_apply_american_timetable()

    def test_timetable_catalog_edits_and_deletions_survive_updates(self):
        science = self.env.ref('school_planning.subject_us_science')
        science.name = 'Integrated Science'
        self.env.ref('school_planning.subject_us_tw').unlink()
        convert_file(self.env, 'school_planning', 'data/american_subjects.xml', {}, mode='update')
        self.assertEqual(science.name, 'Integrated Science')
        self.assertFalse(self.env.ref('school_planning.subject_us_tw', raise_if_not_found=False))
        self.seed()
        self.assertIn('Science', self.rows('Grade 1').subject_id.mapped('name'))
