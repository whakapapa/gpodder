import sys

from gi.repository import Gtk

from gpodder.gtkui.draw import draw_cake_pixbuf

sys.path.insert(0, 'src')


def gen(percentage):
    pixbuf = draw_cake_pixbuf(percentage)
    return Gtk.Image.new_from_pixbuf(pixbuf)


w = Gtk.Window()
w.connect('destroy', Gtk.main_quit)
v = Gtk.VBox()
w.add(v)
for y in range(1):
    h = Gtk.HBox()
    h.set_homogeneous(True)
    v.add(h)
    PARTS = 20
    for x in range(PARTS + 1):
        h.add(gen(x / PARTS))
w.set_default_size(400, 100)
w.show_all()
Gtk.main()
