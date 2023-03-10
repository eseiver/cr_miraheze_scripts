#!/usr/bin/python3
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
try:
    TIMEZONE = ZoneInfo("America/Los_Angeles")
except ZoneInfoNotFoundError:
    print("\nTimezone info not found. Please run `pip install tzdata` and try again.\n", file=sys.stderr)
    sys.exit()

"""
Requires Python 3.9+ (imports zoneinfo). Place this file in your scripts folder.
* Windows users: You will need to run `pip install tzdata` one time to install timezone information.
This script is for criticalrole.miraheze.org when a new video posts to Critical Role's YouTube channel.

To test the script run:
>> python pwb.py vod -simulate -all -ep_id:3x25 -page:User:FCGBot/episode

Example command for cut and pasting in the values:
>> python pwb.py vod -all -ep:3x38 -page:"Campaign 3 Episode 38" -yt:U5mkmw46m4U -new_ep_name:"A Dark Balance" -runtime:4:20:43 -episode_summary:"Bells Hells return to safety..." -actors:"Marisha, Sam" -airdate:2022-10-20 -simulate

A number of maintenance activities can be performed together (-all) or independently:

-update_page      Add runtime, thumbnail image & caption, episode summary, & VOD link to episode page

-move             Move the episode page from a placeholder name to the name specified in the video

-ep_list          Add entry to list of episodes page, as determined from EPISODE_DECODER

-ep_array         In Module:Ep/Array, make new episode title valid input & the display value

-yt_switcher      Add the episode + YouTube ID to Module:Ep/YTURLSwitcher

-airdate_order    Add the episode id & airdate to Module:AirdateOrder/Array

-transcript       Create transcript page (auto-skips TRANSCRIPT_EXCLUSIONS)

-transcript_list  Add transcript page to list of transcripts (auto-skips TRANSCRIPT_EXCLUSIONS)

-upload           Upload and link to the episode thumbnail; ignored if already exists

-main_page        Check to see if the latest episode image on the main page needs updating

-redirects        Make sure episode code redirect(s) exist and link to newest episode name

-navbox           Make sure the episode code is in the navbox, as determined from EPISODE_DECODER

-4SD              For 4-Sided Dive only, add ep_id to the 3xNN episodes since the previous

Use global -simulate option for test purposes. No changes to live wiki will be done.
For every potential change, you will be shown a diff of the edit and asked to accept or reject it.
No changes will be made automatically. Actions are skipped if change is not needed (e.g., an entry for
the episode already exists on the module page).

All other parameters are passed in the format -parameter:value. Use "quotes" around value if it has
spaces (e.g., -actors:"Marisha, Taliesin, Matt"). "!" needs to be escaped, even in quotes, as "\!".
You will be prompted to enter a missing value if needed. No quotation marks needed in this case.

-ep:              REQUIRED. The CxNN code of the episode with newly uploaded VOD (-ep_id also valid)

-page:            REQUIRED. The page to be edited, usually current episode page

-yt:              The 11-character unique identifier or full URL for the YouTube video (-yt_id also valid)

-airdate:         YYYY-MM-DD of the date episode aired. Can be inferred from episode page if filled in.

-airtime:         Time of day the episode aired. Optional, can be inferred from episode page if filled in.

-runtime:         HH:MM:SS length of the episode video

-actors:          L-R of actors in thumbnail. Separate with ','. First names ok (from ACTORS list)

-episode_summary: The 1-2 line summary of the episode from the YouTube video.

-old_ep_name:     If different from -page:, the current name of the episode (mostly for testing)

-new_ep_name:     Where the episode will be moved to, if it has been renamed

-new_page_name:   Only if page name differs from new_ep_name (usually 'A' vs 'A (episode)')

-summary:         A pywikibot command that adds an edit summary message and shouldn't be needed.

-host:            Actor who is the 4SD host or running one-shot (DM, GM also work here)

-game_system:     For one-shots, game system if not Dungeons & Dragons

Other parameters (most of which are automatically calculated values but still can be passed in)
can be found in `update_options` for EpisodeBot (line 804).

Potential future features:
1) Make sure that the episode has been removed from upcoming events
2) Update the episode on the main page
3) Pull YouTube info automatically using the YouTube API

This script is a
:py:obj:`ConfigParserBot <pywikibot.bot.ConfigParserBot>`. All settings can be
made either by giving option with the command line or with a settings file
which is scripts.ini by default.
"""
# Distributed under the terms of the MIT license.
import re
from copy import deepcopy
from datetime import datetime
import mwparserfromhell
import pywikibot
from pywikibot import pagegenerators
from pywikibot.bot import (
    AutomaticTWSummaryBot,
    ConfigParserBot,
    ExistingPageBot,
    SingleSiteBot,
    QuitKeyboardInterrupt,
)
from cr import *
from pywikibot.specialbots import UploadRobot


