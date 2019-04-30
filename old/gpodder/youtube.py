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
#  gpodder.youtube - YouTube and related magic
#  Justin Forest <justin.forest@gmail.com> 2008-10-13
#

import json
import logging
import re
import urllib
import xml.etree.ElementTree
from html.parser import HTMLParser
from urllib.parse import parse_qs

from gpodder import util

logger = logging.getLogger(__name__)

# http://en.wikipedia.org/wiki/YouTube#Quality_and_codecs
# format id, (preferred ids, path(?), description) # video bitrate, audio bitrate
formats = [
    # WebM VP8 video, Vorbis audio
    # Fallback to an MP4 version of same quality.
    # Try 34 (FLV 360p H.264 AAC) if 18 (MP4 360p) fails.
    # Fallback to 6 or 5 (FLV Sorenson H.263 MP3) if all fails.
    (46, ([46, 37, 45, 22, 44, 35, 43, 18, 6, 34, 5],
          '45/1280x720/99/0/0',
          'WebM 1080p (1920x1080)')),  # N/A,      192 kbps
    (45, ([45, 22, 44, 35, 43, 18, 6, 34, 5],
          '45/1280x720/99/0/0',
          'WebM 720p (1280x720)')),    # 2.0 Mbps, 192 kbps
    (44, ([44, 35, 43, 18, 6, 34, 5],
          '44/854x480/99/0/0',
          'WebM 480p (854x480)')),     # 1.0 Mbps, 128 kbps
    (43, ([43, 18, 6, 34, 5],
          '43/640x360/99/0/0',
          'WebM 360p (640x360)')),     # 0.5 Mbps, 128 kbps

    # MP4 H.264 video, AAC audio
    # Try 35 (FLV 480p H.264 AAC) between 720p and 360p because there's no MP4 480p.
    # Try 34 (FLV 360p H.264 AAC) if 18 (MP4 360p) fails.
    # Fallback to 6 or 5 (FLV Sorenson H.263 MP3) if all fails.
    (38, ([38, 37, 22, 35, 18, 34, 6, 5],
          '38/1920x1080/9/0/115',
          'MP4 4K 3072p (4096x3072)')),  # 5.0 - 3.5 Mbps, 192 kbps
    (37, ([37, 22, 35, 18, 34, 6, 5],
          '37/1920x1080/9/0/115',
          'MP4 HD 1080p (1920x1080)')),  # 4.3 - 3.0 Mbps, 192 kbps
    (22, ([22, 35, 18, 34, 6, 5],
          '22/1280x720/9/0/115',
          'MP4 HD 720p (1280x720)')),    # 2.9 - 2.0 Mbps, 192 kbps
    (18, ([18, 34, 6, 5],
          '18/640x360/9/0/115',
          'MP4 360p (640x360)')),        # 0.5 Mbps,  96 kbps

    # FLV H.264 video, AAC audio
    # Does not check for 360p MP4.
    # Fallback to 6 or 5 (FLV Sorenson H.263 MP3) if all fails.
    (35, ([35, 34, 6, 5],
          '35/854x480/9/0/115',
          'FLV 480p (854x480)')),  # 1 - 0.80 Mbps, 128 kbps
    (34, ([34, 6, 5],
          '34/640x360/9/0/115',
          'FLV 360p (640x360)')),  # 0.50 Mbps, 128 kbps

    # FLV Sorenson H.263 video, MP3 audio
    (6, ([6, 5],
         '5/480x270/7/0/0',
         'FLV 270p (480x270)')),  # 0.80 Mbps,  64 kbps
    (5, ([5],
         '5/320x240/7/0/0',
         'FLV 240p (320x240)')),  # 0.25 Mbps,  64 kbps
]
formats_dict = dict(formats)

V3_API_ENDPOINT = 'https://www.googleapis.com/youtube/v3'
CHANNEL_VIDEOS_XML = 'https://www.youtube.com/feeds/videos.xml'


class YouTubeError(Exception):
    pass


def get_fmt_ids(youtube_config):
    fmt_ids = youtube_config.preferred_fmt_ids
    if not fmt_ids:
        format = formats_dict.get(youtube_config.preferred_fmt_id)
        if format is None:
            fmt_ids = []
        else:
            fmt_ids, path, description = format

    return fmt_ids


