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

-ep_list          Add entry to list of episodes page, as determined from Module:Ep/Decoder

-ep_array         In Module:Ep/Array, make new episode title valid input & the display value

-yt_switcher      Add the episode + YouTube ID to Module:Ep/YTURLSwitcher

-airdate_order    Add the episode id & airdate to Module:AirdateOrder/Array

-transcript       Create transcript page (auto-skips TRANSCRIPT_EXCLUSIONS)

-transcript_list  Add transcript page to list of transcripts (auto-skips TRANSCRIPT_EXCLUSIONS)

-upload           Upload and link to the episode thumbnail; ignored if already exists

-long_short       Check whether the runtime for the episode is one of the longest or shortest

-redirects        Make sure episode code redirect(s) exist and link to newest episode name

-navbox           Make sure the episode code is in the navbox, as determined from Module:Ep/Decoder

-4SD              For 4-Sided Dive only, add ep_id to the 3xNN episodes since the previous

Local data can be downloaded from various modules:

-decoder          For forcing a re-download of Module:Ep/Decoder. Does not occur with -all

-actor_data       For forcing a re-download of Module:ActorData. Does not occur with -all

-download_data    For forcing a re-download of all data listed above. Does not occur with -all

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

-actors:          L-R of actors in thumbnail. Separate with ','. First names ok (from ActorData list)

-episode_summary: The 1-2 line summary of the episode from the YouTube video.

-old_ep_name:     If different from -page:, the current name of the episode (mostly for testing)

-new_ep_name:     Where the episode will be moved to, if it has been renamed

-new_page_name:   Only if page name differs from new_ep_name (usually 'A' vs 'A (episode)')

-image_name:      The name of the thumbnail image file to upload. Automatic and shouldn't be needed.

-summary:         A pywikibot command that adds an edit summary message and shouldn't be needed.

-host:            Actor who is the 4SD host or running one-shot (DM, GM also work here)

-game_system:     For one-shots, game system if not Dungeons & Dragons

Other parameters (most of which are automatically calculated values but still can be passed in)
can be found in `update_options` for EpisodeBot (line 804).

