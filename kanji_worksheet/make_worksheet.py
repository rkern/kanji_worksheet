#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" Make a Kanji writing practice worksheet from the Nihongo Kanji Anki flashcard deck.

By default, the cards you reviewed in the last day will be used.
"""

from __future__ import unicode_literals, print_function

from collections import OrderedDict
import json
from operator import itemgetter
import os
import subprocess
import time

from jinja2 import Environment, PackageLoader, select_autoescape
from lxml import etree
import sqlsoup


FIELD_SEP = u'\x1f'


def get_notes_for_reviewed_cards(soup, last_time_ms=None, only_forgotten=False):
    # Find out how to separate the note data into fields.
    collection = soup.col.one()
    models = json.loads(collection.models)
    for k, v in models.items():
        if v['name'] == u'NihongoShark.com: Kanji':
            model = v
            break
    else:
        raise RuntimeError("Could not find the NihongoShark.com: Kanji metadata.")
    fields = sorted(model['flds'], key=itemgetter('ord'))
    field_names = [f['name'] for f in fields]

    notes_query = soup.notes.filter(soup.notes.c.mid == model['id'])

    if last_time_ms is not None:
        # Query the review log for cards reviewed in the specified time window.
        q = soup.revlog.filter(soup.revlog.c.id >= last_time_ms)
        if only_forgotten:
            # ease==1 means that we pressed the "again" button
            q = q.filter(soup.revlog.c.ease == 1)
        revs = q.all()
        card_ids = sorted(set(rev.cid for rev in revs))
        if not card_ids:
            raise RuntimeError("No cards found in time window!")
        notes_query = notes_query.filter(
            soup.cards.c.id.in_(card_ids),
            soup.notes.c.id == soup.cards.c.nid)

    # Find the notes for the given cards.
    notes = notes_query.all()

    # Turn the notes into field dicts.
    note_fields = [
        OrderedDict(zip(field_names, note.flds.split(FIELD_SEP)))
        for note in notes
    ]

    return note_fields


def inline_data_images(note_fields, media_dir):
    for note in note_fields:
        img = etree.fromstring(note['strokeDiagram'])
        basename = img.get('src')
        fn = os.path.join(media_dir, basename)
        with open(fn) as f:
            base64_data = f.read().encode('base64')
        img.set('src', 'data:image/png;base64,{}'.format(base64_data))
        note['strokeDiagram'] = etree.tostring(img)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-n', '--name', default='Robert',
                        help='The Anki user name.')
    parser.add_argument('-d', '--days', default=1, type=int,
                        help='The number of days to go back.')
    parser.add_argument('-f', '--forgotten', action='store_true',
                        help='Only use cards that we forgot.')
    parser.add_argument('-o', '--output', default='worksheet.html',
                        help='The HTML file to write to.')

    args = parser.parse_args()

    anki_root = os.path.expanduser(
        '~/Library/Application Support/Anki2/{}'.format(args.name))
    media_dir = os.path.join(anki_root, 'collection.media')
    anki_db_fn = os.path.join(anki_root, 'collection.anki2')

    # Don't go back a full 24 hours for the first day to allow for a little
    # variation in the routine.
    hours = (args.days - 1) * 24 + 16
    seconds = hours * 60 * 60
    last_time_ms = int(round((time.time() - seconds) * 1000))

    soup = sqlsoup.SQLSoup('sqlite:///{}'.format(anki_db_fn))
    try:
        note_fields = get_notes_for_reviewed_cards(soup, last_time_ms, args.forgotten)
    except RuntimeError as e:
        raise SystemExit(unicode(e))
    inline_data_images(note_fields, media_dir)

    env = Environment(
        loader=PackageLoader('kanji_worksheet', 'templates'),
        autoescape=select_autoescape(['html', 'xml'])
    )
    template = env.get_template('worksheet.html')
    text = template.render(notes=note_fields)
    with open(args.output, 'wb') as f:
        f.write(text.encode('utf-8'))
    print('Wrote worksheet to {0.output}'.format(args))
    subprocess.call(['open', args.output])

if __name__ == '__main__':
    main()
