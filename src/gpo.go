
"""
  Usage: gpo [--verbose|-v] [COMMAND] [params...]

  - Subscription management -

    subscribe URL [TITLE]      Subscribe to a new feed at URL (as TITLE)
    search QUERY               Search the gpodder.net directory for QUERY
    toplist                    Show the gpodder.net top-subscribe podcasts

    import FILENAME|URL        Subscribe to all podcasts in an OPML file
    export FILENAME            Export all subscriptions to an OPML file

    rename URL TITLE           Rename feed at URL to TITLE
    unsubscribe URL            Unsubscribe from feed at URL
    enable URL                 Enable feed updates for the feed at URL
    disable URL                Disable feed updates for the feed at URL

    info URL                   Show information about feed at URL
    list                       List all subscribed podcasts
    update [URL]               Check for new episodes (all or only at URL)

  - Episode management -

    download [URL] [GUID]      Download new episodes (all or only from URL) or single GUID
    delete [URL] [GUID]        Delete from feed at URL an episode with given GUID
    pending [URL]              List new episodes (all or only from URL)
    episodes [--guid] [URL]    List episodes with or without GUIDs (all or only from URL)
    partial [--guid]           List partially downloaded episodes with or without GUIDs
    resume [--guid]            Resume partially downloaded episodes or single GUID

  - Episode management -

    sync                       Sync podcasts to device

  - Configuration -

    set [key] [value]          List one (all) keys or set to a new value

  - Other commands -

    youtube URL                Resolve the YouTube URL to a download URL
    youtubefix                 Migrate old YouTube subscriptions to new feeds
    rewrite OLDURL NEWURL      Change the feed URL of [OLDURL] to [NEWURL]

"""


import collections
import contextlib
import functools
import inspect
import logging
import os
import pydoc
import re
import shlex
import sys
import threading

try:
    import readline
except ImportError:
    readline = None

try:
    import termios
    import fcntl
    import struct
except ImportError:
    termios = None
    fcntl = None
    struct = None

# A poor man's argparse/getopt - but it works for our use case :)
verbose = False
for flag in ('-v', '--verbose'):
    if flag in sys.argv:
        sys.argv.remove(flag)
        verbose = True
        break

gpodder_script = sys.argv[0]
gpodder_script = os.path.realpath(gpodder_script)
gpodder_dir = os.path.join(os.path.dirname(gpodder_script), '..')
# TODO: Read parent directory links as well (/bin -> /usr/bin, like on Fedora, see Bug #1618)
# This would allow /usr/share/gpodder/ (not /share/gpodder/) to be found from /bin/gpodder
prefix = os.path.abspath(os.path.normpath(gpodder_dir))

src_dir = os.path.join(prefix, 'src')

if os.path.exists(os.path.join(src_dir, 'gpodder', '__init__.py')):
    # Run gPodder from local source folder (not installed)
    sys.path.insert(0, src_dir)

import gpodder  # isort:skip
from gpodder import common, core, download, feedcore, log, model, my, opml, sync, util, youtube  # isort:skip
from gpodder.config import config_value_to_string  # isort:skip
from gpodder.syncui import gPodderSyncUI  # isort:skip

_ = gpodder.gettext
N_ = gpodder.ngettext

gpodder.images_folder = os.path.join(prefix, 'share', 'gpodder', 'images')
gpodder.prefix = prefix

# This is the command-line UI variant
gpodder.ui.cli = True

have_ansi = sys.stdout.isatty()
interactive_console = sys.stdin.isatty() and sys.stdout.isatty()
is_single_command = False

log.setup(verbose)


def noop(*args, **kwargs):
    pass


def incolor(color_id, s):
    if have_ansi and cli._config.ui.cli.colors:
        return '\033[9%dm%s\033[0m' % (color_id, s)
    return s


# ANSI Colors: red = 1, green = 2, yellow = 3, blue = 4
inred, ingreen, inyellow, inblue = (functools.partial(incolor, x) for x in range(1, 5))


def FirstArgumentIsPodcastURL(function):
    """Decorator for functions that take a podcast URL as first arg"""
    setattr(function, '_first_arg_is_podcast', True)
    return function


