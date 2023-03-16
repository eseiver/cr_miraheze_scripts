import re
from collections import Counter
from itertools import groupby

import pywikibot
from nltk import everygrams
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter

from cr import wikify_html_string, SPEAKER_TAGS

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


class Transcript:
    def __init__(self, ep, yt, ext='txt', write_ts_file=False, **kwargs):
        self.ep = ep
        self.yt = yt
        self.ext = ext
        self.filename = f"{self.ep.code}.{self.ext}"
        self.write_ts_file = write_ts_file
        self.preserve_formatting = True

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
        # Step 1: remove and replace html markup
        captions = wikify_html_string(captions)

        # Step 2: Combine lines and remove extraneous quotation marks
        ts = self.process_captions(captions)

        # Step 3: Flag repeated phrases in-line
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
            with open(f'{self.ep.code}_fixed.{self.ext}', 'w') as f:
                f.write(ts)

        # autogenerated captions require different processing (TBD)

        return ts