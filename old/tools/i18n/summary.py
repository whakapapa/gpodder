import glob
import math
import os
import re
import subprocess
import sys

width = 40


class Language(object):
    def __init__(self, language, translated, fuzzy, untranslated):
        self.language = language
        self.translated = int(translated)
        self.fuzzy = int(fuzzy)
        self.untranslated = int(untranslated)


COUNTS_RE = '((\d+) translated message[s]?)?(, (\d+) fuzzy translation[s]?)?(, (\d+) untranslated message[s]?)?\.'

po_folder = os.path.join(os.path.dirname(__file__), '..', '..', 'po')
for filename in glob.glob(os.path.join(po_folder, '*.po')):
    language, _ = os.path.splitext(os.path.basename(filename))
    msgfmt = subprocess.Popen(['msgfmt', '--statistics', filename],
                              stderr=subprocess.PIPE)
    _, stderr = msgfmt.communicate()

    match = re.match(COUNTS_RE, stderr).groups()
    languages.append(Language(language, match[1] or '0', match[3] or '0', match[5] or '0'))

print('')


print("""
  Total translations: %s
""" % (len(languages)))
