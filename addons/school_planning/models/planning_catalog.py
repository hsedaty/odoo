from odoo import api, models


# A string denotes an allocated item; a tuple specifies a fixed item.
CATALOG = {
    'income': {
        'Incomes': {
            None: [('Tuition Fees', 'fixed')],
            'Admission Fees': ['Admission Exam Fees', 'Enrollment Fees'],
            'Other Incomes': [
                ('Activity fees', 'fixed'), 'Resource Fees (Books, Booklets)', 'Technology Fees',
                'Transportation Fees', 'Uniform Fees', 'Cafeteria Fees', 'Extra Course Fees',
                'Competition Fees', 'Club Fees', 'Trip Fees',
            ],
        },
    },
    'expense': {
        'Official Payments': {
            'Tax Payments': ['Income Taxes', '1% Revenue Contribution', 'Property Taxes'],
            'Ministry Payments': [('School License Renewal', 'fixed'), 'Book Approvals',
                                  'Educational Directory Forms and Document Stamping Fees'],
            'Accreditation Fees': [('Cognia Candidacy Fee', 'fixed'), ('Cognia Annual Membership Fee', 'fixed'),
                                   ('Cognia Engagement Review Fee', 'fixed')],
        },
        'Administrative Expenses': {
            'Discounts and Refunds': ['Sibling Discount (-)', 'Early Enrollment Discount (-)', 'Full Payment Discount (-)',
                                      'Administrative Discounts', 'Scholarships', 'Refunds'],
            None: ['Bank Commissions and Fees', 'Marketing, Promotional Expenses', 'Health, Medication, Treatment Expenses',
                   'Office Supplies, Furniture, Other Tools', 'Domestic Travel, Uber and Taxi Expenses',
                   'Shipping, Freight and Carrying Expenses', 'Hospitality and Guests', 'Tips and Bonuses'],
        },
        'Utility Expenses': {
            None: [('Internet Bills', 'fixed'), 'Mobile Phone Bills', ('Landline Bills', 'fixed'),
                   'Electric Bills', ('Water Bills', 'fixed')],
        },
        'Maintenance Expenses': {
            'Building Maintenance and Repair': ['Building Repairs (Plumbing, Carpentary)', 'Painting',
                'Electrical Maintenance and Repair', 'Air Conditioners', 'Fire Fighter System', 'Generator', 'Elevator'],
            'Device Maintenance and Repair': ['Electronic Device Maintenance and Repair', 'Network',
                                               'Cameras (Surveillance System)', 'Photocopy Machine'],
            None: [('Landscaping Expenses', 'fixed')],
        },
        'Student Activity Expenses': {
            None: ['Educational and Fun Trip Expenses', 'Sport Days Expenses', 'In-school Activities',
                   'Annual Shows', 'Graduation Ceremonies'],
        },
        'Learning Facilities and Resource Expenses': {
            'Books': [('Hardcopy Books', 'fixed'), ('Printed Worksheets and Booklets', 'fixed'), ('Ministry Books', 'fixed')],
            'Digital Resource Expenses': [('IXL', 'fixed'), ('HMH', 'fixed'), ('MAP Growth', 'fixed'), ('myON', 'fixed')],
            'Education Products and Management Solution Expenses': [
                ('JupiterEd', 'fixed'), ('JotForm', 'fixed'), ('Galaxy', 'fixed'),
                ('CollegeBoard', 'fixed'), ('ASC Timetable', 'fixed')],
            None: ['Stationary Tools', 'Educational Gifts and Rewards', ('Sport, Art and Music Room Equipments and Supplies', 'fixed'),
                   ('Laboratory Equipments and Supplies', 'fixed'), 'Printing Posters, Banner and Decoration Tools and Supplies'],
        },
        'Operational Expenses': {None: ['Cleaning and Hygiene']},
        'Outsource Services and Products': {None: ['Photocopy Supplies, Photocopy Machine Rent, Maintanence',
                                                   'Consultation Services']},
    },
}

FIXED_SECTIONS = {'Ministry Payments', 'Books', 'Digital Resource Expenses',
                  'Education Products and Management Solution Expenses'}


class PredictionSeedConfiguration(models.Model):
    _inherit = 'school.prediction.seed.configuration'

    @api.model
    def _install_planning_catalog(self):
        config = self.env.ref('school_planning.prediction_seed_configuration')
        # Preserve old selections and amounts, but exclude the old catalog from new forecasts.
        config.operational_seed_ids.write({'active': False})
        config.expense_ids.filtered('is_detailed_category').write({'active': False})
        category_model = self.env['school.prediction.seed.expense']
        item_model = self.env['school.prediction.operational.seed']
        for kind, groups in CATALOG.items():
            for order, (group_name, sections) in enumerate(groups.items(), 1):
                group = category_model.create({
                    'configuration_id': config.id, 'name': group_name, 'catalog_type': kind,
                    'is_detailed_category': True, 'display_order': order * 10,
                })
                for section_order, (section_name, entries) in enumerate(sections.items(), 1):
                    category = group
                    if section_name:
                        category = category_model.create({
                            'configuration_id': config.id, 'name': section_name, 'catalog_type': kind,
                            'is_detailed_category': True, 'parent_id': group.id, 'display_order': section_order * 10,
                            'price_type': 'fixed' if section_name in FIXED_SECTIONS else 'allocated',
                        })
                    for entry in entries:
                        name, price_type = entry if isinstance(entry, tuple) else (entry, 'allocated')
                        item_model.create({
                            'configuration_id': config.id, 'category_seed_id': category.id,
                            'name': name, 'price_type': price_type,
                            'basis': 'student' if kind == 'income' and group_name == 'Incomes'
                                                   and not section_name and name == 'Tuition Fees' else 'fixed',
                            'replaces_tuition': kind == 'income' and group_name == 'Incomes'
                                                and not section_name and name == 'Tuition Fees',
                        })
