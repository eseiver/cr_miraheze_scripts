# ***Critical Role*** Miraheze scripts
These pywikibot scripts are for maintaining Encyclopedia Exandria at https://criticalrole.miraheze.org. For more information about how these scripts work and setting up Python and/or Pywikibot, please see [Help:VOD script](https://criticalrole.miraheze.org/wiki/Help:VOD_script) on the wiki.

## Requirements
* Python 3.9 or newer
* [Pywikibot](https://github.com/wikimedia/pywikibot/commit/4d6e674bf1385961a27b3ddf9acc16bcb32373b0)

## Installation
Copy this directory inside "pywikibot/core/scripts/userscripts".

Then update your `user-config.py` file in "pywikibot/core/" to include:
```
user_script_paths = ['scripts.userscripts.cr_miraheze_scripts']
```

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