class EpisodeBot(
    SingleSiteBot,  # A bot only working on one site
    ConfigParserBot,  # A bot which reads options from scripts.ini setting file
    ExistingPageBot,  # CurrentPageBot which only treats existing pages
    AutomaticTWSummaryBot,  # Automatically defines summary; needs summary_key
):
    """
    :ivar summary_key: Edit summary message key. The message that should be
        used is placed on /i18n subdirectory. The file containing these
        messages should have the same name as the caller script (i.e. basic.py
        in this case). Use summary_key to set a default edit summary message.
    :type summary_key: str
    """

    use_redirects = False  # treats non-redirects only
    summary_key = 'basic-changing'

    update_options = {
        'summary': 'Updating newly-released episode page (via pywikibot)',
        'yt': None, # YT object
        'runtime': None,  # how long the episode goes for
        'old_ep_name': None,  # the old placeholder name of the episode
        'new_ep_name': None,  # the new official name of the episode
        'new_page_name': None,  # if different from episode title (usually 'A' vs 'A (episode)')
        'ep': None,  # Ep object
        'image_name': None,  # unless specified, builds automatically from make_image_filename(ep_id)
        'actors': None, # Actors object. list of actors in thumbnail image (optional)
        'host': None,  # the host (4SD) or GM (one-shot, defaults to Matt)
        'game_system': None,  # rules for gameplay (one-shot, defaults to Dungeons & Dragons)
        'airdate': None,  # usually from episode page, used to update list of episodes
        'airtime': None,  # usually from episode page
        'episode_summary': None,  # taken from list of episodes to add to episode page
        'summary_only': None,  # for only adding episode_summary to episode page
        'airdate_dict': None,  # for using airdates to determine 4SD-C3 episodes
        'array_dicts': None, # for converting episode codes into page names and episode titles
        'all': None,  # run: -update_page, -move, -upload, -ep_list, -yt_switcher, -ep_array, -transcript, -redirects, -navbox
        'update_page': None,  # update the contents of the episode page (may still need to access for info)
        'move': None,  # move page (only if new page name exists & is different from old one)
        'upload': None,  # upload the YouTube video thumbnail
        'main_page': None,  # check the main page has the latest thumbnail
        'ep_list': None,  # add to/update list of episodes
        'airdate_order': None,  # add to/update the airdate order
        'yt_switcher': None,  # add to/update the yt url switcher
        'ep_array': None,  # add to/update the ep array
        'transcript': None,  # create episode transcript page (auto-skips TRANSCRIPT_EXCLUSIONS)
        'transcript_list': None,  # add transcript page to list of transcripts (auto-skips TRANSCRIPT_EXCLUSIONS)
        'redirects': None,  # add/update redirects from ep_id to new_page_name
        'navbox': None,  # add ep_id to the appropriate navbox template
        '4SD': None,  # add 4SD param to 3xNN pages (4SD only)
    }

    def get_wikicode(self):
        text = self.current_page.text
        wikicode = mwparserfromhell.parse(text)
        return wikicode

    def get_infobox(self, wikicode=None):
        if wikicode is None:
            wikicode = self.get_wikicode()
        return next(x for x in wikicode.filter_templates() if x.name.matches(INFOBOX_EPISODE))

    def move_page(self) -> None:
        move_summary = 'Moving page to new episode name (via pywikibot)'

        # get the new target title
        if not (self.opt.new_page_name or self.opt.new_ep_name):
            target_title = pywikibot.input("Please enter the new name of the episode")
        elif not self.opt.new_page_name:
            target_title = self.opt.new_ep_name
        else:
            target_title = self.opt.new_page_name

         # make sure doesn't conflict with existing page (handling redirects separately)
        target_page = pywikibot.Page(self.site, target_title)
        if target_page.exists() and not target_page.isRedirectPage():
            add_end = pywikibot.input_yn(f"{self.opt.new_page_name} already exists. Add ' (episode)' to page name?")
            if add_end:
                self.opt.new_page_name = target_title + " (episode)"
            else:
                new_name = pywikibot.input(f"Please enter new page name for {target_title}")
                self.opt.new_page_name = new_name
        elif target_page.exists():
            overwrite = pywikibot.input_yn(f"{self.opt.new_page_name} is a redirect. Overwrite?")
            if overwrite:
                new_name = pywikibot.input(f"Please enter new page name for {target_title}")
                self.opt.new_page_name = new_name
        else:
            self.opt.new_page_name = self.opt.new_ep_name

        move_it = pywikibot.input_yn(f"Move [[{self.current_page.title()}]] to [[{self.opt.new_page_name}]]?")
        if move_it:
            pywikibot.output(f"Moving page from [[{self.current_page.title()}]] to [[{self.opt.new_page_name}]]")
            self.current_page.move(self.opt.new_page_name,
                                   reason=move_summary,
                                   )
            pywikibot.output('Page move complete.')
        else:
            pywikibot.output('Page move skipped.')

    def update_summary(self, wikicode=None):
        '''For adding the episode summary to the intro paragraph of the episode article.
        It can be added after it is retrieved from an existing list of episodes entry parameter,
        or it can be passed into the opening command (presumably, from YouTube description).
        '''
        if self.opt.summary_only:
            self.current_page = pywikibot.Page(self.site, self.opt.new_page_name)

        if wikicode is None:
            wikicode = self.get_wikicode()
        else:
            text = str(wikicode)

        # if there's an episode summary not included in the text, create new article text
        no_markup = ''.join([str(x) for x in wikicode.filter_text()])
        if (self.opt.episode_summary and 
            self.opt.episode_summary not in no_markup):
            old_intro = str(wikicode.get_sections(include_lead=True, flat=True)[0])
            new_intro = old_intro.rstrip() + ' ' + self.opt.episode_summary + '\n\n'
            new_text = str(wikicode).replace(old_intro, new_intro)
        else:
            new_text = text

        # have editor decide whether to add on the summary or not
        if new_text != text:
            pywikibot.showDiff(text, new_text)
            do_it = pywikibot.input_yn('Continue with summary addition?')
            if do_it:
                wikicode = mwparserfromhell.parse(new_text)
                if self.opt.summary_only:
                    self.put_current(new_text, summary=self.opt.summary)
            else:
                pass

        return wikicode

    def treat_page(self) -> None:
        """Load the episode page, change the relevant fields, save it, move it."""
        ep = self.opt.ep

        if not self.opt.old_ep_name:
            self.opt.old_ep_name = self.current_page.title()

        old_ep_name = self.opt.old_ep_name
        self.current_page = pywikibot.Page(self.site, old_ep_name)
        wikicode = deepcopy(self.get_wikicode())
        infobox = self.get_infobox(wikicode=wikicode)

        infobox['VOD'] = ep.wiki_vod
        infobox['Podcast'] = ep.wiki_podcast
        infobox['EpCode'] = ep.code

        if self.opt.runtime and not does_value_exist(infobox, param_name='Runtime'):
            infobox['Runtime'] = ' ' + self.opt.runtime.lstrip()
        # get the airdate & airtime so it can be used later, or prompt if infobox conflicts w/user entry
        if infobox.has_param('Airdate') and self.opt.airdate:
            if Airdate(infobox['Airdate'].value.strip()).date == self.opt.airdate.date:
                pass
            else:
                airdate_1 = Airdate(infobox['Airdate'].value.strip()).date
                airdate_2 = self.opt.airdate.date
                if len(airdate_1) and airdate_1 != airdate_2:
                    new_airdate_string = get_validated_input(arg='airdate', regex=DATE_REGEX, input_msg=f'Infobox airdate {airdate_1} does not match entered airdate {airdate_2}. Enter airdate (YYYY-MM-DD):')
                    new_airdate = Airdate(new_airdate_string)
                    self.opt.airdate.datetime = self.opt.airdate.datetime.replace(**{x: getattr(new_airdate.datetime, x) for x in ['day', 'month', 'year']})
                    infobox['Airdate'] = new_airdate.date
                else:
                    infobox['Airdate'] = self.opt.airdate
        elif infobox.has_param('Airdate') and infobox['Airdate'].value.strip() and not self.opt.airdate:
            self.opt.airdate = Airdate(infobox['Airdate'].value.strip())
        else:
            self.opt.airdate = ""
        if infobox.has_param('Airtime') and infobox['Airdate'].value.strip() and not self.opt.airtime:
            # add airtime to airdate object
            self.opt.airtime = Airdate(infobox['Airtime'].value.strip())
            if self.opt.airtime:
                self.opt.airdate = Airdate(datetime.combine(
                    self.opt.airdate.datetime.date(),
                    self.opt.airtime.datetime.timetz()))
        else:
            self.opt.airtime = ""

        # if image field is already filled in beyond comments, cancel thumbnail procedure
        if does_value_exist(infobox, param_name='Image'):
            pywikibot.output(f"Value '{(remove_comments(infobox['Image'].value)).strip()}' in image field detected; thumbnail will not be uploaded")
            self.opt.upload = False
        elif self.opt.image_name:
            infobox['Image'] = ' ' + self.opt.image_name.lstrip()
        else:
            infobox['Image'] = ' ' + ep.image_filename

        # only write caption if field not filled in or missing
        if not infobox.has_param('Caption') or not does_value_exist(infobox, param_name='Caption'):
            infobox['Caption'] = make_image_caption(actors=self.opt.actors, ep=ep)

        if not any([x.name.matches(ep.navbox_name.replace('Template:', '')) for x in wikicode.filter_templates()]):
            wikicode.append('\n' + f"{{{{{ep.navbox_name.replace('Template:', '')}}}}}")

        if self.opt.episode_summary:
            wikicode = self.update_summary(wikicode=wikicode)

        text = str(wikicode)

        if self.opt.update_page:
            self.put_current(text, summary=self.opt.summary)

        if (self.opt.move or self.opt.all) and self.opt.new_page_name != self.opt.old_ep_name:
            self.move_page()


