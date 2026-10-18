def migrate(cr, version):
    cr.execute("""
        UPDATE school_academic_years AS year
           SET students_per_classroom = CASE WHEN year.students_per_classroom > 0 THEN year.students_per_classroom
                   ELSE COALESCE((SELECT MIN(enrollment.max_students_per_class)
                                    FROM school_grade_enrollment AS enrollment
                                   WHERE enrollment.academic_year_id = year.id
                                  HAVING COUNT(DISTINCT enrollment.max_students_per_class) = 1),
                                 school.default_students_per_classroom) END,
               classroom_weekly_hours = CASE WHEN year.classroom_weekly_hours > 0 THEN year.classroom_weekly_hours ELSE school.default_classroom_weekly_hours END,
               teacher_weekly_hours = CASE WHEN year.teacher_weekly_hours > 0 THEN year.teacher_weekly_hours ELSE school.default_teacher_weekly_hours END
          FROM school_schools AS school
         WHERE school.id = year.school_id
           AND (year.students_per_classroom = 0 OR year.classroom_weekly_hours = 0 OR year.teacher_weekly_hours = 0)
    """)