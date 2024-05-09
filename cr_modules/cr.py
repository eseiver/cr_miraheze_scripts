import json
import os
import re
import sys

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import mwparserfromhell
import pywikibot

from .ep import Ep, LuaReader, DATA_PATH

# regular expressions for string matching
ARRAY_ENTRY_REGEX = r'''\[\"(?P<epcode>.*?)\"\] = \{\s*\[\"title\"\] = \"(?P<title>.*)\",?((\s*\[\"pagename\"\] = \"(?P<pagename>.*)\",)?(\s*\[\"altTitles\"\] = \{(?P<altTitles>.*)\})?)?'''
YT_LINK_REGEX = r'(?P<vod>(?:https?:\/\/)?(?:www\.)?(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))(?P<yt_id>[-\w_]{11})(&t=(?P<timecode>.*))?)'
YT_ID_REGEX = r'[-\w_]{11}'
LONG_SHORT_REGEX = r"\|\s*(?P<num>\d+)\s*\|\|.*?\{\{ep\|(?P<ep_code>.*?)(\|.*?)?\}\}.*?\|\| (?P<timecode>(\d+:\d+){2,3})"
MIDST_APPENDIX_REGEX = r'''\[\"(?P<epcode>.*?)\"\] = \{\s*\[\"ID\"\] = \"(?P<ID>.*)\",?((\s*\[\"date\"\] = \"(?P<date>.*)\",)?(\s*\[\"prefix\"\] = \"(?P<prefix>.*)\",)?)?(\s*\[\"quote\"\] = \"(?P<quote>.*)\",)?(\s*\[\"archive\"\] = \"(?P<archive>.*)\",)?(\s*\[\"ghostarchive\"\] = \"(?P<ghostarchive>.*)\")?'''

# pagenames
INFOBOX_EPISODE = 'Infobox Episode'
EP_ARRAY = 'Module:Ep/Array'
AIRDATE_ORDER = 'Module:AirdateOrder/Array'
YT_SWITCHER = 'Module:Ep/YTURLSwitcher/URLs'
PODCAST_SWITCHER = 'Module:Ep/PodcastSwitcher/URLs'
TRANSCRIPTS_LIST = 'Transcripts'
MIDST_APPENDIX_ARRAY = 'Module:Midst appendices/Array'

# offline access
DUMP_FILE = 'criticalrolewiki_xml_9f434337d0bebb5e3bad.xml.gz'
DUMP_STRING = '12:33, April 22, 2024'
DUMP_PATH = os.path.join(DATA_PATH, DUMP_FILE)
DUMP_DATE = datetime.strptime(DUMP_STRING, '%H:%M, %B %d, %Y')
LATEST_DUMP_FILE = 'latest_revisions_only.xml.gz'
LATEST_DUMP_PATH = os.path.join(DATA_PATH, LATEST_DUMP_FILE)

# date and time
TIMEZONE = ZoneInfo("America/Los_Angeles")  # where Critical Role is based
DATE_REGEX = r'\d{4}-\d{1,2}-\d{1,2}'
DATE_FORMAT = '%Y-%m-%d'
DATE_2_REGEX = r'\d{1,2}-\d{1,2}-\d{4}'
DATE_2_FORMAT = '%m-%d-%Y'
TIME_REGEX = r'\d{1,2}:\d{2}\s*(?P<tz_entry>\w{2,3})?'
TIME_FORMAT = '%H:%M'
DATETIME_REGEX = r'\s*'.join([DATE_REGEX, TIME_REGEX])
DATETIME_FORMAT = ' '.join([DATE_FORMAT, TIME_FORMAT])
date_options = ((DATETIME_REGEX, DATETIME_FORMAT),
                (DATE_REGEX, DATE_FORMAT),
                (DATE_2_REGEX, DATE_2_FORMAT),
                (TIME_REGEX, TIME_FORMAT),
               )
# runtimes
RUNTIME_REGEX = r'\d{1,2}:\d{2}:\d{2}'
RUNTIME_FORMAT = '%H:%M:%S'
RUNTIME_2_REGEX = r'\d{1,2}:\d{2}'
RUNTIME_2_FORMAT = '%M:%S'
runtime_options = ((RUNTIME_REGEX, RUNTIME_FORMAT),
                   (RUNTIME_2_REGEX, RUNTIME_2_FORMAT),
                   )


def does_value_exist(infobox_obj, param_name):
    '''On a wiki, a parameter's value is blank if it either a) just whitespace or b) a comment.
    Removes whitespace and comments to see whether the value remaining is an empty string.'''
    has_param = infobox_obj.has_param(param_name)
    value = infobox_obj[param_name].value if has_param else ''
    if value:
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

@dataclass
class ActorData(LuaReader):
    '''Actor names and all relevant speaker tags.'''
    module_name: str = 'ActorData'
    json_filename: str = 'actors.json'

    @property
    def actor_names(self):
        return [x[0] for x in self._json['actors']]

    @property
    def speaker_tags(self):
        return [x[1] for x in self._json['actors']] + self._json['otherSpeakerTags']

ACTOR_DATA = ActorData()
# ACTORS = actor_data.actor_names
# SPEAKER_TAGS = actor_data.speaker_tags

