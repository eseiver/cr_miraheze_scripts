import json
import os
import re
import sys

from copy import deepcopy
from datetime import datetime, timedelta
from string import ascii_lowercase
from zoneinfo import ZoneInfo

import pywikibot

DATA_PATH = '/'.join([pywikibot.config.user_script_paths[0], 'data'])
os.makedirs(DATA_PATH, exist_ok=True)

# regular expressions for string matching
EP_REGEX = '^(\d+|OS|M|E\d*|U|4SD|LVM\d+|TM(OS|S)?\d*)x\d+(a|b)?$'  # https://regex101.com/r/QXhVhb/4
ARRAY_ENTRY_REGEX = '''\[\"(?P<epcode>.*?)\"\] = \{\s*\[\"title\"\] = \"(?P<title>.*)\",?((\s*\[\"pagename\"\] = \"(?P<pagename>.*)\",)?(\s*\[\"altTitles\"\] = \{(?P<altTitles>.*)\})?)?'''
YT_LINK_REGEX = '(?P<vod>(?:https?:\/\/)?(?:www\.)?(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))(?P<yt_id>[-\w_]{11})(&t=(?P<timecode>.*))?)'
YT_ID_REGEX = '[-\w_]{11}'
LONG_SHORT_REGEX = "\|\s*(?P<num>\d+)\s*\|\|.*?\{\{ep\|(?P<ep_code>.*?)(\|.*?)?\}\}.*?\|\| (?P<timecode>(\d+:\d+){2,3})"

# pagenames
INFOBOX_EPISODE = 'Infobox Episode'
EP_ARRAY = 'Module:Ep/Array'
AIRDATE_ORDER = 'Module:AirdateOrder/Array'
YT_SWITCHER = 'Module:Ep/YTURLSwitcher/URLs'
PODCAST_SWITCHER = 'Module:Ep/PodcastSwitcher/URLs'
TRANSCRIPTS_LIST = 'Transcripts'

# date and time
TIMEZONE = ZoneInfo("America/Los_Angeles")  # where Critical Role is based
DATE_REGEX = '\d{4}-\d{1,2}-\d{1,2}'
DATE_FORMAT = '%Y-%m-%d'
DATE_2_REGEX = '\d{1,2}-\d{1,2}-\d{4}'
DATE_2_FORMAT = '%m-%d-%Y'
TIME_REGEX = '\d{1,2}:\d{2}\s*(?P<tz_entry>\w{2,3})?'
TIME_FORMAT = '%H:%M'
DATETIME_REGEX = '\s*'.join([DATE_REGEX, TIME_REGEX])
DATETIME_FORMAT = ' '.join([DATE_FORMAT, TIME_FORMAT])
date_options = ((DATETIME_REGEX, DATETIME_FORMAT),
                (DATE_REGEX, DATE_FORMAT),
                (DATE_2_REGEX, DATE_2_FORMAT),
                (TIME_REGEX, TIME_FORMAT),
               )
# runtimes
RUNTIME_REGEX = '\d{1,2}:\d{2}:\d{2}'
RUNTIME_FORMAT = '%H:%M:%S'
RUNTIME_2_REGEX = '\d{1,2}:\d{2}'
RUNTIME_2_FORMAT = '%M:%S'
runtime_options = ((RUNTIME_REGEX, RUNTIME_FORMAT),
                   (RUNTIME_2_REGEX, RUNTIME_2_FORMAT),
                   )

