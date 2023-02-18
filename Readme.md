# ***Critical Role*** Miraheze scripts

These pywikibot scripts are for maintaining Encyclopedia Exandria at <https://criticalrole.miraheze.org>. For more information about how these scripts work and setting up Python and/or Pywikibot, including creating a bot password, please see [Help:VOD script](https://criticalrole.miraheze.org/wiki/Help:VOD_script) on the wiki.

## Requirements

* Python 3.9 or newer
* [Pywikibot](https://github.com/wikimedia/pywikibot/commit/4d6e674bf1385961a27b3ddf9acc16bcb32373b0)
* Git (comes bundled automatically w/MacOS and Linux; download [https://gitforwindows.org/](here) for Windows)

## Installation

### Cloning pywikibot and this repo

Create a folder called `pywikibot` somewhere easy to access on your computer. Open your [command line tool](https://en.wikipedia.org/wiki/Command-line_interface) and navigate to that folder. In there run:

```git clone https://github.com/eseiver/cr_miraheze_scripts```
```git clone https://gerrit.wikimedia.org/r/pywikibot/core.git```

Then run:

```python -c "import os;from pathlib import Path;os.symlink(Path('./cr_miraheze_scripts').resolve(), Path('./core/scripts/userscripts/cr_miraheze_scripts').resolve(), target_is_directory=True)"```

Now whenever you want to get the latest pywikibot or cr_miraheze_scripts updates, you can go into that folder and run `git pull` (first running `git fetch` and `git status` to compare the two states). This process will not overwrite any user files you create in the next step.

### Create user files

Generate the wiki-specific files you need for logging into Miraheze by following the [configuration guide for third-party wikis](https://www.mediawiki.org/wiki/Manual:Pywikibot/Use_on_third-party_wikis); `miraheze_family.py` does not exist by default and must be created. Your login credentials will be stored in `user-config.py` and `user-password.py`.

### Update user-config file

Then update your `user-config.py` file in "pywikibot/core/" to include:

```user_script_paths = ['scripts.userscripts.cr_miraheze_scripts']```

## Usage

To run one of these scripts, navigate to "pywikibot/core/" on the command line and run:
```python pwb SCRIPTNAME```
where SCRIPTNAME is something like `vod.py`.

## Scripts

| Name                    | Description                                                       |
| ------------------------| ----------------------------------------------------------------- |
| [cr.py](cr.py)          | Helper functions & data for Critical Role Wiki. |
| [vod.py](vod.py)        | Update relevant wiki pages when a new VOD is released on YouTube. |
| [podcast.py](podcast.py)| Update ```Module:Ep/PodcastSwitcher/URLs``` when a podcast is released.|
