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
        _json = json.loads(
            site.expand_text(
                f'{{{{#invoke:Json exporter|dump_as_json|Module:{self.module_name}}}}}'
                )
            )
        _json = self.custom_cleanup(_json)
        return _json

    def custom_cleanup(self, _json):
        '''For specific modules, replace with whatever is needed here'''
        return _json

    def create_from_json_file(self):
        with open(self.json_filename) as f:
            _json = json.load(f)
        return _json


@dataclass
class EpisodeReader(LuaReader):
    '''Read-only information about episodes.'''
    module_name: str = 'Ep/Array'
    json_filename: str = 'episodes.json'

    def custom_cleanup(self, _json):
        '''Custom cleanup for episode data.'''
        copied_json = deepcopy(_json)
        for k, v in copied_json.items():
            _json[k]['pagename'] = v.get('pagename', v['title'])
        return _json

    @property
    def conversion_dict(self):
        if not hasattr(self, '_conversion_dict') or self._conversion_dict is None:
            self._conversion_dict = self.build_conversion_dict()
        return self._conversion_dict

    def build_conversion_dict(self):
        new_dict = {}
        for k, v in self._json.items():
            if v:
                all_values = ([v[key] for key in v.keys() if not isinstance(v[key], list)]
                        + v.get('altTitles', []) + [k.lower()])
            else:
                v = {'title': ''}
                all_values = [k.lower()]
            if not v.get('pagename'):
                v['pagename'] = v['title']
            for value in all_values:
                new_dict[value.lower()] = {
                    'pagename': v['pagename'],
                    'episode_title': v['title'],
                    'episode_code': k,
                }
        return new_dict

    def get_ep_dict(self, value):
        # first try calling ep directly:
        ep = Ep(value)
        if ep.code == '0x00':
            value = value.lower()
            ep_dict = self.conversion_dict.get(value, {})
        else:
            ep_dict = self.conversion_dict.get(ep.code, {})
        return ep_dict

    def get_pagename(self, value):
        ep_dict = self.get_ep_dict(value)
        return ep_dict.get('pagename', '')

    def get_title(self, value):
        ep_dict = self.get_ep_dict(value)
        return ep_dict.get('episode_title', '')

    def get_ep_code(self, value):
        ep_dict = self.get_ep_dict(value)
        return ep_dict.get('episode_code', '')


@dataclass
class Decoder(LuaReader):
    '''Information about every (active) campaign, series, and season.'''
    module_name: str = 'Ep/Decoder'
    json_filename: str = 'decoder.json'

    def custom_cleanup(self, _json):
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
    regex = r'^(' + r'|'.join(key_list) + r')'
    return regex

EP_REGEX = build_prefix_regex(episode_decoder=EPISODE_DECODER) + r'x\d+(a|b)?$'  # https://regex101.com/r/QXhVhb/4

# TO DO: make Ep __init__ use '0x00' as default code for any invalid input (matching modules on wiki)


class Show:
    '''A Critical Role show or campaign, as represented in the Decoder.'''
    def __init__(self, key, decoder=None):
        if decoder is None:
            decoder = EPISODE_DECODER
        if key in decoder:
            # convert from camelCase to snake_case
            pattern = re.compile(r'(?<!^)(?=[A-Z])')
            for attr, value in decoder[key].items():
                name = pattern.sub('_', attr).lower()
                setattr(self, name, value)
            self.prefix = key
        else:
            raise ValueError(f"Key '{key}' not found in episode decoder")

        if hasattr(self, 'seasons'):
            '''Create season objects'''
            season_dict = {}
            for season_number, season_data in self.seasons.items():
                season = Season(self.prefix, season_number, season_data)
                season_dict[season_number] = season
            self.seasons = season_dict

        if hasattr(self, 'arcs'):
            '''Create arc objects'''
            arc_dict = {}
            for arc in self.arcs:
                arc_number = str(arc['arcNum'])
                arc = Arc(self.prefix, arc_number, arc)
                arc_dict[arc_number] = arc
            self.arcs = arc_dict

        # use default attributes if they are missing
        if not hasattr(self, 'list_link'):
            self.list_link = self.title

        if not hasattr(self, 'thumbnail_category'):
            self.thumbnail_category = 'Episode thumbnails'

        if not hasattr(self, 'latest'):
            self.latest = ''

        if not hasattr(self, 'navbox'):
            self.navbox = f"Nav-{self.prefix}"

        if not hasattr(self, 'transcript_category'):
            self.transcript_category = 'Transcripts'

    def __repr__(self):
        return f"Show({self.title}, '{self.prefix}')"

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.prefix == other.prefix
        else:
            return False