class EpArrayBot(EpisodeBot):
    '''Change the display value for ep_array and add page title as value.
    If an entry for the episode does not already exist, it will create one after prev_ep_id.'''

    def get_array_dicts(self):
        if not self.opt.array_dicts:
            self.opt.array_dicts = self.make_array_dicts()
        return self.opt.array_dicts

    def make_array_dicts(self):
        self.current_page = pywikibot.Page(self.site, EP_ARRAY)
        array_dicts = []
        text = self.current_page.text

        for x in re.finditer(ARRAY_ENTRY_REGEX, text):
            y = x.groupdict()
            if not y['pagename']:
                y['pagename'] = ''
            if y['altTitles']:
                y['altTitles'] = re.findall('"(.*?)"', y['altTitles'])
            else:
                y['altTitles'] = []
            array_dicts.append(y)
        return array_dicts

    def dict_to_entry(self, array_dict):
        '''for turning one of these dicts into a string'''
        entry = ''
        for k, v in array_dict.items():
            if not v:
                continue
            elif k == 'epcode':
                entry += f'    ["{v}"] = {{' + '\n'
            elif isinstance(v, str):
                entry += f'        ["{k}"] = "{v}"' + ',\n'
            elif isinstance(v, list):
                list_string = ', '.join([f'"{x}"' for x in v])
                entry += f'        ["{k}"] = {{{list_string}}}' + ',\n'
            else:
                raise
        entry += '    },\n'
        return entry

    def build_full_array_page(self, array_dicts):
        array_string = 'return {\n'
        for array_dict in array_dicts:
            entry = self.dict_to_entry(array_dict)
            array_string += entry
        dict_string += '}'
        return dict_string

    def get_current_dict(self, array_dicts):
        '''Get array dict for current episode'''
        ep = self.opt.ep
        current_entry = next((x for x in array_dicts if x['epcode'] ==
            ep.code), '')
        return current_entry

    # replace self.opt.ep.get_prev_episode().code
    def get_previous_dict(self, array_dicts):
        prev_ep_code = self.opt.ep.get_prev_episode().code
        prev_entry = next((x for x in array_dicts if x['epcode'] ==
            prev_ep_code), '')
        return prev_entry

    def build_new_array_dict(self):
        '''Creating values for the fields that would populate an episode entry.'''
        ep = self.opt.ep
        if ep.prefix == '4SD':
            display_title = "''4-Sided Dive'': " + self.opt.new_ep_name
        else:
            display_title = self.opt.new_ep_name

        if self.opt.old_ep_name not in [self.opt.new_ep_name, self.opt.new_page_name]:
            ep_values = [self.opt.old_ep_name.lower()]
        else:
            ep_values = []

        if self.opt.new_page_name != display_title:
            pagename = self.opt.new_page_name
        else:
            pagename = ''

        array_dict = {
            'epcode': ep.code,
            'title': display_title,
            'pagename': pagename,
            'altTitles': ep_values,
        }
        return array_dict

    def update_new_dict(self, new_dict, current_dict):
        '''Add the existing altTitles together, but assume new_dict is otherwise correct.'''
        new_dict['altTitles'] = list(dict.fromkeys(new_dict['altTitles'] + current_dict.get('altTitles')))
        return new_dict

    def treat_page(self):
        self.current_page = pywikibot.Page(self.site, EP_ARRAY)
        text = self.current_page.text
        ep = self.opt.ep

        current_entry = next((x for x in re.split('\n    \},\n',
                            text) if re.search(f'\["{ep.code}"\]', x)),
                            '')
        if current_entry:
            current_entry += '\n    },\n'
            array_dicts = self.get_array_dicts()
            current_dict = self.get_current_dict(array_dicts=array_dicts)
        else:
            prev_entry = next((x for x in re.split('\n    \},\n',
                            text) if re.search(f'\["{ep.get_previous_episode().code}"\]', x)),
                            '') + '\n    },\n'
            current_dict = {}

        new_dict = self.build_new_array_dict()
        new_dict = self.update_new_dict(new_dict, current_dict)

        # Make sure that for 3xNN episode codes it is also "c3 latest"
        if ep.prefix == '3' and 'c3 latest' not in new_dict['altTitles']:
            text = re.sub('c3 latest(, )?', '', text)
            new_dict['altTitles'].append('c3 latest')

        new_entry = self.dict_to_entry(new_dict)

        if current_entry:
            text = text.replace(current_entry, new_entry)
        else:
            text = text.replace(prev_entry, '\n'.join([prev_entry, new_entry]))

        self.put_current(text, summary=f"Updating {ep.code} entry (via pywikibot)")


