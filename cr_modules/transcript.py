import json
import re
from collections import Counter
from itertools import groupby

import pywikibot
from nltk import everygrams
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter, JSONFormatter

from .cr import wikify_html_string, SPEAKER_TAGS

def make_ngrams(text, ngram_min=2, ngram_max=4):
    '''for words in a string'''
    return list(everygrams(text.split(), ngram_min, ngram_max))


def sort_ngram_list(ngram_list):
    keyfunc = lambda x:len(x)
    data = sorted(ngram_list, key=keyfunc)
    ngram_dict = {k:list(g) for k, g in groupby(data,keyfunc)}
    return ngram_dict


def text_to_ngram_dict(text, ngram_min=4, ngram_max=None, exclude_quotes=True):
    # Quotation marks are edited from raw and may affect matches.
    if exclude_quotes:
        text = text.replace('"', '')
    if ngram_max is None:
        ngram_max = len(text.split())
    ngram_list = make_ngrams(text, ngram_min, ngram_max)
    ngram_dict = sort_ngram_list(ngram_list)
    return ngram_dict

'''Below is a temporary solution to the problem documented here: https://github.com/jdepoix/youtube-transcript-api/pull/192
If/when this change goes live, the content from here to the next comment marker should be deleted.'''

TEXT_FORMATS = [
    'strong',  # important
    'em',  # emphasized
    'b',  # bold
    'i',  # italic
    'mark',  # marked
    'small',  # smaller
    'del',  # deleted
    'ins',  # inserted
    'sub',  # subscript
    'sup',  # superscript
]
from html import unescape
from xml.etree import ElementTree

class _TranscriptParserNew(object):
    def __init__(self, preserve_formatting=True):
        self.preserve_formatting = preserve_formatting

    @property
    def html_regex(self):
        if self.preserve_formatting:
            formats_regex = '|'.join(TEXT_FORMATS)
            formats_regex = r'<\/?(?!\/?(' + formats_regex + r')\b).*?\b>'
            html_regex = re.compile(formats_regex, re.IGNORECASE)
        else:
            html_regex = re.compile(r'<[^>]*>', re.IGNORECASE)
        return html_regex

    def parse(self, plain_data):
        return [
            {
                'text': re.sub(self.html_regex, '', unescape(xml_element.text)),
                'start': float(xml_element.attrib['start']),
                'duration': float(xml_element.attrib.get('dur', '0.0')),
            }
            for xml_element in ElementTree.fromstring(plain_data)
            if xml_element.text is not None
        ]
import youtube_transcript_api
youtube_transcript_api._transcripts._TranscriptParser = _TranscriptParserNew
'''End deletion HERE. After deleting, update the function in Transcript to read:
transcript_list = YouTubeTranscriptApi.list_transcripts(self.yt.yt_id,
                                                                preserve_formatting=self.preserve_formatting)'''

BREAK_PHRASES = [
    'our break', "we'll take a break", 'go to break',
    "we're going to break", 'after the break', "we're going to take a break",
    'after we take a break', "take an early break", "from our break",
    'back here in a few minutes', 'back in a few minutes', 'see you here in a few minutes',
    'see you in a few minutes',
]
DURING_BREAK_PHRASES = [
    'Hey Critters! Laura Bailey here', 'open your heart to chaos', 'Hi Critters, Sam Riegel here',
]


def break_criteria_1(line, break_taken=False, during_break=False):
    '''Matt says they're taking a break'''
    if (not break_taken and not during_break and
        line.startswith('MATT:') and
        any([x in line.lower() for x in BREAK_PHRASES
            ])):
        return True
    else:
        return False


def break_criteria_2(line, break_taken=False, during_break=False):
    '''One of the speaker names appears capitalized'''
    if (not break_taken and not during_break and
        any([''.join([x.capitalize(), ':']) in line for x in SPEAKER_TAGS
            ])):
        return True
    else:
        return False
SPEAKER_TAGS


def break_criteria_3(line, break_taken=False, during_break=False):
    if (not break_taken and not during_break and
        any([x in line.lower() for x in DURING_BREAK_PHRASES
            ])):
        return True
    else:
        return False


