import json
import os
import re

from copy import deepcopy
from string import ascii_lowercase

import pywikibot

DATA_PATH = '/'.join([pywikibot.config.user_script_paths[0], 'data'])
os.makedirs(DATA_PATH, exist_ok=True)

class Decoder:
    '''Information about every (active) campaign, series, and season.'''
    def __init__(self, json_filename='decoder.json', force_download=False,
                 try_local_file=True, write_file=True, pretty_print=True):
        self.json_filename = '/'.join([DATA_PATH, json_filename])
        self.try_local_file = try_local_file
        self.pretty_print = pretty_print
        # check for local file first
        if self.try_local_file:
            try:
                self._json = self.create_from_json_file()
            except FileNotFoundError:
                pass

        if not hasattr(self, '_json') or force_download is True:
            self._json = self.download_decoder_json()
            if write_file:
                with open(self.json_filename, 'w', encoding='utf-8') as json_file:
                    if self.pretty_print:
                        json_file.write(json.dumps(self._json, indent=4))
                    else:
                        json_file.write(json.dumps(self._json))

    def download_decoder_json(self):
        site = pywikibot.Site()
        _json = json.loads(site.expand_text('{{#invoke:Json exporter|dump_as_json|Module:Ep/Decoder}}'))
        _json = self.fix_seasons(_json)
        return _json

    def create_from_json_file(self):
        with open(self.json_filename) as f:
            _json = json.load(f)
        return _json

    def fix_seasons(self, _json):
        '''When downloading .json, Lua removes season numbers. Restores them as dict.'''
        copied_json = deepcopy(_json)
        for k, v in dict(copied_json).items():
            if v.get('seasons'):
                _json[k]['seasons'] = {}
                for i, season in enumerate(v['seasons']):
                    _json[k]['seasons'][str(i+1)] = season
        return _json


decoder = Decoder()
EPISODE_DECODER = decoder._json

def build_prefix_options():
    key_list = []
    for key, value in EPISODE_DECODER.items():
        if 'TM' in key:
            continue
        if value.get('seasons'):
            key_list.append(fr"{key}\d+")
        else:
            key_list.append(key)
    # handle TM
    key_list += [r'TMOS', r'TM\d*', 'TMS'] 
    return key_list

def build_prefix_regex():
    key_list = build_prefix_options()
    regex = '^(' + '|'.join(key_list) + ')'
    return regex

EP_REGEX = build_prefix_regex() + 'x\d+(a|b)?$'  # https://regex101.com/r/QXhVhb/4

class Ep:
    '''for handling episode ids'''
    def __init__(self, episode_code, padding_limit=2):
        episode_code = episode_code.strip()
        assert re.match(EP_REGEX, episode_code, flags=re.IGNORECASE), f"{episode_code} not valid. Check Module:Ep/Decoder and data/decoder.json"
        self._code = episode_code
        self.code = self.standardize_code(episode_code)
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
        return EPISODE_DECODER[self.prefix]['title']

    @property
    def list_page(self):
        return EPISODE_DECODER[self.prefix].get('listLink', self.show)

    @property
    def thumbnail_page(self):
        return EPISODE_DECODER[self.prefix].get('thumbnailCategory', 'Episode thumbnails')

    @property
    def navbox_name(self):
        return EPISODE_DECODER[self.prefix].get('navbox', '')

    @property
    def transcript_category(self):
        return EPISODE_DECODER[self.prefix].get('transcriptCategory', 'Transcripts')

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
        wiki = f'{{{{ep|noshow=1|{self.code}}}}}'
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
            previous_episode = Ep(old_id)
        elif old_number > 0:
            old_id = 'x'.join([self.full_prefix, f"{old_number:02}"]) + letter
            previous_episode = Ep(old_id)
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
            next_episode = Ep(next_id)
        elif next_number > 0:
            next_id = 'x'.join([self.full_prefix, f"{next_number:02}"]) + letter
            next_episode = Ep(next_id)
        else:
            # no previous id, because the first of its kind
            next_episode = None
        return next_episode