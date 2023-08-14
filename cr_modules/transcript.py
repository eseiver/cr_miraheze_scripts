import json
import re
from dataclasses import dataclass, field

import pywikibot
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from youtube_transcript_api.formatters import JSONFormatter

from .cr import wikify_html_string, ActorData, Ep

BREAK_PHRASES = [
    'our break', "we'll take a break", 'go to break',
    "we're going to break", 'after the break', "we're going to take a break",
    'after we take a break', "take an early break", 'go ahead and take a break',
    'back here in a few minutes', 'back in a few minutes', 'see you here in a few minutes',
    'see you in a few minutes',
]
DURING_BREAK_PHRASES = [
    'hey critters! laura bailey here', 'open your heart to chaos', 'hi critters, sam riegel here',
    "chop it off. let's do it.", '(gale laughing) later, chudruckers!'
]

actor_data = ActorData()

def break_criteria_1(line, break_taken=False, during_break=False):
    '''Matt says they're taking a break'''
    if (not break_taken and not during_break and
        line.startswith('MATT:') and
        any([x in line.lower() for x in BREAK_PHRASES
            ])):
        return True
    else:
        return False


def break_criteria_2(line, break_taken=False, during_break=False, actor_data=actor_data):
    '''One of the speaker names appears capitalized'''
    if (not break_taken and not during_break and
        any([''.join([x.capitalize(), ':']) in line for x in actor_data.speaker_tags
            ])):
        return True
    else:
        return False


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
    ep: Ep = ''
    break_found: bool = False

    def __post_init__(self):
        self.revised_transcript = self.find_break()
        if not self.break_found:
            self.revised_transcript = self.find_break(break_function=break_criteria_2)
        if not self.break_found:
            self.revised_transcript = self.find_break(break_function=break_criteria_3)
        try:
            assert self.revised_transcript == self.transcript or 'BREAK ENDS' in self.revised_transcript, 'End of break not detected'
        except AssertionError as e:
            if self.ep.prefix in ['M'] and self.transcript != self.revised_transcript:
                self.revised_transcript = self.transcript  # Discard the revised version, assume has no break
                pywikibot.output(f'Break not detected for {self.ep.code} transcript')
            else:
                # important that there is not a hanging beginning of comment without the end
                raise e

    def find_break(self, break_function=None):
        if self.break_found:
            return self.transcript

        if break_function is None:
            break_function = break_criteria_1

        break_taken = False
        during_break = False
        old_first_line = ''
        old_last_line = ''
        new_first_line = ''
        new_last_line = ''
        revised_transcript = self.transcript
        lines = self.transcript.splitlines()
        for i, line in enumerate(lines):
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
                next_lines = '\n'.join(lines[i+1:i+5])   # avoids adding this twice
                old_last_line = '\n'.join([line, next_lines])
                new_last_line = 'BREAK ENDS -->\n\n== Part II ==\n\n' + old_last_line
                break
        if old_first_line and new_first_line:
            revised_transcript = (revised_transcript
                                  .replace(old_first_line, new_first_line))
        if old_last_line and new_last_line:
            revised_transcript = (revised_transcript
                                  .replace(old_last_line, new_last_line))
        return revised_transcript


