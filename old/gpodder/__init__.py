# This metadata block gets parsed by setup - use single quotes only
__tagline__ = 'Media aggregator and podcast client'
__author__ = 'Thomas Perl <thp@gpodder.org>'
__version__ = '3.10.8'
__date__ = '2019-04-04'
__copyright__ = '© 2005-2019 The gPodder Team'
__license__ = 'GNU General Public License, version 3 or later'
__url__ = 'http://gpodder.org/'

__version_info__ = tuple(int(x) for x in __version__.split('.'))

import os
import sys
import platform
import gettext
import locale

from gpodder.build_info import BUILD_TYPE

# Check if real hard dependencies are available
try:
    import podcastparser
except ImportError:
    print("""
  Error: Module "podcastparser" (python-podcastparser) not found.
         The podcastparser module can be downloaded from
         http://gpodder.org/podcastparser/

  From a source checkout, you can download local copies of all
  CLI dependencies for debugging (will be placed into "src/"):

      python3 tools/localdepends.py
""")
    sys.exit(1)
del podcastparser

try:
    import mygpoclient
except ImportError:
    print("""
  Error: Module "mygpoclient" (python-mygpoclient) not found.
         The mygpoclient module can be downloaded from
         http://gpodder.org/mygpoclient/

  From a source checkout, you can download local copies of all
  CLI dependencies for debugging (will be placed into "src/"):

      python3 tools/localdepends.py
""")
    sys.exit(1)
del mygpoclient

try:
    import sqlite3
except ImportError:
    print("""
  Error: Module "sqlite3" not found.
         Build Python with SQLite 3 support or get it from
         http://code.google.com/p/pysqlite/
""")
    sys.exit(1)
del sqlite3


# The User-Agent string for downloads
user_agent = 'gPodder/%s (+%s) %s/%s' % (__version__, __url__, platform.system(), platform.release())


# Are we running in GUI or console mode?
class UI(object):
    def __init__(self):
        self.gtk = False
        self.cli = False


ui = UI()

# D-Bus specific interface names
dbus_bus_name = 'org.gpodder'
dbus_gui_object_path = '/gui'
dbus_podcasts_object_path = '/podcasts'
dbus_interface = 'org.gpodder.interface'
dbus_podcasts = 'org.gpodder.podcasts'
dbus_session_bus = None

# i18n setup (will result in "gettext" to be available)
# Use   _ = gpodder.gettext   in modules to enable string translations
textdomain = 'gpodder'
locale_dir = gettext.bindtextdomain(textdomain)

t = gettext.translation(textdomain, locale_dir, fallback=True)

gettext = t.gettext
ngettext = t.ngettext

del t

# Set up textdomain for Gtk.Builder (this accesses the C library functions)
if hasattr(locale, 'bindtextdomain'):
    locale.bindtextdomain(textdomain, locale_dir)

del locale_dir

# Set up socket timeouts to fix bug 174
SOCKET_TIMEOUT = 60
import socket
socket.setdefaulttimeout(SOCKET_TIMEOUT)
del socket
del SOCKET_TIMEOUT

# Variables reserved for GUI-specific use (will be set accordingly)
ui_folders = []
icon_file = None
images_folder = None
user_extensions = None

# Episode states used in the database
STATE_NORMAL, STATE_DOWNLOADED, STATE_DELETED = list(range(3))

# Paths (gPodder's home folder, config, db, download and data prefix)
home = None
config_file = None
database_file = None
downloads = None
prefix = None

ENV_HOME, ENV_DOWNLOADS = 'GPODDER_HOME', 'GPODDER_DOWNLOAD_DIR'


# Function to set a new gPodder home folder
def set_home(new_home):
    global home, config_file, database_file, downloads
    home = os.path.abspath(new_home)

    config_file = os.path.join(home, 'Settings.json')
    database_file = os.path.join(home, 'Database')
    if ENV_DOWNLOADS not in os.environ:
        downloads = os.path.join(home, 'Downloads')


def fixup_home(old_home):
    new_home = os.path.expanduser(os.path.join('~', 'Library',
        'Application Support', 'gPodder'))

    if not os.path.exists(old_home) or os.path.exists(new_home):
        return new_home

    return old_home


# Default locations for configuration and data files
default_home = os.path.expanduser(os.path.join('~', 'gPodder'))
default_home = fixup_home(default_home)
set_home(os.environ.get(ENV_HOME, default_home))

if home != default_home:
    print('Storing data in', home, '(GPODDER_HOME is set)', file=sys.stderr)

if ENV_DOWNLOADS in os.environ:
    # Allow to relocate the downloads folder (pull request 4, bug 466)
    downloads = os.environ[ENV_DOWNLOADS]
    print('Storing downloads in %s (%s is set)' % (downloads,
            ENV_DOWNLOADS), file=sys.stderr)

# Plugins to load by default
DEFAULT_PLUGINS = [
    'gpodder.plugins.soundcloud',
]


def load_plugins():
    """Load (non-essential) plugin modules

    This loads a default set of plugins, but you can use
    the environment variable "GPODDER_PLUGINS" to modify
    the list of plugins."""
    PLUGINS = os.environ.get('GPODDER_PLUGINS', None)
    if PLUGINS is None:
        PLUGINS = DEFAULT_PLUGINS
    else:
        PLUGINS = PLUGINS.split()
    for plugin in PLUGINS:
        try:
            __import__(plugin)
        except Exception as e:
            print('Cannot load plugin: %s (%s)' % (plugin, e), file=sys.stderr)