class Campaign(Show):
    '''A show is more specifically called a campaign for Campaigns 1-3.'''
    def __repr__(self):
        return f"Campaign({self.title})"


class Season:
    '''A season within a Critical Role show or campaign.'''
    def __init__(self, show_prefix, season_number, show_data):
        self.show_prefix = show_prefix
        self.number = season_number
        # to handle creation as standalone object or generated within a show
        if season_number in show_data.get('seasons', {}):
            show_data = show_data['seasons'][season_number]
        elif show_data.get('arcs', {}):
            show_data = show_data['arcs'][int(season_number)]
        # convert from camelCase to snake_case
        pattern = re.compile(r'(?<!^)(?=[A-Z])')
        for attr, value in show_data.items():
            name = pattern.sub('_', attr).lower()
            setattr(self, name, value)
        if not hasattr(self, 'name'):
            self.name = f"Season {self.number}"

    def __repr__(self, episode_decoder=EPISODE_DECODER):
        campaign_title = episode_decoder.get(self.show_prefix, {}).get('title', '')
        return f"Season({campaign_title}, {self.name})"


class Arc(Season):
    def __repr__(self):
        return f"Arc({self.page})"

    @property
    def page(self, episode_decoder=EPISODE_DECODER):
        campaign_title = episode_decoder.get(self.show_prefix, {}).get('title', '')
        arc_title = (f'Arc {self.arc_num}: {self.title}'
                       if hasattr(self, 'title') and self.title
                       else f' Arc {self.arc_num}')
        return f"{campaign_title} {arc_title}"

    @property
    def category(self):
        return f'Category: {self.title} arc'

    @property
    def character_category(self):
        arc_title = re.sub(r'^The ', '', self.title)
        return f'Category:Characters in the {arc_title} arc'


