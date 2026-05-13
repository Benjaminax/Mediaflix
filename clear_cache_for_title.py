#!/usr/bin/env python3
import os
import argparse
import urllib.parse

POSTER_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".media_organizer_cache", "posters")
BACKDROP_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".media_organizer_cache", "backdrops")
SYNOPSIS_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".media_organizer_cache", "synopsis")


def matches_title(title, filename):
    # Normalize by unquoting percent-encoding and replacing underscores
    try:
        un = urllib.parse.unquote(filename)
    except Exception:
        un = filename
    un = un.replace('_', ' ')
    return title.lower() in un.lower()


def find_matches(title, dirs):
    matches = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if matches_title(title, fn):
                matches.append(os.path.join(d, fn))
    return matches


def main():
    p = argparse.ArgumentParser(description='Clear poster/backdrop cache variants for a title')
    p.add_argument('title', help='Title to match (case-insensitive substring match)')
    p.add_argument('--yes', '-y', action='store_true', help='Delete without confirmation')
    p.add_argument('--dry-run', action='store_true', help='Only show matching files, do not delete')
    args = p.parse_args()

    dirs = [POSTER_CACHE_DIR, BACKDROP_CACHE_DIR, SYNOPSIS_CACHE_DIR]
    matches = find_matches(args.title, dirs)

    if not matches:
        print('No cached files found for title:', args.title)
        return

    print('Found {} matching files:'.format(len(matches)))
    for m in matches:
        print(' -', m)

    if args.dry_run:
        print('\nDry run complete. No files deleted.')
        return

    if not args.yes:
        confirm = input('\nDelete these files? [y/N]: ').strip().lower()
        if confirm not in ('y', 'yes'):
            print('Aborting. No files deleted.')
            return

    deleted = 0
    for m in matches:
        try:
            os.remove(m)
            deleted += 1
        except Exception as e:
            print('Failed to delete', m, '-', e)

    print('Deleted {} files.'.format(deleted))


if __name__ == '__main__':
    main()