class Actors:
    def __init__(self, input_names, actor_data=None, **kwargs):
        self._input_names = input_names
        self.actor_data = actor_data
        if not self.actor_data:
            self.actor_data = ACTOR_DATA
        self.link = kwargs.get('link', True)
        self.matched_only = kwargs.get('matched_only', True)
        self.link_unmatched = kwargs.get('link_unmatched', True)
        if len(input_names.strip()):
            self.name_list, self.name_string = self.actor_names_to_wiki_list()
        else:
            self.name_list = []
            self.name_string = ''

    def match_actors(self):
        actors = re.split(r'[^\w\s]+', self._input_names)
        matched_list = []
        all_names = self.actor_data.actor_names
        all_unique_names = len(set([x.lower().split()[0] for x in all_names])) == len(all_names)
        for actor in actors:
            actor = actor.strip()
            # Skip joining words
            if actor.lower() in ['and', 'also']:
                continue
            candidates = []
            if all_unique_names:
                candidates = [x for x in all_names if actor.lower() in x.lower().split()[0]]
            if not candidates:
                candidates = [x for x in all_names if actor.lower() in x.lower()]
            if len(candidates) == 1:
                match = candidates[0]
            elif len(candidates) > 1:
                choices = [(str(i+1), x) for i, x in enumerate(candidates)]
                choice = pywikibot.input_choice(f"Please clarify '{actor}'", choices)
                match = next(x for x in candidates if x.lower() == choice.lower())
            elif self.matched_only:
                pywikibot.output(f"No match for '{actor}'. Check spelling or re-run script using <<yellow>>-download_data<<default>> flag.")
                name_entered = pywikibot.input_yn(f"Is {actor} their full name?")
                if not name_entered:
                    match = pywikibot.input("Enter full name:")
                else:
                    match = actor
                if match not in self.actor_data.actor_names:
                    pywikibot.output(f"Done. Please add {match} to <<yellow>>Module:ActorData<<default>>.")
            else:
                match = actor
            matched_list.append(match)
        return matched_list

    def make_actor_list_string(self, actor_list=None):
        if actor_list is None:
            actor_list = self.match_actors()
#         matched_actors = [x for x in actor_list if x in ACTORS]
        unmatched_actors = [x for x in actor_list if x not in self.actor_data.actor_names]
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
        caption = f' {{{{art official caption|nointro=true|subject=Thumbnail|screenshot=1|source={ep.wiki_nolink}}}}}'
    elif actors and len(actors.name_list):
        caption = f' {ep.wiki_nolink} thumbnail featuring {actors.name_string}.'
    else:
        caption = f' {ep.wiki_nolink} thumbnail.'
    return caption


def make_image_file_description(ep: Ep, actors: Actors) -> str:
    """The description of the image thumbnail file to be uploaded."""
    actor_list = actors.name_string if actors and actors.name_string else "the ''Critical Role'' cast"

    file_description = f"""== Summary ==
{ep.wiki_code} thumbnail featuring {actor_list}.

== Licensing ==
{{{{Fairuse}}}}

[[Category:{ep.campaign.thumbnail_category}]]"""
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

    @property
    def thumbnail_url_backup(self):
        url = f"https://img.youtube.com/vi/{self.yt_id}/hqdefault.jpg"
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

    def __add__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return Runtime(self.timecode + other.timecode)

    def __sub__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return Runtime(self.timecode - other.timecode)

    def __eq__(self, other): 
        if not isinstance(other, self.__class__):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode == other.timecode

    def __lt__(self, other): 
        if not isinstance(other, self.__class__):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode < other.timecode

    def __le__(self, other): 
        if not isinstance(other, self.__class__):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode <= other.timecode

    def __gt__(self, other): 
        if not isinstance(other, self.__class__):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode > other.timecode

    def __ge__(self, other): 
        if not isinstance(other, self.__class__):
            # don't attempt to compare against unrelated types
            return False

        return self.timecode >= other.timecode

    def __hash__(self):
        # necessary for dicts and sets
        return hash((self.timecode))


class Logline:
    '''For Midst, create a logline quotebox for the top of the article.'''
    def __init__(self, text):
        if isinstance(text, str):
            self.line = ''.join([
                f'''\n{{{{Quotebox|class=header|quote={text}|''',
                'source=Official logline<ref>[https://midst.co/episodes/ Episodes] '
                'at the official ''Midst'' website.</ref>}}'])
        else:
            raise ValueError('Logline text must be a string')

    @property
    def wikicode(self):
        # TO DO: make wikicode object version
        template = mwparserfromhell.nodes.Template('Quotebox')
        pass

    def __repr__(self):
        return self.line


def remove_comments(wikicode, return_string=True):
    '''For an item of wikicode, strip out comments. Used to determine if an infobox value
    is truly empty.'''
    raw_value = str(wikicode)

    # Check if there are comments in the wikicode
    if wikicode.filter_comments():
        # Replace all comments in one go
        for comment in wikicode.filter_comments():
            raw_value = raw_value.replace(str(comment), '')

    if return_string:
        value = raw_value
    else:
        value = mwparserfromhell.parse(raw_value)

    return value


def wikify_html_string(html_string):
    '''Replace italics and bold html with equivalent wiki markup.'''
    # italics
    html_string = re.sub(r'</?i>', "''", html_string)

    # bold
    html_string = re.sub(r'</?b>', "'''", html_string)

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
    elif arg == 'airsub' and input_msg is None:
        input_msg = 'Please enter valid subscriber airdate (YYYY-MM-DD)'
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