ACTORS = [
    # main cast
    'Ashley Johnson',
    'Laura Bailey',
    "Liam O'Brien",
    'Marisha Ray',
    'Matthew Mercer',
    'Sam Riegel',
    'Taliesin Jaffe',
    'Travis Willingham',

    # guest stars
    'Aabria Iyengar',
    'Anjali Bhimani',
    'Brennan Lee Mulligan',
    'Dani Carr',
    'Erika Ishii',
    'Robbie Daymond',
    'Christian Navarro',
]
SPEAKER_TAGS = [
    'ASHLEY', 'LAURA', 'LIAM', 'MARISHA', 'MATT', 'SAM', 'TALIESIN', 'TRAVIS',
    'ALL', 'AABRIA', 'ANJALI', 'BRENNAN', 'CHRISTIAN', 'DANI', 'ERIKA', 'ROBBIE', 
]
# EPISODE_DECODER = {
#     '3': ('Campaign 3', 'List of Campaign 3 episodes',
#           'Campaign 3 episode thumbnails', 'Template:Nav-C3Arc1',
#           'Category:Campaign 3 transcripts'),
#     'OS': ('One-shots', 'One-shots', 'One-shot episode thumbnails',
#            'Template:Nav-OneShots', 'Category:One-shot transcripts'),
#     'M': ('Bits and bobs', 'Bits and bobs',
#           'Bits and bobs episode thumbnails',  'Template:Nav-Bitsnbobs',
#           'Category:Transcripts'),
#     'LVM2': ('The Legend of Vox Machina',
#             'List of The Legend of Vox Machina episodes',
#             'The Legend of Vox Machina episode thumbnails',
#             'Template:Nav-LoVM Season 2',
#             'Category:Transcripts'),
#     '4SD': ('4-Sided Dive', '4-Sided Dive', 'Episode thumbnails', 'Template:Nav-4SD',
#             'Category:Transcripts'),
    # 'Ep_type': ('show page', 'episode list page',
    # 'episode thumbnail category', 'navbox', 'transcript category'),
# }

# Episode codes where the transcript will not be added (-transcript is auto-skipped)
TRANSCRIPT_EXCLUSIONS = ['4SD', 'LVM2']

# Episode codes that are currently producing new episodes
# ignore shows not in YT stream (e.g., LVM)
CURRENT_PREFIXES = ['3', '4SD', 'OS', 'M']

def does_value_exist(infobox_obj, param_name):
    '''On a wiki, a parameter's value is blank if it either a) just whitespace or b) a comment.
    Removes whitespace and comments to see whether the value remaining is an empty string.'''
    has_param = infobox_obj.has_param(param_name)
    value = infobox_obj[param_name].value if has_param else ''
    simplified_val = remove_comments(value).strip()
    is_nonempty_val = bool(simplified_val)
    return (has_param and value and is_nonempty_val)


def join_array_on_and(str_iter):
    '''Turns list into a string where items are separated by "," except the last,
    which uses "and" if it is at least three items. Pair joined by "and" only.'''
    return_val = ''
    if len(str_iter) <= 1:
        return_val = str_iter[0]
    elif len(str_iter) == 2:
        return_val = ' and '.join(str_iter)
    elif len(str_iter) > 2:
        return_val = ', '.join([*str_iter[:-1], f'and {str_iter[-1]}'])
    return return_val


class Decoder:
    '''Replaces EPISODE_DECODER with information about every (active) campaign, series, and season.'''
    def __init__(self, filter_to_active=True, json_filename='decoder.json',
                force_download=False, try_local_file=True, write_file=True):
        self.filter_to_active = filter_to_active
        self.json_filename = '/'.join([DATA_PATH, json_filename])
        self.try_local_file = try_local_file
        # check for local file first
        if self.try_local_file:
            try:
                self.decoder_json = self.create_from_json_file()
            except FileNotFoundError:
                pass

        if not hasattr(self, 'decoder_json') or force_download is True:
            self.decoder_json = self.download_decoder_json()
            if write_file:
                with open(self.json_filename, 'w', encoding='utf-8') as json_file:
                    json_file.write(json.dumps(self.decoder_json))

        self.decoder_dict = self.build_decoder_dict()

    def download_decoder_json(self, filter_to_active=None):
        site = pywikibot.Site()
        decoder_json = json.loads(site.expand_text('{{#invoke:Json exporter|dump_as_json|Module:Ep/Decoder/sandbox}}'))
        return decoder_json

    def build_decoder_dict(self, decoder_json=None, filter_to_active=None):
        if decoder_json is None:
            decoder_json = self.decoder_json
        if filter_to_active is None:
            filter_to_active = self.filter_to_active
        decoder_dict = {}
        for campaign_code, campaign_info in decoder_json.items():
            show_title = campaign_info['title']
            list_title = campaign_info.get('listLink', show_title)
            thumbnail_category = campaign_info.get('thumbnailCategory', 'Thumbnails')
            transcript_category = f"Category:{campaign_info.get('transcriptCategory', 'Transcripts')}"
            navbox = f"Template:{campaign_info.get('navbox', '')}"
            values = (show_title, list_title, thumbnail_category, navbox, transcript_category)
            decoder_dict[campaign_code] = values
        if filter_to_active:
            decoder_dict = {k:v for k, v in decoder_dict.items() if k in CURRENT_PREFIXES}
        return decoder_dict

    def create_from_json_file(self):
        with open(self.json_filename) as f:
            decoder_json = json.load(f)
        return decoder_json

