import logging
logger = logging.Logger('cr wiki')
import re
from copy import deepcopy

from ..cr import pyPage
from .logger_config import logger

INFOBOX_APP_PARAM_NAMES = ['First', 'Last', 'Stream', 'Television', 'Comic', 'Other']


class pyCharacter(pyPage):
    @property
    def appearances_section(self):
        return self.get_section_by_heading('Appearances and mentions')

    @property
    def infobox_appearances_raw(self):
        infobox_app_params = [
            x for x in self.infobox.params
            if any([x.name.matches(y) for y in INFOBOX_APP_PARAM_NAMES])
        ]
        return infobox_app_params

    @property
    def infobox_appearances(self):
        return self.process_infobox_appearances()

    @property
    def appearances(self):
        if not hasattr(self, '_appearances') or not self._appearances:
            self._appearances = self.get_appearances()
        return self._appearances

    def get_appearances(self):
        appearance_dicts = []
        if not self.appearances_section:
            return appearance_dicts
        appearances = [t for t in deepcopy(self.appearances_section.filter_templates())
                       if t.name.matches('appearance')]
        for app in appearances:
            modifiers = []
            fc_dict = {}
            for param in app.params:
                if param.name == '1':
                    fc_dict['work'] = param.value.strip()
                elif param.name == '2':
                    fc_dict['status'] = param.value.strip()
                else:
                    modifiers.append(param.value.strip())
            fc_dict['modifiers'] = modifiers
            assert fc_dict, logger.debug(f"Invalid appearance object in {self.title}: {app}")
            if not fc_dict.get('status'):
                fc_dict['status'] = 'appear'
            fc_dict['raw_description'] = str(app)
            fc_dict['name'] = self.title()
#             if [x for x in self.categories() if x.title() == 'Category:Player characters']:
            # TO DO: get from the player characters dict instead
            if (self.infobox.has_param('Type') and
                self.infobox['Type'].value and
                self.infobox['Type'].value.matches('Player Character')):
                fc_dict.update({
                    'is_pc': True,
                })
            appearance_dicts.append(fc_dict)

        return appearance_dicts

    def process_infobox_appearances(self):
        infobox_apps = {}
        for param in self.infobox_appearances_raw:
            param_name = str(param.name).strip()
            infobox_apps[param_name] = process_appearance_plainlist(param.value)
        return infobox_apps

    @property
    def episodes(self):
        return [x['work'] for x in self.appearances]


def process_plainlist(wikicode):
    '''For handling a bulleted list, whether wrapped in plainlist or not.
    Can also return a single item list.'''
    z = wikicode
    temps = wikicode.filter_templates()
    if temps and temps[0].name.matches('plainlist'):
        z = temps[0].params[0]
    z = [x.strip() for x in z.split('*') if x.strip()]
    return z


def process_appearance_plainlist(wikicode):
    '''Parses the specific formatting of appearances in Infobox Character'''
    list_items = process_plainlist(wikicode)
    item_dict = {}
    for item in list_items:
        sub_items = [x for x in re.split('(:\<br\/\>|(?<![\w])\s)',
                                         item,
                                         maxsplit=1)
                     if x.strip()]
        item_dict[sub_items[0].replace("'", "")] = sub_items[-1]
    return item_dict