import json
import os
import re

from copy import deepcopy
from dataclasses import dataclass, field
from string import ascii_lowercase

import pywikibot

DATA_PATH = '/'.join([pywikibot.config.user_script_paths[0], 'data'])
os.makedirs(DATA_PATH, exist_ok=True)

@dataclass
class LuaReader:
    '''For storing Lua data modules as json and reading from them.'''
    module_name: str
    json_filename: str
    force_download: bool = False
    try_local_file: bool = True
    write_file: bool = True
    pretty_print: bool = True

    def __post_init__(self):
        self.json_filename = '/'.join([DATA_PATH, self.json_filename])
        # check for local file first
        self._json = {}
        if self.try_local_file:
            try:
                self._json = self.create_from_json_file()
            except FileNotFoundError:
                pass

        if not self._json or self.force_download is True:
            self._json = self.download_json()
            if self.write_file:
                with open(self.json_filename, 'w', encoding='utf-8') as json_file:
                    if self.pretty_print:
                        json_file.write(json.dumps(self._json, indent=4))
                    else:
                        json_file.write(json.dumps(self._json))

    def download_json(self):
        site = pywikibot.Site()
        _json = json.loads(site.expand_text(f'{{{{#invoke:Json exporter|dump_as_json|Module:{self.module_name}}}}}'))
        return _json

    def create_from_json_file(self):
        with open(self.json_filename) as f:
            _json = json.load(f)
        return _json

@dataclass
class Decoder(LuaReader):
    '''Information about every (active) campaign, series, and season.'''
    module_name: str = 'Ep/Decoder'
    json_filename: str = 'decoder.json'

    def download_json(self):
        self._json = super().download_json()
        _json = self.fix_seasons()
        return _json

    def fix_seasons(self, _json=None):
        '''When downloading .json, Lua removes season numbers. Restores them as dict.'''
        if _json is None:
            _json = self._json
        copied_json = deepcopy(_json)
        for k, v in dict(copied_json).items():
            if v.get('seasons'):
                _json[k]['seasons'] = {}
                for i, season in enumerate(v['seasons']):
                    _json[k]['seasons'][str(i+1)] = season
        return _json


decoder = Decoder()
EPISODE_DECODER = decoder._json

def build_prefix_options(episode_decoder=None):
    if episode_decoder is None:
        episode_decoder = EPISODE_DECODER
    key_list = []
    for key, value in episode_decoder.items():
        if 'TM' in key:
            continue
        if value.get('seasons'):
            key_list.append(fr"{key}\d+")
        else:
            key_list.append(key)
    # handle TM
    key_list += [r'TMOS', r'TM\d*', 'TMS'] 
    return key_list

def build_prefix_regex(episode_decoder=None):
    if episode_decoder is None:
        episode_decoder = EPISODE_DECODER
    key_list = build_prefix_options(episode_decoder=episode_decoder)
    regex = '^(' + '|'.join(key_list) + ')'
    return regex

# EP_REGEX = build_prefix_regex(episode_decoder=EPISODE_DECODER) + 'x\d+(a|b)?$'  # https://regex101.com/r/QXhVhb/4