decoder = Decoder()
EPISODE_DECODER = decoder.decoder_dict

class Ep:
    '''for handling episode ids'''
    def __init__(self, episode_code, padding_limit=2):
        episode_code = episode_code.strip()
        assert re.match(EP_REGEX, episode_code, flags=re.IGNORECASE)
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
    def prefix(self):
        prefix = self.code.split('x')[0]
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
    def show(self):
        return EPISODE_DECODER[self.prefix][0]

    @property
    def list_page(self):
        return EPISODE_DECODER[self.prefix][1]

    @property
    def thumbnail_page(self):
        return EPISODE_DECODER[self.prefix][2]

    @property
    def navbox_name(self):
        return EPISODE_DECODER[self.prefix][3]

    @property
    def transcript_category(self):
        return EPISODE_DECODER[self.prefix][4]

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
        if self.prefix.isdigit():
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
            code_list = ['x'.join([self.prefix, str(self.number).zfill(1+n)]) for n in range(self.padding_limit)]
        else:
            code_list = ['x'.join([self.prefix, str(self.number).zfill(1+n)]) + self.code[-1] for n in range(self.padding_limit)]
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
            old_id = 'x'.join([self.prefix, f"{old_number:02}"])
            previous_episode = Ep(old_id)
        elif old_number > 0:
            old_id = 'x'.join([self.prefix, f"{old_number:02}"]) + letter
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
            next_id = 'x'.join([self.prefix, f"{next_number:02}"])
            next_episode = Ep(next_id)
        elif next_number > 0:
            next_id = 'x'.join([self.prefix, f"{next_number:02}"]) + letter
            next_episode = Ep(next_id)
        else:
            # no previous id, because the first of its kind
            next_episode = None
        return next_episode


class Actors:
    def __init__(self, input_names, **kwargs):
        self._input_names = input_names
        self.link = kwargs.get('link', True)
        self.matched_only = kwargs.get('matched_only', True)
        self.link_unmatched = kwargs.get('link_unmatched', True)
        if len(input_names.strip()):
            self.name_list, self.name_string = self.actor_names_to_wiki_list()
        else:
            self.name_list = []
            self.name_string = ''

    def match_actors(self):
        actors = re.split('[^\w\s]+', self._input_names)
        matched_list = []
        for actor in actors:
            actor = actor.strip()
            #skip joining words
            if actor.lower() in ['and', 'also']:
                continue
            candidates = [x for x in ACTORS if actor.lower() in x.lower()]
            if len(candidates) == 1:
                match = candidates[0]
            elif len(candidates) > 1:
                if candidates:
                    pywikibot.output(f"Please clarify '{actor}': {candidates}")
                else:
                    pywikibot.output(f"No match for '{actor}'")
                continue
            elif self.matched_only:
                pywikibot.output(f"'{actor}' did not match an actor. Check spelling and use actor's full name")
                continue
            else:
                match = actor
            matched_list.append(match)
        return matched_list

    def make_actor_list_string(self, actor_list=None):
        if actor_list is None:
            actor_list = self.match_actors()