class YTSwitcherBot(EpisodeBot):
    '''Add yt_link as value by updating or creating entry'''
    def treat_page(self):
        self.current_page = pywikibot.Page(self.site, YT_SWITCHER)
        text = self.current_page.text
        ep = self.opt.ep
        yt = self.opt.yt
        prev_ep = ep.get_previous_episode()

        # if it already exists as an entry, substitute in yt_link
        if ep.code in text:
            text = re.sub(fr'["{ep.code}"]\s*=.*', fr'["{ep.code}"] = "{yt.url}",', text)

        # if previous episode is already there, append after it
        elif prev_ep.code in text:
            prev_entry = next(x for x in text.splitlines()
                if any([y in x for y in prev_ep.generate_equivalent_codes()]))
            new_entry = f'    ["{ep.code}"]  = "{yt.url}",'
            text = text.replace(prev_entry,
                                '\n'.join([prev_entry, new_entry])
                                )
        # otherwise, append episode to the end of the list
        else:
            text = text.replace('["default"] = ""',
                                f'["{ep.code}"]  = "{yt.url}",\n    ["default"] = ""')

        self.put_current(text, summary=f"Adding youtube link for {ep.code} (via pywikibot)")


class EpListBot(EpisodeBot):
    '''For updating a list of episodes with a brand-new entry or new values for the current episode.'''

    def build_episode_entry_dict(self):
        ep = self.opt.ep
        '''Creating values for the fields that would populate an episode entry.'''
        if self.opt.host:
            host = self.opt.host.make_actor_list_string()
        else:
            host = ''
        if self.opt.ep.prefix == '4SD':
            color = '6f4889'
            wiki_code = ep.wiki_code.replace('ep|', 'ep|noshow=1|')
        else:
            color = ''
            wiki_code = ep.wiki_code
        if self.opt.ep.prefix == 'OS':
            game_system = self.opt.game_system
        else:
            game_system = ''
        entry_dict = {
            'no': str(ep.number),
            'ep': wiki_code,
            'airdate': self.opt.airdate.date,
            'VOD': ep.wiki_vod,
            'runtime': self.opt.runtime,
            'aux1': host,
            'aux2': game_system,
            'summary': self.opt.episode_summary,
            'color': color,
        }
        return entry_dict

    def build_episode_entry(self):
        '''Create the string for a brand new episode entry.'''
        entry_dict = self.build_episode_entry_dict()

        ep_entry = "{{Episode table entry\n"
        for k, v in entry_dict.items():
            if v:
                ep_entry += f'|{k} = {v}' + '\n'
        ep_entry += '}}'

        return ep_entry

    def treat_page(self):
        '''Also has the option of getting an existing episode summary from the page.'''
        ep = self.opt.ep
        prev_ep = ep.get_previous_episode()

        list_page_name = ep.list_page
        if not list_page_name:
            list_page_name = pywikibot.input(f"Please enter name of list of episodes page for {ep.code}")

        self.current_page = pywikibot.Page(self.site, list_page_name)
        wikicode = deepcopy(self.get_wikicode())
        text = str(wikicode)
        # if previous episode isn't there, search episode num - 1 until find one (otherwise none)
        while prev_ep and (prev_ep.code.lower() not in text.lower()):
            prev_ep = prev_ep.get_previous_episode(prev_ep.code)

        # create new table entry from scratch if it doesn't exist yet, inserting after previous episode
        if not re.search(fr'\|\s*ep\s*=\s*{{{{(E|e)p\|{ep.code}}}}}', text):
            ep_entry = self.build_episode_entry()
            previous_entry_wiki = next((x for x in wikicode.filter_templates()
                if x.name.matches('Episode table entry') and prev_ep.code in x['ep']), '')
            if previous_entry_wiki:
                previous_entry = ''.join(['|' + str(x) for x in previous_entry_wiki.params]) + '}}'
                if previous_entry in text:
                    text = text.replace(previous_entry, '\n'.join([previous_entry, ep_entry]))
                else:
                    pywikibot.output(f"Episode table entry for {prev_ep.code} not formatted correctly; cannot insert {ep.code} entry")
            elif '}}<section end="episodes" />' in text:
                text = text.replace('}}<section end="episodes" />',
                                    ep_entry + '\n}}<section end="episodes" />')
            elif '<!-- Place new entries ABOVE this line -->' in text:
                text = text.replace('<!-- Place new entries ABOVE this line -->',
                                    ep_entry + '\n<!-- Place new entries ABOVE this line -->')
            else:
                pywikibot.output("No previous entry or end-of-section marker to append to")
        # if the table entry exists, update any individual params to the new ones in ep_entry_dict
        else:
            ep_entry_dict = self.build_episode_entry_dict()
            existing_entry = next(x for x in wikicode.filter_templates()
                if x.name.matches('Episode table entry') and ep.code in x['ep'])
            for k, v in ep_entry_dict.items():
                if v and not (existing_entry.has_param(k) and existing_entry[k].value.strip() == v):
                    if len(str(v).strip()):
                        existing_entry[k] = v
                    else:
                        existing_entry[k] = ' \n' # adding wiki standard whitespace padding
                else:
                    pass  # any values already in the table & not in the newly-created entry will be kept

            # offer the episode summary if available and if episode page is to be updated
            if not self.opt.episode_summary and self.opt.update_page and len(existing_entry['summary'].value.strip()):
                eplist_summary = existing_entry['summary'].value.strip()
                summ = pywikibot.input_yn(f'\n{eplist_summary}\nUse above existing episode list entry summary on episode page?')
                if summ:
                    self.opt.episode_summary = eplist_summary
                else:
                    pass
            text = str(wikicode)

        self.put_current(text, summary=f"Updating entry for {ep.code} (via pywikibot)")