@dataclass
class Breakfinder:
    '''Take a compiled transcript and comment out the break section.'''
    transcript: str = ''
    break_found: bool = False

    def __post_init__(self):
        self.revised_transcript = self.find_break()
        if not self.break_found:
            self.revised_transcript = self.find_break(break_function=break_criteria_2)
        if not self.break_found:
            self.revised_transcript = self.find_break(break_function=break_criteria_3)
        if (self.revised_transcript == self.transcript or
            'BREAK ENDS' not in self.revised_transcript):
            raise

    def find_break(self, break_function=None):
        if self.break_found:
            return self.transcript

        if break_function is None:
            break_function = break_criteria_1

        break_taken = False
        during_break = False
        lines = self.transcript.splitlines()
        for line in lines:
            if break_function(line, break_taken, during_break):
                during_break = True
                old_first_line = line
                new_first_line = old_first_line + '\n\n<!-- BREAK BEGINS\n'
                self.break_found = True
                continue
            elif (during_break and line.startswith('MATT:')
                  and 'welcome back' in line.lower()):
                during_break = False
                break_taken = True
                old_last_line = line
                new_last_line = 'BREAK ENDS -->\n\n== Part II ==\n' + old_last_line
                break
        revised_transcript = (self.transcript
                              .replace(old_first_line, new_first_line)
                              .replace(old_last_line, new_last_line))
        return revised_transcript


class Transcript:
    def __init__(self, ep, yt, ext='txt', write_ts_file=False, ignore_duplicates=False,
                 ignore_break=False, try_local_file=True, preserve_formatting=True,
                 force_redownload=False, **kwargs):
        self.ep = ep
        self.yt = yt
        self.text_filename = f"{self.ep.code}.txt"
        self.json_filename = f"{self.ep.code}.json"
        self.write_ts_file = write_ts_file
        self.force_redownload = force_redownload
        self.try_local_file = try_local_file
        self.ignore_break = ignore_break
        self.ignore_duplicates = ignore_duplicates
        self.preserve_formatting = preserve_formatting

    def download_and_build_transcript(self):
        # check for local file first
        if self.try_local_file:
            try:
                self._captions = self.create_from_json_file()
            except FileNotFoundError:
                pass

        if not hasattr(self, '_captions') or self.force_redownload is True:
            self._captions = self.captions_download()
        self.transcript = self.process_transcript(captions=self._captions)

    def create_from_json_file(self):
        with open(self.json_filename) as f:
            captions = json.load(f)
        return captions

    def save_to_json_file(self, captions=None):
        if captions is None:
            captions = self._captions
        formatter = JSONFormatter()

        # .format_transcript(transcript) turns the transcript into a JSON string.
        json_formatted = formatter.format_transcript(captions)

        # Now we can write it out to a file.
        with open(self.json_filename, 'w', encoding='utf-8') as json_file:
            json_file.write(json_formatted)

    def captions_download(self):
        captions = {}
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
            captions = transcript.fetch()
            if self.write_ts_file:
                self.save_to_json_file(captions=captions)

        return captions

    def process_captions(self, captions=None):
        '''Combine raw captions across line breaks to create transcript.'''
        fixed_lines = ['== Pre-show ==']
        line_in_progress = ''
        active_quote = False
        during_intro = False
        intro_done = False

        if captions is None:
            captions = self._captions

        formatter = TextFormatter()
        captions = formatter.format_transcript(captions)

        for i, line in enumerate(captions.splitlines()):

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
                    and (repeated_sentence[0].islower() or 
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
        # Step 1: Combine lines and remove extraneous quotation marks
        ts = self.process_captions(captions)
        
        # Step 2: remove and replace html markup
        ts = wikify_html_string(ts)

        # Step 3: Flag repeated phrases in-line
        if not self.ignore_duplicates:
            ts = self.flag_duplicates(ts)

        # Step 4: add commented_out error messages to top of transcript
        ts = self.process_errors(ts)

        # Step 5: add navigation and category
        t_cat = self.ep.transcript_category
        ts = ''.join(['{{Transcript-Nav}}\n__FORCETOC__\n\n', 
                      ts,
                      '\n{{Transcript-Nav}}\n', 
                      f'[[{t_cat}]]',
                      '\n[[Category:Transcripts with duplicate lines]]'])

        if self.write_ts_file:
            with open(self.text_filename, 'w') as f:
                f.write(ts)

        # autogenerated captions require different processing (TBD)
        return ts