#         matched_actors = [x for x in actor_list if x in ACTORS]
        unmatched_actors = [x for x in actor_list if x not in ACTORS]
        actor_list = deepcopy(actor_list)

        for i, actor in enumerate(actor_list):
            if self.link or (self.link_unmatched and actor in unmatched_actors):
                actor_list[i] = f"[[{actor.strip()}]]"
            else:
                actor = actor

        actor_string = join_array_on_and(actor_list)

        return actor_string

    def actor_names_to_wiki_list(self, actor_list=None):
        if actor_list is None:
            actor_list = self.match_actors()
        if actor_list:
            actor_string = self.make_actor_list_string(actor_list=actor_list)
        else:
            actor_string = ''
        return actor_list, actor_string


def make_image_caption(ep: Ep, actors: Actors) -> str:
    '''For the caption field in the episode article.'''
    # 4-Sided Dive has separate caption conventions from other episode types.
    if ep.prefix == '4SD':
        caption = f' {{{{art official caption|nointro=true|subject=Thumbnail|screenshot=1|source={ep.wiki_code}}}}}'
    elif len(actors.name_list):
        caption = f' {ep.wiki_code} thumbnail featuring {actors.name_string}.'
    else:
        caption = f' {ep.wiki_code} thumbnail.'
    return caption


def make_image_file_description(ep: Ep, actors: Actors) -> str:
    """The description of the image thumbnail file to be uploaded."""
    actor_list = actors.name_string if actors.name_string else "the ''Critical Role'' cast"

    file_description = f"""== Summary ==
{ep.wiki_code} thumbnail featuring {actor_list}.

== Licensing ==
{{{{Fairuse}}}}

[[Category:{ep.thumbnail_page}]]"""
    return file_description


class YT:
    def __init__(self, yt_string):
        yt_string = yt_string.strip()
        self._entry = yt_string
        if re.search(YT_LINK_REGEX, yt_string):
            self.yt_id = re.search(YT_LINK_REGEX, yt_string)['yt_id']
        elif re.match(YT_ID_REGEX, yt_string):
            self.yt_id = yt_string
        else:
            self.yt_id = None

    @property
    def url(self):
        url = f"https://youtu.be/{self.yt_id}"
        return url

    @property
    def thumbnail_url(self):
        url = f"https://img.youtube.com/vi/{self.yt_id}/maxresdefault.jpg"
        return url


def convert_timezone(string, tz=TIMEZONE):
    '''Convert timezone abbreviation to tzinfo-formatted string.'''
    if string in ['PST', 'PDT', 'PT']:
        timezone = ZoneInfo('America/Los_Angeles')
    elif string in ['EST', 'EDT', 'ET']:
        timezone = ZoneInfo('America/New_York')
    else:
        timezone = tz
    return timezone


def convert_string_to_datetime(date_string, tz=TIMEZONE):
    '''Make a datetime object of the episode's airdate and/or airtime.'''
    date = None
    for regex, date_format in date_options:
        if re.search(regex, date_string):
            date_match = re.search(regex, date_string)
            date_string = date_match.group()
            if date_match.groupdict().get('tz_entry'):
                date_string = date_string.replace(date_match['tz_entry'], '').strip()
                timezone = convert_timezone(date_match['tz_entry'])
            else:
                timezone = tz
            date = datetime.strptime(date_string, date_format).replace(tzinfo=timezone)
            break
    return date