class TranscriptBot(EpisodeBot):
    '''For creating the transcript page by downloading and processing youtube captions.'''

    def build_transcript(self):
        ts = Transcript(ep=self.opt.ep, yt=self.opt.yt)
        ts.download_and_build_transcript()
        transcript = ts.transcript
        return transcript

    def treat_page(self):
        url = 'Transcript:' + self.opt.new_page_name
        self.current_page = pywikibot.Page(self.site, url)
        if self.current_page.exists() and self.current_page.text:
            pywikibot.output(f'Transcript page already exists for {self.opt.new_page_name}; transcript creation skipped')
        else:
            transcript = self.build_transcript()
            self.put_current(transcript, summary=f"Creating {self.opt.ep.code} transcript (via pywikibot)")


class TranscriptListBot(EpisodeBot):
    '''For updating the list of transcripts with the transcript of the newest episode.'''
    def build_transcript_entry(self):
        transcript_entry = f"""* {self.opt.ep.wiki_code} [[Transcript:{self.opt.new_page_name}|Transcript]]"""
        return transcript_entry

    def treat_page(self):
        ep = self.opt.ep
        self.current_page = pywikibot.Page(self.site, TRANSCRIPTS_LIST)
        text = self.current_page.text
        ep_entry = self.build_transcript_entry()

        # create new entry from scratch if it doesn't exist yet, inserting after previous episode
        if ep.code not in text:
            ep_entry = self.build_transcript_entry()
            prev_ep = ep.get_previous_episode()
            # if previous episode isn't there, search episode num - 1 until find one (otherwise none)
            while prev_ep and (prev_ep.code not in text):
                prev_ep = prev_ep.get_previous_episode(prev_ep.code)
            prev_ep_entry = next((x for x in text.splitlines() if prev_ep.code in x), '== Miscellaneous ==')
            text = text.replace(prev_ep_entry,
                                '\n'.join([prev_ep_entry, ep_entry]))

            self.put_current(text, summary=f"Add entry for {ep.code} (via pywikibot)")
        # if it exists, replace entry with current values if needed
        else:
            current_entry = next((x for x in text.splitlines() if ep.code in x), None)
            text = text.replace(current_entry, ep_entry)
            self.put_current(text, summary=f"Updating entry for {ep.code} (via pywikibot)")


class RedirectFixerBot(EpisodeBot):
    '''Insures all viable CxNN redirects exist and point at new_page_name.'''
    use_redirects: True

    def treat_page(self):
        ep = self.opt.ep
        for code in ep.generate_equivalent_codes():
            self.current_page = pywikibot.Page(self.site, code)
            text = f"#REDIRECT [[{self.opt.new_page_name}]]"
            self.put_current(text, summary="Updating/creating episode redirects (via pywikibot)")


class NavboxBot(EpisodeBot):
    '''Makes sure the episode code appears on the accompanying navbox'''

    def treat_page(self):
        ep = self.opt.ep
        prev_ep = ep.get_previous_episode()
        navbox_name = ep.navbox_name
        self.current_page = pywikibot.Page(self.site, navbox_name)
        wikicode = deepcopy(self.get_wikicode())
        if ep.code not in str(wikicode):
            navbox = next(x for x in wikicode.filter_templates() if x.name.matches('Navbox'))
            ep_list = next(p for p in navbox.params if prev_ep.code in p)
            if prev_ep.wiki_code in ep_list:
                ep_list.value.replace(prev_ep.wiki_code, f'{prev_ep.wiki_code} ??? {ep.wiki_code}')
            elif prev_ep.code in ep_list:
                ep_list.value.replace(prev_ep.code, f'{prev_ep.code} ??? {ep.code}')
        self.put_current(str(wikicode), summary=f"Adding {ep.code} to navbox (via pywikibot)")