def get_real_download_url(url, preferred_fmt_ids=None):
    if not preferred_fmt_ids:
        preferred_fmt_ids, _, _ = formats_dict[22]  # MP4 720p

    vid = get_youtube_id(url)
    if vid is not None:
        page = None
        url = 'http://www.youtube.com/get_video_info?&el=detailpage&video_id=' + vid

        while page is None:
            req = util.http_request(url, method='GET')
            if 'location' in req.msg:
                url = req.msg['location']
            else:
                page = req.read()

        page = page.decode()
        # Try to find the best video format available for this video
        # (http://forum.videohelp.com/topic336882-1800.html#1912972)

        def find_urls(page):
            r4 = re.search('url_encoded_fmt_stream_map=([^&]+)', page)
            if r4 is not None:
                fmt_url_map = urllib.parse.unquote(r4.group(1))
                for fmt_url_encoded in fmt_url_map.split(','):
                    video_info = parse_qs(fmt_url_encoded)
                    yield int(video_info['itag'][0]), video_info['url'][0]
            else:
                error_info = parse_qs(page)
                error_message = util.remove_html_tags(error_info['reason'][0])
                raise YouTubeError('Cannot download video: %s' % error_message)

        fmt_id_url_map = sorted(find_urls(page), reverse=True)

        if not fmt_id_url_map:
            raise YouTubeError('fmt_url_map not found for video ID "%s"' % vid)

        # Default to the highest fmt_id if we don't find a match below
        _, url = fmt_id_url_map[0]

        formats_available = set(fmt_id for fmt_id, url in fmt_id_url_map)
        fmt_id_url_map = dict(fmt_id_url_map)

        for id in preferred_fmt_ids:
            id = int(id)
            if id in formats_available:
                format = formats_dict.get(id)
                if format is not None:
                    _, _, description = format
                else:
                    description = 'Unknown'

                logger.info('Found YouTube format: %s (fmt_id=%d)',
                        description, id)
                url = fmt_id_url_map[id]
                break

    return url


def get_youtube_id(url):
    r = re.compile('http[s]?://(?:[a-z]+\.)?youtube\.com/v/(.*)\.swf', re.IGNORECASE).match(url)
    if r is not None:
        return r.group(1)

    r = re.compile('http[s]?://(?:[a-z]+\.)?youtube\.com/watch\?v=([^&]*)', re.IGNORECASE).match(url)
    if r is not None:
        return r.group(1)

    r = re.compile('http[s]?://(?:[a-z]+\.)?youtube\.com/v/(.*)[?]', re.IGNORECASE).match(url)
    if r is not None:
        return r.group(1)

    return for_each_feed_pattern(lambda url, channel: channel, url, None)


def is_video_link(url):
    return (get_youtube_id(url) is not None)


def is_youtube_guid(guid):
    return guid.startswith('tag:youtube.com,2008:video:')


def for_each_feed_pattern(func, url, fallback_result):
    """
    Try to find the username for all possible YouTube feed/webpage URLs
    Will call func(url, channel) for each match, and if func() returns
    a result other than None, returns this. If no match is found or
    func() returns None, return fallback_result.
    """
    CHANNEL_MATCH_PATTERNS = [
        'http[s]?://(?:[a-z]+\.)?youtube\.com/user/([a-z0-9]+)',
        'http[s]?://(?:[a-z]+\.)?youtube\.com/profile?user=([a-z0-9]+)',
        'http[s]?://(?:[a-z]+\.)?youtube\.com/channel/([-_a-zA-Z0-9]+)',
        'http[s]?://(?:[a-z]+\.)?youtube\.com/rss/user/([a-z0-9]+)/videos\.rss',
        'http[s]?://gdata.youtube.com/feeds/users/([^/]+)/uploads',
        'http[s]?://gdata.youtube.com/feeds/base/users/([^/]+)/uploads',
        'http[s]?://(?:[a-z]+\.)?youtube\.com/feeds/videos.xml\?channel_id=([-_a-zA-Z0-9]+)',
    ]

    for pattern in CHANNEL_MATCH_PATTERNS:
        m = re.match(pattern, url, re.IGNORECASE)
        if m is not None:
            result = func(url, m.group(1))
            if result is not None:
                return result

    return fallback_result


def get_real_channel_url(url):
    def return_user_feed(url, channel):
        result = 'https://gdata.youtube.com/feeds/users/{0}/uploads'.format(channel)
        logger.debug('YouTube link resolved: %s => %s', url, result)
        return result

    return for_each_feed_pattern(return_user_feed, url, url)


