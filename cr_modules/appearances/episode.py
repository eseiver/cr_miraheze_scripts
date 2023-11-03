import re
from dataclasses import dataclass, field

import mwparserfromhell
from tqdm import tqdm

from ..cr import pyPage
from ..ep import EpisodeReader, Ep
from .character import pyCharacter
from .logger_config import logger 
from .processor import CharacterManager


HEADING_CONVERTER = {
    'Mentioned': 'mention',
    'Mention': 'mention',
    '[[Mighty Nein|Player characters]]': 'Player characters',
    '[[Mighty Nein|The Mighty Nein]]': 'Player characters',
    '[[Vox Machina]]': 'Player characters',
    '[[Campaign 3 adventuring party]]': 'Player characters',
    '[[Crown Keepers]]': 'Player characters',
    "[[Bells Hells]]": 'Player characters',
    "[[Bells Hells|Player Characters]]": 'Player characters',
    "[[Bell's Hells]]": 'Player characters',
    "[[Bell's Hells|Player characters]]": 'Player characters',
    'Player Characters': 'Player characters',
    'Main player characters': 'Player characters',
    'Guest player characters': 'Player characters',
    'Player characters': 'Player characters',
    '[[Ring of Brass]]': 'Player characters',
    'Vox Moronica': 'Player characters',
    'Companions': 'NPCs',
    'Non-player Characters': 'NPCs',
    'Non-player characters': 'NPCs',
    'NPCs': 'NPCs',
    'New': 'appear',
    'Returning': 'appear'}

CHARACTERS_SECTION_NAME = 'featured characters'
APPEARANCES_SECTION_NAME = 'appearances and mentions'

externally_linked_name_regex = '\*+\s*\[http.*?\s(?P<name>.*?)\]'
linked_character_regex = '\*+\s*(<s>)?(\")?\[\[(?P<name>.*?)(\|(?P<alt_name>.*?))?\]\](</s>)?(\")?(?P<raw_description>.*)?'
unlinked_character_regex = '\*\s*(<s>)?(\")?(?P<name>[A-Za-z\"\.\s]+\w+)(\")?(</s>)?(\s*(\:|\,|\-|\—|\–)\s*(?P<raw_description>.*))?'

class pyEpisode(pyPage):
    @property
    def episode_code(self):
        if not hasattr(self, '_episode_code') or self._episode_code is None:
            if self.infobox and self.infobox.name.matches('Infobox Episode'):
                self._episode_code = Ep(self.infobox['EpCode'].value)
            else:
                self._episode_code = ''
        return self._episode_code

    def pre_get(cls):
        if not hasattr(cls, '_episodes_data') or not cls._episodes_data:
            episodes_data = EpisodeReader(force_download=True)
            episodes_data.download_json()
            cls._episodes_data = episodes_data._json

    @property
    def episode_data(self):
        self.pre_get()
        data = self._episodes_data.get(self.episode_code.code)
        data['episode_code'] = self.episode_code.code
        return data

    @property
    def campaign_pcs(self):
        return self.episode_code.campaign.main_characters

    @property
    def featured_characters_section(self):
        return self.get_section_by_heading('Featured characters')

    @property
    def character_dicts(self):
        if not hasattr(self, '_character_dicts') or not self._character_dicts:
            fcp = FeaturedCharactersParser(fc_section=self.featured_characters_section,
                               pagename=self.title())
            fcp.parse()
            character_dicts = []
            for ad in fcp.appearance_dict:
                if not ad:
                    continue
                if ad['name'] in self.campaign_pcs:
                    ad['campaign_pc'] = True
                else:
                    ad['campaign_pc'] = False
                character_dicts.append(ad)
            self._character_dicts = character_dicts
        return self._character_dicts

    @property
    def characters(self):
        return [x['name'] for x in self.character_dicts]