class AirdateBot(EpisodeBot):
    '''For updating the airdate module with the newest episode's airdate.'''

    def build_airdate_entry(self):
        if self.opt.airtime:
            airdate = self.opt.airdate.date_and_time
        else:
            airdate = self.opt.airdate.date
        airdate_entry = f'''    {{epCode = "{self.opt.ep.code}", date = "{airdate}"}},'''
        return airdate_entry

    def parse_airdate_page(self):
        airdate_module_regex = '\{epCode = "(?P<ep_code>.*?)", date = "(?P<airdate_entry>.*)"\}'
        self.current_page = pywikibot.Page(self.site, AIRDATE_ORDER)
        text = self.current_page.text

        airdate_dict = {}
        for ad in re.finditer(airdate_module_regex, text):
            ep_code = ad.group('ep_code')
            airdate = Airdate(ad['airdate_entry'])
            if ep_code == self.opt.ep.code and airdate.datetime != self.opt.airdate.datetime:
                pywikibot.output(f'Airdate on {self.current_page.title()} does not match for \
{self.opt.ep.code}: <<yellow>>{airdate.date_and_time}<<default>> vs <<yellow>>{self.opt.airdate.date_and_time}<<default>>')
                return None
            airdate_dict[ep_code] = airdate
        airdate_dict = {k: v for k, v in sorted(airdate_dict.items(), key=lambda item: item[1].date_and_time)}

        return airdate_dict

    def get_airdate_dict(self):
        if self.opt.airdate_dict is None:
            self.opt.airdate_dict = self.parse_airdate_page()
        airdate_dict = self.opt.airdate_dict

        # add current episode if applicable
        if airdate_dict and self.opt.ep.code not in airdate_dict:
            airdate_dict[self.opt.ep.code] = self.opt.airdate

        return airdate_dict

    def get_previously_aired_episode(self):
        '''Sort the episodes by airdate in reverse. Find the most recent episode that is older than current'''
        airdate_dict = self.get_airdate_dict()

        reversed_airdate_dict = dict(sorted(airdate_dict.items(),
                                            key=lambda item: item[1].date_and_time,
                                            reverse=True,
                                            ))
        last_earlier_ep_id = next(iter([k for k, v in reversed_airdate_dict.items()
            if v.datetime < self.opt.airdate.datetime]))
        return last_earlier_ep_id

    def get_latest_episodes_by_type(self):
        '''For every prefix in CURRENT_PREFIXES, get the most recently aired episode'''
        airdate_dict = self.get_airdate_dict()
        aired = {k: v for k, v in airdate_dict.items() if v.datetime <= datetime.now().astimezone()}
        latest_episodes = [next((Ep(k) for k in reversed(aired.keys())
            if Ep(k).prefix == prefix), Ep(f"{prefix}x01")) for prefix in CURRENT_PREFIXES]
        return latest_episodes

    def treat_page(self):
        ep = self.opt.ep
        self.current_page = pywikibot.Page(self.site, AIRDATE_ORDER)
        text = self.current_page.text

        # create new entry from scratch
        new_entry = self.build_airdate_entry()

        # save airdate_dict to options
        airdate_dict = self.get_airdate_dict()
        if not airdate_dict:
            pywikibot.output('Airdate module process canceled due to date mismatch.')
            return None
        self.opt.airdate_dict = airdate_dict

        if ep.code not in text:
            prev_ep = Ep(self.get_previously_aired_episode())
            prev_entry = next(x for x in text.splitlines() if prev_ep.code in x)
            text = text.replace(prev_entry,
                                '\n'.join([prev_entry, new_entry])
                                )
        else:
            current_entry = next(x for x in text.splitlines() if ep.code in x)
            text = text.replace(current_entry, new_entry)

        self.put_current(text, summary=f"Adding airdate for {ep.code} (via pywikibot)")


class Connect4SDBot(AirdateBot, EpArrayBot):
    '''For updating C3 episode pages with the first 4SD episode after their airdate.'''

    def get_connected_episodes(self, restrict_c3=True):
        '''For constructing the list of (C3) episodes connected to the current 4SD episode.'''
        airdate_dict = self.get_airdate_dict()
        if not airdate_dict:
            pywikibot.output('4SD connector process has been canceled due to date mismatch.')
            return None
        array_dicts = self.get_array_dicts()
        ep_4SD = self.opt.ep
        prev_4SD = self.opt.ep.get_previous_episode()
        eps = list(airdate_dict.keys())
        if ep_4SD.code in eps:
            affected_episodes = eps[(eps.index(prev_4SD.code)+1):eps.index(ep_4SD.code)]
        else:
            affected_episodes = eps[(eps.index(prev_4SD.code)+1):]
        if restrict_c3:
            affected_episodes = [x for x in affected_episodes if Ep(x).prefix == '3']
        affected_pages = ([array_dict['pagename'] if array_dict.get('pagename')
                           else array_dict['title'] for array_dict in array_dicts
                           if array_dict['epcode'] in affected_episodes])
        return affected_pages

    def update_episode_page(self):
        '''Procedure for updating a single episode page's 4SD parameter.'''
        ep = self.opt.ep
        wikicode = deepcopy(self.get_wikicode())
        infobox = self.get_infobox(wikicode=wikicode)
        if not infobox.has_param('4SD') or not does_value_exist(infobox, param_name='4SD'):
            infobox.add('4SD', ep.wiki_code, showkey=None,
                         before='Podcast', preserve_spacing=True)
        self.put_current(str(wikicode), summary="Adding 4SD to infobox (via pywikibot)")

    def treat_page(self):
        assert self.opt.ep.prefix == '4SD'
        # self.get_needed_dicts()
        affected_pages = self.get_connected_episodes()
        if not affected_pages:
            return None
        for page in affected_pages:
            self.current_page = pywikibot.Page(self.site, page)
            self.update_episode_page()


