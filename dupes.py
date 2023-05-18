"""This script is for checking transcripts for duplicate phrases from the captions and removing them.
It is interactive and includes video url links to exact timestamps if it is ambiguous whether a phrase
is duplicated.
It take up to three arguments:
-ep:                REQUIRED. The CxNN code of the episode
-yt:                REQUIRED. The URL or YouTube ID for the episode
-page:              Optional. Can be inferred from ep so not needed

and one potential flag:
-ignore_existing    Optional. Whether to ignore an existing wiki transcript and build from scratch.

Example from top-level pywikibot folder:
>>> python pwb.py dupes -ep:3x37 -yt:bWHYmDFR84I -ignore_existing
This script also runs as part of the regular vod.py "-transcript" option. The process can be skipped
or exited in the middle, with an option to save changes already in progress.
"""

import pywikibot
from pywikibot.bot import (
    AutomaticTWSummaryBot,
    ConfigParserBot,
    ExistingPageBot,
    SingleSiteBot,
    QuitKeyboardInterrupt,
)
from pywikibot import pagegenerators
from cr_modules.cr import YT, YT_ID_REGEX, get_validated_input
from cr_modules.ep import Ep, EP_REGEX
from cr_modules.transcript import YoutubeTranscript

class DuplicateProcessor:
    '''Interactive tool for deleting duplicate phrases from captions.'''
    # def __init__(self, transcript):
    #     self.transcript = transcript

    def process_duplicates(self, t):
        # assert isinstance(t, YoutubeTranscript), 'Must be object of type YoutubeTranscript.'

        line_pairs = []
        try:
            for line, starttime in t.dupe_lines:
                if line not in t.transcript:
                    continue
                transcript_line = next(x for x in t.transcript.splitlines() if line in x)
                display_line = (line
                                .replace('<!-- DUPLICATE ', '<<yellow>>')
                                .replace('-->', '<<default>>'))
                # hide other duplicate markers in same text
                display_text = (transcript_line
                                .replace(line, display_line)
                                .replace('<!-- DUPLICATE ', '')
                                .replace('-->', ''))
                pywikibot.output(f"\n\n{display_text}\n")
                delete = pywikibot.input_choice('Delete this duplicate?',
                                                [('Yes', 'Y'),
                                                 ('No', 'N'),
                                                 ('Check YouTube video', 'C')])
                if delete.lower() == 'y':
                    new_line = ''
                elif delete.lower() == 'n':
                    new_line = (line
                                .replace('<!-- DUPLICATE ', '')
                                .replace('-->', ''))
                else:
                    starttime = starttime-4
                    url = '?t='.join([t.yt.url, str(starttime)])
                    pywikibot.output(f'\n\n<<yellow>>{url}<<default>>\n(ctrl or cmd+click to launch)')
                    delete = pywikibot.input_yn('Delete this duplicate?')
                    if delete:
                        new_line = ''
                    else:
                        new_line = (line
                                    .replace('<!-- DUPLICATE ', '')
                                    .replace('-->', ''))
                line_pairs.append((line, new_line))
            for line in line_pairs:
                t.transcript = t.transcript.replace(line[0], line[1]).replace('  ', ' ')
        except QuitKeyboardInterrupt:
            if line_pairs:
                save = pywikibot.input_yn('Save changes so far?')
                if save:
                    for line in line_pairs:
                        t.transcript = t.transcript.replace(line[0], line[1]).replace('  ', ' ')
                    pywikibot.output('\nUser did not complete duplicate detection.\nChanges saved.\n')
                else:
                    pywikibot.output('\nUser canceled duplicate detection.')
            else:
                pywikibot.output('\nUser canceled duplicate detection.')
        return t


class DupeDetectionBot(SingleSiteBot, ExistingPageBot):
    '''Add yt_link as value by updating or creating entry'''
    update_options = {
        'ep': None,  # Ep object
        'yt': None,  # YouTube ID/URL, if known
        'ts': None,  # YoutubeTranscript object
        'transcript_link': None,  # link to transcript wiki page
        'ignore_existing': False,  # whether to ignore existing wiki ts (defaults to using it)
    }

    def get_transcript_info(self):
        if self.opt.ts:
            self.opt.ep = self.opt.ts.ep
            self.opt.yt = self.opt.ts.yt

    def get_wiki_transcript(self):
        ep = self.opt.ep
        if not self.current_page or (self.current_page and self.current_page.title() == f'Transcript:{ep.code}'):
            self.current_page = (
                pywikibot.Page(
                    self.site,
                    ep.transcript_redirects[-1])
                ).getRedirectTarget()

    def get_transcript(self):
        if not self.opt.ts:
            self.get_wiki_transcript()
            self.opt.ts = YoutubeTranscript().from_text(self.current_page.text)
        return self.opt.ts

    def process_duplicates(self):
        new_ts = DuplicateProcessor().process_duplicates(self.opt.ts)
        # remove maintenance category if all duplicates removed
        if 'DUPLICATE' not in new_ts.transcript:
            new_ts.transcript = (new_ts.transcript
                                 .replace('[[Category:Transcripts with duplicate lines]]',
                                          ''))
        self.put_current(new_ts.transcript,
                         summary='Fixing duplicate captions (via pywikibot)')

    def treat_page(self) -> None:
        if not self.opt.ts:
            self.opt.ts = YoutubeTranscript(ep=self.opt.ep, yt=self.opt.yt)
            self.opt.ts.download_and_build_transcript()
        else:
            self.get_transcript_info()
        self.get_wiki_transcript()
        self.get_transcript()
        # replace with wiki text if transcript has already been saved
        if self.current_page.text and not self.opt.ignore_existing:
            self.opt.ts.transcript = self.current_page.text
        self.process_duplicates()


def main(*args: str) -> None:

    local_args = pywikibot.handle_args(args)
    ep_arg = next((x for x in local_args if x.startswith('-ep:')),None)
    page_arg = next((x for x in local_args if x.startswith('-page:')),None)
    if (ep_arg and not page_arg) or not page_arg.startswith('Transcript:'):
        page_arg = ep_arg.replace('-ep:', '-page:Transcript:')
        local_args.append(page_arg)
    gen_factory = pagegenerators.GeneratorFactory()

    # Process pagegenerators arguments
    local_args = gen_factory.handle_args(local_args)
    options = {}
    for option in local_args:
        arg, _, value = option.partition(':')
        arg = arg[1:]
        if arg == 'ep':
            options['ep'] = Ep(value)
        elif arg == 'yt':
            options['yt'] = YT(value)
        elif not value:
            options[arg] = True
        else:
            options[arg] = value

    if not options.get('ep') and not options.get('transcript'):
        value = get_validated_input(arg='ep', regex=EP_REGEX)
        options['ep'] = Ep(value)
    if not options.get('yt') and not options.get('transcript'):
        value = get_validated_input(arg='yt', regex=YT_ID_REGEX)
        options['yt'] = YT(value)

    gen = gen_factory.getCombinedGenerator(preload=True)

    dbot = DupeDetectionBot(generator=gen, **options)
    dbot.run()

if __name__ == '__main__':
    try:
        main()
    except QuitKeyboardInterrupt:
        pywikibot.info('\nUser quit duplicate detection bot run.')
