{
    'name': 'Agaplan Import CSV',
    'version': '0.1',
    'description': """
    This module allows you to import various file formats to any model.
    You have to define an import type (file definition) and an import profile.

    The import profile will define which fields to fill and which to use for
    matching existing data.
    """,
    'category': 'Generic Modules/Import',
    'author': 'Agaplan',
    'website': 'http://www.agaplan.eu',
    'depends': [
        'agaplan_import',
    ],
    'init': [],
    'update_xml': [
        'agaplan_csv_parser.xml',
    ],
    'demo': [
        'demo/csv_demo.xml'
    ],
    'test': [],
    'installable': True,
}
# vim:sts=4:et