class MainPageBot(AirdateBot, EpArrayBot):
    '''For checking that the articles are the latest on the main page
    NOTE: Depends on airdate module to determine latest episode
    '''
    def check_for_latest_episodes(self, latest_episodes, text):
        pass

    def treat_page(self):
        # self.get_needed_dicts()
        # airdate_dict = self.get_airdate_dict()
        array_dicts = self.get_array_dicts()
        latest_episodes = self.get_latest_episodes_by_type()
        self.current_page = pywikibot.Page(self.site, 'Main Page')
        text = self.current_page.text
        all_ok = True
        for ep in latest_episodes:
            valid_ep = next(x for x in array_dicts
                if x['epcode'].lower() == ep.code.lower())
            valid_codes = [valid_ep['title'], valid_ep['epcode']]
            if valid_ep.get('pagename'):
                valid_codes.append(valid_ep['pagename'])
            if valid_ep.get('alt_titles'):
                valid_codes += valid_ep['alt_titles']
            if any([x for x in valid_codes if x.lower() in text.lower()]):
                pass
            else:
                all_ok = False
                pywikibot.output(f"Latest episode of {ep.show} missing from main page: <<yellow>>{ep.code}<<default>>")

        if all_ok:
            pywikibot.output(f'All latest episodes {latest_episodes} already on main page')