class YoutubeTranscript:
    def __init__(self, ep, yt, write_ts_file=False, ignore_duplicates=False,
                 ignore_break=False, try_local_file=True, preserve_formatting=True,
                 force_redownload=False, **kwargs):
        self.ep = ep
        self.yt = yt
        self.transcript_folder = 'generated_transcripts'
        self.json_folder = 'transcript_json'
        self.text_filename = f"{self.transcript_folder}/{self.ep.code}.txt"
        self.json_filename = f"{self.json_folder}/{self.ep.code}.json"
        self.write_ts_file = write_ts_file
        self.force_redownload = force_redownload
        self.try_local_file = try_local_file
        self.ignore_break = ignore_break
        self.ignore_duplicates = ignore_duplicates
        self.preserve_formatting = preserve_formatting
        self.actor_data = actor_data
        self.dupe_lines = []

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
            captions = transcript.fetch(preserve_formatting=True)
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

        # split captions along linebreaks if a new speaker
        caption_lines = []
        for i, line in enumerate(captions):
            lines = [x.strip() for x in line['text'].split('\n')]
            if not re.match('^([A-Z]{2}|\()', lines[-1]):
                lines = [line['text'].replace('\n', ' ')]
            for l in lines:
                line_and_starttime = (l, int(line['start']))
                caption_lines.append(line_and_starttime)

        # hide duplicate lines with wiki comments
        preprocessed_lines = []
        for i, (line, starttime) in enumerate(caption_lines):
            dupe = False
            # ignore blank lines
            if not line.strip():
                continue
            if line == caption_lines[i-1][0] and not re.match('^\(', line):
                dupe = True
            elif not re.match('^\(', line):
                text1 = [x for x in line if x.isalpha()]
                text2 = [x for x in caption_lines[i-1][0] if x.isalpha()]
                if text1 == text2 and len(text1) > 10:
                    dupe = True
            if dupe:
                dupe_starttime = caption_lines[i-1][1]
                line = '<!-- DUPLICATE ' + line + '-->'
                self.dupe_lines.append((wikify_html_string(line), dupe_starttime))
            preprocessed_lines.append(line)

        # combine across all lines into single txt file
        for i, line in enumerate(preprocessed_lines):

            # ignore the intro song (with predictable beginning and end), add Part I header
            if (not during_intro and
                not intro_done and
                (re.search("♪ Critical\s+\(It's Thursday\)", line)) or
                line.strip() == "ALL: ♪ Critical"):
                during_intro = True
                continue
            elif during_intro and any([x in line.lower() for x in ['(flames', 'welcome back']]):
                during_intro = False
                intro_done = True
                line_in_progress += '\n\n== Part I ==\n'
                continue
            elif during_intro:
                continue

            # if ongoing quote, the first '"' can be ignored
            if active_quote and line.startswith('"'):
                line = line[1:]

            # handle quotation marks, excluding comments
            quote_count = re.sub('<\!--.*?-->', '', line).count('"')
            if not active_quote and quote_count % 2 != 0:
                active_quote = True

            # flag potential missing colon
            if any([x in line for x in self.actor_data.speaker_tags]) and ':' not in line:
                line = '<!-- potential missing speaker tag -->' + line

            # this indicates a person is speaking (and thus a new line begins)
            if re.search('^[A-Z].*?[A-Z]:', line):
                if line_in_progress:
                    fixed_lines.append(line_in_progress)
                line_in_progress = line
                current_speaker = re.search('^[A-Z].*?[A-Z]:', line)

            # these are non-dialogue descriptions that get their own lines (if not in middle of quote)
            elif re.match('^\(.*?\)$', line.strip()) and not active_quote:
                if i+1 >= len(preprocessed_lines):
                    fixed_lines.append(line)
                    continue
                prev_line = preprocessed_lines[i-1] if i != 0 else ''
                next_line = preprocessed_lines[i+1] if len(preprocessed_lines) > i else ''
                if bool(re.search('^[A-Z].*?[A-Z]:', next_line) and not re.search(':$', prev_line)):
                    fixed_lines.append(line_in_progress)
                    line_in_progress = ''
                    fixed_lines.append(line)
                else:
                    line_in_progress = ' '.join([line_in_progress.strip(), line.strip()]).strip()
                    quote_count = re.sub('<\!--.*?-->', '', line_in_progress).count('"')
                    if quote_count % 2 == 0:
                        active_quote = False

            # continuation of previous line; if quotation marks are even, active quote is done
            elif line_in_progress:
                line_in_progress = ' '.join([line_in_progress.strip(), line.strip()]).strip()
                quote_count = re.sub('<\!--.*?-->', '', line_in_progress).count('"')
                if quote_count % 2 == 0:
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

        # don't check names if there are no standard ones to begin with
        if not any(tag in transcript for tag in self.actor_data.speaker_tags):
            return ''

        # the only lowercase word before the colon should be 'and'
        try:
            assert set(re.findall('[a-z]+', transcript_names)) == {'and'}
        except AssertionError:
            errors = [x for x in set(re.findall('[a-z]+', transcript_names)) if x != 'and']
            error_warning += f"Words besides 'and' in lower case for speaker names: {errors}" + '\n'

        # all uppercase words should be names in CR_UPPER
        try:
            assert set(re.findall('[A-Z]+', transcript_names)).issubset(self.actor_data.speaker_tags)
        except AssertionError:
            names = [x for x in set(re.findall('[A-Z]+', transcript_names))
                     if x not in self.actor_data.speaker_tags]
            error_warning += f"Some speaker names potentially misspelled: {names}" + '\n'

        return error_warning

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
        # Step 1: Combine lines, flag duplicates, remove extraneous quotation marks
        ts = self.process_captions(captions)

        # Step 2: remove and replace html markup
        ts = wikify_html_string(ts)

        # Step 3: Comment out the break
        if not self.ignore_break:
            ts = Breakfinder(transcript=ts, ep=self.ep).revised_transcript

        # Step 4: Add cleanup tag if no speaker tags found
        if not any(tag in ts for tag in self.actor_data.speaker_tags):
            ts = f'{{{{cleanup|speaker tags not found}}}}\n\n{ts}'
            pywikibot.output("No speaker tags found in transcript; tagged for cleanup.")

        # Step 5: add commented_out error messages to top of transcript
        ts = self.process_errors(ts)

        # Step 6: add navigation and category
        t_cat = f"Category:{self.ep.transcript_category}"
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
