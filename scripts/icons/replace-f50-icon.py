#!/usr/bin/env python3
"""Replace /f50-settings.png inside the installed PlayPort receiver jar.

Usage (on the box, as root, with dashplay stopped and the jar backed up):
    python3 replace-f50-icon.py [JAR] [PNG]

Without JAR the script picks the one jar under the install's lib directory that
carries f50-settings.png, so a renamed server jar keeps working.
Defaults:
    JAR=<the jar under /opt/dashplay/playport/server/build/install/server/lib>
    PNG=/tmp/f50-settings.png

The icon must be a 180x180 PNG: the receiver advertises that size to the car
whatever bytes it actually loads. A signed jar is refused rather than rewritten,
because that would break the signature the JVM checks at load time.
"""
import argparse
import os
import stat as stat_module
import struct
import sys
import zipfile
from pathlib import Path

RESOURCE = 'f50-settings.png'
LIB = Path('/opt/dashplay/playport/server/build/install/server/lib')
DEFAULT_PNG = Path('/tmp/f50-settings.png')
SIGNATURE_SUFFIXES = ('.SF', '.RSA', '.DSA', '.EC')


def fail(message):
    raise SystemExit(f'error: {message}')


def read_icon(path):
    """The icon's bytes, after checking the receiver can advertise it as 180x180."""
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        fail(f'{path} is not a PNG')
    if data[12:16] != b'IHDR':
        fail(f'{path} has no IHDR chunk')
    width, height = struct.unpack('>II', data[16:24])
    if (width, height) != (180, 180):
        fail(f'{path} is {width}x{height}; the receiver advertises 180x180')
    return data


def resource_jar():
    """The single jar under the install's lib directory that ships the icon."""
    if not LIB.is_dir():
        fail(f'{LIB} does not exist; pass the receiver jar explicitly')
    matches = []
    for candidate in sorted(LIB.glob('*.jar')):
        try:
            with zipfile.ZipFile(candidate) as jar:
                if RESOURCE in jar.namelist():
                    matches.append(candidate)
        except zipfile.BadZipFile:
            continue
    if not matches:
        fail(f'no jar under {LIB} contains {RESOURCE}')
    if len(matches) > 1:
        fail('more than one jar contains the icon (' + ', '.join(str(m) for m in matches)
             + '); pass the wanted one explicitly')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=f'Replace {RESOURCE} inside the receiver jar.')
    parser.add_argument('jar', nargs='?', help='receiver jar (default: found under the install lib)')
    parser.add_argument('png', nargs='?', default=str(DEFAULT_PNG), help=f'180x180 PNG (default: {DEFAULT_PNG})')
    args = parser.parse_args()

    jar = Path(args.jar) if args.jar else resource_jar()
    if not jar.is_file():
        fail(f'{jar} does not exist')
    png = Path(args.png)
    if not png.is_file():
        fail(f'{png} does not exist')
    icon = read_icon(png)

    with zipfile.ZipFile(jar) as source:
        names = source.namelist()
        comment = source.comment
        if RESOURCE not in names:
            fail(f'{jar} has no {RESOURCE}; nothing to replace')
        signed = [name for name in names
                  if name.startswith('META-INF/') and name.endswith(SIGNATURE_SUFFIXES)]
        current = source.read(RESOURCE)
    if signed:
        fail(f'{jar} is signed ({signed[0]}); rewriting a resource invalidates the signature')
    if current == icon:
        print(f'{jar} already carries this icon; nothing to do')
        return

    owner = jar.stat()
    temporary = jar.with_name(jar.name + '.new')
    try:
        with zipfile.ZipFile(jar) as source, zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
            target.comment = comment
            for item in source.infolist():
                target.writestr(item, icon if item.filename == RESOURCE else source.read(item.filename))
        # Replace the jar only once the copy is proven complete.
        with zipfile.ZipFile(temporary) as check:
            if check.testzip() is not None:
                fail(f'{temporary} failed its integrity check')
            if check.namelist() != names:
                fail(f'{temporary} does not hold the same entries as {jar}')
            if check.read(RESOURCE) != icon:
                fail(f'{temporary} did not take the icon')
        os.chmod(temporary, stat_module.S_IMODE(owner.st_mode))
        try:
            os.chown(temporary, owner.st_uid, owner.st_gid)
        except OSError:
            pass    # not root: the file keeps our uid, which still owns the write
        os.replace(temporary, jar)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(f'replaced {RESOURCE} in {jar} ({len(icon)} bytes); restart dashplay to load it')


if __name__ == '__main__':
    sys.exit(main())
