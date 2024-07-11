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

-transcript       Create transcript pages for English and other translations (auto-skips TRANSCRIPT_EXCLUSIONS)

-no_translations  Only create the transcript page for English (auto-skips TRANSCRIPT_EXCLUSIONS)

-transcript_list  Add transcript page to list of transcripts (auto-skips TRANSCRIPT_EXCLUSIONS)

-ignore_break     To manually override break checking for campaign episodes

-upload           Upload and link to the episode thumbnail; ignored if already exists

-long_short       Check whether the runtime for the episode is one of the longest or shortest

-redirects        Make sure episode code redirect(s) exist and link to newest episode name

-navbox           Make sure the episode code is in the navbox, as determined from Module:Ep/Decoder

-cite_cat         Check if the article maintenance category has been created

-4SD              For 4-Sided Dive only, add ep_id to the 3xNN episodes since the previous

-appendix         For Midst only, interactively create [[Module:Midst appendices/Array]] entry

Local data can be downloaded from various modules:

-decoder          For forcing a re-download of Module:Ep/Decoder. Does not occur with -all

-actor_data       For forcing a re-download of Module:ActorData. Does not occur with -all

-download_data    For forcing a re-download of all data listed above. Does not occur with -all

Use global -simulate option for test purposes. No changes to live wiki will be done.
For every potential change, you will be shown a diff of the edit and asked to accept or reject it.
No changes will be made automatically. Actions are skipped if change is not needed (e.g., an entry for
the episode already exists on the module page).

All other parameters are passed in the format -parameter:value. Use "quotes" around value if it has
spaces (e.g., -actors:"Marisha, Taliesin, Matt"). If a string includes a "!", it will only work if it is
enclosed in single quotes like '!'.

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

-file_desc:       To override the automatically generated description for an uploaded image

-caption:         To override the automatically generated caption for an episode thumbnail

-summary:         A pywikibot command that adds an edit summary message and shouldn't be needed.

-host:            Actor who is the 4SD host or running one-shot (DM, GM also work here)

-game_system:     For one-shots, game system if not Dungeons & Dragons

-airsub:          For Midst, the earlier date the episode released to subscribers

-transcript_link: For Midst, the url of the transcript

-illustrator:     For Midst, the illustrator of the thumbnail/icon art

-logline:         For Midst, the episode quote for the quotebox

-icon_url:        For Midst, the url of the .png episode icon

Other parameters (most of which are automatically calculated values but still can be passed in)
can be found in `update_options` for EpisodeBot (line 107).

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
    ExistingPageBot,
    SingleSiteBot,
    QuitKeyboardInterrupt,
)
from pywikibot.specialbots import UploadRobot
import requests
from cr_modules.cr import *
from cr_modules.ep import *
from cr_modules.transcript import YoutubeTranscript, DEFAULT_LANGUAGE
from dupes import DupeDetectionBot

MINISERIES = ['OS', 'E', 'CO']