class Airdate:
    def __init__(self, input_date, tz=TIMEZONE):
        self.tz = tz
        if isinstance(input_date, datetime):
            self.datetime = input_date
        elif isinstance(input_date, str):
            self.datetime = convert_string_to_datetime(input_date, tz=tz)
        if self.datetime.tzinfo is None:
            self.datetime = self.datetime.replace(tzinfo=tz)

    @property
    def date(self):
        date_string = datetime.strftime(self.datetime.astimezone(tz=self.tz), '%Y-%m-%d')
        return date_string

    @property
    def time(self):
        time_string = datetime.strftime(self.datetime.astimezone(tz=self.tz), '%H:%M %Z')
        return time_string

    @property
    def date_and_time(self):
        datetime_string = datetime.strftime(self.datetime.astimezone(tz=self.tz), '%Y-%m-%d %H:%M %Z')
        return datetime_string

    def __repr__(self):
        return self.date_and_time

    def __eq__(self, other): 
        if not isinstance(other, Airdate):
            # don't attempt to compare against unrelated types
            return False

        return self.datetime == other.datetime

    def __lt__(self, other): 
        if not isinstance(other, Airdate):
            # don't attempt to compare against unrelated types
            return False

        return self.datetime < other.datetime

    def __le__(self, other): 
        if not isinstance(other, Airdate):
            # don't attempt to compare against unrelated types
            return False

        return self.datetime <= other.datetime

    def __gt__(self, other): 
        if not isinstance(other, Airdate):
            # don't attempt to compare against unrelated types
            return False

        return self.datetime > other.datetime

    def __ge__(self, other): 
        if not isinstance(other, Airdate):
            # don't attempt to compare against unrelated types
            return False

        return self.datetime >= other.datetime

    def __hash__(self):
        # necessary for dicts and sets
        return hash((self.datetime))


def convert_string_to_timecode(time_string):
    '''Make a timedelta object of the episode's runtime.'''
    timecode = None
    for regex, time_format in runtime_options:
        if re.search(regex, time_string):
            time_match = re.search(regex, time_string)
            time_string = time_match.group()
            t = datetime.strptime(time_string, time_format)
            timecode = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
            break
    return timecode

class Runtime:
    def __init__(self, input_timecode):
        if isinstance(input_timecode, timedelta):
            self.timecode = input_timecode
        elif isinstance(input_timecode, datetime):
            t = input_timecode
            self.timecode = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
        elif isinstance(input_timecode, str):
            self.timecode = convert_string_to_timecode(input_timecode)

    def __repr__(self):
        return str(self.timecode)

    def __eq__(self, other): 
        if not isinstance(other, Runtime):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode == other.timecode

    def __lt__(self, other): 
        if not isinstance(other, Runtime):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode < other.timecode

    def __le__(self, other): 
        if not isinstance(other, Runtime):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode <= other.timecode

    def __gt__(self, other): 
        if not isinstance(other, Runtime):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode > other.timecode

    def __ge__(self, other): 
        if not isinstance(other, Runtime):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode >= other.timecode

    def __hash__(self):
        # necessary for dicts and sets
        return hash((self.timecode))


def remove_comments(wikicode, return_string=True):
    '''For an item of wikicode, strip out comments. Used to determine if an infobox value
    is truly empty.'''
    raw_value = str(wikicode)
    if wikicode.filter_comments():
        for comment in wikicode.filter_comments():
            value = raw_value.replace(str(comment), '')
    else:
        value = wikicode

    if return_string:
        value = str(value)
    return value

def wikify_html_string(html_string):
    '''Replace italics and bold html with equivalent wiki markup.'''
    # italics
    html_string = re.sub('</?i>', "''", html_string)

    # bold
    html_string = re.sub('</?b>', "'''", html_string)

    html_fixes = {
        '&amp;': '&',
        '&nbsp;': ' ',
        '&quot;': '"',
    }

    # escaped characters
    for html, fixed in html_fixes.items():
        html_string = html_string.replace(html, fixed)

    return html_string


def get_validated_input(regex, arg, value='', attempts=3, req=True,
                        input_msg=None):
    '''For getting pywikibot user input that is validated against regex. Ignores case'''
    counter = 0
    if arg == 'ep' and input_msg is None:
        input_msg = 'Please enter valid episode id (CxNN)'
    elif arg == 'airdate' and input_msg is None:
        input_msg = 'Please enter valid airdate (YYYY-MM-DD)'
    elif input_msg is None:
        input_msg = f'Please enter valid {arg}'
    while counter < attempts and not re.match(regex, value, flags=re.IGNORECASE):
        value = pywikibot.input(input_msg)
        counter += 1
    if not re.match(regex, value):
        print(f'\nInvalid {arg} "{value}". Maximum attempts reached\n', file=sys.stderr)
        if req:
            sys.exit()
    return value
