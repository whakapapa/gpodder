# -*- coding: utf-8 -*-
#
# gPodder - A media aggregator and podcast client
# Copyright (C) 2005-2007 Thomas Perl <thp at perli.net>
#
# gPodder is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# gPodder is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

#
#  libgpodder.py -- gpodder configuration
#  thomas perl <thp@perli.net>   20051030
#
#

import gtk
import gtk.gdk
import gobject
import thread
import threading
import urllib
import shutil

from gpodder import util
from gpodder import opml
from gpodder import config

import os
import os.path
import glob
import types
import subprocess

from liblogger import log

import shlex

# my gpodderlib variable
g_podder_lib = None

# some awkward kind of "singleton" ;)
def gPodderLib():
    global g_podder_lib
    if g_podder_lib == None:
        g_podder_lib = gPodderLibClass()
    return g_podder_lib

class gPodderLibClass( object):
    def __init__( self):
        gpodder_dir = os.path.expanduser( '~/.config/gpodder/')
        util.make_directory( gpodder_dir)

        self.feed_cache_file = os.path.join( gpodder_dir, 'feedcache.db')
        self.channel_settings_file = os.path.join( gpodder_dir, 'channelsettings.db')
        self.channel_opml_file = os.path.join( gpodder_dir, 'channels.opml')

        self.config = config.Config( os.path.join( gpodder_dir, 'gpodder.conf'))

        self.__download_history = HistoryStore( os.path.join( gpodder_dir, 'download-history.txt'))
        self.__playback_history = HistoryStore( os.path.join( gpodder_dir, 'playback-history.txt'))
        self.__locked_history = HistoryStore( os.path.join( gpodder_dir, 'lock-history.txt'))
        
    def get_device_name( self):
        if self.config.device_type == 'ipod':
            return _('iPod')
        elif self.config.device_type == 'filesystem':
            return _('MP3 player')
        else:
            log( 'Warning: Called get_device_name() when no device was selected.', sender = self)
            return '(unknown device)'

    def format_filesize( self, bytesize):
        return util.format_filesize( bytesize, self.config.use_si_units)

    def clean_up_downloads( self, delete_partial = False):
        # Clean up temporary files left behind by old gPodder versions
        if delete_partial:
            temporary_files = glob.glob( '%s/*/.tmp-*' % ( self.downloaddir, ))
            for tempfile in temporary_files:
                util.delete_file( tempfile)

        # Clean up empty download folders
        download_dirs = glob.glob( '%s/*' % ( self.downloaddir, ))
        for ddir in download_dirs:
            if os.path.isdir( ddir):
                globr = glob.glob( '%s/*' % ( ddir, ))
                if not globr and ddir != self.config.bittorrent_dir:
                    log( 'Stale download directory found: %s', os.path.basename( ddir))
                    try:
                        os.rmdir( ddir)
                        log( 'Successfully removed %s.', ddir)
                    except:
                        log( 'Could not remove %s.', ddir)

    def get_download_dir( self):
        util.make_directory( self.config.download_dir)
        return self.config.download_dir

    def set_download_dir( self, new_downloaddir):
        if self.config.download_dir != new_downloaddir:
            log( 'Moving downloads from %s to %s', self.config.download_dir, new_downloaddir)
            try:
                # Fix error when moving over disk boundaries
                if os.path.isdir( new_downloaddir) and not os.listdir( new_downloaddir):
                    os.rmdir( new_downloaddir)

                shutil.move( self.config.download_dir, new_downloaddir)
            except:
                log( 'Error while moving %s to %s.', self.config.download_dir, new_downloaddir)
                return

        self.config.download_dir = new_downloaddir

    downloaddir = property(fget=get_download_dir,fset=set_download_dir)

    def history_mark_downloaded( self, url, add_item = True):
        if add_item:
            self.__download_history.add_item( url)
        else:
            self.__download_history.del_item( url)

    def history_mark_played( self, url, add_item = True):
        if add_item:
            self.__playback_history.add_item( url)
        else:
            self.__playback_history.del_item( url)

    def history_mark_locked( self, url, add_item = True):
        if add_item:
            self.__locked_history.add_item( url)
        else:
            self.__locked_history.del_item( url)

    def history_is_downloaded( self, url):
        return (url in self.__download_history)

    def history_is_played( self, url):
        return (url in self.__playback_history)

    def history_is_locked( self, url):
        return (url in self.__locked_history)

    def playback_episode( self, channel, episode):
        self.history_mark_played( episode.url)
        filename = episode.local_filename()

        command_line = shlex.split( util.format_desktop_command( self.config.player, filename).encode('utf-8'))
        log( 'Command line: [ %s ]', ', '.join( [ '"%s"' % p for p in command_line ]), sender = self)
        try:
            subprocess.Popen( command_line)
        except:
            return ( False, command_line[0] )
        return ( True, command_line[0] )

    def open_folder( self, folder):
        try:
            subprocess.Popen( [ 'xdg-open', folder ])
            # FIXME: Win32-specific "open" code needed here
            # as fallback when xdg-open not available
        except:
            log( 'Cannot open folder: "%s"', folder, sender = self)

    def image_download_thread( self, url, callback_pixbuf = None, callback_status = None, callback_finished = None, cover_file = None):
        if callback_status != None:
            gobject.idle_add( callback_status, _('Downloading channel cover...'))
        pixbuf = gtk.gdk.PixbufLoader()
        
        if cover_file == None:
            log( 'Downloading %s', url)
            pixbuf.write( urllib.urlopen(url).read())
        
        if cover_file != None and not os.path.exists( cover_file):
            log( 'Downloading cover to %s', cover_file)
            cachefile = open( cover_file, "w")
            cachefile.write( urllib.urlopen(url).read())
            cachefile.close()
        
        if cover_file != None:
            log( 'Reading cover from %s', cover_file)
            pixbuf.write( open( cover_file, "r").read())
        
        try:
            pixbuf.close()
        except:
            # data error, delete temp file
            util.delete_file( cover_file)
        
        MAX_SIZE = 400
        if callback_pixbuf != None:
            pb = pixbuf.get_pixbuf()
            if pb:
                if pb.get_width() > MAX_SIZE:
                    factor = MAX_SIZE*1.0/pb.get_width()
                    pb = pb.scale_simple( int(pb.get_width()*factor), int(pb.get_height()*factor), gtk.gdk.INTERP_BILINEAR)
                if pb.get_height() > MAX_SIZE:
                    factor = MAX_SIZE*1.0/pb.get_height()
                    pb = pb.scale_simple( int(pb.get_width()*factor), int(pb.get_height()*factor), gtk.gdk.INTERP_BILINEAR)
                gobject.idle_add( callback_pixbuf, pb)
        if callback_status != None:
            gobject.idle_add( callback_status, '')
        if callback_finished != None:
            gobject.idle_add( callback_finished)

    def get_image_from_url( self, url, callback_pixbuf = None, callback_status = None, callback_finished = None, cover_file = None):
        if not url and not os.path.exists( cover_file):
            return

        args = ( url, callback_pixbuf, callback_status, callback_finished, cover_file )
        thread = threading.Thread( target = self.image_download_thread, args = args)
        thread.start()

    def invoke_torrent( self, url, torrent_filename, target_filename):
        self.history_mark_played( url)

        if self.config.use_gnome_bittorrent:
            if util.find_command( 'gnome-btdownload') == None:
                log( 'Cannot find "gnome-btdownload". Please install gnome-bittorrent.', sender = self)
                return False

            command = 'gnome-btdownload "%s" --saveas "%s"' % ( torrent_filename, os.path.join( self.config.bittorrent_dir, target_filename))
            log( command, sender = self)
            os.system( '%s &' % command)
            return True
        else:
            # Simply copy the .torrent with a suitable name
            try:
                target_filename = os.path.join( self.config.bittorrent_dir, os.path.splitext( target_filename)[0] + '.torrent')
                shutil.copyfile( torrent_filename, target_filename)
                return True
            except:
                log( 'Torrent copy failed: %s => %s.', torrent_filename, target_filename)

        return False