#     @property
#     def character_pages(self):
#         if not hasattr(self, '_character_pages') or not self._character_pages:
#             episode_characters = BulkWikiProcessor(self.characters)
#             episode_characters.run()
#             self._character_pages = episode_characters.pages
#         return self._character_pages

    def check_character_pages(self):
        character_manager = CharacterManager()  # Access the shared manager
        character_pages = character_manager.get_character_pages(self.characters)
        print(len(character_pages))
        logger.info(f'Checking whether characters have {self.episode_code} in their appearance section')
        no_errors = True
        for char_dict in self.character_dicts:
            name = char_dict['name']
            page = character_pages.get(name)
            if not page or not page.exists():
                logger.info(f'{name}: page does not exist')
                continue
            if not isinstance(page, pyCharacter):
                logger.info(f'{page.title()}: page not is character')
                continue
            if char_dict.get('campaign_pc') and char_dict.get('status') == 'appear':
                logger.debug(f'{page.title()}: skipping standard campaign PC appearance')
                continue
            if not self.episode_code.code in page.episodes:
                no_errors = False
                logger.info(
                    f'{page.title()} does not have {self.title()} ({self.episode_code}) in appearances')
        if no_errors:
            logger.info(f'All characters found to have {self.title()} in appearances')


@dataclass
class FeaturedCharactersParser:
    '''for a single WikiWork object, parse the featured characters section'''
    fc_section: mwparserfromhell.wikicode
    pagename: str
    section_name: str = CHARACTERS_SECTION_NAME
    # character_list: list = field(default_factory=list)
    linked_only: bool = True  # whether only wikilinked character names will be included in ceas
    # match_name: bool = True  # whether to match the character name with character pages
    check_redirects: bool = True  # whether to see if unmatched names redirect to matched ones
    work_type: str = 'episode'  # whether an episode, issue of a comic, etc
    include_raw_description: bool = True  # whether to include raw description in appearance object
    # fc_section: str = field(init=False)
    divided_fc: dict = field(default_factory=dict)
    cleaned_characters: dict = field(default_factory=dict)
    appearance_dict: dict = field(default_factory=dict)

    def parse(self):
        fc_section = str(self.fc_section)
        if fc_section:
            self.divided_fc = self.divide_characters()
            self.cleaned_characters = self.clean_divided_characters(self.divided_fc)
            self.appearance_dict = self.build_appearance_dict(self.cleaned_characters)
        else:
            logger.debug(f'No featured character section found for {self.title()}')

    def divide_characters(self):
        '''Use the table of contents to further subdivide characters w/keys of meaningful info.'''
        assert self.fc_section
        fc_headings = pyPage.get_toc(self, wikicode=self.fc_section)
        divided_fc = {}
        for fc_heading in fc_headings:
            section = pyPage.get_section_by_heading(self,
                                                    heading=fc_heading,
                                                    wikicode=self.fc_section)
            divided_fc[fc_heading] = section
        if not fc_headings:
            logger.debug(f'No separate character subsections: {self.title()}')
            divided_fc = {}
            divided_fc['Player characters'] = self.fc_section

        return divided_fc

    def clean_divided_characters(self, divided_characters):
        '''Take literal headings and convert them to standardized ones. Flag and print exceptions.'''

        divided_characters_cleaned = {}

        for k, v in divided_characters.items():
            if k not in HEADING_CONVERTER.keys() and self.work_type == 'episode':
                logger.debug(f"WAYWARD K!!! {self.pagename} {k}")
                continue
            # else:
            #     new_heading = heading_replacement_dict[k.strip()]

            # TO DO: make a generalized rule instead of relying on each exact value
            invalid_chars = ['}}', '<!-- Insert returning characters here. -->', '<!-- Insert mentioned characters here. -->',
                             '<!-- Insert new characters here. -->', '  |col2=<nowiki />', '{{div columns|line=false',
                             '  |col1=<nowiki />', '{{div columns|line=true',
                             '{{clr|left}}', '<!-- Lans something; the guy from the story Ogden told Pike -->',
                             '<!-- Insert new NPCs here. -->',
                             '<!-- Insert new characters here. --> ',
                             '<!-- any works that are not a streamed episode or a comic, including "Pre=stream" and "The Legend of Vox Machina" --> ',
                             '<!-- any works that are not a streamed episode or a comic, including "Pre-stream" and "The Legend of Vox Machina" -->',
                             '<!-- Insert new characters as a bulleted list. A character is considered new if they have not previously appeared in a TLOVM episode. -->',
                             '<!-- Insert mentioned characters as a bulleted list. -->',
                             '<!-- Insert returning characters as a bulleted list. A character is considered returning if they previously appeared in a TLOVM episode. -->',
                             "<!--=== '''Mentioned''' ===",
                             'Insert mentioned characters as a bulleted list. -->',
                             ]
            value = [x for x in v.splitlines() if len(x) \
                and not any(x.startswith(y) for y in ['<!-- This section note', '[[File:', '===']) and x not in invalid_chars]
            if not divided_characters_cleaned.get(k, None):
                divided_characters_cleaned[k] = []
            divided_characters_cleaned[k].extend(value)

        return divided_characters_cleaned

    def parse_character_line(self, line, heading=None):
        name_info = {}

        converted_heading = HEADING_CONVERTER[heading]

        if re.search('\*\s*(<s>)?(\")?s*\[\[', line):
            linked = True
            name_info = re.search(linked_character_regex, line).groupdict()
        elif re.search(externally_linked_name_regex, line):
            linked = False
            name_info['name'] = re.search(externally_linked_name_regex, line).group('name')
        elif '[[' in line and line.strip().startswith('*'):
            # catch the stragglers who are linked, but not unlinked chars with links in description
            first_line = re.split('\,|-|\:|\(', line)[0]
            if all([x in first_line for x in ['[[', ']]']]):
                name_info['name'] = re.search('(?<=\[\[)(?P<linked_name>.*?)(?=\||\]\])', first_line).group('linked_name')
                # logger.debug(f"Got linked char: {name_info['name']}, {line}")
                # guessing linked, for now
                linked = True
            else:
                linked = False
                name_info = re.search(unlinked_character_regex, line).groupdict()
                # logger.debug(f"Got unlinked char: {name_info['name']}, {line}")
        else:
            if not line.strip().startswith('*'):
                return name_info
            linked = False
            if re.search(unlinked_character_regex, line):
                name_info = re.search(unlinked_character_regex, line).groupdict()
            elif [x for x in mwparserfromhell.parse(line).filter_templates()
                  if x.name.matches('anchor')]:
                name_info['name'] = next(
                    x for x in mwparserfromhell.parse(line).filter_templates()
                  if x.name.matches('anchor'))[1].strip()
                name_info['raw_description'] = line.split('}}', 1)[-1]

        if not name_info.get('name'):
            logger.debug(f"No character info found for {line}")

        if converted_heading in ['mention', 'appear']:
            status = heading
        elif heading == 'Main player characters':
            if any([x in line.lower() for x in ["not mentioned", "unmentioned"]]):
                status = "absent"
            elif "mentioned" in line.lower():
                status = "mention"
            elif "absent" in line.lower():
                status = "absent" 
            elif 'DM-controlled' in line:
                status = 'appear'
            elif ']]' in line and (len(line.split(']]', 1)[1].strip()) == 0):