def get_cover(url):
    if 'youtube.com' in url:

        class YouTubeHTMLCoverParser(HTMLParser):
            """This custom html parser searches for the youtube channel thumbnail/avatar"""
            def __init__(self):
                super().__init__()
                self.url = ""

            def handle_starttag(self, tag, attributes):
                attribute_dict = {attribute[0]: attribute[1] for attribute in attributes}

                # Look for 900x900px image first.
                if tag == 'link' \
                        and 'rel' in attribute_dict \
                        and attribute_dict['rel'] == 'image_src':
                    self.url = attribute_dict['href']

                # Fallback to image that may only be 100x100px.
                elif tag == 'img' \
                        and 'class' in attribute_dict \
                        and attribute_dict['class'] == "channel-header-profile-image":
                    self.url = attribute_dict['src']

        try:
            raw_xml_data = util.urlopen(url).read().decode('utf-8')
            xml_data = xml.etree.ElementTree.fromstring(raw_xml_data)
            channel_id = xml_data.find("{http://www.youtube.com/xml/schemas/2015}channelId").text
            channel_url = 'https://www.youtube.com/channel/{}'.format(channel_id)
            html_data = util.urlopen(channel_url).read().decode('utf-8')
            parser = YouTubeHTMLCoverParser()
            parser.feed(html_data)
            if parser.url:
                logger.debug('Youtube cover art for {} is: {}'.format(url, parser.url))
                return parser.url

        except Exception:
            logger.warning('Could not retrieve cover art', exc_info=True)


def get_channels_for_user(username, api_key_v3):
    # already a channel ID: return videos.xml.
    # Can't rely on automatic discovery, see #371
    if username.startswith('UC'):
        try:
            url = '{0}?channel_id={1}'.format(CHANNEL_VIDEOS_XML, username)
            stream = util.urlopen(url)
            return [url]
        except urllib.error.HTTPError as e:
            logger.debug("get_channels_for_user(%s) not a channel id (got %i response code)", username, e.code)
        except:
            logger.error("get_channels_for_user(%s) not a channel id (got unexpected exception)", username)

    # try username to channel ID conversion
    stream = util.urlopen('{0}/channels?forUsername={1}&part=id&key={2}'.format(V3_API_ENDPOINT, username, api_key_v3))
    data = json.load(stream)
    return ['{0}?channel_id={1}'.format(CHANNEL_VIDEOS_XML, item['id']) for item in data['items']]


def parse_youtube_url(url):
    """
    Youtube Channel Links are parsed into youtube feed links
    >>> parse_youtube_url("https://www.youtube.com/channel/CHANNEL_ID")
    'https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID'

    Youtube User Links are parsed into youtube feed links
    >>> parse_youtube_url("https://www.youtube.com/user/USERNAME")
    'https://www.youtube.com/feeds/videos.xml?user=USERNAME'

    Youtube Playlist Links are parsed into youtube feed links
    >>> parse_youtube_url("https://www.youtube.com/playlist?list=PLAYLIST_ID")
    'https://www.youtube.com/feeds/videos.xml?playlist_id=PLAYLIST_ID'

    >>> parse_youtube_url(None)
    None

    @param url: the path to the channel, user or playlist
    @return: the feed url if successful or the given url if not
    """
    if url is None:
        return url
    scheme, netloc, path, query, fragment = urllib.parse.urlsplit(url)
    logger.debug("Analyzing URL: {}".format(" ".join([scheme, netloc, path, query, fragment])))

    if 'youtube.com' in netloc and ('/user/' in path or '/channel/' in path or 'list=' in query):
        logger.debug("Valid Youtube URL detected. Parsing...")

        if path.startswith('/user/'):
            user_id = path.split('/')[2]
            query = 'user={user_id}'.format(user_id=user_id)

        if path.startswith('/channel/'):
            channel_id = path.split('/')[2]
            query = 'channel_id={channel_id}'.format(channel_id=channel_id)

        if 'list=' in query:
            playlist_query = [query_value for query_value in query.split("&") if 'list=' in query_value][0]
            playlist_id = playlist_query.strip("list=")
            query = 'playlist_id={playlist_id}'.format(playlist_id=playlist_id)

        path = '/feeds/videos.xml'

        new_url = urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))
        logger.debug("New Youtube URL: {}".format(new_url))
        return new_url
    else:
        logger.debug("Not a valid Youtube URL: {}".format(url))
        return url
