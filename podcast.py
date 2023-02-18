"""This script is for updating [[Module:Ep/PodcastSwitcher/URLs]] when a new podcast is released.
The URL for the podcast can be directly supplied by the user, or inferred from CR blog posts.
It take two arguments:
-ep:    REQUIRED. The CxNN code of the episode with newly uploaded podcast
-url:   Optional. The URL for the podcast
"""

import re
import time
from collections import namedtuple
from random import randint
from string import ascii_uppercase
import pywikibot
from pywikibot.bot import (
    AutomaticTWSummaryBot,
    ConfigParserBot,
    ExistingPageBot,
    SingleSiteBot,
    BaseBot,
    QuitKeyboardInterrupt,
)
from pywikibot import pagegenerators
import requests
from bs4 import BeautifulSoup
from cr import Ep, PODCAST_SWITCHER, get_validated_input, EP_REGEX

CRITROLE_TAG_URL = 'https://critrole.com/podcasts/page/'
headers = {'User-Agent': 'PWBot 1.0'}

def parse_search_result(soup, result=None):
    '''
    Given a souped search result item for the tag 'podcasts' on critrole.com blog,
    return blog post info as a tuple.
    :param soup: BeautifulSoupified search result page from critrole.com
    '''
    post_title = soup.a.text.strip()
    post_link = soup.a.get('href')
    postinfo = namedtuple('post', ['title', 'link'])
    result = postinfo(title=post_title,
                        link=post_link)

    return result


def get_search_results(url=None,
                       page_counter=1,
                       max_search_pages=1,
                       max_page_counter=None,
                       sleep=5,
                       status_code=200,
                       ):
    ''' Get links to all podcast blog posts on critrole.com.
    Iterate through one of many search result pages at a time, parsed with BeautifulSoup
    Includes an arbitrary hard stop to avoid an infinite loop.
    Avoids duplicate entries with set()
    :param url: structure for podcast tag search results page
    :param page_counter: iterates through each page of search results
    :param max_page_counter: hard stop on finding more search result pages
    :param sleep: number of seconds to wait between server hits
    :param status_code: status code of http request (200, 403, 504, etc)
    '''
    blog_posts_cr = []
    if page_counter is None:
        page_counter = randint(1, 18)
    if max_page_counter is None:
        max_page_counter = page_counter + max_search_pages
    if url is None:
        url = CRITROLE_TAG_URL

    pywikibot.output('Downloading list of blog posts.')

    # iterate through all pages of search results
    while status_code == 200:
        results_page = f'{url}{page_counter}'
        r = requests.get(results_page, headers=headers)
        status_code = r.status_code
        soup = BeautifulSoup(r.text, 'html.parser')
        for result in soup.body.find_all('div', class_="qt-item-content-s qt-card"):
            # only add new fan art galleries to list
            blog_post = parse_search_result(result)
            if blog_post:
                blog_posts_cr.append(blog_post)

        # arbitrarily end at max_page_counter to avoid infinite loop
        page_counter += 1
        if page_counter >= max_page_counter:
            pywikibot.output('Maximum results pages reached.')
            break
        time.sleep(sleep)
    pywikibot.output('Search results complete.')

    # dedupe blog post list
    blog_posts_cr = list(set(blog_posts_cr))

    return blog_posts_cr


class PodcastBot(SingleSiteBot, ExistingPageBot):
    '''Add yt_link as value by updating or creating entry'''
    update_options = {
        'ep': None,  # Ep object
        'url': None, # Blogpost URL, if known
        'text': None, # text of the module page
    }
    def initialize(self):
        self.current_page = pywikibot.Page(self.site, PODCAST_SWITCHER)
        self.opt.text = self.current_page.text

    def check_podcast_entry(self):
        self.initialize()
        ep = self.opt.ep
        text = self.opt.text
        existing_url = re.search(fr'\["{ep.code}"\]\s*=\s*"(?P<existing_url>.*?)",',
                                 text).groupdict().get('existing_url')
        return existing_url


    def treat_page(self):
        text = self.opt.text
        ep = self.opt.ep
        url = self.opt.url
        prev_ep = ep.get_previous_episode()

        # if it already exists as an entry, substitute in url
        if ep.code in text:
            text = re.sub(fr'\["{ep.code}"\]\s*=.*', fr'["{ep.code}"] = "{url}",', text)

        # if previous episode is already there, append after it
        elif prev_ep.code in text:
            prev_entry = next(x for x in text.splitlines()
                if any([y in x for y in prev_ep.generate_equivalent_codes()]))
            new_entry = f'    ["{ep.code}"]  = "{url}",'
            text = text.replace(prev_entry,
                                '\n'.join([prev_entry, new_entry])
                                )
        # otherwise, append episode to the end of the list
        else:
            text = text.replace('}',
                                f'    ["{ep.code}"]  = "{url}",' + '\n}')

        self.put_current(text, summary=f"Adding podcast link for {ep.code} (via pywikibot)")


def main(*args: str) -> None:
    ep = None
    blogpost_title = None
    url = None
    posts = None

    local_args = pywikibot.handle_args(args)
    gen_factory = pagegenerators.GeneratorFactory()

    # Process pagegenerators arguments
    local_args = gen_factory.handle_args(local_args)
    options = {}
    for option in local_args:
        arg, _, value = option.partition(':')
        arg = arg[1:]
        if arg == 'ep':
            options['ep'] = Ep(value)
        else:
            options[arg] = value

    if not options.get('ep'):
        value = get_validated_input(arg='ep', regex=EP_REGEX)
        options['ep'] = Ep(value)

    gen = gen_factory.getCombinedGenerator(preload=True)

    bot = PodcastBot(generator=gen, **options)
    existing_url = bot.check_podcast_entry()
    overwrite = True
    if existing_url:
        pywikibot.output(f"Episode already has a podcast url:\n{existing_url}")
        overwrite = pywikibot.input_yn("Overwrite?")

    if not url and not overwrite:
        pywikibot.output('\nNo changes made. Podcast bot closed.')
        return None

    posts = get_search_results()

    # if campaign episode, find Ep.ce_code in blogpost title
    if posts and options['ep'].ce_code and not url:
        post = next((post for post in posts if options['ep'].ce_code in post.title), None)
        if post:
            correct = pywikibot.input_yn(f'\n<<yellow>>Does this title match?<<default>>\n"{post.title}"')
            if correct:
                bot.opt['url'] = post.link

    # if not campaign, give multiple choice between posts
    if posts and not bot.opt.get('url'):
        choices = [(ascii_uppercase[i], x.title) for i, x in enumerate(posts)]
        choice = pywikibot.input_choice(
            '\n<<yellow>>Does one of these titles match? Enter letter:<<default>>',
            choices,
            return_shortcut=False)
        bot.opt['url'] = posts[choice].link

    if bot.opt.get('url'):
        bot.treat_page()
    else:
        pywikibot.output('\nNo blogposts found.')


if __name__ == '__main__':
    try:
        main()
    except QuitKeyboardInterrupt:
            pywikibot.info('\nUser quit podcast bot run.')