Potential future features:
1) Make sure that the episode has been removed from upcoming events
2) Pull YouTube info automatically using the YouTube API

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
from pywikibot.specialbots import UploadRobot
import requests
from cr_modules.cr import *
from cr_modules.ep import *
from cr_modules.transcript import YoutubeTranscript
from dupes import DupeDetectionBot


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
        'long_short': None, # check whether runtime is one of longest or shortest
        'ep_list': None,  # add to/update list of episodes
        'airdate_order': None,  # add to/update the airdate order
        'yt_switcher': None,  # add to/update the yt url switcher
        'ep_array': None,  # add to/update the ep array
        'transcript': None,  # create episode transcript page (auto-skips TRANSCRIPT_EXCLUSIONS)
        'transcript_list': None,  # add transcript page to list of transcripts (auto-skips TRANSCRIPT_EXCLUSIONS)
        'ts': None, # YoutubeTranscript object
        'redirects': None,  # add/update redirects from ep_id to new_page_name
        'navbox': None,  # add ep_id to the appropriate navbox template
        '4SD': None,  # add 4SD param to 3xNN pages (4SD only)
    }

    @property
    def display_ep(self):
        display = f'"{self.opt.new_ep_name}" ({self.opt.ep.code})'
        return display

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

        # prepend short description
        # don't add if already exists
        shortdesc = next((x for x in wikicode.filter_templates()
                          if x.name.matches("short description")),
                         '')
        shortdesc_value = ''

        if (isinstance(shortdesc, mwparserfromhell.wikicode.Template) and
            shortdesc[1].strip() != 'Campaign 3 Episode x'):
            pywikibot.output("Short description already on episode page; creation skipped.")
        elif ep.shortdesc_value:
            # if one-shot in the episode title, no shortdesc is needed
            if ep.prefix == 'OS' and any(
                any(
                    target.lower() in value.lower()
                    for target in ['one-shot', 'one shot']
                )
                for value in [old_ep_name, self.opt.new_ep_name]
            ):
                shortdesc_value = 'none'
            else:
                shortdesc_value = ep.shortdesc_value
            pywikibot.output(shortdesc_value)
            answer = pywikibot.input("Hit enter to accept automatic short description or write your own:")
            if answer:
                shortdesc_value = answer
            else:
                pass
        else:
            write_shortdesc = pywikibot.input_yn("No short description auto-generated. Write one?")
            if write_shortdesc:
                shortdesc_value = pywikibot.input("Please write the short description (no template info)")


        # handle infobox
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

        # if image field is filled in with existing file, cancel thumbnail procedure
        # otherwise, use image_name if entered 
        if does_value_exist(infobox, param_name='Image') and self.opt.upload:
            image_value = (remove_comments(infobox['Image'].value)).strip()
            if image_value and 'file' not in image_value.lower():
                file_value = 'File:' + image_value
            else:
                file_value = image_value
            file = pywikibot.Page(self.site, file_value)
            if file.exists():
                pywikibot.output(f"Existing page '{file_value}' in image field; skipping thumbnail upload")
                self.opt.upload = False
            elif image_value and not self.opt.image_name:
                image_value = image_value.replace('File:', '')
                self.opt.image_name = image_value
            if image_value and image_value != self.opt.image_name:
                pywikibot.output(
                    f'Infobox image {image_value} does not match entered {self.opt.image_name}. Please resolve and try again.')
                sys.exit()
        if self.opt.image_name and not does_value_exist(infobox, param_name='Image'):
            infobox['Image'] = ' ' + self.opt.image_name.lstrip()
        else:
            infobox['Image'] = ' ' + ep.image_filename

        # only write caption if field not filled in or missing
        if not infobox.has_param('Caption') or not does_value_exist(infobox, param_name='Caption'):
            infobox['Caption'] = make_image_caption(actors=self.opt.actors, ep=ep)

        if not any([x.name.matches(ep.navbox_name) for x in wikicode.filter_templates()]):
            wikicode.append('\n' + f"{{{{{ep.navbox_name}}}}}")

        if self.opt.episode_summary:
            wikicode = self.update_summary(wikicode=wikicode)

        if (shortdesc and shortdesc_value):
            shortdesc.value = shortdesc_value.strip()
            text = str(wikicode)
        elif shortdesc_value:
            shortdesc = f"{{{{short description|{shortdesc_value}}}}}"
            text = '\n'.join([str(shortdesc), str(wikicode)])
        else:
            text = str(wikicode)

        if self.opt.update_page:
            self.put_current(text, summary=self.opt.summary)

        if (self.opt.move or self.opt.all) and self.opt.new_page_name != self.opt.old_ep_name:
            self.move_page()

def verify_default_thumbnail_url(yt):
    if type(yt) == str:
        url = yt
    elif type(yt) == YT:
        url = yt.thumbnail_url

    r = requests.get(url)
    if r.ok:
        return url
    elif type(yt) == YT:
        r2 = requests.get(yt.thumbnail_url_backup)
        if r2.ok:
            return yt.thumbnail_url_backup
    return None