class Ep:
    '''for handling episode ids'''
    def __init__(self, episode_code, padding_limit=2, episode_decoder=None):
        episode_code = episode_code.strip()
        self.code = self.standardize_code(episode_code)
        if not episode_decoder:
            self.episode_decoder = EPISODE_DECODER
        else:
            self.episode_decoder = episode_decoder
        self.ep_regex = build_prefix_regex(episode_decoder=self.episode_decoder)
        assert re.match(self.ep_regex, episode_code, flags=re.IGNORECASE), f"{episode_code} not valid. Check Module:Ep/Decoder and data/decoder.json"
        self._code = episode_code
        self.padding_limit = padding_limit
        self.max_letter = 'b'


    def __repr__(self):
        return self.code

    def __eq__(self, other):
        if isinstance(other, Ep):
            return self.code == other.code
        return False

    def __hash__(self):
        return hash(self.code)

    def standardize_code(self, code):
        '''Format standardized with single zero padding'''
        prefix, number = code.split('x')
        if number[-1].isdigit():
            number = int(number)
            standardized_code = 'x'.join([prefix, f"{number:02}"])
        else:
            number_1 = int(number[:-1])
            standardized_code = 'x'.join([prefix, f"{number_1:02}"]) + number[-1]
        return standardized_code

    @property
    def ends_in_letter(self):
        if self.code[-1].isdigit():
            return False
        else:
            return True

    @property
    def full_prefix(self):
        full_prefix = self.code.split('x')[0]
        return full_prefix

    @property
    def prefix(self):
        if self.is_campaign or not self.full_prefix[-1].isdigit():
            return self.full_prefix
        else:
            return self.full_prefix[:-1]

    @property
    def number(self):
        number = self.code.split('x')[-1]
        if self.ends_in_letter:
            number = int(number[:-1])
        else:
            number = int(number)
        return number

    @property
    def show(self):
        return self.episode_decoder[self.prefix]['title']

    @property
    def season(self):
        season = ''
        if self.episode_decoder[self.prefix].get('seasons'):
            assert self.full_prefix[-1].isdigit()
            season = self.full_prefix[-1]
        return season

    @property
    def season_name(self):
        season_name = ''
        if self.season:
            season_name = self.episode_decoder[self.prefix]['seasons'][self.season]['page']
            if not season_name:
                season_name = f"Season {self.season}"
        return season_name

    @property
    def list_page(self):
        return self.episode_decoder[self.prefix].get('listLink', self.show)

    @property
    def thumbnail_page(self):
        return self.episode_decoder[self.prefix].get('thumbnailCategory', 'Episode thumbnails')

    @property
    def latest(self):
        '''The name in Module:Ep/Array that denotes the latest episode for this show'''
        return self.episode_decoder[self.prefix].get('latest')

    @property
    def navbox_name(self):
        navbox = (self.episode_decoder[self.prefix]['navbox']
                  if self.episode_decoder[self.prefix].get('navbox')
                  else f"Nav-{self.prefix}")
        return navbox

    @property
    def transcript_category(self):
        return self.episode_decoder[self.prefix].get('transcriptCategory', 'Transcripts')

    @property
    def image_filename(self):
        filename = f"{self.code} Episode Thumb.jpg"
        return filename

    @property
    def wiki_code(self):
        wiki = f'{{{{ep|{self.code}}}}}'
        return wiki

    @property
    def wiki_noshow(self):
        wiki = f'{{{{ep|{self.code}|noshow=true}}}}'
        return wiki

    @property
    def transcript_redirects(self):
        trs = [f'Transcript:{x}' for x in self.generate_equivalent_codes()]
        return trs

    @property
    def is_campaign(self):
        if self.full_prefix.isdigit():
            return True
        else:
            return False

    @property
    def ce_codes(self):
        '''For creating the C[Campaign]E[Episode] formatted code. Used by CR.'''
        ces = []
        if self.is_campaign:
            for code in self.generate_equivalent_codes():
                campaign, number = code.split('x')
                ce = f'C{campaign}E{number}'
                ces.append(ce)
        return ces

    @property
    def ce_words(self):
        '''For creating the written-out version of self.ce_codes.'''
        if self.is_campaign:
            words = f'Campaign {self.prefix} Episode {self.number}'
        else:
            words = ''
        return words

    @property
    def shortdesc_value(self):
        '''For building a short description to prepend to article.
        Italics do not display in this view.'''
        shortdesc = ''
        if self.show in ['Bits and bobs', 'Midst']:
            return shortdesc

        if self.ce_words:
            shortdesc += self.ce_words
        elif self.prefix == 'OS':
            shortdesc += 'One-shot episode'
        elif self.show in ['Talks Machina', 'UnDeadwood']:
            shortdesc += 'none'
        else:
            shortdesc += self.show

        if self.season_name:
            shortdesc += f", {self.season_name}"

        # Handle Exandria Unlimited separately
        if self.prefix == 'E':
            if self.season == '1':
                shortdesc = "Exandria Unlimited Prime"
            elif self.season == '2':
                shortdesc = "none"
            elif self.season == '3':
                shortdesc =  "Exandria Unlimited: Calamity"
            else:
                raise

        if self.prefix not in ['OS'] and not self.is_campaign and shortdesc != "none":
            shortdesc += f" Episode {self.number}"
        return shortdesc

    @property
    def shortdesc(self):
        '''Wrap short description in the appropriate wiki template markup.'''
        shortdesc = ''
        if self.shortdesc_value:
            shortdesc = f"{{{{short description|{self.shortdesc_value}}}}}"
        return shortdesc

    @property
    def wiki_vod(self):
        vod = f"{{{{Ep/YTURLSwitcher|ep={self.code}}}}}"
        return vod

    @property
    def wiki_podcast(self):
        podcast = f"{{{{Ep/PodcastSwitcher|ep={self.code}}}}}"
        return podcast

    def generate_equivalent_codes(self):
        '''Get all equivalent valid episode codes up to the padding limit number of digits'''
        if len([x for x in str(self.number) if x.isdigit()]) >= self.padding_limit:
            code_list = [self.code]
        elif not self.ends_in_letter:
            code_list = ['x'.join([self.full_prefix, str(self.number).zfill(1+n)]) for n in range(self.padding_limit)]
        else:
            code_list = ['x'.join([self.full_prefix, str(self.number).zfill(1+n)]) + self.code[-1] for n in range(self.padding_limit)]
        return code_list

    def get_previous_episode(self):
        '''Cannot calculate across seasons (e.g., what was before 3x01). Handles letters (valid letters regex-limited).'''
        old_number = self.number - 1
        letter = ''
        if self.ends_in_letter and not self.code.endswith('a'):
            old_number = self.number
            suffix = self.code[-1]
            look_up = dict(zip(ascii_lowercase, ascii_lowercase[1:]+'a'))
            letter = next(k for k, v in look_up.items() if v == suffix)
        if old_number > 0 and (not self.ends_in_letter or self.code.endswith('a')):
            old_id = 'x'.join([self.full_prefix, f"{old_number:02}"])
            previous_episode = Ep(old_id, episode_decoder=self.episode_decoder)
        elif old_number > 0:
            old_id = 'x'.join([self.full_prefix, f"{old_number:02}"]) + letter
            previous_episode = Ep(old_id, episode_decoder=self.episode_decoder)
        else:
            # no previous id, because the first of its kind
            previous_episode = None
        return previous_episode

    def get_next_episode(self):
        '''Cannot calculate across seasons (e.g., what was after 2x141). Handles letters (valid letters regex-limited).'''
        next_number = self.number + 1
        letter = ''
        if self.ends_in_letter and not self.code.endswith('a'):
            next_number = self.number
            suffix = self.code[-1]
            look_up = dict(zip(ascii_lowercase, ascii_lowercase[1:]+'a'))
            letter = next(k for k, v in look_up.items() if v == suffix)
        if next_number > 0 and (not self.ends_in_letter or self.code.endswith('a')):
            next_id = 'x'.join([self.full_prefix, f"{next_number:02}"])
            next_episode = Ep(next_id, episode_decoder=self.episode_decoder)
        elif next_number > 0:
            next_id = 'x'.join([self.full_prefix, f"{next_number:02}"]) + letter
            next_episode = Ep(next_id, episode_decoder=self.episode_decoder)
        else:
            # no previous id, because the first of its kind
            next_episode = None
        return next_episode