from osv import osv, fields

import logging
log = logging.getLogger('csv.import.profile')

class csv_profile_line(osv.osv):
    _inherit = 'import.profile.line'

    def __init__(self, pool, cr):
        def _get_actions(self, cursor, uid, context=None):
            res = super(csv_profile_line, self)._get_actions(cursor, uid, context)
            res += (
                ('newline','Goto next line'),
            )
            return res
        self._columns['action'].selection = _get_actions
        return super(csv_profile_line, self).__init__(pool, cr)
csv_profile_line()
