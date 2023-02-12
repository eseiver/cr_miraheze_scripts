import re
import sys

from collections import Counter
from copy import deepcopy
from datetime import datetime
from itertools import groupby
from string import ascii_lowercase
from zoneinfo import ZoneInfo

import pywikibot

from nltk.util import everygrams
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter


# regular expressions for string matching
EP_REGEX = '^(\d+|OS|M|E\d*|U|4SD|LVM\d+|TM(OS|S)?\d*)x\d+(a|b)?$'  # https://regex101.com/r/QXhVhb/4
ARRAY_ENTRY_REGEX = '''\[\"(?P<epcode>.*?)\"\] = \{\s*\[\"title\"\] = \"(?P<title>.*)\",?((\s*\[\"pagename\"\] = \"(?P<pagename>.*)\",)?(\s*\[\"altTitles\"\] = \{(?P<altTitles>.*)\})?)?'''
YT_LINK_REGEX = '(?P<vod>(?:https?:\/\/)?(?:www\.)?(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))(?P<yt_id>[-\w_]{11})(&t=(?P<timecode>.*))?)'
YT_ID_REGEX = '[-\w_]{11}'

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
    'Brennan Lee Mulligan',
    'Dani Carr',
    'Erika Ishii',
    'Robbie Daymond',
]
SPEAKER_TAGS = [
    'ASHLEY', 'LAURA', 'LIAM', 'MARISHA', 'MATT', 'SAM', 'TALIESIN', 'TRAVIS',
    'ALL', 'AABRIA', 'BRENNAN', 'DANI', 'ERIKA', 'ROBBIE',
]
EPISODE_DECODER = {
    '3': ('Campaign 3', 'List of Campaign 3 episodes',
          'Campaign 3 episode thumbnails', 'Template:Nav-C3Arc1'),
    'OS': ('One-shots', 'One-shots', 'One-shot episode thumbnails', 'Template:Nav-OneShots'),
    'M': ('Bits and bobs', 'Bits and bobs',
          'Bits and bobs episode thumbnails',  'Template:Nav-Bitsnbobs'),
    'LVM2': ('The Legend of Vox Machina',
            'List of The Legend of Vox Machina episodes',
            'The Legend of Vox Machina episode thumbnails',
            'Template:Nav-LoVM Season 2',
            ),
    '4SD': ('4-Sided Dive', '4-Sided Dive', 'Episode thumbnails', 'Template:Nav-4SD'),
    # 'Ep_type': ('show page', 'episode list page', 'episode thumbnail category', 'navbox'),
}

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
    def image_filename(self):
        filename = f"{self.code} Episode Thumb.jpg"
        return filename

    @property
    def wiki_code(self):
        wiki = f'{{{{ep|{self.code}}}}}'
        return wiki

    @property
    def ce_code(self):
        '''For creating the C[Campaign]E[Episode] formatted code. Used by CR.'''
        if self.prefix.isdigit():
            ce = f'C{self.prefix}E{self.number}'
        else:
            ce = ''
        return ce

    @property
    def ce_words(self):
        '''For creating the written-out version of self.ce_code.'''
        if self.prefix.isdigit():
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


def make_ngrams(text, ngram_min=2, ngram_max=4):
    '''for words in a string'''
    return list(everygrams(text.split(), ngram_min, ngram_max))


def sort_ngram_list(ngram_list):
    keyfunc = lambda x:len(x)
    data = sorted(ngram_list, key=keyfunc)
    ngram_dict = {k:list(g) for k, g in groupby(data,keyfunc)}
    return ngram_dict


def text_to_ngram_dict(text, ngram_min=4, ngram_max=None):
    if ngram_max is None:
        ngram_max = len(text.split())
    ngram_list = make_ngrams(text, ngram_min, ngram_max)
    ngram_dict = sort_ngram_list(ngram_list)
    return ngram_dict