class EpisodeBot(
    SingleSiteBot,  # A bot only working on one site
    ExistingPageBot,  # CurrentPageBot which only treats existing pages
):
    """
    :ivar summary_key: Edit summary message key. The message that should be
        used is placed on /i18n subdirectory. The file containing these
        messages should have the same name as the caller script (i.e. basic.py
        in this case). Use summary_key to set a default edit summary message.
    :type summary_key: str
    """

    use_redirects = False  # treats non-redirects only

    update_options = {
        'summary': 'Updating newly-released episode page (via pywikibot)',
        'yt': None, # YT object
        'runtime': None,  # how long the episode goes for
        'old_ep_name': None,  # the old placeholder name of the episode
        'new_ep_name': None,  # the new official name of the episode
        'new_page_name': None,  # if different from episode title (usually 'A' vs 'A (episode)')
        'ep': None,  # Ep object
        'image_name': None,  # unless specified, builds automatically from Ep.image_filename
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
        'file_desc': None,  # manually created thumbnail file description
        'caption': None,  # manually created infobox thumbnail caption
        'long_short': None, # check whether runtime is one of longest or shortest
        'ep_list': None,  # add to/update list of episodes
        'airdate_order': None,  # add to/update the airdate order
        'yt_switcher': None,  # add to/update the yt url switcher
        'ep_array': None,  # add to/update the ep array
        'transcript': None,  # create episode transcript pages (auto-skips TRANSCRIPT_EXCLUSIONS)
        'ignore_break': None,  # Don't run BreakFinder when generating the transcript
        'no_translations': None,  # only create English transcript (auto-skips TRANSCRIPT_EXCLUSIONS)
        'transcript_list': None,  # add transcript page to list of transcripts (auto-skips TRANSCRIPT_EXCLUSIONS)
        'TRANSCRIPT_EXCLUSIONS': None, # calculated from Decoder. CxNN prefixes with no transcripts
        'ts': None, # YoutubeTranscript object
        'redirects': None,  # add/update redirects from ep_id to new_page_name
        'navbox': None,  # add ep_id to the appropriate navbox template
        'cite_cat': None,  # create article maintenance category for episode code
        '4SD': None,  # add 4SD param to 3xNN pages (4SD only)
        'airsub': None,  # date episode released to subscribers (Midst only)
        'transcript_link': None,  # external transcript link (Midst only)
        'illustrator': None, #  name of thumbnail illustrator (Midst only)
        'logline': None,  # add quotebox after infobox (Midst only)
        'icon_url': None,  # direct url to icon image (Midst only)
        'appendix': None,  # whether to prompt for appendix (Midst only)
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
            old_title = str(self.current_page.title())
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
        if new_text != text and self.opt.update_page:
            pywikibot.showDiff(text, new_text)
            do_it = pywikibot.input_yn('Continue with summary addition?')
            if do_it:
                wikicode = mwparserfromhell.parse(new_text)
                if self.opt.summary_only:
                    self.put_current(new_text, summary=self.opt.summary)
            else:
                pass

        return wikicode

    def handle_infobox_image(self, infobox, param_name='image', image='thumbnail'):
        # if image field is filled in with existing file, cancel thumbnail procedure
        # otherwise, use image_name if entered
        if image == 'thumbnail':
            image_name = (self.opt.image_name
                          if self.opt.get('image_name')
                          else self.opt.ep.image_filename)
        elif image == 'icon':
            image_name = self.opt.ep.icon_filename
        file = None
        if infobox.has_param(param_name) and self.opt.upload:
            image_value = (remove_comments(infobox[param_name].value)).strip()
            if image_value and 'file' not in image_value.lower():
                file_value = 'File:' + image_value
            elif not image_value:
                file_value = 'File:' + image_name
            else:
                file_value = image_value
            file = pywikibot.Page(self.site, file_value)
            if image_value and not image_name:
                image_value = image_value.replace('File:', '')
                self.opt.image_name = image_value
            # if image already (or to be) uploaded but not in param, add to infobox
            if not image_value:
                infobox[param_name] = image_name
            if self.opt.upload and image_value and image_value != image_name:
                pywikibot.output(
                    f'Infobox image {image_value} does not match entered {image_name}. Please resolve and try again.')
                sys.exit()
        # don't offer to fill in field if upload not in procedure or file doesn't exist
        if self.opt.image_name and not file:
            file = pywikibot.Page(self.site, image_name)
        if not self.opt.upload and (not file or not file.exists()):
            pass
        elif (image_name and
              infobox.has_param('param_name') and
              not does_value_exist(infobox, param_name)):
            infobox[param_name] = ' ' + image_name.lstrip()

        return infobox

    def update_4SD_infobox(self, infobox):
        params_to_update = {
        'image1_tab': 'Main',
        'image1': self.opt.ep.image_filename,
        'image1_caption': f'{{{{art official caption|nointro=true|subject=Thumbnail|screenshot=1|source={self.opt.ep.wiki_nolink}}}}}',
        'image2_tab': 'Game',
        'image2': self.opt.ep.game_filename,
        'image2_caption': 'Thumbnail for the C-block game portion, entitled More-Sided Dive.'
    }

        for param_name, default_value in params_to_update.items():
            if not does_value_exist(infobox, param_name):
                if not infobox.has_param(param_name):
                    infobox.add(param_name, default_value, before='epCode')
                else:
                    infobox[param_name] = default_value

        if infobox.has_param('image'):
            infobox.remove('image')
        if infobox.has_param('caption'):
            infobox.remove('caption')

        return infobox

    def update_midst_infobox(self, infobox):
        params_to_update = {
        'image1_tab': 'Icon',
        'image1': self.opt.ep.icon_filename,
        'image1_caption': 'Icon by Third Person',
        'image2_tab': 'Thumbnail',
        'image2': self.opt.ep.image_filename,
        'image2_caption': 'Thumbnail for the video version'
    }

        for param_name, default_value in params_to_update.items():
            if not does_value_exist(infobox, param_name):
                if not infobox.has_param(param_name):
                    infobox.add(param_name, default_value, before='epCode')
                else:
                    infobox[param_name] = default_value

        if infobox.has_param('image'):
            infobox.remove('image')
        if infobox.has_param('caption'):
            infobox.remove('caption')

        # subscriber airdate
        if not does_value_exist(infobox, 'airsub'):
            if self.opt.get('airsub'):
                infobox['airsub'] = self.opt.airsub.date
            else:
                airsub_string = get_validated_input(arg='airsub', regex=DATE_REGEX)
                airsub = Airdate(airsub_string)
                self.opt.airsub = airsub
                infobox['airsub'] = airsub.date
        elif self.opt.airsub:
            infobox_airsub = Airdate(infobox['airsub'].value.strip())
            try:
                assert self.opt.airsub.date == infobox_airsub.date
            except AssertionError:
                new_airsub_string = get_validated_input(arg='airsub', regex=DATE_REGEX, input_msg=f'Infobox airsub {infobox_airsub.date} does not match entered airsub {self.opt.airsub.date}. Enter airsub date (YYYY-MM-DD):')
                new_airsub = Airdate(new_airsub_string)
                infobox['airsub'] = new_airsub.date
        else:
            self.opt.airsub = Airdate(infobox['airsub'].value.strip())
        try:
            assert self.opt.airsub.date <= self.opt.airdate.date
        except AssertionError:
            print(f'\nAirdate for subscribers {self.opt.airsub.date} is after general airdate {self.opt.airdate.date}. Check dates and try again')
            sys.exit()

        return infobox

    def treat_page(self) -> None:
        """Load the episode page, change the relevant fields, save it, move it."""
        # TO DO: split up into multiple functions for each type of update
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

        if self.opt.update_page:
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
                pywikibot.output(f'\nSHORT DESCRIPTION: {shortdesc_value}')
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

        infobox['epCode'] = ep.code

        if self.opt.runtime and not does_value_exist(infobox, param_name='runtime'):
            # add all runtimes together
            total_runtime = str(sum(self.opt.runtime, timedelta()))
            if ep.prefix == '4SD' and len(self.opt.runtime) == 2:
                # footnote explaining runtime addition for 4SD 2-parters
                runtime_footnote = ''.join([
                    '''{{fn|This episode was uploaded in two parts. ''',
                    '''The first, which covered the question portions, was uploaded as 4-Sided Dive ''',
                    f'''and ran for {str(self.opt.runtime[0])}. ''',
                    '''The second, which covered the game portion, was uploaded as More-Sided Dive ''',
                    f'''and ran for {str(self.opt.runtime[1])}.}}}}'''
                    ])
                total_runtime += runtime_footnote
            infobox['runtime'] = total_runtime
        # prompt if infobox airdate conflicts w/user entry
        if does_value_exist(infobox, 'airdate') and self.opt.airdate:
            if Airdate(infobox['airdate'].value.strip()).date == self.opt.airdate.date:
                pass
            else:
                airdate_1 = Airdate(infobox['airdate'].value.strip()).date
                airdate_2 = self.opt.airdate.date
                if len(airdate_1) and airdate_1 != airdate_2:
                    new_airdate_string = get_validated_input(arg='airdate', regex=DATE_REGEX, input_msg=f'Infobox airdate {airdate_1} does not match entered airdate {airdate_2}. Enter airdate (YYYY-MM-DD):')
                    new_airdate = Airdate(new_airdate_string)
                    self.opt.airdate.datetime = self.opt.airdate.datetime.replace(**{x: getattr(new_airdate.datetime, x) for x in ['day', 'month', 'year']})
                    infobox['airdate'] = new_airdate.date
                else:
                    infobox['airdate'] = self.opt.airdate
        # get the airdate & airtime from infobox so it can be used later
        elif does_value_exist(infobox, 'airdate') and not self.opt.airdate:
            self.opt.airdate = Airdate(infobox['airdate'].value.strip())
        # add airdate to infobox if entered and not already there
        elif self.opt.airdate and not does_value_exist(infobox, 'airdate'):
            infobox['airdate'] = self.opt.airdate.date
        # prompt for airdate if updating episode page, existing field is blank, and not already provided
        elif (self.opt.update_page and
              not infobox['airdate'].value.strip() and
              infobox.has_param('airdate') and
              not self.opt.airdate):
            airdate_string = get_validated_input(arg='airdate', regex=DATE_REGEX)
            self.opt.airdate = Airdate(airdate_string)
            infobox['airdate'] = self.opt.airdate.date
        else:
            self.opt.airdate = ""
        if infobox.has_param('airtime') and infobox['airdate'].value.strip() and not self.opt.airtime:
            # add airtime to airdate object
            self.opt.airtime = Airdate(infobox['airtime'].value.strip())
            if self.opt.airtime:
                self.opt.airdate = Airdate(datetime.combine(
                    self.opt.airdate.datetime.date(),
                    self.opt.airtime.datetime.timetz()))
        else:
            self.opt.airtime = ""

        # Midst: add image fields, plus transcript link
        if ep.prefix == 'Midst':
            self.handle_infobox_image(infobox, param_name='image1', image='icon')
            self.handle_infobox_image(infobox, param_name='image2', image='thumbnail')
            self.update_midst_infobox(infobox)
            if not does_value_exist(infobox, 'transcript'):
                infobox['transcript'] = self.opt.transcript_link
            if not does_value_exist(infobox, 'midst illustrator'):
                infobox['midst illustrator'] = self.opt.illustrator
        elif ep.prefix == '4SD' and len(self.opt.yt) == 2:
            infobox = self.update_4SD_infobox(infobox)
        else:
             infobox = self.handle_infobox_image(infobox)


        # only write caption if field not filled in or missing AND image field filled in
        if ((not infobox.has_param('caption')
            or not does_value_exist(infobox, param_name='caption'))
            and does_value_exist(infobox, param_name='image')
            and ep.prefix != 'Midst'):
            if self.opt.get('caption'):
                infobox['caption'] = self.opt['caption']
            else:
                infobox['caption'] = make_image_caption(actors=self.opt.actors, ep=ep)

        # Add game system for one-shots
        if (ep.prefix == 'OS' and not
            (infobox.has_param('system') or remove_comments(infobox['system'].value)) and
            self.opt.get('game_system', '').lower() != 'dungeons & dragons'):
            infobox.add('system', self.opt['game_system'], after='runtime')

        # add logline for Midst if not there yet
        if ep.prefix == 'Midst' and self.opt.get('logline'):
            logline = Logline(self.opt['logline'])
            if self.opt['logline'] not in wikicode:
                wikicode.insert_after(infobox, logline.line)
            else:
                pywikibot.output(f'Logline already present for {ep.code}; skipping')

        if not any([x.name.matches(ep.campaign.navbox) for x in wikicode.filter_templates()]):
            wikicode.append('\n' + f"{{{{{ep.campaign.navbox}}}}}")

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

        # Add {{TranscriptLink}} template to synopsis
        link_template = next((x for x in wikicode.filter_templates() if x.name.matches('TranscriptLink')), None)
        url = 'Transcript:' + self.opt.new_page_name
        transcript_page = pywikibot.Page(self.site, url)
        if (not link_template
            and (self.opt.transcript or transcript_page.exists())
            and self.opt['ep'].prefix not in self.opt.TRANSCRIPT_EXCLUSIONS
            ):
            synopsis_heading = next((x for x in wikicode.filter_headings() if x.title.matches('Synopsis')), None)
            if synopsis_heading:
                text = text.replace(str(synopsis_heading), str(synopsis_heading) + '\n{{TranscriptLink}}\n')
                assert 'TranscriptLink' in text
            else:
                pywikibot.output("No synopsis section found; link to transcript in article will not be added.")

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
                y['altTitles'] = re.findall(r'"(.*?)"', y['altTitles'])
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

        # Replace tabs with 4 spaces
        text = text.replace('\t', '    ')

        current_entry = next((x for x in re.split(r'\n\s+\},\n',
                            text) if re.search(fr'\["{ep.code}"\]', x)),
                            '')
        if current_entry:
            current_entry += '\n    },\n'
            array_dicts = self.get_array_dicts()
            current_dict = self.get_current_dict(array_dicts=array_dicts)
        else:
            current_dict = {}

        new_dict = self.build_new_array_dict()
        new_dict = self.update_new_dict(new_dict, current_dict)

        # Make sure that for relevant episode codes it is also the latest
        latest = ep.campaign.latest
        if latest and latest not in new_dict['altTitles']:
            text = re.sub(fr'"{latest}"(, )?', '', text)
            new_dict['altTitles'].append(latest)

        new_entry = self.dict_to_entry(new_dict)

        if current_entry:
            text = text.replace(current_entry, new_entry)
        else:
            prev_entry = next((x for x in re.split(r'\n\s+\},\n',
                                                   text) if re.search(fr'\["{ep.get_previous_episode().code}"\]', x)),
                              '') + '\n    },\n'
            text = text.replace(prev_entry, '\n'.join([prev_entry, new_entry]))

        self.put_current(text, summary=f"Updating {ep.code} entry (via pywikibot)")


class YTSwitcherBot(EpisodeBot):
    '''Add yt_link as value by updating or creating entry'''
    def treat_page(self):
        self.current_page = pywikibot.Page(self.site, YT_SWITCHER)
        text = self.current_page.text
        ep = self.opt.ep
        prev_ep = ep.get_previous_episode()
        yt_url_list = [yt.url for yt in self.opt.yt]

        # format yt_urls
        if len(yt_url_list) == 1:
            yt_urls = f'{{"{yt_url_list[0]}"}}'
        elif ep.prefix == '4SD':
            yt_urls = '\n'.join([
                f'{{',
                f'        {{"{yt_url_list[0]}", "4-Sided Dive"}},',
                f'        {{"{yt_url_list[1]}", "More-Sided Dive"}},',
                f'    }}'])
        else:
            yt_urls = f'{{\n' + ',\n'.join([f'        {{"{yt_url}"}}' for yt_url in yt_url_list]) + f'\n}}'

        # Pattern to match ep code and its video array
        pattern = fr'''\["{ep.code}"\]\s*=\s*(\{{.*?\}},|\{{(?:\s*\{{.*?\}},\s*)+}},)'''

        # if it already exists as an entry, substitute in yt_link
        if ep.code in text:
            text = re.sub(pattern,
                          fr'''["{ep.code}"] = {yt_urls},''',
                          text,
                          flags=re.DOTALL)

        # if previous episode is already there, append after it
        elif prev_ep and re.search(fr'''\["{prev_ep.code}"\]\s*=\s*\{{.*?\}},''', text):
            prev_entry = re.search(fr'''\["{prev_ep.code}"\]\s*=\s*\{{.*?\}},''', text).group()
            new_entry = f'''    ["{ep.code}"]  = {yt_urls},'''
            text = text.replace(prev_entry, '\n'.join([prev_entry, new_entry]))

        # otherwise, append episode to the end of the list
        else:
            text = text.replace(
                '["default"] = {""}',
                f'["{ep.code}"]  = {yt_urls},\n    ["default"] = {{""}}'
                )

        self.put_current(text, summary=f"Adding youtube link for {ep.code} (via pywikibot)")



class EpListBot(EpisodeBot):
    '''For updating a list of episodes with a brand-new entry or new values for the current episode.'''

    def build_episode_entry_dict(self, num=None):
        ep = self.opt.ep
        '''Creating values for the fields that would populate an episode entry.'''
        # default number in table is episode number; can be overwritten
        if num is None:
            num = str(ep.number)
        if self.opt.host:
            aux1 = self.opt.host.make_actor_list_string()
        else:
            aux1 = ''
        if self.opt.ep.prefix == '4SD':
            wiki_code = ep.wiki_noshow
            transcript = ''
        elif self.opt.ep.prefix == 'Midst':
            wiki_code = ep.wiki_code
            transcript = self.opt.transcript_link
            aux1 = self.opt.illustrator
        else:
            wiki_code = ep.wiki_code
            transcript = f'{{{{ep/Transcript|{ep.code}|style=unlinked}}}}'
        if self.opt.ep.prefix == 'OS':
            game_system = self.opt.game_system
        else:
            game_system = ''
        entry_dict = {
            'no': num,
            'ep': wiki_code,
            'airdate': self.opt.airdate.date,
            'VOD': ep.wiki_vod,
            'transcript': transcript,
            'runtime': str(sum(self.opt.runtime, timedelta())),
            'aux1': aux1,
            'aux2': game_system,
            'summary': self.opt.episode_summary,
        }
        return entry_dict

    def build_episode_entry(self, num=None):
        '''Create the string for a brand new episode entry.'''
        entry_dict = self.build_episode_entry_dict(num=num)

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

        list_page_name = ep.campaign.current_list
        if not list_page_name:
            list_page_name = pywikibot.input(f"Please enter name of list of episodes page for {ep.code}")

        self.current_page = pywikibot.Page(self.site, list_page_name)
        wikicode = deepcopy(self.get_wikicode())
        text = str(wikicode)
        # if previous episode isn't there, search episode num - 1 until find one (otherwise none)
        while prev_ep and (prev_ep.code.lower() not in text.lower()):
            prev_ep = prev_ep.get_previous_episode()

        # find previous entry and use to calculate table number two ways
        # try finding by episode code
        previous_entry_wiki = next((x for x in wikicode.filter_templates()
                if x.has_param('ep') and x.name.matches('Episode table entry') and
                prev_ep and prev_ep.code in x['ep']), '')
        #if that fails, try finding the last entry
        if not previous_entry_wiki:
            for template in reversed(wikicode.filter_templates()):
                if template.name.matches('Episode table entry'):
                    previous_entry_wiki = template
                    break 

        num = int(str(previous_entry_wiki['no'].value)) + 1 if previous_entry_wiki else ep.number

        # create new table entry from scratch if it doesn't exist yet, inserting after previous episode
        if not any([ep.code in str(x) for x in wikicode.filter_templates()
                    if x.name.matches('ep')]):
            ep_entry = self.build_episode_entry(num=num)
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
        # do not overwrite 'no' parameter
        else:
            ep_entry_dict = self.build_episode_entry_dict(num=num)
            existing_entry = next(x for x in wikicode.filter_templates()
                if x.has_param('ep') and x.name.matches('Episode table entry') and ep.code in x['ep'])
            for k, v in ep_entry_dict.items():
                if (v and
                    not (existing_entry.has_param(k) and
                         existing_entry[k].value.strip() == v) and
                    k != 'no'):
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
    '''For creating transcript pages by downloading and processing youtube captions.
    Works for both English and all manually translated captions.'''

    def build_transcripts(self, no_translations=None):
        if no_translations is None:
            no_translations = self.opt.no_translations
        assert no_translations is not None
        if self.opt.ignore_break:
            ts = YoutubeTranscript(ep=self.opt.ep, yt=self.opt.yt[0],
                                   actor_data=ACTOR_DATA, ignore_break=True)
        else:
            ts = YoutubeTranscript(ep=self.opt.ep, yt=self.opt.yt[0],
                                   actor_data=ACTOR_DATA)
        if no_translations:
            ts.download_and_build_transcript()
        else:
            ts.download_all_language_transcripts()
        return ts

    def make_single_transcript(self, language=DEFAULT_LANGUAGE):
        url = 'Transcript:' + self.opt.new_page_name
        self.current_page = pywikibot.Page(self.site, url)
        ts = self.build_transcripts(no_translations=True)
        if self.current_page.exists() and self.current_page.text:
            # if existing transcript page, replace transcript in transcript_dict
            # all duplicate line detection and .json should still be the same
            pywikibot.output(f'Transcript page already exists for {self.opt.new_page_name}; creation skipped')
            ts.transcript_dict[language] = self.current_page.text
        else:
            self.put_current(ts.transcript_dict.get(language),
                             summary=f"Creating {self.opt.ep.code} transcript (via pywikibot)")
        self.opt.ts = ts

    def make_all_transcripts(self):
        ts = self.build_transcripts(no_translations=False)
        for language, transcript in ts.transcript_dict.items():
            if language == DEFAULT_LANGUAGE:
                url = 'Transcript:' + self.opt.new_page_name
            else:
                url = f'Transcript:{self.opt.new_page_name}/{language}'

            self.current_page = pywikibot.Page(self.site, url)
            if self.current_page.exists() and self.current_page.text:
                # if existing transcript page, replace in dict
                pywikibot.output(f'{language} transcript page already exists for {self.opt.new_page_name}; creation skipped')
                ts.transcript_dict[language] = self.current_page.text
            else:
                self.put_current(transcript,
                                 summary=f"Creating {self.opt.ep.code} {language} transcript (via pywikibot)")
        self.opt.ts = ts


    def treat_page(self):
        if self.opt.no_translations:
            self.make_single_transcript()
        else:
            self.make_all_transcripts()


class TranscriptListBot(EpisodeBot):
    '''For updating the list of transcripts with the transcript of the newest episode.'''
    def build_transcript_entry(self):
        transcript_entry = f"""* {self.opt.ep.wiki_code} - [[Transcript:{self.opt.new_page_name}|Transcript]]"""
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
        all_codes = ep.generate_equivalent_codes() + ep.ce_codes + [ep.ce_words, ep.ce_words_comma]
        all_codes = [x for x in all_codes if x]  # remove blanks
        for code in all_codes:
            self.current_page = pywikibot.Page(self.site, code)
            text = f"#REDIRECT [[{self.opt.new_page_name}]]\n[[Category:Episode code redirects]]"
            self.put_current(text, summary="Updating/creating episode redirects (via pywikibot)")


def get_navbox(navbox_text):
    if isinstance(navbox_text, mwparserfromhell.wikicode.Wikicode):
        navbox_wikicode = navbox_text
    else:
        assert isinstance(navbox_text, str)
        navbox_wikicode = mwparserfromhell.parse(navbox_text)
    navbox = next((x for x in navbox_wikicode.filter_templates() if x.name.contains('Navbox')), None)
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
        navbox_name = f'Template:{self.opt.ep.campaign.navbox}'
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


class CategoryBot(EpisodeBot):
    '''Create the article maintenance category for that episode code.'''

    def treat_page(self):
        ep = self.opt.ep
        if ep.prefix != 'M':
            show = f' {ep.show.title}'
        else:
            show = ''
        category_name = f'Category:Articles needing citations/{ep.code}'
        campaign_category = f'[[Category:Articles needing{show} citations]]'

        self.current_page = pywikibot.Page(self.site, category_name)
        text = '\n'.join([campaign_category,
                         '__HIDDENCAT__'])
        if not self.current_page.exists():
            self.put_current(
                text,
                summary=f"Creating maintenance category (via pywikibot)"
            )
        else:
            pywikibot.output(f'Maintenance category already exists for {ep.code}')


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
        airdate_module_regex = r'\{epCode\s*=\s*"(?P<ep_code>.*?)",\s*date\s*=\s*"(?P<airdate_entry>.*?)"\}'
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
            pywikibot.output('Cannot read airdate array; airdate module process canceled.')
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
            pywikibot.output('Cannot read airdate array; 4SD connector process canceled.')
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
                                 if Ep(x).prefix == '3']
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
                         before='prevEp', preserve_spacing=True)
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
        if self.opt.ep.prefix in ['4SD', 'M', 'LVM', 'Midst']:
            return pywikibot.output(f'Skipping longest/shortest checking for {self.opt.ep.code}')
        self.current_page = pywikibot.Page(self.site, 'Longest and shortest episodes')
        is_longest = self.check_if_longest()
        is_shortest = self.check_if_shortest()
        if not is_shortest and not is_longest:
            pywikibot.output(f"{self.opt.ep.code} is neither a longest or shortest episode.")

    def get_relevant_heading(self):
        '''Use ep prefix to find section of page. Miniseries and one-shots go together.'''
        ep = self.opt.ep
        if ep.prefix in MINISERIES:
            heading = Show('OS').title
        else:
            heading = ep.show.title
        return heading

    def check_if_longest(self):
        ep = self.opt.ep
        runtime = sum(self.opt.runtime, timedelta())
        wikicode = self.get_wikicode()
        heading = self.get_relevant_heading()
        is_longest = False
        longest = next(x for x in wikicode.get_sections() if any([
            y.title.matches('Longest episodes') for y in x.filter_headings()]))
        longest_overall = longest.get_sections(flat=True)[1]
        relevant_section = next((section for section in longest.get_sections(flat=True)[2:]
                        if heading.lower() in section.filter_headings()[0].title.lower()),
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
        runtime = sum(self.opt.runtime, timedelta())
        wikicode = self.get_wikicode()
        heading = self.get_relevant_heading()
        is_shortest = False
        shortest = next(x for x in wikicode.get_sections() if any(
            [y.title.matches('Shortest episodes') for y in x.filter_headings()]))
        shortest_overall = shortest.get_sections(flat=True)[1]
        # for one-shots and miniseries, don't compare to campaign-only table
        if not ep.is_campaign:
            shortest_overall = mwparserfromhell.parse(shortest_overall.split('Shortest episodes, exclud')[0])
        relevant_section = next((section for section in shortest.get_sections(flat=True)[2:]
                                if heading.lower() in section.filter_headings()[0].title.lower()),
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


class MidstAppendixBot(EpArrayBot):

    def __init__(self, **kwargs):
        self.available_options.update(**{
            'm_id': None,
            'm_date': None,
            'm_prefix': None,
            'm_quote': None,
            'm_archive': None,
            'm_ghostarchive': None,
                })
        super().__init__(**kwargs)

    def make_array_dicts(self):
        self.current_page = pywikibot.Page(self.site, MIDST_APPENDIX_ARRAY)
        array_dicts = []
        text = self.current_page.text

        for x in re.finditer(MIDST_APPENDIX_REGEX, text):
            y = x.groupdict()
            array_dicts.append(y)
        return array_dicts

    def build_new_array_dict(self):
        '''Creating values for the fields that would populate an appendix entry.'''
        ep = self.opt.ep

        array_dict = {
            'epcode': ep.code,
            'ID': self.opt.m_id,
            'date': self.opt.m_date,
            'prefix': self.opt.m_prefix,
            'quote': self.opt.m_quote,
            'archive': self.opt.m_archive,
            'ghostarchive': self.opt.m_ghostarchive,
                }
        return array_dict

    def treat_page(self):
        self.current_page = pywikibot.Page(self.site, MIDST_APPENDIX_ARRAY)
        text = self.current_page.text
        ep = self.opt.ep

        # appendix_params = {
        # 'm_id': None,
        # 'm_date': None,
        # 'm_prefix': None,
        # 'm_quote': None,
        # 'm_archive': None,
        # 'm_ghostarchive': None,
        # }
        # self.available_options.update(appendix_params)

        # Replace tabs with 4 spaces
        text = text.replace('\t', '    ')

        current_entry = next((x for x in re.split(r'\n\s+\},\n',
                            text) if re.search(fr'\["{ep.code}"\]', x)),
                            '')
        if current_entry:
            current_entry += '\n    },\n'
            array_dicts = self.get_array_dicts()
            current_dict = self.get_current_dict(array_dicts=array_dicts)
        else:
            current_dict = {}

        new_dict = self.build_new_array_dict()

        new_entry = self.dict_to_entry(new_dict)

        if current_entry:
            text = text.replace(current_entry, new_entry)
        else:
            prev_entry = next((x for x in re.split(r'\n\s+\},\n',
                                                   text) if re.search(fr'\["{ep.get_previous_episode().code}"\]', x)),
                              '') + '\n    },\n'
            text = text.replace(prev_entry, '\n'.join([prev_entry, new_entry]))

        self.put_current(text, summary=f"Updating {ep.code} appendix (via pywikibot)")


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
    TRANSCRIPT_EXCLUSIONS = [k for k, v in decoder._json.items()
                             if v.get('noTranscript') is True]
    options['TRANSCRIPT_EXCLUSIONS'] = TRANSCRIPT_EXCLUSIONS

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
            options['ep'] = Ep(value)
        elif re.match(r'^(yt|vod)\d*$', option, flags=re.IGNORECASE):
            # allow for a list of videos/youtube IDs
            value = get_validated_input(arg=option, value=value, regex=YT_ID_REGEX)
            if not options.get('yt'):
                options['yt'] = []
            options['yt'].append(YT(value))
        elif re.match(r'^runtime\d*$', option, flags=re.IGNORECASE):
            # allow for a list of videos/youtube IDs
            value = get_validated_input(arg=option, value=value, regex=r'\d{1,2}:\d{1,2}(:\d{1,2})?')
            if not options.get('runtime'):
                options['runtime'] = []
            options['runtime'].append(Runtime(value))
        elif option in ['actors', 'host']:
            if option == 'actors':
                options[option] = Actors(value, actor_data=ACTOR_DATA)
            elif option == 'host':
                options[option] = Actors(value, link=False, actor_data=ACTOR_DATA)
        elif option in ['airdate', 'airsub']:
            if re.search(DATE_2_REGEX, value):
                pass
            else:
                value = get_validated_input(arg=option, value=value, regex=DATE_REGEX)
            options[option] = Airdate(value)
        elif option == 'airtime':
            options['airtime'] = Airdate(value)
        elif option in (
            'summary', 'new_ep_name', 'episode_summary', 'image_name'):
            if not value:
                value = pywikibot.input(f'Please enter a value for {arg} (leave blank to ignore)')
            if value:
                options[option] = value
        elif value:
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
                 'navbox', '4SD', 'long_short', 'cite_cat']:
        if options.get('all'):
            options[task] = True
        elif not options.get(task):
            options[task] = False

    # handle optional no_translations flag
    if not options.get('no_translations'):
        options['no_translations'] = False

    # get user input for required values that were not passed in.
    # only required if certain tasks will be conducted
    required_options = ['ep', 'yt', 'new_ep_name', 'runtime', 'actors']
    for req in required_options:
        if req not in options:
            if req == 'yt' and any([options.get(x) for x in ['update_page', 'yt_list', 'transcript', 'upload']]):
                value = get_validated_input(arg='yt', regex=YT_ID_REGEX, input_msg="Please enter 11-digit YouTube ID for the video")
                options[req] = [YT(value)]
            elif req == 'new_ep_name':
                if any([options.get(x) for x in ['update_page', 'move']]):
                    value = pywikibot.input(f"If {options['old_ep_name']} will be moved, enter new page name")
                else:
                    value = ''
                if len(value.strip()):
                    options[req] = value
                else:
                    options[req] = options['old_ep_name']
            elif (req == 'actors' and
                  any([options.get(x) for x in ['update_page', 'upload']]) and
                  options.get('ep').prefix != 'Midst'):
                value = pywikibot.input(f"Optional: L-R actor order in {options['ep']} thumbnail (first names ok)")
                options[req] = Actors(value, actor_data=ACTOR_DATA)
            elif req == 'runtime' and any([options.get(x) for x in ['update_page', 'ep_list', 'long_short']]):
                value = get_validated_input(arg='runtime', regex=r'\d{1,2}:\d{1,2}(:\d{1,2})?', input_msg="Please enter video runtime (HH:MM:SS or MM:SS)")
                options['runtime'] = [Runtime(value)]
            elif req == 'ep':
                value = get_validated_input(arg=req, value=value, regex=EP_REGEX)
                options['ep'] = Ep(value)

    # default new page name is same as new episode name (and page being parsed)
    if not options.get('new_page_name'):
        options['new_page_name'] = options['new_ep_name']

    # if 4SD, make sure host is provided. If one-shot, default host/DM/GM to Matt.
    if (options['ep'].prefix == '4SD' and
        not options.get('host') and
        (options['update_page'] or options['ep_list'])):
        host = pywikibot.input(f"4-Sided Dive host for {options['ep'].code} (first name ok)")
        options['host'] = Actors(host, link=False, actor_data=ACTOR_DATA)
    if options['ep'].prefix == 'OS':
        host = next((options[x] for x in ['host', 'DM', 'GM', 'dm', 'gm']
            if options.get(x)), '')
        if not host:
            host = pywikibot.input('Enter one-shot host (leave blank for Matt Mercer)')
            if not host.strip():
                host = 'Matthew Mercer'
        options['host'] = Actors(host, link=False, actor_data=ACTOR_DATA)

    # if one-shot, default game system is D&D.
    if options['ep'].prefix == 'OS' and not options.get('game_system'):
        game_system = pywikibot.input('Enter one-shot game system (leave blank for D&D)')
        if not game_system.strip():
            game_system = 'Dungeons & Dragons'
        options['game_system'] = game_system

    # if Midst, prompt for optional logline icon url, illsutrator, transcript_link
    if options['ep'].prefix == 'Midst':
        if not options.get('transcript_link'):
            transcript_link = pywikibot.input('Enter Midst transcript link (optional)')
            options['transcript_link'] = transcript_link
        if not options.get('logline'):
            logline = pywikibot.input('Enter one-sentence Midst logline for quotebox (optional)')
            options['logline'] = logline
        if not options.get('icon_url'):
            icon_url = pywikibot.input('Enter url of Midst icon .png (optional)')
            options['icon_url'] = icon_url
        if not options.get('illustrator'):
            illustrator = pywikibot.input('Enter Midst illustrator name (optional)')
            options['illustrator'] = illustrator

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
        if (options.get('ep_list') or options.get('airdate_order')) and not options.get('airdate'):
            airdate_string = get_validated_input(arg='airdate', regex=DATE_REGEX)
            options['airdate'] = Airdate(airdate_string)


        if options.get('upload'):
            if options.get('image_name'):
                filename = options['image_name']
            else:
                filename = options['ep'].image_filename
            file_value = f"File:{filename}"
            file = pywikibot.Page(bot1.site, file_value)
            if file.exists():
                pywikibot.output('Skipping thumbnail creation (file already exists)')
            else:
                if options.get('file_desc'):
                    description = options['file_desc']
                elif options['ep'].prefix == 'Midst':
                    description = f'''== Summary ==
    {{{{ep|{options['ep'].code}}}}} thumbnail from the [https://youtu.be/{options['yt'][0].yt_id} YouTube video].

    == Licensing ==
    {{{{Fairuse}}}}

    [[Category:Midst episode thumbnails]]'''
                else:
                    description = make_image_file_description(
                        ep=options['ep'],
                        actors=options.get('actors'),
                        )
                summary = f"{options['ep'].code} episode thumbnail (uploaded via pywikibot)"
                thumbnail_url = select_thumbnail_url(options['yt'][0])
                pywikibot.output(f"\n{description}\n")
                keep = pywikibot.input_yn("Do you want to use this default image description?")
                if not keep:
                    from pywikibot import editor as editarticle
                    editor = editarticle.TextEditor()
                    try:
                        new_description = editor.edit(description)
                        description = new_description
                        pywikibot.output(f"\n<<yellow>>New description:<<default>>\n\n{description}\n")
                    except ImportError:
                        raise
                    except Exception as e:
                        pywikibot.error(e)
                if thumbnail_url and not file.exists():
                    thumbnail_bot = UploadRobot(
                        generator=gen,
                        url=thumbnail_url,
                        description=description,
                        use_filename=filename,
                        summary=summary,
                        verify_description=False,
                    )
                    thumbnail_bot.run()
                elif not thumbnail_url:
                    pywikibot.output('High-res and backup YouTube thumbnail not found. Check if YouTube ID is correct.')

            if options['ep'].prefix == 'Midst':
                file_value = f"File:{options['ep'].icon_filename}"
                file = pywikibot.Page(bot1.site, file_value)
                if file.exists():
                    pywikibot.output('Skipping Midst icon creation (file already exists)')
                else:
                    description = f'''{{{{caption|nointro=true|Episode icon for {{{{ep|{options['ep'].code}}}}}|Third Person|https://midst.co/episodes/}}}}
{{{{fairuse}}}}
[[Category:Midst episode icons]]'''
                    summary = f"{options['ep'].code} icon (uploaded via pywikibot)"
                    pywikibot.output(f"\n{description}\n")
                    keep = pywikibot.input_yn("Do you want to use this default Midst icon description?")
                    if not keep:
                        from pywikibot import editor as editarticle
                        editor = editarticle.TextEditor()
                        try:
                            new_description = editor.edit(description)
                            description = new_description
                            pywikibot.output(f"\n<<yellow>>New description:<<default>>\n\n{description}\n")
                        except ImportError:
                            raise
                        except Exception as e:
                            pywikibot.error(e)
                    if options.get('icon_url'):
                        icon_bot = UploadRobot(
                        generator=gen,
                        url=options['icon_url'],
                        description=description,
                        use_filename=options['ep'].icon_filename,
                        summary=summary,
                        verify_description=False,
                    )
                        icon_bot.run()
            elif options['ep'].prefix == '4SD':
                file_value = f"File:{options['ep'].game_filename}"
                file = pywikibot.Page(bot1.site, file_value)
                if file.exists():
                    pywikibot.output('Skipping 4SD game thumbnail creation (file already exists)')
                else:
                    if len(options['yt']) < 2:
                        game_yt = get_validated_input(
                            arg='yt', value='',regex=YT_ID_REGEX, req=False, attempts=1,
                            input_msg="Enter YT id for More-Sided Dive (leave blank to ignore)")
                        if game_yt:
                            game_yt = YT(game_yt)
                            options['yt'][1] = game_yt
                            pywikibot.output('\n<<yellow>>Runtime<<default>> likely does not include this video and may need to be changed.\n')
                    else:
                        game_yt = options['yt'][1]
                    if game_yt:
                        summary = f"{options['ep'].code} game thumbnail (uploaded via pywikibot)"
                        value = pywikibot.input(f"L-R actor order in {game_yt.thumbnail_url} game thumbnail (first names ok)")
                        actors = Actors(value, actor_data=ACTOR_DATA)
                        description = make_image_file_description(
                            ep=options['ep'],
                            actors=actors,
                        )
                        pywikibot.output(f"\n{description}\n")
                        keep = pywikibot.input_yn("Do you want to use this default 4SD game thumbnail description?")
                        if not keep:
                            from pywikibot import editor as editarticle
                            editor = editarticle.TextEditor()
                            try:
                                new_description = editor.edit(description)
                                description = new_description
                                pywikibot.output(f"\n<<yellow>>New description:<<default>>\n\n{description}\n")
                            except ImportError:
                                raise
                            except Exception as e:
                                pywikibot.error(e)
                        game_thumb_bot = UploadRobot(
                        generator=gen,
                        url=game_yt.thumbnail_url,
                        description=description,
                        use_filename=options['ep'].game_filename,
                        summary=summary,
                        verify_description=False,
                    )
                        game_thumb_bot.run()

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

        if options.get('cite_cat'):
            bot7 = CategoryBot(generator=gen, **options)
            bot7.treat_page()

        if options.get('airdate_order') and options['ep'].prefix != 'Midst':
            bot8 = AirdateBot(generator=gen, **options)
            bot8.treat_page()
            options['airdate_dict'] = bot8.opt.airdate_dict

        if options['ep'].prefix == '4SD' and options.get('4SD'):
            bot9 = Connect4SDBot(generator=gen, **options)
            bot9.treat_page()
            if not options.get('array_dicts'):
                options['array_dicts'] = bot8.opt.array_dicts
            if not options.get('airdate_dict'):
                options['airdate_dict'] = bot8.opt.airdate_dict

        if options.get('transcript'):
            if options['ep'].prefix in TRANSCRIPT_EXCLUSIONS:
                pywikibot.output(f'\nSkipping transcript page creation for {options["ep"].show.title} episode')
            else:
                bot10 = TranscriptBot(generator=gen, **options)
                bot10.treat_page()
                if bot10.opt.ts:
                    options['ts'] = bot10.opt.ts
                bot11 = TranscriptRedirectBot(generator=gen, **options)
                bot11.treat_page()

        if options.get('ts'):
            dupe_count = len(options['ts'].dupe_lines[DEFAULT_LANGUAGE])
            if dupe_count and '<!-- DUPLICATE' in options['ts'].transcript_dict[DEFAULT_LANGUAGE]:
                dupes = pywikibot.input_yn(f'Process {dupe_count} duplicate captions in transcript now?')
                has_dupes = True
            else:
                dupes = False
                has_dupes = False
                pywikibot.output('No duplicates found in transcript to process.')
            if dupes:
                bot12 = DupeDetectionBot(generator=gen, **options)
                bot12.current_page = pywikibot.Page(bot11.site, f"Transcript:{options['new_ep_name']}")
                bot12.treat_page()
            elif has_dupes:
                command = f"\n<<yellow>>python pwb.py dupes -ep:{options['ep'].code} -yt:{options['yt'][0].yt_id}<<default>>"
                pywikibot.output(f'Skipping ts duplicate processing. You can run this later:{command}')

        if options.get('transcript_list'):
            if options['ep'].prefix in TRANSCRIPT_EXCLUSIONS:
                pywikibot.output(f'\nSkipping transcript list update for {options["ep"].show.title} episode')
            else:
                bot13 = TranscriptListBot(generator=gen, **options)
                bot13.treat_page()

        if options.get('long_short'):
            if options['ep'].prefix in ['4SD', 'Midst']:
                pywikibot.output(f'\nSkipping longest/shortest for {options["ep"].show.title} episode')
            else:
                bot14 = LongShortBot(generator=gen, **options)
                bot14.treat_page()

        if options['ep'].prefix == 'Midst':
            app = options.get('appendix')
            if not app:
                app = pywikibot.input_yn('Create an entry for the Midst appendix?')
            if app:
                pywikibot.output('\nEnter Midst entry values below')
                m_id = pywikibot.input('ID')
                m_date = get_validated_input(arg='date', regex=DATE_REGEX)
                m_prefix = pywikibot.input('Prefix')
                m_quote = pywikibot.input('Quote')
                m_archive = pywikibot.input('Archive')
                m_ghostarchive = pywikibot.input('Ghostarchive')
                m_params = {
                    'm_id': m_id,
                    'm_date': m_date,
                    'm_prefix': m_prefix,
                    'm_quote': m_quote,
                    'm_archive': m_archive,
                    'm_ghostarchive': m_ghostarchive,
                }
                bot15 = MidstAppendixBot(generator=gen, **options, **m_params)
                bot15.treat_page()


if __name__ == '__main__':
    try:
        main()
    except QuitKeyboardInterrupt:
        pywikibot.info('\nUser quit vod bot run.')