#                     print(len(line.split(']]', 1)[1]))
                # logger.debug(f"This shouldn't need status help: {line}")
                status = 'appear'
            else:
                if ']]' in line:
                    new_status =  line.split(']]', 1)[1]
                    logger.debug(f"New status: {line}")
                else:
                    new_status = re.split('(:|,|-)', line)[-1]
                    logger.debug(f"New status: {line}")
                status = 'appear'  # new status better not negate this
        else:
            assert any([x not in line for x in ['mention', 'absent']])
            status = 'appear'

        name_info.update({
            'has_linked_name': linked,
            'name_matched': None,
            'status': status,
            'modifiers': [],
        })

        if self.work_type == 'episode':
            if converted_heading == 'Player characters':
                name_info.update({
                'is_pc': True,
                })
            elif heading == 'New':
                name_info.update({
                'is_pc': False,
                })
                name_info['modifiers'].append('1st app')
            else: 
                name_info.update({
                'is_pc': False,
                })

        if not name_info.get('raw_description'):
            name_info.update({
                'raw_description': '',
            })


        return name_info

    def build_appearance_dict(self, cleaned_characters=None):
        appearance_dict = []
        if cleaned_characters is None:
            cleaned_characters = self.cleaned_characters
        for key, val in self.cleaned_characters.items():
            for char in val:
                if mwparserfromhell.parse(char).filter_headings():
                    continue
                character_dict = self.parse_character_line(char, heading=key)
                appearance_dict.append(character_dict)
        return appearance_dict