def main(*args: str) -> None:
    """
    Process command line arguments and invoke bot.
    If args is an empty list, sys.argv is used.
    :param args: command line arguments
    """
    options = {}
    # Process global arguments to determine desired site
    local_args = pywikibot.handle_args(args)

    # get global page name and set as local options['old_ep_name']
    page = ''
    for arg in local_args:
        arg, _, value = arg.partition(':')
        if arg[1:] == 'page':
            page = value.strip()
            options['old_ep_name'] = page

    if not options.get('old_ep_name'):
        print('''\nNo page given. Please add a pagename with `-page:"PAGENAME"` and try again.\n''', file=sys.stderr)
        sys.exit()

    # This factory is responsible for processing command line arguments
    # that are also used by other scripts and that determine on which pages
    # to work on.
    gen_factory = pagegenerators.GeneratorFactory()

    # Process pagegenerators arguments
    local_args = gen_factory.handle_args(local_args)

    # Parse script-specific command line arguments
    for arg in local_args:
        arg, _, value = arg.partition(':')
        option = arg[1:]
        if option in ['ep_id', 'ep']:
            value = get_validated_input(arg='ep', value=value, regex=EP_REGEX)
            options['ep'] = Ep(value)
        elif option in ['yt_id', 'yt']:
            value = get_validated_input(arg=option, value=value, regex=YT_ID_REGEX)
            options['yt'] = YT(value)
        elif option in ['actors', 'host']:
            if option == 'actors':
                options[option] = Actors(value)
            elif option == 'host':
                options[option] = Actors(value, link=False)
        elif option == 'airdate':
            if re.search(DATE_2_REGEX, value):
                pass
            else:
                value = get_validated_input(arg=option, value=value, regex=DATE_REGEX)
            options['airdate'] = Airdate(value)
        elif option == 'airtime':
            options['airtime'] = Airdate(value)
        elif option in ('summary', 'actors', 'runtime', 'new_ep_name', 'episode_summary'):
            if not value:
                value = pywikibot.input('Please enter a value for ' + arg)
            options[option] = value
        # take the remaining options as booleans.
        else:
            options[option] = True

    # add airtime to airdate if both were entered by user
    if options.get('airdate') and options.get('airtime'):
        options['airdate'] = Airdate(datetime.combine(options['airdate'].datetime.date(),
                                                      options['airtime'].datetime.timetz()))

    # handle which things to run if all is selected, and set to False any not yet defined
    for task in ['update_page', 'move', 'upload', 'ep_list', 'yt_switcher', 'ep_array',
                 'main_page', 'airdate_order', 'transcript', 'transcript_list', 'redirects',
                 'navbox', '4SD']:
        if options.get('all'):
            options[task] = True
        elif not options.get(task):
            options[task] = False

    # get user input for required values that were not passed in.
    # only required if certain tasks will be conducted
    required_options = ['ep', 'yt', 'new_ep_name', 'runtime', 'actors']
    for req in required_options:
        if req not in options:
            if req == 'yt' and any([options.get(x) for x in ['update_page', 'ep_list', 'yt_list', 'transcript']]):
                value = get_validated_input(arg='yt', regex=YT_ID_REGEX, input_msg="Please enter 11-digit YouTube ID for the video")
                options[req] = YT(value)
            elif req == 'new_ep_name':
                if any([options.get(x) for x in ['update_page', 'move']]):
                    value = pywikibot.input(f"If {options['old_ep_name']} will be moved, enter new page name")
                else:
                    value = ''
                if len(value.strip()):
                    options[req] = value
                else:
                    options[req] = options['old_ep_name']
            elif req == 'actors' and any([options.get(x) for x in ['update_page', 'upload']]):
                value = pywikibot.input(f"Optional: L-R actor order in {options['ep']} thumbnail (first names ok)")
                options[req] = Actors(value)
            elif req == 'runtime' and any([options.get(x) for x in ['update_page', 'ep_list']]):
                value = get_validated_input(arg='runtime', regex='\d{1,2}:\d{1,2}(:\d{1,2})?', input_msg="Please enter video runtime (HH:MM:SS or MM:SS)")
                options['runtime'] = value
            elif req == 'ep':
                value = get_validated_input(arg=req, value=value, regex=EP_REGEX)
                options['ep'] = Ep(value)

    # default new page name is same as new episode name (and page being parsed)
    if not options.get('new_page_name'):
        options['new_page_name'] = options['new_ep_name']

    # if 4SD, make sure host is provided. If one-shot, default host/DM/GM to Matt.
    if options['ep'].prefix == '4SD' and not options.get('host'):
        host = pywikibot.input(f"4-Sided Dive host for {options['ep'].code} (first name ok)")
        options['host'] = Actors(host, link=False)
    if options['ep'].prefix == 'OS':
        host = next((options[x] for x in ['host', 'DM', 'GM', 'dm', 'gm']
            if options.get(x)), 'Matthew Mercer')
        options['host'] = Actors(host, link=False)

    # if one-shot, default game system is D&D.
    if options['ep'].prefix == 'OS' and not options.get('game_system'):
        options['game_system'] = 'Dungeons & Dragons'

    # The preloading option is responsible for downloading multiple
    # pages from the wiki simultaneously.
    gen = gen_factory.getCombinedGenerator(preload=True)

    # check if further help is needed
    if not pywikibot.bot.suggest_help(missing_generator=not gen):
        # pass generator and private options to the bots
        bot1 = EpisodeBot(generator=gen, **options)
        # if page is a redirect to new_page_name, warn user and cancel procedure
        page = pywikibot.Page(bot1.site, options['old_ep_name'])
        if page.isRedirectPage() and page.getRedirectTarget().title() == options['new_page_name']:
            pywikibot.output('\n' + f'The value after -page, "{options["old_ep_name"]}", is a redirect.')
            color = 'yellow'
            pywikibot.output(f'Please use <<{color}>>-page:"{page.getRedirectTarget().title()}"<<default>> and try again.' + '\n')
            return None
        bot1.run()

        # get the airdate info & new page name from episode page processing & moving
        if not options.get('old_ep_name'):
            options['old_ep_name'] = bot1.opt.old_ep_name
        if options.get('airdate') != bot1.opt.airdate:
            options['airdate'] = bot1.opt.airdate
        if not options.get('airdate'):
            options['airdate'] = bot1.opt.airdate
        if not options.get('airtime'):
            options['airtime'] = bot1.opt.airtime
            if options['airtime']:
                options['airdate'] = Airdate(datetime.combine(
                    options['airdate'].datetime,
                    options['airtime'].datetime.timetz()))
        if options.get('new_page_name') != bot1.opt.new_page_name:
            options['new_page_name'] = bot1.opt.new_page_name
        # if image thumbnail field was filled in, do not upload.
        if bot1.opt.upload is False:
            options['upload'] = False

        if options.get('upload'):
            description = make_image_file_description(ep=options['ep'],
                                                      actors=options.get('actors'),
                                                      )
            summary = f"{options['ep'].code} episode thumbnail (uploaded via pywikibot)"
            filename = options['ep'].image_filename
            thumbnail_bot = UploadRobot(
                generator=gen,
                url=options['yt'].thumbnail_url,
                description=description,
                use_filename=filename,
                summary=summary,
                verify_description=True,
            )
            thumbnail_bot.run()

        if options.get('ep_array'):
            bot2 = EpArrayBot(generator=gen, **options)
            bot2.treat_page()
            options['array_dicts'] = bot2.opt.array_dicts

        if options.get('yt_switcher'):
            bot3 = YTSwitcherBot(generator=gen, **options)
            bot3.treat_page()

        if options.get('ep_list'):
            bot4 = EpListBot(generator=gen, **options)
            bot4.treat_page()
            if bot4.opt.episode_summary and not options.get('episode_summary') and options.get('update_page'):
                options['episode_summary'] = bot4.opt.episode_summary
                tinybot = EpisodeBot(generator=gen,
                                     summary=f"Adding {options['ep'].code} summary (via pywikibot)",
                                     summary_only=True,
                                     **{k: v for k, v in options.items() if k in ['episode_summary',
                                                                                  'new_page_name']})
                tinybot.update_summary()
                # TO DO: run teeny episodebot with one option for summary

        if options.get('transcript'):
            if options['ep'].prefix in TRANSCRIPT_EXCLUSIONS:
                pywikibot.output(f'Skipping transcript page creation for {options["ep"].show} episode')
            else:
                bot5 = TranscriptBot(generator=gen, **options)
                bot5.treat_page()

        if options.get('transcript_list'):
            if options['ep'].prefix in TRANSCRIPT_EXCLUSIONS:
                pywikibot.output(f'Skipping transcript list update for {options["ep"].show} episode')
            else:
                bot6 = TranscriptListBot(generator=gen, **options)
                bot6.treat_page()

        if options.get('redirects'):
            bot7 = RedirectFixerBot(generator=gen, **options)
            bot7.treat_page()

        if options.get('navbox'):
            bot8 = NavboxBot(generator=gen, **options)
            bot8.treat_page()

        if options.get('airdate_order'):
            if not options.get('airdate'):
                airdate_string = pywikibot.input('Please enter episode airdate (YYYY-MM-DD)')
                options['airdate'] = Airdate(airdate_string)
            bot9 = AirdateBot(generator=gen, **options)
            bot9.treat_page()
            options['airdate_dict'] = bot9.opt.airdate_dict

        if options['ep'].prefix == '4SD' and options.get('4SD'):
            bot10 = Connect4SDBot(generator=gen, **options)
            bot10.treat_page()
            if not options.get('array_dicts'):
                options['array_dicts'] = bot10.opt.array_dicts
            if not options.get('airdate_dict'):
                options['airdate_dict'] = bot10.opt.airdate_dict

        if options.get('main_page'):
            bot11 = MainPageBot(generator=gen, **options)
            bot11.treat_page()


if __name__ == '__main__':
    try:
        main()
    except QuitKeyboardInterrupt:
        pywikibot.info('\nUser quit vod bot run.')