class Transcript:
    def __init__(self, ep, yt, ext='txt', write_ts_file=False, **kwargs):
        self.ep = ep
        self.yt = yt
        self.ext = ext
        self.filename = f"{self.ep.code}.{self.ext}"
        self.write_ts_file = write_ts_file

    def download_and_build_transcript(self):
        self._raw_captions = self.captions_download()
        self.transcript = self.process_transcript(captions=self._raw_captions)

    def captions_download(self):
        captions = ''
        transcript_list = YouTubeTranscriptApi.list_transcripts(self.yt.yt_id)
        transcript = None
        try:
            transcript = transcript_list.find_manually_created_transcript(['en'])
            self.manual = True
        except NoTranscriptFound:
            try:
                transcript = transcript_list.find_generated_transcript(['en'])
                self.manual = False
            except NoTranscriptFound:
                pywikibot.output(f'Youtube video for {self.ep.code} does not have any English captions')
        if transcript:
            ts_dict = transcript.fetch()

            formatter = TextFormatter()
            captions = formatter.format_transcript(ts_dict)

        # Now we can write it out to a file.
        if self.write_ts_file:
            with open(f"{self.filename}", "w") as f:
                f.write(captions)

        return captions

    def process_captions(self, captions):
        '''Combine raw captions across line breaks to create transcript.'''
        fixed_lines = ['== Pre-show ==']
        line_in_progress = ''
        active_quote = False
        during_intro = False
        intro_done = False
        during_break = False
        break_taken = False

        for line in captions.splitlines():

            # ignore blank lines
            if not line.strip():
                continue

            # ignore the intro song (with predictable beginning and end), add Part I header
            if "♪ Critical (It's Thursday)" in line and not during_intro and not intro_done:
                during_intro = True
                continue
            elif during_intro and any([x in line.lower() for x in ['(flames', 'welcome back']]):
                during_intro = False
                intro_done = True
                line_in_progress += '\n\n== Part I ==\n\n'
                continue
            elif during_intro:
                continue

            # ignore the content of the break
            if (not break_taken and not during_break and (line.startswith('MATT:') or line_in_progress.startswith('MATT:'))
                and any([x in line.lower() for x in [
                'take our break', "we'll take a break", 'go to break', 'after our break',
                "we're going to break", 'after the break', "we're going to take a break",
                'after we take a break', "take an early break",
            ]])):
                during_break = True
                line += '\n\n<!-- BREAK BEGINS '
            elif (during_break and (line.startswith('MATT:') or line_in_progress.startswith('MATT:'))
                and 'welcome back' in line.lower()):
                during_break = False
                break_taken = True
                # if line_in_progress:
                #     line_in_progress = 'BREAK ENDS -->\n\n== Part II ==\n\n' + line_in_progress
                # else:
                line_in_progress += 'BREAK ENDS -->\n\n== Part II ==\n'
            elif during_break:
                pass

            # if ongoing quote, the first '"' can be ignored
            if active_quote and line.startswith('"'):
                line = line[1:]

            # handle quotation marks
            if not active_quote and line.count('"') % 2 != 0:
                active_quote = True

            # this indicates a person is speaking (and thus a new line begins)
            if re.search('^[A-Z].*?[A-Z]:', line):
                if line_in_progress:
                    fixed_lines.append(line_in_progress)
                line_in_progress = line

            # these are non-dialogue descriptions that get their own lines (if not in middle of quote)
            elif line.startswith('(') and not line_in_progress and not active_quote:
                fixed_lines.append(line_in_progress)
                line_in_progress = ''
                fixed_lines.append(line)

            # this is a continuation of the previous line. If quotation marks are even, the active quote is done.
            elif line_in_progress:
                line_in_progress = ' '.join([line_in_progress.strip(), line.strip()]).strip()
                if line_in_progress.count('"') % 2 == 0:
                    active_quote = False

            else:
                pass
        # add last line
        fixed_lines.append(line_in_progress)

        transcript = '\n\n'.join(fixed_lines)

        # replace curly quotes and apostrophes
        transcript = (transcript
                .replace('“', '"')
                .replace('”','"')
                .replace("‘", "'")
                .replace("’", "'")
                )
        return transcript

    def check_ts_names(self, transcript):
        '''For making sure that there are no typos in speakers' names. Returns error message if not.'''
        error_warning = ''
        transcript_names = ' '.join([x.split(':')[0] for x in transcript.splitlines() if ':' in x])

        # the only lowercase word before the colon should be 'and'
        try:
            assert set(re.findall('[a-z]+', transcript_names)) == {'and'}
        except AssertionError:
            errors = [x for x in set(re.findall('[a-z]+', transcript_names)) if x != 'and']
            error_warning += f"Words besides 'and' in lower case for speaker names: {errors}" + '\n'

        # all uppercase words should be names in CR_UPPER
        try:
            assert set(re.findall('[A-Z]+', transcript_names)).issubset(SPEAKER_TAGS)
        except AssertionError:
            names = [x for x in set(re.findall('[A-Z]+', transcript_names)) if x not in SPEAKER_TAGS]
            error_warning += f"Some speaker names potentially misspelled: {names}" + '\n'

        return error_warning

    def flag_duplicates(self, transcript):
        during_break = False
        for line in transcript.splitlines():
            # don't worry about music
            if '♪' in line:
                continue

            # ignore lines during breaks
            if 'BREAK BEGINS' in line:
                during_break = True
            if 'BREAK ENDS' in line:
                during_break = False
                continue
            elif during_break:
                continue

            ngram_dict = text_to_ngram_dict(line)

            duplicate_ngrams = {k: [x for x in v if Counter(v)[x] > 1] for k,v in reversed(ngram_dict.items())
                                if len(set(v)) != len(v)}
            longest_ngrams = []
            dupe_ngrams = [ngram for v in duplicate_ngrams.values() for ngram in set(v)]
            for ngram in dupe_ngrams:
                if not any([set(ngram).issubset(x) for x in longest_ngrams]):
                    longest_ngrams.append(ngram)

            new_line = line
            for ngram in longest_ngrams:
                repeated_sentence = ' '.join(ngram)
                first_idx = new_line.find(repeated_sentence)
                second_idx = new_line.rfind(repeated_sentence)
                distance_between_lines = second_idx-(first_idx+len(repeated_sentence))
                if (-1 < distance_between_lines < 3 and line.count(repeated_sentence) == 2
                    and (repeated_sentence[0].lower() == repeated_sentence[0] or 
                         repeated_sentence[-1] not in ['!', '?', '.'])):
                    new_line = f'{repeated_sentence}<!-- potential duplicate -->'.join(new_line.rsplit(repeated_sentence, 1))
                else:
                    new_line = f'{repeated_sentence}<!-- should not be a duplicate -->'.join(new_line.rsplit(repeated_sentence, 1))
            if new_line != line:
                transcript = transcript.replace(line, new_line)
        return transcript

    def process_errors(self, ts):
        '''Can add more processes later if needed.'''
        errors_comments = ''

        # verify that actor names are correct
        errors_comments += self.check_ts_names(ts)

        # add commented_out error messages to top of transcript
        if errors_comments:
            errors_comments = ''.join(['<!--', errors_comments, '-->\n\n'])
            ts = errors_comments + ts

        return ts

    def process_transcript(self, captions):
        # Step 1: remove and replace html markup
        captions = wikify_html_string(captions)

        # Step 2: Combine lines and remove extraneous quotation marks
        ts = self.process_captions(captions)

        # Step 3: Flag repeated phrases in-line
        ts = self.flag_duplicates(ts)

        # Step 4: add commented_out error messages to top of transcript
        ts = self.process_errors(ts)

        # Step 5: add navigation
        ts = '{{Transcript-Nav}}\n__FORCETOC__\n\n' + ts + '\n{{Transcript-Nav}}'

        if self.write_ts_file:
            with open(f'{self.ep.code}_fixed.{self.ext}', 'w') as f:
                f.write(ts)

        # autogenerated captions require different processing (TBD)

        return ts


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