def get_terminal_size():
    if None in (termios, fcntl, struct):
        return (80, 24)

    s = struct.pack('HHHH', 0, 0, 0, 0)
    stdout = sys.stdout.fileno()
    x = fcntl.ioctl(stdout, termios.TIOCGWINSZ, s)
    rows, cols, xp, yp = struct.unpack('HHHH', x)
    return rows, cols


class gPodderCli(object):
    COLUMNS = 80
    EXIT_COMMANDS = ('quit', 'exit', 'bye')

    def __init__(self):
        self.core = core.Core()
        self._db = self.core.db
        self._config = self.core.config
        self._model = self.core.model

        self._current_action = ''
        self._commands = dict(
            (name.rstrip('_'), func)
            for name, func in inspect.getmembers(self)
            if inspect.ismethod(func) and not name.startswith('_'))
        self._prefixes, self._expansions = self._build_prefixes_expansions()
        self._prefixes.update({'?': 'help'})
        self._valid_commands = sorted(self._prefixes.values())
        gpodder.user_extensions.on_ui_initialized(
            self.core.model,
            self._extensions_podcast_update_cb,
            self._extensions_episode_download_cb)

    @contextlib.contextmanager
    def _action(self, msg, *args):
        self._start_action(msg, *args)
        try:
            yield
            self._finish_action()
        except Exception as ex:
            logger.warning('Action could not be completed', exc_info=True)
            self._finish_action(False)

    def _run_cleanups(self):
        # Find expired (old) episodes and delete them
        old_episodes = list(common.get_expired_episodes(self._model.get_podcasts(), self._config))
        if old_episodes:
            with self._action('Cleaning up old downloads'):
                for old_episode in old_episodes:
                    old_episode.delete_from_disk()

    def _build_prefixes_expansions(self):
        prefixes = {}
        expansions = collections.defaultdict(list)
        names = sorted(self._commands.keys())
        names.extend(self.EXIT_COMMANDS)

        # Generator for all prefixes of a given string (longest first)
        # e.g. ['gpodder', 'gpodde', 'gpodd', 'gpod', 'gpo', 'gp', 'g']
        def mkprefixes(n):
            return (n[:x] for x in range(len(n), 0, -1))

        # Return True if the given prefix is unique in "names"
        def is_unique(p):
            return len([n for n in names if n.startswith(p)]) == 1

        for name in names:
            is_still_unique = True
            unique_expansion = None
            for prefix in mkprefixes(name):
                if is_unique(prefix):
                    unique_expansion = '[%s]%s' % (prefix, name[len(prefix):])
                    prefixes[prefix] = name
                    continue

                if unique_expansion is not None:
                    expansions[prefix].append(unique_expansion)
                    continue

        return prefixes, expansions

    def _extensions_podcast_update_cb(self, podcast):
        self._info(_('Podcast update requested by extensions.'))
        self._update_podcast(podcast)

    def _extensions_episode_download_cb(self, episode):
        self._info(_('Episode download requested by extensions.'))
        self._download_episode(episode)

    def _start_action(self, msg, *args):
        line = util.convert_bytes(msg % args)
        if len(line) > self.COLUMNS - 7:
            line = line[:self.COLUMNS - 7 - 3] + '...'
        else:
            line = line + (' ' * (self.COLUMNS - 7 - len(line)))
        self._current_action = line
        print(self._current_action, end='')

    def _update_action(self, progress):
        if have_ansi:
            progress = '%3.0f%%' % (progress * 100.,)
            result = '[' + inblue(progress) + ']'
            print('\r' + self._current_action + result, end='')

    def _finish_action(self, success=True, skip=False):
        if skip:
            result = '[' + inyellow('SKIP') + ']'
        elif success:
            result = '[' + ingreen('DONE') + ']'
        else:
            result = '[' + inred('FAIL') + ']'

        if have_ansi:
            print('\r' + self._current_action + result)
        else:
            print(result)
        self._current_action = ''

    def _atexit(self):
        self.core.shutdown()

    # -------------------------------------------------------------------

    def import_(self, url):
        for channel in opml.Importer(url).items:
            self.subscribe(channel['url'], channel.get('title'))

    def export(self, filename):
        podcasts = self._model.get_podcasts()
        opml.Exporter(filename).write(podcasts)

    def get_podcast(self, original_url, create=False, check_only=False):
        """Get a specific podcast by URL

        Returns a podcast object for the URL or None if
        the podcast has not been subscribed to.
        """
        url = util.normalize_feed_url(original_url)
        if url is None:
            self._error(_('Invalid url: %s') % original_url)
            return None

        # Check if it's a YouTube channel, user, or playlist and resolves it to its feed if that's the case
        url = youtube.parse_youtube_url(url)

        # Subscribe to new podcast
        if create:
            auth_tokens = {}
            while True:
                try:
                    return self._model.load_podcast(
                        url, create=True,
                        authentication_tokens=auth_tokens.get(url, None),
                        max_episodes=self._config.max_episodes_per_feed)
                except feedcore.AuthenticationRequired as e:
                    if e.url in auth_tokens:
                        print(inred(_('Wrong username/password')))
                        return None
                    else:
                        print(inyellow(_('Podcast requires authentication')))
                        print(inyellow(_('Please login to %s:') % (url,)))
                        username = input(_('User name:') + ' ')
                        if username:
                            password = input(_('Password:') + ' ')
                            if password:
                                auth_tokens[e.url] = (username, password)
                                url = e.url
                            else:
                                return None
                        else:
                            return None

        # Load existing podcast
        for podcast in self._model.get_podcasts():
            if podcast.url == url:
                return podcast

        if not check_only:
            self._error(_('You are not subscribed to %s.') % url)
        return None

    def subscribe(self, url, title=None):
        existing = self.get_podcast(url, check_only=True)
        if existing is not None:
            self._error(_('Already subscribed to %s.') % existing.url)
            return True

        try:
            podcast = self.get_podcast(url, create=True)
            if podcast is None:
                self._error(_('Cannot subscribe to %s.') % url)
                return True

            if title is not None:
                podcast.rename(title)
            podcast.save()
        except Exception as e:
            logger.warn('Cannot subscribe: %s', e, exc_info=True)
            if hasattr(e, 'strerror'):
                self._error(e.strerror)
            else:
                self._error(str(e))
            return True

        self._db.commit()

        self._info(_('Successfully added %s.' % url))
        return True

    def _print_config(self, search_for):
        for key in self._config.all_keys():
            if search_for is None or search_for.lower() in key.lower():
                value = config_value_to_string(self._config._lookup(key))
                print(key, '=', value)

    def set(self, key=None, value=None):
        if value is None:
            self._print_config(key)
            return

        try:
            current_value = self._config._lookup(key)
            current_type = type(current_value)
        except KeyError:
            self._error(_('This configuration option does not exist.'))
            return

        if current_type == dict:
            self._error(_('Can only set leaf configuration nodes.'))
            return

        self._config.update_field(key, value)
        self.set(key)

    @FirstArgumentIsPodcastURL
    def rename(self, url, title):
        podcast = self.get_podcast(url)

        if podcast is not None:
            old_title = podcast.title
            podcast.rename(title)
            self._db.commit()
            self._info(_('Renamed %(old_title)s to %(new_title)s.') % {
                'old_title': util.convert_bytes(old_title),
                'new_title': util.convert_bytes(title),
            })

        return True

    @FirstArgumentIsPodcastURL
    def unsubscribe(self, url):
        podcast = self.get_podcast(url)

        if podcast is None:
            self._error(_('You are not subscribed to %s.') % url)
        else:
            podcast.delete()
            self._db.commit()
            self._error(_('Unsubscribed from %s.') % url)

        return True

    def is_episode_new(self, episode):
        return (episode.state == gpodder.STATE_NORMAL and episode.is_new)

    def _episodesList(self, podcast, show_guid=False):
        def status_str(episode):
            # is new
            if self.is_episode_new(episode):
                return ' * '
            # is downloaded
            if (episode.state == gpodder.STATE_DOWNLOADED):
                return ' ▉ '
            # is deleted
            if (episode.state == gpodder.STATE_DELETED):
                return ' ░ '

            return '   '

        def guid_str(episode):
            return ((' %s' % episode.guid) if show_guid else '')

        episodes = ('%3d.%s %s %s' % (i + 1, guid_str(e),
                                      status_str(e), e.title)
                    for i, e in enumerate(podcast.get_all_episodes()))
        return episodes

    @FirstArgumentIsPodcastURL
    def info(self, url):
        podcast = self.get_podcast(url)

        if podcast is None:
            self._error(_('You are not subscribed to %s.') % url)
        else:
            def feed_update_status_msg(podcast):
                if podcast.pause_subscription:
                    return "disabled"
                return "enabled"

            title, url, status = podcast.title, podcast.url, \
                feed_update_status_msg(podcast)
            episodes = self._episodesList(podcast)
            episodes = '\n      '.join(episodes)
            self._pager("""
    Title: %(title)s
    URL: %(url)s
    Feed update is %(status)s

    Episodes:
      %(episodes)s
            """ % locals())

        return True

    @FirstArgumentIsPodcastURL
    def episodes(self, *args):
        show_guid = False
        args = list(args)
        # TODO: Start using argparse for things like that
        if '--guid' in args:
            args.remove('--guid')
            show_guid = True

        if len(args) > 1:
            self._error(_('Invalid command.'))
            return
        elif len(args) == 1:
            url = args[0]
            if url.startswith('-'):
                self._error(_('Invalid option: %s.') % (url,))
                return
        else:
            url = None

        output = []
        for podcast in self._model.get_podcasts():
            podcast_printed = False
            if url is None or podcast.url == url:
                episodes = self._episodesList(podcast, show_guid=show_guid)
                episodes = '\n      '.join(episodes)
                output.append("""
    Episodes from %s:
      %s
""" % (podcast.url, episodes))

        self._pager('\n'.join(output))
        return True

    def list(self):
        for podcast in self._model.get_podcasts():
            if not podcast.pause_subscription:
                print('#', ingreen(podcast.title))
            else:
                print('#', inred(podcast.title),
                      '-', _('Updates disabled'))

            print(podcast.url)

        return True

    def _update_podcast(self, podcast):
        with self._action(' %s', podcast.title):
            podcast.update()

    def _pending_message(self, count):
        return N_('%(count)d new episode', '%(count)d new episodes',
                  count) % {'count': count}

    @FirstArgumentIsPodcastURL
    def update(self, url=None):
        count = 0
        print(_('Checking for new episodes'))
        for podcast in self._model.get_podcasts():
            if url is not None and podcast.url != url:
                continue

            if not podcast.pause_subscription:
                self._update_podcast(podcast)
                count += sum(1 for e in podcast.get_all_episodes() if self.is_episode_new(e))
            else:
                self._start_action(_('Skipping %(podcast)s') % {
                    'podcast': podcast.title})
                self._finish_action(skip=True)

        util.delete_empty_folders(gpodder.downloads)
        print(inblue(self._pending_message(count)))
        return True

    @FirstArgumentIsPodcastURL
    def pending(self, url=None):
        count = 0
        for podcast in self._model.get_podcasts():
            podcast_printed = False
            if url is None or podcast.url == url:
                for episode in podcast.get_all_episodes():
                    if self.is_episode_new(episode):
                        if not podcast_printed:
                            print('#', ingreen(podcast.title))
                            podcast_printed = True
                        print(' ', episode.title)
                        count += 1

        util.delete_empty_folders(gpodder.downloads)
        print(inblue(self._pending_message(count)))
        return True

    @FirstArgumentIsPodcastURL
    def partial(self, *args):
        def by_channel(e):
            return e.channel.title

        def guid_str(episode):
            return (('%s ' % episode.guid) if show_guid else '')

        def on_finish(resumable_episodes):
            count = len(resumable_episodes)
            resumable_episodes = sorted(resumable_episodes, key=by_channel)
            last_channel = None
            for e in resumable_episodes:
                if e.channel != last_channel:
                    print('#', ingreen(e.channel.title))
                    last_channel = e.channel
                print('  %s%s' % (guid_str(e), e.title))
            print(inblue(N_('%(count)d partial file',
                   '%(count)d partial files',
                   count) % {'count': count}))

        show_guid = '--guid' in args

        common.find_partial_downloads(self._model.get_podcasts(),
                                      noop,
                                      noop,
                                      on_finish)
        return True

    def _download_episode(self, episode):
        with self._action('Downloading %s', episode.title):
            task = download.DownloadTask(episode, self._config)
            task.add_progress_callback(self._update_action)
            task.status = download.DownloadTask.DOWNLOADING
            task.run()

    def _download_episodes(self, episodes):
        if self._config.downloads.chronological_order:
            # download older episodes first
            episodes = list(model.Model.sort_episodes_by_pubdate(episodes))

        if episodes:
            last_podcast = None
            for episode in episodes:
                if episode.channel != last_podcast:
                    print(inblue(episode.channel.title))
                    last_podcast = episode.channel
                self._download_episode(episode)

            util.delete_empty_folders(gpodder.downloads)
        print(len(episodes), 'episodes downloaded.')
        return True

    @FirstArgumentIsPodcastURL
    def download(self, url=None, guid=None):
        episodes = []
        for podcast in self._model.get_podcasts():
            if url is None or podcast.url == url:
                for episode in podcast.get_all_episodes():
                    if (not guid and self.is_episode_new(episode)) or (guid and episode.guid == guid):
                        episodes.append(episode)
        return self._download_episodes(episodes)

    @FirstArgumentIsPodcastURL
    def resume(self, guid=None):
        def guid_str(episode):
            return (('%s ' % episode.guid) if show_guid else '')

        def on_finish(episodes):
            if guid:
                episodes = [e for e in episodes if e.guid == guid]
            self._download_episodes(episodes)

        common.find_partial_downloads(self._model.get_podcasts(),
                                      noop,
                                      noop,
                                      on_finish)
        return True

    @FirstArgumentIsPodcastURL
    def delete(self, url, guid):
        podcast = self.get_podcast(url)
        episode_to_delete = None

        if podcast is None:
            self._error(_('You are not subscribed to %s.') % url)
        else:
            for episode in podcast.get_all_episodes():
                if (episode.guid == guid):
                    episode_to_delete = episode

            if not episode_to_delete:
                self._error(_('No episode with the specified GUID found.'))
            else:
                if episode_to_delete.state != gpodder.STATE_DELETED:
                    episode_to_delete.delete_from_disk()
                    self._info(_('Deleted episode "%s".') % episode_to_delete.title)
                else:
                    self._error(_('Episode has already been deleted.'))

        return True

    @FirstArgumentIsPodcastURL
    def disable(self, url):
        podcast = self.get_podcast(url)

        if podcast is None:
            self._error(_('You are not subscribed to %s.') % url)
        else:
            if not podcast.pause_subscription:
                podcast.pause_subscription = True
                podcast.save()
            self._db.commit()
            self._error(_('Disabling feed update from %s.') % url)

        return True

    @FirstArgumentIsPodcastURL
    def enable(self, url):
        podcast = self.get_podcast(url)

        if podcast is None:
            self._error(_('You are not subscribed to %s.') % url)
        else:
            if podcast.pause_subscription:
                podcast.pause_subscription = False
                podcast.save()
            self._db.commit()
            self._error(_('Enabling feed update from %s.') % url)

        return True

    def youtube(self, url):
        fmt_ids = youtube.get_fmt_ids(self._config.youtube)
        yurl = youtube.get_real_download_url(url, fmt_ids)
        print(yurl)

        return True

    def youtubefix(self):
        if not self._config.youtube.api_key_v3:
            self._error(_('Please register a YouTube API key and set it using %(command)s.') % {
                'command': 'set youtube.api_key_v3 KEY',
            })
            return False

        reported_anything = False
        for podcast in self._model.get_podcasts():
            url, user = youtube.for_each_feed_pattern(lambda url, channel: (url, channel), podcast.url, (None, None))
            if url is not None and user is not None:
                try:
                    logger.info('Getting channels for YouTube user %s (%s)', user, url)
                    new_urls = youtube.get_channels_for_user(user, self._config.youtube.api_key_v3)
                    logger.debug('YouTube channels retrieved: %r', new_urls)

                    if len(new_urls) != 1:
                        self._info('%s: %s' % (url, _('No unique URL found')))
                        reported_anything = True
                        continue

                    new_url = new_urls[0]
                    if new_url in set(x.url for x in self._model.get_podcasts()):
                        self._info('%s: %s' % (url, _('Already subscribed')))
                        reported_anything = True
                        continue

                    logger.info('New feed location: %s => %s', url, new_url)

                    self._info(_('Changing: %(old_url)s => %(new_url)s') % {'old_url': url, 'new_url': new_url})
                    reported_anything = True
                    podcast.url = new_url
                    podcast.save()
                except Exception as e:
                    logger.error('Exception happened while updating download list.', exc_info=True)
                    self._error(_('Make sure the API key is correct. Error: %(message)s') % {'message': str(e)})
                    return False

            if not reported_anything:
                self._info(_('Nothing to fix'))
            return True

    def search(self, *terms):
        query = ' '.join(terms)
        if not query:
            return

        directory = my.Directory()
        results = directory.search(query)
        self._show_directory_results(results)

    def toplist(self):
        directory = my.Directory()
        results = directory.toplist()
        self._show_directory_results(results, True)

    def _show_directory_results(self, results, multiple=False):
        if not results:
            self._error(_('No podcasts found.'))
            return

        if not interactive_console or is_single_command:
            print('\n'.join(url for title, url in results))
            return

        def show_list():
            self._pager('\n'.join(
                '%3d: %s\n     %s' % (index + 1, title, url if title != url else '')
                for index, (title, url) in enumerate(results)))

        show_list()

        msg = _('Enter index to subscribe, ? for list')
        while True:
            index = input(msg + ': ')

            if not index:
                return

            if index == '?':
                show_list()
                continue

            try:
                index = int(index)
            except ValueError:
                self._error(_('Invalid value.'))
                continue

            if not (1 <= index <= len(results)):
                self._error(_('Invalid value.'))
                continue

            title, url = results[index - 1]
            self._info(_('Adding %s...') % title)
            self.subscribe(url)
            if not multiple:
                break

    @FirstArgumentIsPodcastURL
    def rewrite(self, old_url, new_url):
        podcast = self.get_podcast(old_url)
        if podcast is None:
            self._error(_('You are not subscribed to %s.') % old_url)
        else:
            result = podcast.rewrite_url(new_url)
            if result is None:
                self._error(_('Invalid URL: %s') % new_url)
            else:
                new_url = result
                self._error(_('Changed URL from %(old_url)s to %(new_url)s.') %
                            {'old_url': old_url,
                             'new_url': new_url, })
        return True

    def help(self):
        print(stylize(__doc__), file=sys.stderr, end='')
        return True

    def sync(self):
        def ep_repr(episode):
            return '{} / {}'.format(episode.channel.title, episode.title)

        def msg_title(title, message):
            if title:
                msg = '{}: {}'.format(title, message)
            else:
                msg = '{}'.format(message)
            return msg

        def _notification(message, title=None, important=False, widget=None):
            print(msg_title(message, title))

        def _show_confirmation(message, title=None):
            msg = msg_title(message, title)
            msg = _("%(title)s: %(msg)s ([yes]/no): ") % dict(title=title, msg=message)
            if not interactive_console:
                return True
            line = input(msg)
            return not line or (line.lower() == _('yes'))

        def _delete_episode_list(episodes, confirm=True, skip_locked=True, callback=None):
            if not episodes:
                return False

            if skip_locked:
                episodes = [e for e in episodes if not e.archive]

                if not episodes:
                    title = _('Episodes are locked')
                    message = _(
                        'The selected episodes are locked. Please unlock the '
                        'episodes that you want to delete before trying '
                        'to delete them.')
                    _notification(message, title)
                    return False

            count = len(episodes)
            title = N_('Delete %(count)d episode?', 'Delete %(count)d episodes?',
                       count) % {'count': count}
            message = _('Deleting episodes removes downloaded files.')

            if confirm and not _show_confirmation(message, title):
                return False

            print(_('Please wait while episodes are deleted'))

            def finish_deletion(episode_urls, channel_urls):
                # Episodes have been deleted - persist the database
                self.db.commit()

            episode_urls = set()
            channel_urls = set()

            episodes_status_update = []
            for idx, episode in enumerate(episodes):
                if not episode.archive or not skip_locked:
                    self._start_action(_('Deleting episode: %(episode)s') % {
                            'episode': episode.title})
                    episode.delete_from_disk()
                    self._finish_action(success=True)
                    episode_urls.add(episode.url)
                    channel_urls.add(episode.channel.url)
                    episodes_status_update.append(episode)

            # Notify the web service about the status update + upload
            if self.mygpo_client.can_access_webservice():
                self.mygpo_client.on_delete(episodes_status_update)
                self.mygpo_client.flush()

            if callback is None:
                util.idle_add(finish_deletion, episode_urls, channel_urls)
            else:
                util.idle_add(callback, episode_urls, channel_urls, None)

            return True

        def _episode_selector(parent_window, title=None, instructions=None, episodes=None,
                              selected=None, columns=None, callback=None, _config=None):
            if not interactive_console:
                return callback([e for i, e in enumerate(episodes) if selected[i]])

            def show_list():
                self._pager('\n'.join(
                    '[%s] %3d: %s' % (('X' if selected[index] else ' '), index + 1, ep_repr(e))
                    for index, e in enumerate(episodes)))

            print("{}. {}".format(title, instructions))
            show_list()

            msg = _('Enter episode index to toggle, ? for list, X to select all, space to select none, empty when ready')
            while True:
                index = input(msg + ': ')

                if not index:
                    return callback([e for i, e in enumerate(episodes) if selected[i]])

                if index == '?':
                    show_list()
                    continue
                elif index == 'X':
                    selected = [True, ] * len(episodes)
                    show_list()
                    continue
                elif index == ' ':
                    selected = [False, ] * len(episodes)
                    show_list()
                    continue
                else:
                    try:
                        index = int(index)
                    except ValueError:
                        self._error(_('Invalid value.'))
                        continue

                    if not (1 <= index <= len(episodes)):
                        self._error(_('Invalid value.'))
                        continue

                    e = episodes[index - 1]
                    selected[index - 1] = not selected[index - 1]
                    if selected[index - 1]:
                        self._info(_('Will delete %(episode)s') % dict(episode=ep_repr(e)))
                    else:
                        self._info(_("Won't delete %(episode)s") % dict(episode=ep_repr(e)))

        def _not_applicable(*args, **kwargs):
            pass

        class DownloadStatusModel(object):
            def register_task(self, ask):
                pass

        class DownloadQueueManager(object):
            def queue_task(x, task):
                def progress_updated(progress):
                    self._update_action(progress)
                with self._action(_('Syncing %s'), ep_repr(task.episode)):
                    task.status = sync.SyncTask.DOWNLOADING
                    task.add_progress_callback(progress_updated)
                    task.run()

        done_lock = threading.Lock()
        self.mygpo_client = my.MygPoClient(self._config)
        sync_ui = gPodderSyncUI(self._config,
                                _notification,
                                None,
                                _show_confirmation,
                                _not_applicable,
                                self._model.get_podcasts(),
                                DownloadStatusModel(),
                                DownloadQueueManager(),
                                _not_applicable,
                                self._db.commit,
                                _delete_episode_list,
                                _episode_selector)
        done_lock.acquire()
        sync_ui.on_synchronize_episodes(self._model.get_podcasts(), episodes=None, force_played=True, done_callback=done_lock.release)
        done_lock.acquire()  # block until done

    # -------------------------------------------------------------------

    def _pager(self, output):
        if have_ansi:
            # Need two additional rows for command prompt
            rows_needed = len(output.splitlines()) + 2
            rows, cols = get_terminal_size()
            if rows_needed < rows:
                print(output)
            else:
                pydoc.pager(output)
        else:
            print(output)

    def _shell(self):
        print(os.linesep.join(x.strip() for x in ("""
        gPodder %(__version__)s (%(__date__)s) - %(__url__)s
        %(__copyright__)s
        License: %(__license__)s

        Entering interactive shell. Type 'help' for help.
        Press Ctrl+D (EOF) or type 'quit' to quit.
        """ % gpodder.__dict__).splitlines()))

        cli._run_cleanups()

        if readline is not None:
            readline.parse_and_bind('tab: complete')
            readline.set_completer(self._tab_completion)
            readline.set_completer_delims(' ')

        while True:
            try:
                line = input('gpo> ')
            except EOFError:
                print('')
                break
            except KeyboardInterrupt:
                print('')
                continue

            if self._prefixes.get(line, line) in self.EXIT_COMMANDS:
                break

            try:
                args = shlex.split(line)
            except ValueError as value_error:
                self._error(_('Syntax error: %(error)s') %
                            {'error': value_error})
                continue

            try:
                self._parse(args)
            except KeyboardInterrupt:
                self._error('Keyboard interrupt.')
            except EOFError:
                self._error('EOF.')

        self._atexit()

    def _error(self, *args):
        print(inred(' '.join(args)), file=sys.stderr)

    # Warnings look like error messages for now
    _warn = _error

    def _info(self, *args):
        print(*args)

    def _checkargs(self, func, command_line):
        argspec = inspect.getfullargspec(func)
        assert not argspec.kwonlyargs  # keyword-only arguments are unsupported
        args, varargs, keywords, defaults = argspec.args, argspec.varargs, argspec.varkw, argspec.defaults
        args.pop(0)  # Remove "self" from args
        defaults = defaults or ()
        minarg, maxarg = len(args) - len(defaults), len(args)

        if (len(command_line) < minarg or
                (len(command_line) > maxarg and varargs is None)):
            self._error('Wrong argument count for %s.' % func.__name__)
            return False

        return func(*command_line)

    def _tab_completion_podcast(self, text, count):
        """Tab completion for podcast URLs"""
        urls = [p.url for p in self._model.get_podcasts() if text in p.url]
        if count < len(urls):
            return urls[count]

        return None

    def _tab_completion(self, text, count):
        """Tab completion function for readline"""
        if readline is None:
            return None

        current_line = readline.get_line_buffer()
        if text == current_line:
            for name in self._valid_commands:
                if name.startswith(text):
                    if count == 0:
                        return name
                    else:
                        count -= 1
        else:
            args = current_line.split()
            command = args.pop(0)
            command_function = getattr(self, command, None)
            if not command_function:
                return None
            if getattr(command_function, '_first_arg_is_podcast', False):
                if not args or (len(args) == 1 and not current_line.endswith(' ')):
                    return self._tab_completion_podcast(text, count)

        return None

    def _parse_single(self, command_line):
        try:
            result = self._parse(command_line)
        except KeyboardInterrupt:
            self._error('Keyboard interrupt.')
            result = -1
        self._atexit()
        return result

    def _parse(self, command_line):
        if not command_line:
            return False

        command = command_line.pop(0)

        # Resolve command aliases
        command = self._prefixes.get(command, command)

        if command in self._commands:
            func = self._commands[command]
            if inspect.ismethod(func):
                return self._checkargs(func, command_line)

        if command in self._expansions:
            print(_('Ambiguous command. Did you mean..'))
            for cmd in self._expansions[command]:
                print('   ', inblue(cmd))
        else:
            self._error(_('The requested function is not available.'))

        return False


def stylize(s):
    s = re.sub(r'    .{27}', lambda m: inblue(m.group(0)), s)
    s = re.sub(r'  - .*', lambda m: ingreen(m.group(0)), s)
    return s


def main():
    global logger, cli
    logger = logging.getLogger(__name__)
    cli = gPodderCli()
    msg = model.check_root_folder_path()
    if msg:
        print(msg, file=sys.stderr)
    args = sys.argv[1:]
    if args:
        is_single_command = True
        cli._run_cleanups()
        cli._parse_single(args)
    elif interactive_console:
        cli._shell()
    else:
        print(__doc__, end='')


if __name__ == '__main__':
    main()
