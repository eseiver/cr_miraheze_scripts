import pywikibot
from pywikibot import pagegenerators
from datetime import datetime
from pywikibot.data.api import Request

from ..cr import pyPage
from .character import pyCharacter
from .logger_config import logger 


class BulkWikiProcessor:
    def __init__(self, titles):
        self.site = pywikibot.Site()
        self.pages = {}
        self.titles = titles

    def run(self):

        gen = (pyPage(self.site, title) for title in self.titles)

        # Use PreloadingGenerator to preload the pages efficiently
        gen = pagegenerators.PreloadingGenerator(gen)
        from .episode import pyEpisode

        for page in gen:
            title = page.title()  # so redirects link to the page contents
            if not page.exists():
                logger.info(f'{page.title()} does not exist (redlinked)')
                self.pages[title] = page
                continue
            if page.isRedirectPage():
                page = pyPage(page.getRedirectTarget())
            if '#' in page.title():
                title = page.title().split('#')[0]
            if not page.infobox:
                logger.info(f"{title} missing infobox")
                continue
            if page.infobox.name.matches('Infobox Episode'):
                converted_page = pyEpisode(page)
            elif page.infobox.name.matches(['Infobox Character', 'Infobox Deity', 'Infobox Sentient Item']):
                converted_page = pyCharacter(page)
            else:
                logger.info(f"{title} neither character or episode")
                continue

            self.pages[title] = converted_page


class CharacterManager:
    _instance = None
    character_cache = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
#             cls._instance.character_cache = {}  # Cache for character pages
        return cls._instance

    def get_character_pages(self, character_titles):
        # Check the cache for character pages
        cached_characters = {title: self.character_cache.get(title) for title in character_titles}

        # Determine which characters need to be fetched
        characters_to_fetch = [title for title, page in cached_characters.items() if page is None]

        # Bulk query character pages for characters that are not in the cache
        if characters_to_fetch:
            character_downloader = BulkWikiProcessor(characters_to_fetch)
            character_downloader.run()
            character_pages = character_downloader.pages
            print('character pages!!!!', len(character_pages))

            # Update the cache with the fetched character pages
            for title, page in character_pages.items():
                self.character_cache[title] = page

        logger.info(f'current character cache: {len(self.character_cache)}')
        logger.debug(f'why not here?!, {[x for x in character_titles if x not in self.character_cache]}')
        logger.debug(f'curiouser and curiouser {[x for x in self.character_cache if x not in character_titles]}')

        return {title: self.character_cache.get(title) for title in character_titles}

