from osv import osv
from tools.translate import _
from agaplan_import.models.import_parser import ParserInst

import logging
log = logging.getLogger('import.parser.csv')

import csv
from io import StringIO
try:
    from collections import OrderedDict # Python 2.7 and upwards
except ImportError:
    from odict import OrderedDict

def utf8_encoder(csv_data):
    for line in csv_data:
        yield line.encode('utf8')

class CsvParserInst(ParserInst):
    pool = None
    cursor = None
    uid = None
    context = None

    def __init__(self, cursor, uid, context, pool, **args):
        super(CsvParserInst, self).__init__(cursor, uid, context, pool)
        self.arguments = args
        self.dialect = str(args.get('csv_dialect', None))
        self.delimiter = str(args.get('csv_delimiter', ', '))
        self.quotechar = str(args.get('csv_quotechar', '"'))
        self.skiplines = int(args.get('csv_skip', 1))

        self.csv_iter = None
        self.csv_line = None
        self.csv_field = None

        self.rec_dict = {}
        self.line = 0
        self.filename = None
        self.data = None

    def __repr__(self):
        return "CsvParserInst(%(cursor)s, %(uid)s, %(context)s, %(arguments)s)" % self.__dict__

    def check_xml_id(self, xml_id, model):
        """
            Function takes an xml_id and model as argument and returns
            the database id if found or False if not found
        """
        log.debug("Finding %s in %s", xml_id, model)
        search = [
            ('name', '=', xml_id),
            ('model', '=', model),
        ]
        if '.' in xml_id:
            mod, xml_id = xml_id.split('.')
            search = [
                ('name', '=', xml_id),
                ('model', '=', model),
                ('module', '=', mod),
            ]
        search_res = self.pool.get('ir.model.data').search(self.cursor, self.uid, search, context=self.context)
        if search_res:
            if len(search_res) > 1:
                log.warn("Search for xml_id '%s' yielded %d results", xml_id, len(search_res))
            res = self.pool.get('ir.model.data').browse(self.cursor, self.uid, search_res, context=self.context)[0].res_id
            log.debug("Found res_id: %d", res)
            return res
        else:
            log.warn("Search for xml_id '%s' yielded no results", xml_id)
            return False

    def hook_post_field(self, imp_line, csv_field, field_dict):
        """
            Hook for future extensions
            @param imp_line import.profile.line which was used
            @param csv_field value of the csv field
            @param field_dict the current field definiton
            @return field_dict the altered field definition
        """
        log.debug("hook_post_field: %s, %s, %s", imp_line, csv_field, field_dict)
        return field_dict

    def parse(self, name, data, imp_profile):
        """
            Main import entry point
            @param name The filename, used for xml_id generation and feedback
            @param data The file data, not in base64 encoding
            @param imp_profile The profile to use for importing
            @returns A dictionary used to create osv_memory records in import.wizard
        """
        self.filename = name.replace('.', '_')
        fileptr = StringIO(data.decode('utf8'))
        self.data = csv.reader( utf8_encoder(fileptr),
            #~ dialect=self.dialect, # TODO fix how dialect should be passed/not-passed
            delimiter=self.delimiter,
            quotechar=self.quotechar,
        )
        self.line = 1
        for header_line in xrange(self.skiplines):
            header_line = self.data.next()
            if self.line == 1:
                header = header_line
                log.info("Registered %s as csv header", header)
            log.debug('Skipped over line : %s', header_line)
            self.line += 1

        line_obj = self.pool.get('import.profile.line')
        line_ids = line_obj.search(self.cursor, self.uid, [('parent_id','=',False),('action','=','record'),('profile_id','=',imp_profile.id)])
        prof_iter = iter(line_obj.browse(self.cursor, self.uid, line_ids))
        self.rec_dict = OrderedDict()
        for self.csv_line in self.data:
            # The main loop over each line in the csv
            try:
                imp_rec = prof_iter.next()
            except StopIteration:
                log.debug("repeating last profile line")

            if imp_rec.action != 'record':
                raise osv.except_osv( _("Invalid profile"), _("The csv parser expects one record type line to start with") )

            xml_id = '%s_line_%d' % (self.filename, self.line) #, imp_rec.model_id.model.replace('.', '_'))
            if len(xml_id) > 128:
                raise osv.except_osv( _("Too long"), _("The generated xml_id was too long: %d (%s)") % (len(xml_id), xml_id) )

            try:
                self.create_sub({}, imp_rec, xml_id) # Kickoff for the recursive calls
                self.line += 1
            except Exception, exc:
                log.error("Error importing '%s' file", exc_info=True)
                raise osv.except_osv( _("Import Error"), _("Could not import file '%s'\n%s") % (name, exc) )

        res = []
        for frec in self.rec_dict.values():
            frec['field_ids'] = frec.get('field_ids', [])
            for ffield in frec['field_dict'].values():
                frec['field_ids'] += [(0, 0, ffield)]
            del frec['field_dict']
            res.append( (0, 0, frec) )
        return res

    def match_sub(self, value, imp_line):
        """
            Used for sub_action == 'findid'
            We presume the @param value is a link to
            a related field described in imp_line.
        """
        match_res = self.check_xml_id( value, imp_line.field_id.relation )
        if not match_res:
            # Not an xml id it seems, check if we can find a database id match
            try:
                log.warn('No result on xml_id %s', value)
                match_res = self.pool.get( imp_line.field_id.relation ).browse(self.cursor, self.uid, int(value), context=self.context)
                log.info('Linking to %s', match_res)
                match_res = match_res.id
            except ValueError:
                # Means the csv_field was not an integer
                log.warn('No luck converting %s to an integer', value)
            except KeyError:
                # Means search had no results
                log.warn('No luck searching for %d in %s', int(value), imp_line.field_id.relation)
        if not match_res:
            log.error("Could not find %s as xml_id or as database id in %s", value, imp_line.field_id.relation)
            return {}
            #raise osv.except_osv( _("Invalid File"), _("While importing we could not find %s in table %s to link with") % (value, imp_line.field_id.relation) )
        return {
            'line_id': imp_line.id,
            'field_id': imp_line.field_id.id,
            'value': str(match_res),
        }

    def create_sub(self, cur_field, imp_line, xml_id, parent_xml=None):
        """
            sub_action == 'create'
            User wants to create the sub_record, we should put the
            result of this in the rec_dict
        """
        sub_xml_id = xml_id
        if imp_line.model_id:
            sub_xml_id = '%s_%s' % (xml_id, imp_line.model_id.model.replace('.', '_'))
        if imp_line.field_id:
            sub_xml_id = '%s_%s' % (xml_id, imp_line.field_id.name.replace('.', '_'))

        log.info("Generated xml_id: %s for line %s", sub_xml_id, imp_line)

        if len(sub_xml_id) > 128:
            raise osv.except_osv( _("Too long"), _("The generated xml_id was too long: %d (%s)") % (len(sub_xml_id), sub_xml_id) )

        if imp_line.action == 'record':
            self.rec_dict[sub_xml_id] = {
                'xml_id': sub_xml_id,
                'rec_id': self.check_xml_id( sub_xml_id, imp_line.model_id.model ),
                'rec_model': imp_line.model_id.id,
                'field_ids': [],
                'field_dict': {},
                'line_id': imp_line.id,
                'notes': str(self.csv_line),
            }
            # Fetch a line from the csv so the subfields
            self.csv_iter = iter(self.csv_line)
            self.next_column()
        elif imp_line.action == 'field':
            # Simple value field without childs
            cur_field = {
                'line_id': imp_line.id,
                'field_id': imp_line.field_id.id,
                'value': self.csv_field,
            }
        elif imp_line.action == 'skip':
            self.next_column()
            return {}

        # Don't forget to link one of the 2 sides via xml_id
        if imp_line.field_id.ttype == 'one2many':
            rem_model_id = self.pool.get('ir.model').search(self.cursor, self.uid,
                [('model', '=', imp_line.field_id.relation)])
            rem_field_id = self.pool.get('ir.model.fields').search(self.cursor, self.uid,
                [('model_id', 'in', rem_model_id),('name', '=', imp_line.field_id.relation_field)])
            rem_field = self.pool.get('ir.model.fields').browse(self.cursor, self.uid, rem_field_id[0])
            self.rec_dict[sub_xml_id] = {
                'line_id': imp_line.id,
                'xml_id': sub_xml_id,
                'rec_id': self.check_xml_id( sub_xml_id, imp_line.field_id.relation ),
                'rec_model': rem_model_id[0],
                'field_dict': {},
                'field_ids': [
                    (0,0,{
                        'line_id': imp_line.id,
                        'field_id': rem_field.id,
                        'value': parent_xml,
                    }),
                ],
            }
        elif imp_line.field_id.ttype == 'many2one':
            rem_model_id = self.pool.get('ir.model').search(self.cursor, self.uid, [('model', '=', imp_line.field_id.relation)])
            self.rec_dict[sub_xml_id] = {
                'line_id': imp_line.id,
                'xml_id': sub_xml_id,
                'rec_id': self.check_xml_id( sub_xml_id, imp_line.field_id.relation ),
                'rec_model': rem_model_id[0],
                'field_dict': {},
                'field_ids': [],
            }
            # We ensure the xml_id record is readded after the many2one
            # because of the reference to a sub_xml_id which we just now added
            # Remember, this is because we use OrderedDict for self.rec_dict
            readd = self.rec_dict[parent_xml or xml_id]
            del self.rec_dict[parent_xml or xml_id]
            self.rec_dict[parent_xml or xml_id] = readd
            cur_field = {
                'line_id': imp_line.id,
                'field_id': imp_line.field_id.id,
                'value': sub_xml_id,
            }
        elif imp_line.field_id.ttype == 'many2many':
            # What about many2many TODO?
            raise NotImplementedError("Not yet implemented create_sub many2many")
            # rem_model_id = self.pool.get('ir.model').search(self.cursor, self.uid, [('model', '=',imp_line.field_id.relation)])

        # Now start looping on child_ids and create fields for the rec_dict[sub_xml_id]
        for sub in imp_line.child_ids:
            sub_field = {
                'line_id': sub.id,
                'field_id': sub.field_id.id,
                'value': self.csv_field,
            }

            if sub.action == 'skip':
                log.debug("Skipping column '%s'", field.value)
            elif sub.action == 'xmlid':
                # We copy the original record to our new one
                self.rec_dict[self.csv_field] = self.rec_dict[sub_xml_id]

                # TODO ? Check any sub fields for references to old sub_xml_id ?

                # Remove old sub_xml_id record
                del self.rec_dict[sub_xml_id]

                # Save our current columns as the new sub_xml_id
                sub_xml_id = self.csv_field

                # Update the dictionary
                log.debug("About to update dictionary: %s", self.rec_dict[sub_xml_id])
                self.rec_dict[sub_xml_id].update({
                    'xml_id': sub_xml_id,
                    'rec_id': self.check_xml_id( sub_xml_id, imp_line.model_id.model ),
                })
            elif sub.action == 'field':
                if sub.sub_action == 'findid':
                    if self.delimiter in self.csv_field:
                        log.debug("Found a multi-xml field: %s", self.csv_field)
                    for multi_value in self.csv_field.split(self.delimiter):
                        sub_field = self.match_sub( multi_value, sub )
                        sub_field = self.hook_post_field(sub, multi_value, sub_field)
                        if sub_field:
                            self.rec_dict[sub_xml_id]['field_dict'][str(sub.id)+multi_value] = sub_field
                if sub.sub_action == 'find':
                    sub_field = self.find_sub( sub_field, sub, sub_xml_id )
                if sub.sub_action == 'create':
                    sub_field = self.create_sub( sub_field, sub, sub_xml_id, sub_xml_id )

                sub_field = self.hook_post_field(sub, self.csv_field, sub_field)
                if sub_field:
                    self.rec_dict[sub_xml_id]['field_dict'][sub.id] = sub_field
            elif sub.action == 'record':
                raise ValueError("CSV Parser does not allow nested records to be imported")

            self.next_column()

        if imp_line.field_id.ttype == 'one2many':
            return False # No need to create any field in the model cause it was one2many
        return cur_field

    def find_sub(self, cur_field, imp_line, xml_id):
        """
            sub_action == 'find'
            User tells us to go search for a record to link with based on
            some sub record definitions.
        """
        search_args = []
        for sub in imp_line.child_ids:
            search_args += [(sub.field_id.name, 'ilike', '%%%s%%' % self.csv_field)]
            if len( imp_line.child_ids ) > 1:
                # Only need to read next column if we have more childs than 1
                self.next_column()

        match_res = self.pool.get(imp_line.field_id.relation).search(self.cursor, self.uid, search_args, context=self.context)
        log.debug("Looking in '%s' for %s => %s", imp_line.field_id.relation, search_args, match_res)
        if not match_res:
            log.warn("Nothing found in '%s' when looking for %s", imp_line.field_id.relation, search_args)
            # Pass / raise / return ?
        if imp_line.field_id.ttype == 'many2one':
            if len(match_res) > 1:
                log.warn("When finding records in '%s' we found %d results, using first one", imp_line.field_id.model, len(match_res))
            cur_field['value'] = str(match_res[0])
        if imp_line.field_id.ttype == 'one2many':
            # Search for record in im
            # TODO Should be simple, search in relation field model,
            # alter the relation_field column to point to the current record
            raise NotImplementedError("Not implemented yet find_sub one2many")
        if imp_line.field_id.ttype == 'many2many':
            for found in match_res:
                self.rec_dict[xml_id]['field_ids'] += [(0, 0, {
                    'line_id': imp_line.id,
                    'field_id': imp_line.field_id.id,
                    'value': found,
                })]
            return False # To avoid adding duplicate field
        return cur_field

    def next_column(self):
        """
            Reads the next column and stores it in self.csv_field
        """
        try:
            self.csv_field = self.csv_iter.next()
            log.debug("New column value: %s", self.csv_field)
            return True
        except StopIteration:
            log.debug("Reached end of line, column value still: %s", self.csv_field)
            return False # End of line but possibly also end of childs

class csv_parser(osv.osv):
    _inherit = 'import.parser'

    def import_csv(self, cursor, uid, ids, arguments, context):
        return CsvParserInst(cursor, uid, context, self.pool, **arguments)
csv_parser()

class csv_parser_argument(osv.osv):
    _inherit = 'import.parser.argument'

    def _get_validation_context(self, cursor, uid, ids, context=None):
        """
            We add the 'csv' keyword to the validation context
        """
        res = super(csv_parser_argument, self)._get_validation_context(cursor, uid, ids, context)
        res.update({
            'csv': csv,
        })
        return res
csv_parser_argument()