def select_thumbnail_url(yt):
    '''Interactive way to select thumbnail url if default fails.'''
    verified = verify_default_thumbnail_url(yt)
    if verified == yt.thumbnail_url:
        url = yt.thumbnail_url
    elif verified == yt.thumbnail_url_backup:
        pywikibot.output('Highest-res YouTube thumbnail was not found.\n')
        choices = [('Use lower-res YouTube thumbnail', '1'), ('Use Twitter or other image url', '2')]
        response = pywikibot.input_choice(
            'What would you like to do?',
            choices)
        if response == '1':
            url = yt.thumbnail_url_backup
        else:
            url = pywikibot.input('Enter the url for the high-quality episode thumbnail')
    else:
        url = ''
    return url


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
        array_string += '}'
        return array_string

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

        # Get the 'altTitles' lists from both dictionaries (default to empty lists if the key does not exist)
        new_alt_titles = new_dict.get('altTitles', [])
        current_alt_titles = current_dict.get('altTitles', [])

        # Merge the altTitles lists and remove duplicates
        new_dict['altTitles'] = list(dict.fromkeys(new_alt_titles + current_alt_titles))

        return new_dict

    def treat_page(self):
        self.current_page = pywikibot.Page(self.site, EP_ARRAY)
        text = self.current_page.text
        ep = self.opt.ep

        current_entry = next((x for x in re.split('\n\s+\},\n',
                            text) if re.search(f'\["{ep.code}"\]', x)),
                            '')
        if current_entry:
            current_entry += '\n    },\n'
            array_dicts = self.get_array_dicts()
            current_dict = self.get_current_dict(array_dicts=array_dicts)
        else:
            prev_entry = next((x for x in re.split('\n\s+\},\n',
                            text) if re.search(f'\["{ep.get_previous_episode().code}"\]', x)),
                            '') + '\n    },\n'
            current_dict = {}

        new_dict = self.build_new_array_dict()
        new_dict = self.update_new_dict(new_dict, current_dict)

        # Make sure that for relevant episode codes it is also the latest
        latest = ep.latest
        if latest and latest not in new_dict['altTitles']:
            text = re.sub(fr'{latest}(, )?', '', text)
            new_dict['altTitles'].append(latest)

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
        elif prev_ep and prev_ep.code in text:
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
            wiki_code = ep.wiki_noshow
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
            prev_ep = prev_ep.get_previous_episode()

        # create new table entry from scratch if it doesn't exist yet, inserting after previous episode
        if not any([ep.code in str(x) for x in wikicode.filter_templates()
                    if x.name.matches('ep')]):
            ep_entry = self.build_episode_entry()
            previous_entry_wiki = next((x for x in wikicode.filter_templates()
                if x.has_param('ep') and x.name.matches('Episode table entry') and
                prev_ep.code in x['ep']), '')
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
                if x.has_param('ep') and x.name.matches('Episode table entry') and ep.code in x['ep'])
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
        ts = YoutubeTranscript(ep=self.opt.ep, yt=self.opt.yt, actor_data=ACTOR_DATA)
        ts.download_and_build_transcript()
        return ts

    def treat_page(self):
        url = 'Transcript:' + self.opt.new_page_name
        self.current_page = pywikibot.Page(self.site, url)
        ts = self.build_transcript()
        self.opt.ts = ts
        if self.current_page.exists() and self.current_page.text:
            pywikibot.output(f'Transcript page already exists for {self.opt.new_page_name}; transcript creation skipped')
        else:
            self.put_current(ts.transcript, summary=f"Creating {self.opt.ep.code} transcript (via pywikibot)")


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
                prev_ep = prev_ep.get_previous_episode()
            prev_ep_entry = next((x for x in text.splitlines()
                                  if prev_ep and prev_ep.code in x),
                                 '== Miscellaneous ==')
            text = text.replace(prev_ep_entry,
                                '\n'.join([prev_ep_entry, ep_entry]))

            self.put_current(text, summary=f"Add entry for {ep.code} (via pywikibot)")
        # if it exists, replace entry with current values if needed
        else:
            current_entry = next((x for x in text.splitlines() if ep.code in x), None)
            text = text.replace(current_entry, ep_entry)
            self.put_current(text, summary=f"Updating entry for {ep.code} (via pywikibot)")

class TranscriptRedirectBot(EpisodeBot):
    '''Insures all viable Transcript:CxNN redirects exist and point at Transcript:new_page_name.'''
    use_redirects: True

    def treat_page(self):
        ep = self.opt.ep
        url = 'Transcript:' + self.opt.new_page_name
        for code in ep.transcript_redirects:
            self.current_page = pywikibot.Page(self.site, code)
            text = f"#REDIRECT [[{url}]]"
            self.put_current(text, summary="Updating/creating transcript redirects (via pywikibot)")


