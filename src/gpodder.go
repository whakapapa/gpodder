package main


import(
	""
)


//// TODO: old python code


import gettext
import logging
import os
import os.path
import platform
import subprocess
import sys
from optparse import OptionParser

logger = logging.getLogger(__name__)


def main():
    # Paths to important files
    gpodder_script = sys.argv[0]
    gpodder_script = os.path.realpath(gpodder_script)
    gpodder_dir = os.path.join(os.path.dirname(gpodder_script), '..')
    prefix = os.path.abspath(os.path.normpath(gpodder_dir))

    src_dir = os.path.join(prefix, 'src')
    locale_dir = os.path.join(prefix, 'share', 'locale')
    ui_folder = os.path.join(prefix, 'share', 'gpodder', 'ui')
    images_folder = os.path.join(prefix, 'share', 'gpodder', 'images')
    icon_file = os.path.join(prefix, 'share', 'icons', 'hicolor', 'scalable', 'apps', 'gpodder.svg')

    if os.path.exists(os.path.join(src_dir, 'gpodder', '__init__.py')):
        # Run gPodder from local source folder (not installed)
        sys.path.insert(0, src_dir)

    # on Mac OS X, read from the defaults database the locale of the user
    if platform.system() == 'Darwin' and 'LANG' not in os.environ:
        locale_cmd = ('defaults', 'read', 'NSGlobalDomain', 'AppleLocale')
        process = subprocess.Popen(locale_cmd, stdout=subprocess.PIPE)
        output, error_output = process.communicate()
        # the output is a string like 'fr_FR', and we need 'fr_FR.utf-8'
        user_locale = output.decode('utf-8').strip() + '.UTF-8'
        os.environ['LANG'] = user_locale
        print('Setting locale to', user_locale, file=sys.stderr)

    # Set up the path to translation files
    gettext.bindtextdomain('gpodder', locale_dir)

    import gpodder  # isort:skip

    gpodder.prefix = prefix

    # Enable i18n for gPodder translations
    _ = gpodder.gettext

    # Set up paths to folder with GtkBuilder files and gpodder.svg
    gpodder.ui_folders.append(ui_folder)
    gpodder.images_folder = images_folder
    gpodder.icon_file = icon_file

    s_usage = 'usage: %%prog [options]\n\n%s' % (__doc__.strip())
    s_version = '%%prog %s' % (gpodder.__version__)

    parser = OptionParser(usage=s_usage, version=s_version)

    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help=_("print logging output on the console"))

    parser.add_option('-s', '--subscribe', dest='subscribe', metavar='URL',
                      help=_('subscribe to the feed at URL'))

    options, args = parser.parse_args(sys.argv)

    gpodder.ui.gtk = True
    gpodder.ui.python3 = True

    from gpodder import log
    log.setup(options.verbose)

    if have_dbus:
        # Try to find an already-running instance of gPodder
        session_bus = dbus.SessionBus()

        # Obtain a reference to an existing instance; don't call get_object if
        # such an instance doesn't exist as it *will* create a new instance
        if session_bus.name_has_owner(gpodder.dbus_bus_name):
            try:
                remote_object = session_bus.get_object(
                    gpodder.dbus_bus_name,
                    gpodder.dbus_gui_object_path)

                # An instance of GUI is already running
                logger.info('Activating existing instance via D-Bus.')
                remote_object.show_gui_window(
                    dbus_interface=gpodder.dbus_interface)

                if options.subscribe:
                    remote_object.subscribe_to_url(options.subscribe)

                return
            except dbus.exceptions.DBusException as dbus_exception:
                logger.info('Cannot connect to remote object.', exc_info=True)

    if gpodder.ui.gtk:
        from gpodder.gtkui import app
        gpodder.ui_folders.insert(0, os.path.join(ui_folder, 'gtk'))
        app.main(options)
    else:
        logger.error('No GUI selected.')


if __name__ == '__main__':
    main()
