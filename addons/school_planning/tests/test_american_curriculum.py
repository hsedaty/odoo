from pathlib import Path
from runpy import run_path

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
        schedules = [
            (('KG1', 'KG2'), {
                'English': 10, 'Math': 5, 'Science': 2, 'Social Studies - Eng': 0, '2nd Lang': 0,
                'Computer': 1, 'P.E': 2, 'Art': 1, 'Music': 1, 'Arabic': 5, 'Religion': 2, 'Social Studies - Ar': 0,
            }),
            (('Grade 1', 'Grade 2', 'Grade 3'), {
                'English': 9, 'Math': 5, 'Science': 3, 'Social Studies - Eng': 1, '2nd Lang': 0,
                'Computer': 2, 'P.E': 2, 'Art': 2, 'Music': 2, 'Arabic': 5, 'Religion': 3, 'Social Studies - Ar': 0,
            }),
            (('Grade 4',), {
                'English': 7, 'Math': 5, 'Science': 3, 'Social Studies - Eng': 1, '2nd Lang': 2,
                'Computer': 2, 'P.E': 2, 'Art': 2, 'Music': 1, 'Arabic': 5, 'Religion': 2, 'Social Studies - Ar': 2,
            }),
            (('Grade 5',), {
                'English': 7, 'Math': 5, 'Science': 3, 'Social Studies - Eng': 1, '2nd Lang': 2,
                'Computer': 2, 'P.E': 2, 'Art': 1, 'Music': 1, 'Arabic': 5, 'Religion': 3, 'Social Studies - Ar': 2,
            }),
            (('Grade 6',), {
                'English': 7, 'Math': 5, 'Science': 3, 'Social Studies - Eng': 2, '2nd Lang': 2,
                'Computer': 2, 'P.E': 2, 'Art': 1, 'Music': 1, 'Arabic': 5, 'Religion': 2, 'Social Studies - Ar': 2,
            }),
            (('Grade 7', 'Grade 8'), {
                'English': 6, 'Math': 4, 'Science': 4, 'Social Studies - Eng': 3, '2nd Lang': 2,
                'Computer': 2, 'P.E': 1, 'Art/Music': 1, 'Arabic': 3, 'Religion': 2, 'Social Studies - Ar': 1,
            }),
            (('Grade 9',), {
                'English': 4, 'Creative Writing': 2, 'Math 1': 4, 'Biology': 4, 'World History 1': 4,
                '2nd Lang': 2, 'Computer': 1, 'P.E': 1, 'Art/Music': 1,
                'Arabic': 3, 'Religion': 2, 'Social Studies - Ar': 1,
            }),
            (('Grade 10',), {
                'English': 4, 'Creative Writing': 1, 'Math 2': 4, 'Chemistry': 4, 'World History 2': 4,
                '2nd Lang': 2, 'ICT': 1, 'P.E': 1, 'Art/Music': 1,
                'Arabic': 3, 'Religion': 2, 'Social Studies - Ar': 1, 'TW': 1,
            }),
            (('Grade 11',), {
                'English': 4, 'Creative Writing': 1, 'Math 3': 4, 'Physics': 4, 'Adv. Chem/Sociology': 4,
                '2nd Lang': 4, 'P.E': 2, 'Arabic': 3, 'Religion': 2, 'TW': 1,
            }),
            (('Grade 12',), {
                'Literature': 4, 'Adv. Math/Psychology': 4, 'Adv. Phys/Business': 4, 'Adv. Bio/Pol. Science': 4,
                'Computer': 4, 'Economy': 4, 'Arabic': 3, 'Religion': 1, 'TW': 1,
            }),
        ]
        for grades, expected in schedules:
            for grade in grades:
                with self.subTest(grade=grade):
                    rows = self.rows(grade)
                    expanded = {subject: hours for name, hours in expected.items() for subject in name.split('/')}
                    self.assertEqual({row.subject_id.name: row.weekly_hours for row in rows}, expanded)
                    self.assertEqual(len(rows), len(expanded))
                    total = 34 if grade in {f'Grade {i}' for i in range(1, 7)} else 29
                    self.assertEqual(sum(rows.mapped('class_weekly_hours')), total)
                    seed = self.env.ref('school_planning.timetable_american').line_ids.filtered(
                        lambda line: line.grade_id.name == grade
                    )
                    self.assertEqual(sum(seed.mapped('class_weekly_hours')), total)

    def test_new_prediction_keeps_supplied_hours(self):
        self.wizard.line_ids.write({'student_count': 350, 'annual_fee_per_student': 100})
        self.wizard.action_apply()
        for year in self.wizard._existing_forecast_years():
            for name, expected in (('KG1', 29), ('Grade 1', 34), ('Grade 7', 29), ('Grade 10', 29),
                                   ('Grade 11', 29), ('Grade 12', 29)):
                rows = year.subject_distribution_ids.filtered(lambda row: row.grade_level_id == self.grade(name))
                self.assertEqual(sum(rows.mapped('class_weekly_hours')), expected)
            teacher = year.employment_salary_ids.filtered(lambda row: row.staff_position_id.planning_role == 'teacher')
            self.assertEqual(teacher.employee_count, year.required_teachers)

    def test_choice_is_one_slot_and_survives_copy(self):
        self.seed()
        choice = self.rows('Grade 7').filtered('elective_group')
        self.assertEqual(set(choice.subject_id.mapped('name')), {'Art', 'Music'})
        self.assertEqual(set(choice.mapped('elective_group')), {'ELCT1'})
        self.assertEqual(sum(self.rows('Grade 7').mapped('class_weekly_hours')), 29)
        actual = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': self.year.academic_year_name,
            'start_date': self.year.start_date, 'end_date': self.year.end_date,
            'dataset_type': 'actual', 'forecast_year_id': self.year.id,
        })
        actual.action_load_from_forecast()
        copied = actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == choice.grade_level_id and row.elective_group
        )
        self.assertEqual(copied.subject_id, choice.subject_id)
        self.assertEqual(copied.mapped('elective_group'), choice.mapped('elective_group'))
        self.assertEqual(copied.timetable_id, choice.timetable_id)
        self.assertEqual(sum(actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == choice.grade_level_id).mapped('class_weekly_hours')), 29)
        self.year.action_freeze_baseline()
        with self.assertRaises(ValidationError):
            self.year.action_apply_timetables()

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
        english = self.rows('Grade 1').filtered(lambda row: row.subject_id.name == 'English')
        english.weekly_hours = 8
        self.assertEqual(salary.employee_count, 62)
        self.year.write({'classroom_weekly_hours': 35})
        self.assertEqual(english.weekly_hours, 8)
        self.assertEqual(self.year.required_teachers, 62)

    def test_teacher_breakdown_aggregates_grades_and_rounds_each_subject(self):
        english = self.school.subject_ids.filtered(lambda subject: subject.name == 'English')
        math = self.school.subject_ids.filtered(lambda subject: subject.name == 'Math')
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

        self.assertEqual(breakdown(), [['English', '47.00', '3'], ['Math', '25.00', '2']])
        self.assertEqual(self.year.required_teachers, 5)
        self.year.teacher_weekly_hours = 25
        self.assertEqual(breakdown(), [['English', '47.00', '2'], ['Math', '25.00', '1']])
        self.assertEqual(self.year.required_teachers, 3)
        english.name = '<English & Writing>'
        self.assertIn('<English & Writing>', breakdown()[0])
        self.assertNotIn('<English & Writing>', self.year.teacher_requirement_details)

    def test_teacher_breakdown_includes_both_elective_subjects(self):
        self.seed()
        self.env['school.grade.enrollment'].create({
            'academic_year_id': self.year.id, 'grade_level_id': self.grade('Grade 7').id, 'student_count': 50,
        })
        choice = self.rows('Grade 7').filtered('elective_group')
        tree = html.fromstring(self.year.teacher_requirement_details)
        rows = {row[0].text_content(): int(row[2].text_content()) for row in tree.xpath('//tbody/tr')}
        self.assertEqual(rows['Music'], 1)
        self.assertEqual(rows['Art'], 1)
        self.assertEqual(choice.mapped('total_teaching_hours'), [2, 2])
        self.assertEqual(sum(rows.values()), self.year.required_teachers)
        self.assertEqual(int(tree.xpath('//tfoot/tr/td[last()]')[0].text_content()), self.year.required_teachers)
        self.assertEqual(sum(choice.mapped('class_weekly_hours')), 1)
        self.assertEqual(sum(self.rows('Grade 7').mapped('class_weekly_hours')), 29)

    def test_senior_electives_share_hours_and_teachers(self):
        self.seed()
        self.env['school.grade.enrollment'].create([
            {'academic_year_id': self.year.id, 'grade_level_id': self.grade(grade).id, 'student_count': 25}
            for grade in ('Grade 11', 'Grade 12')
        ])
        self.year.teacher_weekly_hours = 3
        choices = self.year.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id.name in ('Grade 11', 'Grade 12') and row.elective_group
        )
        self.assertEqual(len(choices), 8)
        self.assertEqual(self.year.required_teachers, 36)
        for label, subjects in {
            'ELCT1': {'Adv. Math', 'Psychology'},
            'ELCT2': {'Adv. Phys', 'Business'},
            'ELCT3': {'Adv. Bio', 'Pol. Science'},
        }.items():
            self.assertEqual(set(self.rows('Grade 12').filtered(
                lambda row: row.elective_group == label).subject_id.mapped('name')), subjects)
        tree = html.fromstring(self.year.teacher_requirement_details)
        breakdown = {
            row[0].text_content(): (float(row[1].text_content()), int(row[2].text_content()))
            for row in tree.xpath('//tbody/tr')
        }
        for name in choices.subject_id.mapped('name'):
            self.assertEqual(breakdown[name], (4, 2))
        self.assertEqual(sum(hours for hours, count in breakdown.values()), 74)
        self.assertEqual(sum(count for hours, count in breakdown.values()), self.year.required_teachers)
        self.assertEqual(sum(self.rows('Grade 11').mapped('class_weekly_hours')), 29)
        self.assertEqual(sum(self.rows('Grade 12').mapped('class_weekly_hours')), 29)

    def test_elective_hours_are_scoped_by_grade_and_curriculum(self):
        art, music = [self.school.subject_ids.filtered(lambda subject: subject.name == name) for name in ('Art', 'Music')]
        ib_subject = self.env['school.subjects'].create({
            'school_id': self.school.id, 'name': 'PYP elective', 'display_order': 100,
            'preset_id': self.env.ref('school_planning.curriculum_ib_pyp').subject_preset_ids[0].id,
        })
        self.env['school.subject.distribution'].create([
            {'academic_year_id': self.year.id, 'grade_level_id': self.grade(grade).id,
             'subject_id': subject.id, 'weekly_hours': hours, 'elective_group': 'ELCT1'}
            for grade, subject, hours in (
                ('Grade 7', art, 1), ('Grade 7', music, 1), ('Grade 7', ib_subject, 3),
                ('Grade 8', art, 2), ('Grade 8', music, 1),
            )
        ])
        self.assertEqual(sum(self.rows('Grade 7').mapped('class_weekly_hours')), 4)
        self.assertEqual(sum(self.rows('Grade 8').mapped('class_weekly_hours')), 2)
        self.rows('Grade 8').filtered(lambda row: row.subject_id == music).weekly_hours = 4
        self.assertEqual(sum(self.rows('Grade 8').mapped('class_weekly_hours')), 4)
        self.rows('Grade 7').filtered(lambda row: row.subject_id == art).unlink()
        self.assertEqual(sum(self.rows('Grade 7').mapped('class_weekly_hours')), 4)

    def test_elective_migration_expands_legacy_slots_without_rewriting_approved_hours(self):
        timetable = self.env.ref('school_planning.timetable_american')
        lines = timetable.line_ids.filtered(lambda line: line.grade_id.name == 'Grade 7' and line.elective_group)
        presets = lines.subject_id
        primary = lines[0]
        lines[1:].unlink()
        primary.write({'elective_group': False, 'choice_subject_ids': [fields.Command.set(presets.ids)]})
        self.seed()
        row = self.rows('Grade 7').filtered(lambda row: row.subject_id.preset_id == primary.subject_id)
        subjects = self.school.subject_ids.filtered(lambda subject: subject.preset_id in presets)
        row.write({'weekly_hours': 2, 'choice_subject_ids': [fields.Command.set(subjects.ids)]})
        frozen = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': '2048-2049',
            'start_date': '2048-09-01', 'end_date': '2049-06-30', 'dataset_type': 'forecast', 'students_per_classroom': 25,
        })
        saved = row.copy({'academic_year_id': frozen.id, 'weekly_hours': 7})
        self.env['school.grade.enrollment'].create({
            'academic_year_id': frozen.id, 'grade_level_id': saved.grade_level_id.id, 'student_count': 50,
        })
        frozen.action_freeze_baseline()
        saved.flush_recordset(['total_teaching_hours'])
        self.cr.execute('UPDATE school_subject_distribution SET total_teaching_hours = 21 WHERE id = %s', (saved.id,))
        saved.invalidate_recordset(['total_teaching_hours'])
        before = saved.read(['subject_id', 'weekly_hours', 'total_teaching_hours'])
        totals = frozen.baseline_totals

        migration = run_path(str(Path(__file__).parents[1] / 'migrations' / '19.0.1.64.0' / 'post-migrate.py'))
        migration['migrate'](self.cr, '19.0.1.63.0')
        electives = self.rows('Grade 7').filtered('elective_group')
        self.assertEqual(set(electives.subject_id.mapped('name')), {'Art', 'Music'})
        self.assertEqual(electives.mapped('weekly_hours'), [2, 2])
        self.assertEqual(sum(electives.mapped('class_weekly_hours')), 2)
        self.assertEqual(sum(timetable.line_ids.filtered(
            lambda line: line.grade_id.name == 'Grade 7').mapped('class_weekly_hours')), 29)
        self.assertEqual(frozen.subject_distribution_ids, saved)
        self.assertEqual(saved.read(['subject_id', 'weekly_hours', 'total_teaching_hours']), before)
        self.assertEqual(frozen.baseline_totals, totals)
        migration['migrate'](self.cr, '19.0.1.63.0')
        self.assertEqual(self.rows('Grade 7').filtered('elective_group'), electives)
        actual = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': frozen.academic_year_name,
            'start_date': frozen.start_date, 'end_date': frozen.end_date,
            'dataset_type': 'actual', 'forecast_year_id': frozen.id,
        })
        actual.action_load_from_forecast()
        copied = actual.subject_distribution_ids.filtered(
            lambda item: item.grade_level_id == saved.grade_level_id and item.elective_group
        )
        self.assertEqual(set(copied.subject_id.mapped('name')), {'Art', 'Music'})
        self.assertEqual(sorted(copied.mapped('weekly_hours')), [0, 7])
        self.assertEqual(set(copied.mapped('elective_group')), {'ELCT1'})

    def test_explicit_apply_preserves_unsupported_grades_and_other_years(self):
        other = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': '2048-2049',
            'start_date': '2048-09-01', 'end_date': '2049-06-30', 'dataset_type': 'forecast',
        })
        subject = self.school.subject_ids[0]
        unsupported = self.env['school.grade.levels'].create({
            'school_id': self.school.id, 'group_id': self.grade('Grade 12').group_id.id,
            'name': 'Postgraduate', 'sort_order': 99,
        })
        keep = self.env['school.subject.distribution'].create([
            {'academic_year_id': year.id, 'grade_level_id': unsupported.id,
             'subject_id': subject.id, 'weekly_hours': 7}
            for year in (self.year, other)
        ])
        self.year.action_apply_timetables()
        self.assertEqual(keep.mapped('weekly_hours'), [7, 7])
        self.assertEqual(other.subject_distribution_ids, keep.filtered(lambda row: row.academic_year_id == other))
        self.assertEqual(sum(self.rows('KG1').mapped('weekly_hours')), 29)

    def test_curricula_without_timetables_keep_existing_distribution(self):
        for xmlid in ('curriculum_england', 'curriculum_ib_pyp', 'curriculum_ib_myp', 'curriculum_ib_dp'):
            curriculum = self.env.ref(f'school_planning.{xmlid}')
            self.school.curriculum_ids = [fields.Command.set(curriculum.ids)]
            self.wizard._ensure_subject_distribution(self.year, self.grades, self.school.subject_ids)
            self.assertFalse(self.year.uses_timetables)
            self.assertAlmostEqual(sum(self.rows('Grade 1').mapped('weekly_hours')), self.wizard.classroom_weekly_hours)
            self.assertEqual(len(self.rows('Grade 1')), len(self.school.subject_ids))
        self.school.curriculum_ids = [fields.Command.set((self.curriculum | curriculum).ids)]
        self.assertTrue(self.year.timetable_ids)
        self.year.action_apply_timetables()
        self.assertEqual(sum(self.rows('Grade 1').mapped('weekly_hours')), 34)
        self.school.curriculum_ids = [fields.Command.set(curriculum.ids)]
        with self.assertRaises(ValidationError):
            self.year.action_apply_timetables()

    def test_timetable_catalog_edits_and_deletions_survive_updates(self):
        science = self.env.ref('school_planning.subject_us_science')
        science.name = 'Integrated Science'
        self.env.ref('school_planning.subject_us_tw').unlink()
        convert_file(self.env, 'school_planning', 'data/american_subjects.xml', {}, mode='update')
        self.assertEqual(science.name, 'Integrated Science')
        self.assertFalse(self.env.ref('school_planning.subject_us_tw', raise_if_not_found=False))
        self.seed()
        self.assertIn('Science', self.rows('Grade 1').subject_id.mapped('name'))

    def test_editable_timetable_seed_is_used_only_on_load(self):
        timetable = self.env.ref('school_planning.timetable_american')
        self.seed()
        line = timetable.line_ids.filtered(
            lambda line: line.grade_id.name == 'Grade 1' and line.subject_id.name == 'Math'
        ).ensure_one()
        line.weekly_hours = 8
        self.assertEqual(sum(self.rows('Grade 1').mapped('weekly_hours')), 34)
        self.year.action_apply_timetables()
        self.assertEqual(sum(self.rows('Grade 1').mapped('weekly_hours')), 37)
        line.unlink()
        self.year.action_apply_timetables()
        self.assertNotIn('Math', self.rows('Grade 1').subject_id.mapped('name'))
        self.env['school.timetable']._install_american_timetable()
        self.assertFalse(line.exists())

    def test_screenshot_migration_replaces_only_american_seed(self):
        self.seed()
        timetable = self.env.ref('school_planning.timetable_american')
        ib = self.env.ref('school_planning.curriculum_ib_pyp')
        ib_subject = ib.subject_preset_ids[0]
        ib_subject.name = 'Custom PYP subject'
        other = self.env['school.timetable'].create({
            'name': 'Custom PYP Timetable', 'curriculum_id': ib.id,
            'line_ids': [fields.Command.create({
                'grade_id': self.env.ref('school_planning.grade_level_preset_grade_1').id,
                'subject_id': ib_subject.id, 'weekly_hours': 6,
            })],
        })
        self.env.ref('school_planning.subject_us_ela').name = 'Old English seed'
        self.school.subject_ids.filtered(lambda subject: subject.name == 'English').name = 'School English'
        loaded = self.year.subject_distribution_ids
        snapshot = loaded.read(['subject_id', 'choice_subject_ids', 'weekly_hours', 'timetable_id'])
        timetable.line_ids.unlink()
        timetable.line_ids = [fields.Command.create({
            'grade_id': self.env.ref('school_planning.grade_level_preset_grade_1').id,
            'subject_id': self.env.ref('school_planning.subject_us_quran').id, 'weekly_hours': 99,
        })]
        self.env.ref('school_planning.subject_us_tw').unlink()

        migration = run_path(str(Path(__file__).parents[1] / 'migrations' / '19.0.1.62.0' / 'post-migrate.py'))
        migration['migrate'](self.cr, '19.0.1.61.0')

        self.assertEqual(self.env.ref('school_planning.timetable_american'), timetable)
        self.assertEqual(self.env.ref('school_planning.subject_us_ela').name, 'English')
        self.assertEqual(other.line_ids.weekly_hours, 6)
        self.assertEqual(ib_subject.name, 'Custom PYP subject')
        self.assertEqual(self.year.subject_distribution_ids, loaded)
        self.assertEqual(loaded.read(['subject_id', 'choice_subject_ids', 'weekly_hours', 'timetable_id']), snapshot)
        self.assertNotIn('Quran', timetable.line_ids.subject_id.mapped('name'))
        self.assertEqual(sum(timetable.line_ids.filtered(
            lambda line: line.grade_id.name == 'Grade 12').mapped('class_weekly_hours')), 29)

        line = timetable.line_ids.filtered(lambda line: line.subject_id.name == 'TW')[-1]
        line.weekly_hours = 3
        convert_file(self.env, 'school_planning', 'data/american_subjects.xml', {}, mode='update')
        self.env['school.timetable']._install_american_timetable()
        self.assertEqual(line.weekly_hours, 3)

    def test_multiple_curricula_load_their_own_timetables_and_preserve_unrelated_rows(self):
        ib = self.env.ref('school_planning.curriculum_ib_pyp')
        preset = ib.subject_preset_ids[0]
        timetable = self.env['school.timetable'].create({
            'name': 'PYP Timetable', 'curriculum_id': ib.id,
            'line_ids': [fields.Command.create({
                'grade_id': self.env.ref('school_planning.grade_level_preset_grade_1').id,
                'subject_id': preset.id, 'weekly_hours': 6,
            })],
        })
        self.school.curriculum_ids = [fields.Command.link(ib.id)]
        manual = self.env['school.subjects'].create({
            'school_id': self.school.id, 'name': 'Local elective', 'display_order': 100,
        })
        keep = self.env['school.subject.distribution'].create({
            'academic_year_id': self.year.id, 'grade_level_id': self.grade('Grade 1').id,
            'subject_id': manual.id, 'weekly_hours': 2,
        })
        self.year.action_apply_timetables()
        self.assertEqual(self.year.timetable_ids, self.school._matching_timetables())
        self.assertEqual(sum(self.rows('Grade 1').filtered('timetable_id').mapped('weekly_hours')), 40)
        self.assertEqual(keep.weekly_hours, 2)
        self.assertEqual(self.rows('Grade 1').filtered(lambda row: row.timetable_id == timetable).weekly_hours, 6)
        self.env['school.grade.enrollment'].create({
            'academic_year_id': self.year.id, 'grade_level_id': self.grade('Grade 1').id, 'student_count': 25,
        })
        self.year.teacher_weekly_hours = 1
        self.assertEqual(self.year.required_teachers, 42)
        self.year.classroom_weekly_hours = 30
        self.assertEqual(sum(self.rows('Grade 1').mapped('weekly_hours')), 42)
        self.assertEqual(self.year.required_teachers, 42)
        self.assertIn(preset.name, html.fromstring(self.year.teacher_requirement_details).text_content())

    def test_timetable_seed_validation(self):
        timetable = self.env.ref('school_planning.timetable_american')
        line = timetable.line_ids[0]
        line.weekly_hours = 0
        for value in (-1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValidationError), self.cr.savepoint():
                line.weekly_hours = value
        with self.assertRaises(ValidationError), self.cr.savepoint():
            line.copy()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            line.subject_id = self.env.ref('school_planning.curriculum_ib_pyp').subject_preset_ids[0]
        with self.assertRaises(ValidationError), self.cr.savepoint():
            timetable.curriculum_id = self.env.ref('school_planning.curriculum_ib_pyp')

    def test_prediction_loads_multiple_timetables_without_equal_hour_normalization(self):
        ib = self.env.ref('school_planning.curriculum_ib_pyp')
        self.env['school.timetable'].create({
            'name': 'PYP Timetable', 'curriculum_id': ib.id,
            'line_ids': [fields.Command.create({
                'grade_id': self.env.ref('school_planning.grade_level_preset_grade_1').id,
                'subject_id': ib.subject_preset_ids[0].id, 'weekly_hours': 6,
            })],
        })
        self.school.curriculum_ids = [fields.Command.link(ib.id)]
        self.env['school.subjects'].create({'school_id': self.school.id, 'name': 'Unassigned elective', 'display_order': 100})
        self.wizard.line_ids.write({'student_count': 350, 'annual_fee_per_student': 100})
        self.wizard.action_apply()
        for year in self.wizard._existing_forecast_years():
            rows = year.subject_distribution_ids.filtered(lambda row: row.grade_level_id == self.grade('Grade 1'))
            self.assertEqual(sum(rows.mapped('weekly_hours')), 40)
            self.assertEqual(len(rows), len(set(rows.subject_id.ids)))
            teacher = year.employment_salary_ids.filtered(lambda row: row.staff_position_id.planning_role == 'teacher')
            self.assertEqual(teacher.employee_count, year.required_teachers)

    def test_actual_templates_keep_zero_hours_and_do_not_duplicate_choices(self):
        manual = self.env['school.subjects'].create({
            'school_id': self.school.id, 'name': 'Unassigned elective', 'display_order': 100,
        })
        actual = self.env['school.academic.years'].create({
            'school_id': self.school.id, 'academic_year_name': self.year.academic_year_name,
            'start_date': self.year.start_date, 'end_date': self.year.end_date, 'dataset_type': 'actual',
        })
        self.assertFalse(any(actual.subject_distribution_ids.mapped('weekly_hours')))
        self.assertNotIn(manual, actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == self.grade('Grade 7')
        ).subject_id)
        choice = actual.subject_distribution_ids.filtered(
            lambda row: row.grade_level_id == self.grade('Grade 7') and row.elective_group
        )
        self.assertEqual(set(choice.subject_id.mapped('name')), {'Art', 'Music'})
        self.assertEqual(choice.mapped('weekly_hours'), [0, 0])
        before = actual.subject_distribution_ids
        actual.action_prepare_actual_entry()
        self.assertEqual(actual.subject_distribution_ids, before)

    def test_new_timetable_does_not_change_existing_non_american_requirements_before_loading(self):
        ib = self.env.ref('school_planning.curriculum_ib_pyp')
        self.school.curriculum_ids = [fields.Command.set(ib.ids)]
        self.env['school.grade.enrollment'].create({
            'academic_year_id': self.year.id, 'grade_level_id': self.grade('Grade 1').id, 'student_count': 25,
        })
        before = self.year.required_teachers
        timetable = self.env['school.timetable'].create({
            'name': 'PYP Timetable', 'curriculum_id': ib.id,
            'line_ids': [fields.Command.create({
                'grade_id': self.env.ref('school_planning.grade_level_preset_grade_1').id,
                'subject_id': ib.subject_preset_ids[0].id, 'weekly_hours': 60,
            })],
        })
        self.assertIn(timetable, self.year.timetable_ids)
        self.assertEqual(self.year.required_teachers, before)
        self.year.action_apply_timetables()
        self.assertEqual(self.year.required_teachers, 3)
        timetable.active = False
        self.assertNotIn(timetable, self.year.timetable_ids)
        self.assertEqual(self.year.required_teachers, 3)
        self.year.classroom_weekly_hours = 30
        self.assertEqual(self.year.subject_distribution_ids.weekly_hours, 60)