class RedirectFixerBot(EpisodeBot):
    '''Insures all viable CxNN redirects exist and point at new_page_name.'''
    use_redirects: True

    def treat_page(self):
        ep = self.opt.ep
        all_codes = ep.generate_equivalent_codes() + ep.ce_codes
        for code in all_codes:
            self.current_page = pywikibot.Page(self.site, code)
            text = f"#REDIRECT [[{self.opt.new_page_name}]]"
            self.put_current(text, summary="Updating/creating episode redirects (via pywikibot)")


def get_navbox(navbox_text):
    if isinstance(navbox_text, mwparserfromhell.wikicode.Wikicode):
        navbox_wikicode = navbox_text
    else:
        assert isinstance(navbox_text, str)
        navbox_wikicode = mwparserfromhell.parse(navbox_text)
    navbox = next((x for x in navbox_wikicode.filter_templates() if x.name.matches('Navbox')), None)
    return navbox


def get_navbox_pairs(template):
    '''for parsing navbox list names and members, such as group1 and list1.'''
    if isinstance(template, mwparserfromhell.wikicode.Template):
        navbox_pairs = {
            template.get(f"group{n}").value.lower().strip()
            if template.has_param(f"group{n}") else str(n):
            template[f"list{n}"].value
            for n in range(1, len(template.params))
            if template.has_param(f"list{n}")
        }
    else:
        navbox_pairs = {}
    return navbox_pairs


def make_navbox_dict(navbox):
    '''recursively implements get_navbox_pairs() for sublists.'''
    navbox_pairs = get_navbox_pairs(navbox)
    result = {}
    for k, v in navbox_pairs.items():
        navbox_child = next((x for x in v.filter_templates() 
                             if x.name.matches('Navbox') and x.get(1) and x[1].value.matches('child')),
                           None)
        if navbox_child:
            output = {'|'.join([k, key]): value for key, value in make_navbox_dict(navbox_child).items()}
        else:
            output = {k: v}
        result.update(output)
    return result


def select_navbox_list(navbox, item='this item'):
    navbox_dict = make_navbox_dict(navbox)
    if not all([x.isdigit() for x in navbox_dict.keys()]):
        choices = [(str(i+1), k) for i, k in enumerate(navbox_dict.keys())]
        list_name = pywikibot.input_choice(f'Which list does {item} belong in?', choices)
        pywikibot.output(f'adding to {list_name}')
        list_members = navbox_dict[list_name]
    else:
        # just get the last list in the dict
        list_members = list(navbox_dict.items())[-1][1]
    return list_members


def get_last_item(wikicode, name='ep'):
    if isinstance(wikicode, mwparserfromhell.wikicode.Wikicode):
        last_item = next((x for x in reversed(wikicode.filter_templates()) if x.name.matches(name)), None)
        return last_item


def add_to_wiki_list(new_item, wikicode, name='ep'):
    last_item = get_last_item(wikicode, name=name)
    if last_item:
        wikicode.insert_after(last_item, f' • {new_item}')
        return wikicode