class HistoryStore( types.ListType):
    def __init__( self, filename):
        self.filename = filename
        try:
            self.read_from_file()
        except:
            log( 'Creating new history list.', sender = self)

    def read_from_file( self):
        for line in open( self.filename, 'r'):
            self.append( line.strip())

    def save_to_file( self):
        if len( self):
            fp = open( self.filename, 'w')
            for url in self:
                fp.write( url + "\n")
            fp.close()
            log( 'Wrote %d history entries.', len( self), sender = self)

    def add_item( self, data, autosave = True):
        affected = 0
        if data and type( data) is types.ListType:
            # Support passing a list of urls to this function
            for url in data:
                affected = affected + self.add_item( url, autosave = False)
        else:
            if data not in self:
                log( 'Adding: %s', data, sender = self)
                self.append( data)
                affected = affected + 1

        if affected and autosave:
            self.save_to_file()

        return affected

    def del_item( self, data, autosave = True):
        affected = 0
        if data and type( data) is types.ListType:
            # Support passing a list of urls to this function
            for url in data:
                affected = affected + self.del_item( url, autosave = False)
        else:
            if data in self:
                log( 'Removing: %s', data, sender = self)
                self.remove( data)
                affected = affected + 1

        if affected and autosave:
            self.save_to_file()

        return affected