class Ep:
    '''for handling episode ids'''
    def __init__(self, episode_code, padding_limit=2, ep_regex=None):
        episode_code = episode_code.strip()

        if not ep_regex:
            self.ep_regex = EP_REGEX
        else:
            self.ep_regex = ep_regex

        try:
            assert re.match(
                self.ep_regex,
                episode_code,
                flags=re.IGNORECASE)
        except AssertionError:
            if re.match(r'\w+x\w+', episode_code):
                prefix = episode_code.split('x')[0]
                output = '\n'.join([
                    f'<<yellow>>"{episode_code}"<<default>> not valid episode code.',
                    f'Check Module:Ep/Decoder on wiki. Is there an entry for <<yellow>>{prefix}<<default>>?',
                    f'Make sure data/decoder.json is up to date by running <<yellow>>python pwb.py download_data<<default>>'
                ])
            else:
                output = f'<<yellow>>{episode_code}<<default>> is not in format CxNN'
                episode_code = '0x00'
            pywikibot.output(output)

        self.code = self.standardize_code(episode_code)
        self._code = episode_code
        self.padding_limit = padding_limit
        self.max_letter = 'b'

    def __repr__(self):
        return f'Ep({self.code})'

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.code == other.code
        return False

    def __hash__(self):
        return hash(self.code)

    def __lt__(self, other):
        if isinstance(other, self.__class__):
            if self.is_campaign and other.is_campaign and self.prefix < other.prefix:
                return True
            elif self.prefix == other.prefix:
                return self.number < other.number
            else:
                return False
        raise TypeError("Cannot compare Ep with non-Ep")

    def __gt__(self, other):
        if isinstance(other, self.__class__):
            if self.is_campaign and other.is_campaign and self.prefix > other.prefix:
                return True
            elif self.prefix == other.prefix:
                return self.number > other.number
            else:
                return False
        raise TypeError("Cannot compare Ep with non-Ep")

    def __le__(self, other):
        return self < other or self == other

    def __ge__(self, other):
        return self > other or self == other

    def standardize_code(self, code):
        '''Format standardized with single zero padding and capitalized prefix'''
        prefix, number = code.split('x')
        prefix = prefix.upper().replace('MIDST', 'Midst')
        if number[-1].isdigit():
            number = int(number)
            standardized_code = 'x'.join([prefix, f"{number:02}"])
        else:
            number_1 = int(number[:-1])
            standardized_code = 'x'.join([prefix, f"{number_1:02}"]) + number[-1]
        return standardized_code

    @property
    def campaign(self):
        return Campaign(self.prefix)

    @property
    def show(self):
        return Show(self.prefix)

    @property
    def ends_in_letter(self):
        if self.code[-1].isalpha():
            return True
        else:
            return False

    @property
    def full_prefix(self):
        full_prefix = self.code.split('x')[0]
        return full_prefix

    @property
    def prefix(self):
        if self.is_campaign:
            prefix = self.full_prefix
        else:
            prefix = re.sub(r'\d+$', '', self.full_prefix)
        return prefix

    @property
    def number(self):
        number = self.code.split('x')[-1]
        if self.ends_in_letter:
            number = int(number[:-1])
        else:
            number = int(number)
        return number

    @property
    def season(self):
        if not hasattr(self, '_season') or self._season is None:
            season = ''
            season_number = re.search(r'\d+$', self.full_prefix).group()
            if not season_number:
                season = ''
            elif (hasattr(self, 'show') and
                self.show and hasattr(self.show, 'seasons')
                and self.show.seasons):
                # make sure can still infer season even if not in Decoder
                season = self.show.seasons.get(str(season_number),
                                               Season(self.prefix,
                                                      season_number,
                                                      {}))
            self._season = season
        return self._season

    @property
    def arc(self):
        arc = ''
        if not hasattr(self, '_arc') or self._arc is None:
            if (hasattr(self, 'campaign') and
                self.campaign and hasattr(self.campaign, 'arcs')
                and self.campaign.arcs):
                arc = next((arc for arc
                            in self.campaign.arcs.values()
                            if self.number < arc.end_episode
                            ),
                           '')
            self._arc = arc
        return self._arc

    @property
    def image_filename(self):
        filename = f"{self.code} Episode Thumb.jpg"
        return filename

    @property
    def wiki_code(self):
        wiki = f'{{{{ep|{self.code}}}}}'
        return wiki

    @property
    def wiki_nolink(self):
        wiki = f'{{{{ep|{self.code}|nolink=true}}}}'
        return wiki

    @property
    def wiki_noshow(self):
        wiki = f'{{{{ep|{self.code}|noshow=true}}}}'
        return wiki

    @property
    def wiki_noshow_nolink(self):
        wiki = f'{{{{ep|{self.code}|noshow=true|nolink=true}}}}'
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
        if self.show.title in ['Bits and bobs']:
            return shortdesc

        if self.ce_words:
            shortdesc += self.ce_words
        elif self.prefix == 'OS':
            shortdesc += 'One-shot episode'
        elif self.show.title in ['Talks Machina', 'UnDeadwood']:
            shortdesc += 'none'
        else:
            shortdesc += self.show.title

        if self.season:
            shortdesc += f", {self.season.name}"

        # Handle Exandria Unlimited separately
        if self.prefix == 'E':
            shortdesc = self.season.page

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
            code_list = ['x'.join([self.full_prefix, str(self.number).zfill(1+n)])
                         for n in range(self.padding_limit)]
        else:
            code_list = ['x'.join([self.full_prefix, str(self.number).zfill(1+n)]) + self.code[-1]
                         for n in range(self.padding_limit)]
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
        if self.ends_in_letter and not self.code.endswith(self.max_letter):
            next_number = self.number
            suffix = self.code[-1]
            look_up = dict(zip(ascii_lowercase, ascii_lowercase[1:]+'a'))
            letter = next(v for k, v in look_up.items() if k == suffix)
        if next_number > 0 and not self.ends_in_letter:
            next_id = 'x'.join([self.full_prefix, f"{next_number:02}"])
            next_episode = Ep(next_id)
        elif next_number > 0:
            next_id = 'x'.join([self.full_prefix, f"{next_number:02}"]) + letter
            next_episode = Ep(next_id)
        else:
            next_episode = None
        return next_episode