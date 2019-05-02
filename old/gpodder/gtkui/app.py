
import cgi
import logging
import os
import sys

import dbus
import dbus.service

import gpodder
from gpodder import core, util
from gpodder.model import check_root_folder_path

from .config import UIConfig
from .desktop.preferences import gPodderPreferences
from .main import gPodder
from .model import Model

import gi  # isort:skip
gi.require_version('Gtk', '3.0')  # isort:skip
from gi.repository import GdkPixbuf, Gio, GObject, Gtk  # isort:skip


logger = logging.getLogger(__name__)

_ = gpodder.gettext
N_ = gpodder.ngettext


class gPodderApplication(Gtk.Application):

    def __init__(self, options):
        Gtk.Application.__init__(self, application_id='org.gpodder.gpodder',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None
        self.options = options
        self.connect('window-removed', self.on_window_removed)

    def create_actions(self):
        action = Gio.SimpleAction.new('about', None)
        action.connect('activate', self.on_about)
        self.add_action(action)

        action = Gio.SimpleAction.new('quit', None)
        action.connect('activate', self.on_quit)
        self.add_action(action)

        action = Gio.SimpleAction.new('help', None)
        action.connect('activate', self.on_help_activate)
        self.add_action(action)

        action = Gio.SimpleAction.new('preferences', None)
        action.connect('activate', self.on_itemPreferences_activate)
        self.add_action(action)

        action = Gio.SimpleAction.new('gotoMygpo', None)
        action.connect('activate', self.on_goto_mygpo)
        self.add_action(action)

        action = Gio.SimpleAction.new('checkForUpdates', None)
        action.connect('activate', self.on_check_for_updates_activate)
        self.add_action(action)

    def do_startup(self):
        Gtk.Application.do_startup(self)

        self.create_actions()

        builder = Gtk.Builder()
        builder.set_translation_domain(gpodder.textdomain)

        for ui_folder in gpodder.ui_folders:
            filename = os.path.join(ui_folder, 'gtk/menus.ui')
            if os.path.exists(filename):
                builder.add_from_file(filename)
                break

        menubar = builder.get_object('menubar')
        if menubar is None:
            logger.error('Cannot find gtk/menus.ui in %r, exiting' % gpodder.ui_folders)
            sys.exit(1)

        self.menu_view_columns = builder.get_object('menuViewColumns')
        self.set_menubar(menubar)

        self.set_app_menu(builder.get_object('app-menu'))

        Gtk.Window.set_default_icon_name('gpodder')

        try:
            dbus_main_loop = DBusGMainLoop(set_as_default=True)
            gpodder.dbus_session_bus = dbus.SessionBus(dbus_main_loop)

            self.bus_name = dbus.service.BusName(gpodder.dbus_bus_name, bus=gpodder.dbus_session_bus)
        except dbus.exceptions.DBusException as dbe:
            logger.warn('Cannot get "on the bus".', exc_info=True)
            dlg = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL, Gtk.MessageType.ERROR,
                   Gtk.ButtonsType.CLOSE, _('Cannot start gPodder'))
            dlg.format_secondary_markup(_('D-Bus error: %s') % (str(dbe),))
            dlg.set_title('gPodder')
            dlg.run()
            dlg.destroy()
            sys.exit(0)
        util.idle_add(self.check_root_folder_path_gui)

    def do_activate(self):
        # We only allow a single window and raise any existing ones
        if not self.window:
            # Windows are associated with the application
            # when the last one is closed the application shuts down
            self.window = gPodder(self, self.bus_name, core.Core(UIConfig, model_class=Model), self.options)

        self.window.gPodder.present()

    def on_about(self, action, param):
        dlg = Gtk.Dialog(_('About gPodder'), self.window.gPodder,
                Gtk.DialogFlags.MODAL)
        dlg.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.OK).show()
        dlg.set_resizable(False)

        bg = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pb = GdkPixbuf.Pixbuf.new_from_file_at_size(gpodder.icon_file, 160, 160)
        bg.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label()
        label.set_alignment(0, 0.5)
        label.set_markup('\n'.join(x.strip() for x in """
        <b>gPodder {version} ({date})</b>

        {copyright}
        License: {license}

        <a href="{url}">{tr_website}</a> · <a href="{bugs_url}">{tr_bugtracker}</a>
        """.format(version=gpodder.__version__,
                   date=gpodder.__date__,
                   copyright=gpodder.__copyright__,
                   license=gpodder.__license__,
                   bugs_url='https://github.com/gpodder/gpodder/issues',
                   url=cgi.escape(gpodder.__url__),
                   tr_website=_('Website'),
                   tr_bugtracker=_('Bug Tracker')).strip().split('\n')))

        vb.pack_start(label, False, False, 0)
        bg.pack_start(vb, False, False, 0)
        bg.pack_start(Gtk.Label(), False, False, 0)

        dlg.vbox.pack_start(bg, False, False, 0)
        dlg.connect('response', lambda dlg, response: dlg.destroy())

        dlg.vbox.show_all()

        dlg.run()

    def on_quit(self, *args):
        self.window.on_gPodder_delete_event()

    def on_window_removed(self, *args):
        self.quit()

    def on_help_activate(self, action, param):
        util.open_website('https://gpodder.github.io/docs/')

    def on_itemPreferences_activate(self, action, param=None):
        gPodderPreferences(self.window.gPodder,
                _config=self.window.config,
                user_apps_reader=self.window.user_apps_reader,
                parent_window=self.window.main_window,
                mygpo_client=self.window.mygpo_client,
                on_send_full_subscriptions=self.window.on_send_full_subscriptions,
                on_itemExportChannels_activate=self.window.on_itemExportChannels_activate,
                on_extension_enabled=self.on_extension_enabled,
                on_extension_disabled=self.on_extension_disabled)

    def on_goto_mygpo(self, action, param):
        self.window.mygpo_client.open_website()

    def on_check_for_updates_activate(self, action, param):
        self.window.check_for_updates(silent=False)

    def on_extension_enabled(self, extension):
        self.window.on_extension_enabled(extension)

    def on_extension_disabled(self, extension):
        self.window.on_extension_disabled(extension)

    @staticmethod
    def check_root_folder_path_gui():
        msg = check_root_folder_path()
        if msg:
            dlg = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL, Gtk.MessageType.WARNING,
                Gtk.ButtonsType.CLOSE, msg)
            dlg.set_title(_('Path to gPodder home is too long'))
            dlg.run()
            dlg.destroy()


def main(options=None):
    GObject.set_application_name('gPodder')

    gp = gPodderApplication(options)
    gp.run()
    sys.exit(0)
