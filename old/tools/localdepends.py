import io
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request

sys.stdout = sys.stderr

src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
tmp_dir = tempfile.mkdtemp()

MODULES = [
    # Module name, Regex-file chooser (1st group = location in "src/")
    ('podcastparser', r'podcastparser-[0-9.]+/(podcastparser.py)'),
    ('mygpoclient', r'mygpoclient-[0-9.]+/(mygpoclient/[^/]*\.py)')
]


def get_tarball_url(modulename):
    url = 'http://pypi.python.org/pypi/' + modulename
    html = urllib.request.urlopen(url).read().decode('utf-8')
    match = re.search(r'(http[s]?://[^>]*%s-([0-9.]*)(?:\.post\d+)?\.tar\.gz)' % modulename, html)
    return match.group(0) if match is not None else None


for module, required_files in MODULES:
    print('Fetching', module, '...', end=' ')
    tarball_url = get_tarball_url(module)
    if tarball_url is None:
        print('Cannot determine download URL for', module, '- aborting!')
        break
    data = urllib.request.urlopen(tarball_url).read()
    print('%d KiB' % (len(data) // 1024))
    print('  downloaded from %s' % tarball_url)
    tar = tarfile.open(fileobj=io.BytesIO(data))
    for name in tar.getnames():
        match = re.match(required_files, name)
        if match is not None:
            target_name = match.group(1)
            target_file = os.path.join(src_dir, target_name)
            if os.path.exists(target_file):
                print('Skipping:', target_file)
                continue

            target_dir = os.path.dirname(target_file)
            if not os.path.isdir(target_dir):
                os.mkdir(target_dir)

            print('Extracting:', target_name)
            tar.extract(name, tmp_dir)
            shutil.move(os.path.join(tmp_dir, name), target_file)

shutil.rmtree(tmp_dir)
