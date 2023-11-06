import pywikibot

from cr_modules.ep import Decoder
from cr_modules.cr import ActorData


DECODER = Decoder(force_download=True)
ACTOR_DATA = ActorData(force_download=True)
pywikibot.output("Actor and decoder data re-downloaded.")