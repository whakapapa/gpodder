#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# gPodder - A media aggregator and podcast client
# Copyright (c) 2005-2018 The gPodder Team
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
#  widgets.py -- Additional widgets for gPodder
#  Thomas Perl <thp@gpodder.org> 2009-03-31
#

import cgi

from gi.repository import Gdk, GObject, Gtk, Pango


class SimpleMessageArea(Gtk.HBox):
    """A simple, yellow message area. Inspired by gedit.

    Original C source code:
    http://svn.gnome.org/viewvc/gedit/trunk/gedit/gedit-message-area.c
    """
    def __init__(self, message, buttons=()):
        Gtk.HBox.__init__(self, spacing=6)
        self.set_border_width(6)
        self.__in_style_updated = False
        self.connect('style-updated', self.__style_updated)
        self.connect('draw', self.__on_draw)

        self.__label = Gtk.Label()
        self.__label.set_alignment(0.0, 0.5)
        self.__label.set_line_wrap(False)
        self.__label.set_ellipsize(Pango.EllipsizeMode.END)
        self.__label.set_markup('<b>%s</b>' % cgi.escape(message))
        self.pack_start(self.__label, True, True, 0)

        hbox = Gtk.HBox()
        for button in buttons:
            hbox.pack_start(button, True, False, 0)
        self.pack_start(hbox, False, False, 0)

    def set_markup(self, markup, line_wrap=True, min_width=3, max_width=100):
        # The longest line should determine the size of the label
        width_chars = max(len(line) for line in markup.splitlines())

        # Enforce upper and lower limits for the width
        width_chars = max(min_width, min(max_width, width_chars))

        self.__label.set_width_chars(width_chars)
        self.__label.set_markup(markup)
        self.__label.set_line_wrap(line_wrap)

    def __style_updated(self, widget):
        if self.__in_style_updated:
            return

        w = Gtk.Window(Gtk.WindowType.POPUP)
        w.set_name('gtk-tooltip')
        w.ensure_style()
        style = w.get_style()

        self.__in_style_set = True
        self.set_style(style)
        self.__label.set_style(style)
        self.__in_style_set = False

        w.destroy()

        self.queue_draw()

    def __on_draw(self, widget, cr):
        style = widget.get_style()
        x, rect = Gdk.cairo_get_clip_rectangle(cr)
        Gtk.paint_flat_box(style, cr, Gtk.StateType.NORMAL,
                Gtk.ShadowType.OUT, widget, "tooltip",
                rect.x, rect.y, rect.width, rect.height)
        return False


class SpinningProgressIndicator(Gtk.Image):
    # Progress indicator loading inspired by glchess from gnome-games-clutter
    def __init__(self, size=32):
        Gtk.Image.__init__(self)

        self._frames = []
        self._frame_id = 0

        # Load the progress indicator
        icon_theme = Gtk.IconTheme.get_default()

        try:
            icon = icon_theme.load_icon('process-working', size, 0)
            width, height = icon.get_width(), icon.get_height()
            if width < size or height < size:
                size = min(width, height)
            for row in range(height // size):
                for column in range(width // size):
                    frame = icon.subpixbuf(column * size, row * size, size, size)
                    self._frames.append(frame)
            # Remove the first frame (the "idle" icon)
            if self._frames:
                self._frames.pop(0)
            self.step_animation()
        except:
            # FIXME: This is not very beautiful :/
            self.set_from_icon_name('system-run', Gtk.IconSize.BUTTON)

    def step_animation(self):
        if len(self._frames) > 1:
            self._frame_id += 1
            if self._frame_id >= len(self._frames):
                self._frame_id = 0
            self.set_from_pixbuf(self._frames[self._frame_id])