class NavboxBot(EpisodeBot):
    '''Makes sure the episode code appears on the accompanying navbox'''

    def treat_page(self):
        navbox_name = f'Template:{self.opt.ep.navbox_name}'
        ep = self.opt.ep

        self.current_page = pywikibot.Page(self.site, navbox_name)
        wikicode = self.get_wikicode()

        if not any([ep.code.lower() in str(x).lower() for x in wikicode.filter_templates()
                    if x.name.matches('ep')]):
            navbox = get_navbox(wikicode)
            navbox_list = select_navbox_list(navbox, item = self.display_ep)
            if ep.prefix in ['4SD', 'CO']:
                wiki_ep = ep.wiki_noshow
            else:
                wiki_ep = ep.wiki_code
            add_to_wiki_list(wiki_ep, navbox_list)

        self.put_current(
            str(wikicode),
            summary=f"Adding {self.opt.ep.code} to navbox (via pywikibot)"
        )


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
        '''For every prefix in the decoder, get the most recently aired episode'''
        airdate_dict = self.get_airdate_dict()
        aired = {k: v for k, v in airdate_dict.items() if v.datetime <= datetime.now().astimezone()}
        latest_episodes = [next((Ep(k) for k in reversed(aired.keys()) if Ep(k).prefix == prefix), None) 
                           for prefix, v in EPISODE_DECODER.items() if v.get('navbox')]
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
            prev_ep = Ep(self.get_previously_aired_episode(), episode_decoder=EPISODE_DECODER)
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
            affected_episodes = [x for x in affected_episodes
                                 if Ep(x, episode_decoder=EPISODE_DECODER).prefix == '3']
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
            infobox.add('4SD', ep.wiki_noshow, showkey=None,
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


class LongShortBot(EpisodeBot):
    '''For checking whether the runtime of an episode is one of the longest or shortest'''

    def treat_page(self):
        if self.opt.ep.prefix == '4SD':
            return pywikibot.output('Skipping longest/shortest checking for {}')
        self.current_page = pywikibot.Page(self.site, 'Longest and shortest episodes')
        is_longest = self.check_if_longest()
        is_shortest = self.check_if_shortest()
        if not is_shortest and not is_longest:
            pywikibot.output(f"{self.opt.ep.code} is neither a longest or shortest episode.")

    def check_if_longest(self):
        ep = self.opt.ep
        runtime = Runtime(self.opt.runtime)
        wikicode = self.get_wikicode()
        is_longest = False
        longest = next(x for x in wikicode.get_sections() if any([
            y.title.matches('Longest episodes') for y in x.filter_headings()]))
        longest_overall = longest.get_sections(flat=True)[1]
        relevant_section = next((section for section in longest.get_sections(flat=True)[2:]
                        if ep.show.lower() in section.filter_headings()[0].title.lower()),
                       '')
        for section in [relevant_section, longest_overall]:
            if not section:
                continue
            h = section.filter_headings()[0]
            records = [x.groupdict() for x in re.finditer(LONG_SHORT_REGEX, str(section))]
            for rec in records:
                    if runtime >= Runtime(rec['timecode']):
                        pywikibot.output(f"{ep.code} ({runtime}) is longer than #{rec['num']} {rec['ep_code']} ({rec['timecode']}) ({h.title.strip()})")
                        is_longest = True
                        break
        if runtime >= '5:00:00':
            pywikibot.output(f"{ep.code} ({runtime}) is longer than five hours")
        return is_longest

    def check_if_shortest(self):
        ep = self.opt.ep
        runtime = Runtime(self.opt.runtime)
        wikicode = self.get_wikicode()
        is_shortest = False
        shortest = next(x for x in wikicode.get_sections() if any(
            [y.title.matches('Shortest episodes') for y in x.filter_headings()]))
        shortest_overall = shortest.get_sections(flat=True)[1]
        # for one-shots and miniseries, don't compare to campaign-only table
        if not ep.is_campaign:
            shortest_overall = mwparserfromhell.parse(shortest_overall.split('Shortest episodes, exclud')[0])
        relevant_section = next((section for section in shortest.get_sections(flat=True)[2:]
                                if ep.show.lower() in section.filter_headings()[0].title.lower()),
                               '')
        for section in [relevant_section, shortest_overall]:
            if not section:
                continue
            h = section.filter_headings()[0]
            records = [x.groupdict() for x in re.finditer(LONG_SHORT_REGEX, str(section))]
            for rec in records:
                if runtime <= Runtime(rec['timecode']):
                    pywikibot.output(f"{ep.code} ({runtime}) is shorter than #{rec['num']} {rec['ep_code']} ({rec['timecode']}) ({h.title.strip()})")
                    is_shortest = True
                    break
        return is_shortest


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

    # Parse args for downloading module data
    for arg in local_args:
        arg, _, value = arg.partition(':')
        option = arg[1:]
        if option in ['decoder', 'download_data']:
            decoder = Decoder(force_download=True)
            # options['episode_decoder'] = decoder._json
            pywikibot.output("Episode decoder re-downloaded.")
        if option in ['actor_data', 'download_data']:
            ACTOR_DATA = ActorData(force_download=True)
            # options['actors'] =  actor_data.actor_names
            # options['speaker_tags'] = actor_data.speaker_tags
            pywikibot.output("Actor data re-downloaded.")
    if not 'decoder' in locals():
        decoder = Decoder()
    EPISODE_DECODER = decoder._json
    EP_REGEX = Ep('1x01', episode_decoder=EPISODE_DECODER).ep_regex
    TRANSCRIPT_EXCLUSIONS = [k for k, v in decoder._json.items()
                             if v.get('noTranscript') is True]

    if not 'ACTOR_DATA' in locals():
        ACTOR_DATA = ActorData()

    # Parse script-specific command line arguments
    for arg in local_args:
        arg, _, value = arg.partition(':')
        option = arg[1:]
        if option in ['actor_data', 'decoder', 'download_data']:
            continue
        elif option in ['ep_id', 'ep']:
            value = get_validated_input(arg='ep', value=value, regex=EP_REGEX)
            options['ep'] = Ep(value, episode_decoder=EPISODE_DECODER)
        elif option in ['yt_id', 'yt']:
            value = get_validated_input(arg=option, value=value, regex=YT_ID_REGEX)
            options['yt'] = YT(value)
        elif option in ['actors', 'host']:
            if option == 'actors':
                options[option] = Actors(value, actor_data=ACTOR_DATA)
            elif option == 'host':
                options[option] = Actors(value, link=False, actor_data=ACTOR_DATA)
        elif option == 'airdate':
            if re.search(DATE_2_REGEX, value):
                pass
            else:
                value = get_validated_input(arg=option, value=value, regex=DATE_REGEX)
            options['airdate'] = Airdate(value)
        elif option == 'airtime':
            options['airtime'] = Airdate(value)
        elif option in (
            'summary', 'actors', 'runtime', 'new_ep_name', 'episode_summary', 'image_name'):
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
                 'airdate_order', 'transcript', 'transcript_list', 'redirects',
                 'navbox', '4SD', 'long_short']:
        if options.get('all'):
            options[task] = True
        elif not options.get(task):
            options[task] = False

    # get user input for required values that were not passed in.
    # only required if certain tasks will be conducted
    required_options = ['ep', 'yt', 'new_ep_name', 'runtime', 'actors']
    for req in required_options:
        if req not in options:
            if req == 'yt' and any([options.get(x) for x in ['update_page', 'ep_list', 'yt_list', 'transcript', 'upload']]):
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
                options[req] = Actors(value, actor_data=ACTOR_DATA)
            elif req == 'runtime' and any([options.get(x) for x in ['update_page', 'ep_list', 'long_short']]):
                value = get_validated_input(arg='runtime', regex='\d{1,2}:\d{1,2}(:\d{1,2})?', input_msg="Please enter video runtime (HH:MM:SS or MM:SS)")
                options['runtime'] = value
            elif req == 'ep':
                test_ep = Ep('1x01', episode_decoder=EPISODE_DECODER)
                value = get_validated_input(arg=req, value=value, regex=EP_REGEX)
                options['ep'] = Ep(value, episode_decoder=EPISODE_DECODER)

    # default new page name is same as new episode name (and page being parsed)
    if not options.get('new_page_name'):
        options['new_page_name'] = options['new_ep_name']

    # if 4SD, make sure host is provided. If one-shot, default host/DM/GM to Matt.
    if options['ep'].prefix == '4SD' and not options.get('host'):
        host = pywikibot.input(f"4-Sided Dive host for {options['ep'].code} (first name ok)")
        options['host'] = Actors(host, link=False, actor_data=ACTOR_DATA)
    if options['ep'].prefix == 'OS':
        host = next((options[x] for x in ['host', 'DM', 'GM', 'dm', 'gm']
            if options.get(x)), 'Matthew Mercer')
        options['host'] = Actors(host, link=False, actor_data=ACTOR_DATA)

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
        pywikibot.output(f"Now updating wiki for {bot1.display_ep}")
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
            if options.get('image_name'):
                filename = options['image_name']
            else:
                filename = options['ep'].image_filename
            thumbnail_url = select_thumbnail_url(options['yt'])
            if thumbnail_url:
                thumbnail_bot = UploadRobot(
                    generator=gen,
                    url=thumbnail_url,
                    description=description,
                    use_filename=filename,
                    summary=summary,
                    verify_description=True,
                )
                thumbnail_bot.run()
            else:
                pywikibot.output('High-res and backup YouTube thumbnail not found. Check if YouTube ID is correct.')

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

        if options.get('redirects'):
            bot5 = RedirectFixerBot(generator=gen, **options)
            bot5.treat_page()

        if options.get('navbox'):
            bot6 = NavboxBot(generator=gen, **options)
            bot6.treat_page()

        if options.get('airdate_order'):
            if not options.get('airdate'):
                airdate_string = pywikibot.input('Please enter episode airdate (YYYY-MM-DD)')
                options['airdate'] = Airdate(airdate_string)
            bot7 = AirdateBot(generator=gen, **options)
            bot7.treat_page()
            options['airdate_dict'] = bot7.opt.airdate_dict

        if options['ep'].prefix == '4SD' and options.get('4SD'):
            bot8 = Connect4SDBot(generator=gen, **options)
            bot8.treat_page()
            if not options.get('array_dicts'):
                options['array_dicts'] = bot8.opt.array_dicts
            if not options.get('airdate_dict'):
                options['airdate_dict'] = bot8.opt.airdate_dict

        if options.get('transcript'):
            if options['ep'].prefix in TRANSCRIPT_EXCLUSIONS:
                pywikibot.output(f'\nSkipping transcript page creation for {options["ep"].show} episode')
            else:
                bot9 = TranscriptBot(generator=gen, **options)
                bot9.treat_page()
                if bot9.opt.ts:
                    options['ts'] = bot9.opt.ts
                bot9 = TranscriptRedirectBot(generator=gen, **options)
                bot9.treat_page()

        if options.get('ts'):
            dupe_count = len(options['ts'].dupe_lines)
            if dupe_count:
                dupes = pywikibot.input_yn(f'Process {dupe_count} duplicate captions in transcript now?')
            else:
                dupes = False
                pywikibot.output('No duplicates found in transcript to process.')
            if dupes:
                bot10 = DupeDetectionBot(generator=gen, **options)
                bot10.current_page = pywikibot.Page(bot10.site, f"Transcript:{options['new_ep_name']}")
                bot10.treat_page()
            else:
                command = f"\n<<yellow>>python pwb.py dupes -ep:{options['ep'].code} -yt:{options['yt'].yt_id}<<default>>"
                pywikibot.output(f'Skipping ts duplicate processing. You can run this later:{command}')

        if options.get('transcript_list'):
            if options['ep'].prefix in TRANSCRIPT_EXCLUSIONS:
                pywikibot.output(f'\nSkipping transcript list update for {options["ep"].show} episode')
            else:
                bot11 = TranscriptListBot(generator=gen, **options)
                bot11.treat_page()

        if options.get('long_short'):
            if options['ep'].prefix == '4SD':
                pywikibot.output(f'\nSkipping longest/shortest for {options["ep"].show} episode')
            else:
                bot12 = LongShortBot(generator=gen, **options)
                bot12.treat_page()


if __name__ == '__main__':
    try:
        main()
    except QuitKeyboardInterrupt:
        pywikibot.info('\nUser quit vod bot run.')
