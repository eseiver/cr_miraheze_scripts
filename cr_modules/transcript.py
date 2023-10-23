import json
import os
import re
import sys
from dataclasses import dataclass, field

import pywikibot
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from youtube_transcript_api.formatters import JSONFormatter

from .cr import wikify_html_string, ActorData, Ep
from .ep import DATA_PATH

TRANSCRIPT_PATH = os.path.join(DATA_PATH, 'generated_transcripts')
JSON_PATH = os.path.join(DATA_PATH, 'transcript_json')

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

DEFAULT_LANGUAGE = 'en'

actor_data = ActorData()

SPEAKER_TAGS_RU = [
    'МЭТТ',
    'ТРЭВИС',
    'ЛОРА',
    'МАРИША',
    'СЭМ',
    'ЛИАМ',
    'ТАЛЕСИН',
    'ЭШЛИ',
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

def welcome_back(line, language=DEFAULT_LANGUAGE):
    welcome_backs = {
        'en': 'welcome back',
        'fr': 'bienvenue à nouveau',
        'it': 'bentornato',
        'pt': 'bem-vindos de volta',
        'es': 'bienvenido de nuevo',
        }
    if welcome_backs[language] in line.lower():
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
                  and welcome_back(line)):
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
        self.transcript_folder = TRANSCRIPT_PATH
        self.json_folder = JSON_PATH
        self.text_filename = os.path.join(self.transcript_folder, f"{self.ep.code}.txt")
        self.json_filename = os.path.join(self.json_folder, f"{self.ep.code}.json")
        self.write_ts_file = write_ts_file
        self.force_redownload = force_redownload
        self.try_local_file = try_local_file
        self.ignore_break = ignore_break
        self.ignore_duplicates = ignore_duplicates
        self.preserve_formatting = preserve_formatting
        self.actor_data = actor_data
        self.dupe_lines = {}

    def create_from_json_file(self, language=DEFAULT_LANGUAGE):
        if language == DEFAULT_LANGUAGE:
            filename = self.json_filename
        else:
            filename = os.path.join(self.json_folder, f"{self.ep.code}_{language}.json")
        with open(filename) as f:
            captions = json.load(f)
        return captions

    def save_to_json_file(self, captions=None, language=DEFAULT_LANGUAGE):
        os.makedirs(self.json_folder, exist_ok=True)
        if captions is None:
            captions = self.captions_dict.get(language, {})
        formatter = JSONFormatter()
        json_formatted = formatter.format_transcript(captions)

        # Now we can write it out to a file.
        if language == DEFAULT_LANGUAGE:
            filename = self.json_filename
        else:
            filename = os.path.join(self.json_folder, f"{self.ep.code}_{language}.json")
        with open(filename, 'w', encoding='utf-8') as json_file:
            json_file.write(json_formatted)

    @property
    def transcript_list(self):
        if  not hasattr(self, '_transcript_list') or self._transcript_list is None:
            self._transcript_list = YouTubeTranscriptApi.list_transcripts(self.yt.yt_id)
        return self._transcript_list

    @property
    def languages(self, manual_only=True):
        if not hasattr(self, '_languages') or self._languages is None:
            if manual_only:
                self._languages = [x.language_code for x in self.transcript_list
                                   if not x.is_generated]
            else:
                self._languages = [x.language_code for x in self.transcript_list]
        return self._languages

    def captions_download(self, language=DEFAULT_LANGUAGE):
        if not hasattr(self, 'captions_dict'):
            self.captions_dict = {}
        transcript = None

        language_list = [language]
        try:
            transcript = self.transcript_list.find_manually_created_transcript(language_list)
            self.manual = True
        except NoTranscriptFound:
            try:
                transcript = self.transcript_list.find_generated_transcript(language_list)
                self.manual = False
            except NoTranscriptFound:
                pywikibot.output(f'Youtube video for {self.ep.code} does not have any {language} captions')
        if transcript:
            captions = transcript.fetch(preserve_formatting=True)
            self.captions_dict[language] = captions
            if self.write_ts_file:
                self.save_to_json_file(captions=captions, language=language)

        return captions

    def divide_captions_by_speaker(self, captions=None, language=DEFAULT_LANGUAGE):
        if captions is None and language:
            captions = self.captions_dict.get(language, {})
        caption_lines = []
        for i, line in enumerate(captions):
            lines = [x.strip() for x in line['text'].split('\n')]
            if not re.match('^([A-Z]{2}|\()', lines[-1]):
                lines = [line['text'].replace('\n', ' ')]
            for l in lines:
                line_and_starttime = (l, int(line['start']))
                caption_lines.append(line_and_starttime)
        return caption_lines

    def flag_duplicate_captions(self, caption_lines, language=DEFAULT_LANGUAGE):
        preprocessed_captions = []
        if not self.dupe_lines.get(language):
            self.dupe_lines[language] = []
        for i, (line, starttime) in enumerate(caption_lines):
            dupe = False
            # ignore blank lines and music
            if not line.strip():
                continue
            if '♪' in line:
                pass
            elif line == caption_lines[i-1][0] and not re.match('^\(', line):
                dupe = True
            elif not re.match('^\(', line):
                text1 = [x for x in line if x.isalpha()]
                text2 = [x for x in caption_lines[i-1][0] if x.isalpha()]
                if text1 == text2 and len(text1) > 10:
                    dupe = True
            if dupe:
                dupe_starttime = caption_lines[i-1][1]
                line = '<!-- DUPLICATE ' + line + '-->'
                self.dupe_lines[language].append((wikify_html_string(line), dupe_starttime))
            preprocessed_captions.append(line)
        return preprocessed_captions

    def combine_preprocessed_captions(self, preprocessed_captions, language=DEFAULT_LANGUAGE):
        during_intro = False
        intro_done = False
        active_quote = False
        fixed_lines = []
        line_in_progress = ''

        found_music = False

        # don't worry about deleting the intro song if not English
        if language != DEFAULT_LANGUAGE:
            intro_done = True

        if language == 'ru':
            speaker_tags = SPEAKER_TAGS_RU
            all_uppers = '[{}]'.format("".join(
                [chr(i) for i in range(sys.maxunicode) if chr(i).isupper()]
                ))
            speaker_regex = f'^{all_uppers}.*?{all_uppers}\s*:'
        else:
            speaker_tags = self.actor_data.speaker_tags
            speaker_regex = '^[A-Z].*?[A-Z]\s*:'

        for i, line in enumerate(preprocessed_captions):
            next_line = (preprocessed_captions[i+1]
                         if not intro_done and i < len(preprocessed_captions) - 1
                         else '')

            # ignore the intro song (with predictable beginning and end), add Part I header
            # if not during_intro and not intro_done:

            if (not during_intro and
                not intro_done and
                (re.search("♪ It's Thursday night ♪", line) or
                "♪ critical" in line.strip().lower())):
                if during_intro:
                    print(f'error finding intro for {self.ep}')
                during_intro = True
                continue
            elif during_intro and (welcome_back(line, language=language) or
                                   any(x in line.lower() for x in [
                                       'flames',
                                       'fire',
                                       'wind'
                                   ])):
                during_intro = False
                intro_done = True
                if welcome_back(line, language=language):
                    line_in_progress += ('\n\n== Part I ==\n\n' + line)
                else:
                    line_in_progress += '\n\n== Part I =='
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
            if any([x in line for x in speaker_tags]) and ':' not in line:
                line = '<!-- potential missing speaker tag -->' + line

            # this indicates a person is speaking (and thus a new line begins)
            if re.search(speaker_regex, line):
                if line_in_progress:
                    fixed_lines.append(line_in_progress)
                line_in_progress = line
                current_speaker = re.search(speaker_regex, line)

            # these are non-dialogue descriptions that get their own lines (if not in middle of quote)
            elif re.match('^\(.*?\)$', line.strip()) and not active_quote:
                if i+1 >= len(preprocessed_captions):
                    fixed_lines.append(line)
                    continue
                prev_line = preprocessed_captions[i-1] if i != 0 else ''
                next_line = preprocessed_captions[i+1] if len(preprocessed_captions) > i else ''
                if bool(re.search(speaker_regex, next_line) and not re.search(':$', prev_line)):
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

        return transcript

    def process_captions(self, captions=None, language=DEFAULT_LANGUAGE):
        '''Combine raw captions across line breaks to create transcript.'''

        if captions is None and language:
            captions = self.captions_dict.get(language, {})

        # split captions along linebreaks if a new speaker
        caption_lines = self.divide_captions_by_speaker(language=language)

        # hide duplicate lines with wiki comments
        preprocessed_captions = self.flag_duplicate_captions(caption_lines=caption_lines,
                                                             language=language)

        # combine across all lines into single txt file
        transcript = self.combine_preprocessed_captions(preprocessed_captions=preprocessed_captions,
                                                language=language)
        if language == DEFAULT_LANGUAGE:
            transcript = '== Pre-show ==\n' + transcript

        return transcript

    def check_ts_names(self, transcript, language=DEFAULT_LANGUAGE):
        '''For making sure that there are no typos in speakers' names. Returns error message if not.'''
        error_warning = ''
        transcript_names = ' '.join([x.split(':')[0] for x in transcript.splitlines() if ':' in x])
        capital_names = set(re.search(r'[A-Z]+', x).group() for x in transcript_names.split() if re.search(r'\b[A-Z]+\b', x))
        other_names = set(x for x in transcript_names.split()
                          if not re.search(r'[A-Z]+', x) or
                          re.search(r'[A-Z]+', x).group() not in capital_names)

        if language == 'ru':
            speaker_tags = SPEAKER_TAGS_RU
        else:
            speaker_tags = self.actor_data.speaker_tags

        # don't check names if there are no standard ones to begin with
        if not any(tag in transcript for tag in speaker_tags):
            return ''

        # the only lowercase word before the colon should be 'and'
        try:
            assert other_names == {'and'}
        except AssertionError:
            errors = [x for x in other_names if x != 'and']
            error_warning += f"Words besides 'and' in lower case for speaker names: {errors}" + '\n'

        # all uppercase words should be names in CR_UPPER
        try:
            assert capital_names.issubset(speaker_tags)
        except AssertionError:
            names = [x for x in capital_names
                     if x not in speaker_tags]
            error_warning += f"Some speaker names potentially misspelled: {names}" + '\n'

        return error_warning

    def process_errors(self, ts, language=DEFAULT_LANGUAGE):
        '''Can add more processes later if needed.'''
        errors_comments = ''

        # verify that actor names are correct
        errors_comments += self.check_ts_names(ts, language=language)

        # add commented_out error messages to top of transcript
        if errors_comments:
            errors_comments = ''.join(['<!--', errors_comments, '-->\n\n'])
            ts = errors_comments + ts

        return ts

    def process_transcript(self, captions=None, language=DEFAULT_LANGUAGE):
        if language and captions is None:
            captions = self.captions_dict.get(language)

        # Step 1: combine lines and flag duplicates
        ts = self.process_captions(captions, language=language)

        # Step 2: replace curly quotes and apostrophes
        ts = (ts
                .replace('“', '"')
                .replace('”','"')
                .replace("‘", "'")
                .replace("’", "'")
                )

        # Step 3: remove and replace html markup
        ts = wikify_html_string(ts)

        # Step 4: Comment out the break
        if not self.ignore_break and language==DEFAULT_LANGUAGE:
            ts = Breakfinder(transcript=ts, ep=self.ep).revised_transcript

        # Step 5: Add cleanup tag if no speaker tags found
        if language == 'ru':
            speaker_tags = SPEAKER_TAGS_RU
        else:
            speaker_tags = self.actor_data.speaker_tags
        if not any(tag in ts for tag in speaker_tags):
            ts = f'{{{{cleanup|speaker tags not found}}}}\n\n{ts}'
            pywikibot.output(f"No speaker tags found in transcript {self.ep} in {language}; tagged for cleanup.")

        # Step 6: add commented_out error messages to top of transcript
        ts = self.process_errors(ts, language=language)

        # Step 7: add navigation and category
        t_cat = f"Category:{self.ep.transcript_category}"
        if self.dupe_lines.get(language):
            # add duplicate category if duplicate lines found
            t_dupe_cat = f"Category:Transcripts with duplicate lines"
            if language != DEFAULT_LANGUAGE:
                t_cat += f"/{language}"
                t_dupe_cat += f"/{language}"
        else:
            t_dupe_cat = ''

        ts = ''.join(['{{Transcript-Nav}}\n__FORCETOC__\n\n', 
                      ts,
                      '\n{{Transcript-Nav}}\n', 
                      f'[[{t_cat}]]',
                      f'\n[[{t_dupe_cat}]]'])

        if self.write_ts_file:
            os.makedirs(self.transcript_folder, exist_ok=True)
            if language == DEFAULT_LANGUAGE:
                filename = self.text_filename
            else:
                filename = os.path.join(self.transcript_folder, f"{self.ep.code}_{language}.txt")
            with open(filename, 'w') as f:
                f.write(ts)

        # autogenerated captions require different processing (TBD)
        return ts

    def download_and_build_transcript(self, language=DEFAULT_LANGUAGE):
        # check for local file first
        if not hasattr(self, 'captions_dict'):
            self.captions_dict = {}
        if self.try_local_file:
            try:
                captions = self.create_from_json_file(language=language)
                self.captions_dict[language] = captions
            except FileNotFoundError:
                pass
        if not self.captions_dict.get(language) or self.force_redownload is True:
            captions = self.captions_download(language=language)
        else:
            pass
        self.captions_dict[language] = captions
        if not hasattr(self, 'transcript_dict'):
            self.transcript_dict = {}
        self.transcript_dict[language] = self.process_transcript(language=language)

    def download_all_language_transcripts(self):
        for language in self.languages:
            self.download_and_build_transcript(language=language)
