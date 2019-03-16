from datetime import datetime
from copy import deepcopy
from uuid import uuid1

from standardnotes_fs.api import StandardNotesAPI

class ItemManager:
    items = {}
    note_uuids = {}
    note_titles = {}
    ext = ''

    def cache_note(self, item):
        # remove note from caches if it's in there
        self.note_uuids.pop(self.note_titles.pop(item['uuid'], None), None)

        note = item['content']
        original_title = note.get('title', 'Untitled')

        # remove title duplicates by adding a number to the end
        count = 0
        while True:
            title = original_title + ('' if not count else str(count + 1))

            # clean up filenames
            title = title.replace('/', '-') + self.ext

            if title in self.note_uuids:
                count += 1
            else:
                break

        self.note_uuids[title] = item['uuid']
        self.note_titles[item['uuid']] = title

    def map_items(self, response_items, metadata_only=False):
        DATA_KEYS = ['content', 'enc_item_key', 'auth_hash']

        # sort so deduplication is consistent
        response_items = sorted(response_items, key=lambda x: x['created_at'])

        for item in response_items:
            uuid = item['uuid']

            if item['deleted']:
                if uuid in self.items:
                    del self.items[uuid]
                continue

            item['dirty'] = False

            if uuid not in self.items:
                self.items[uuid] = {}

            for key, value in item.items():
                if metadata_only and key in DATA_KEYS:
                    continue
                self.items[uuid][key] = value

            if item['content_type'] == 'Note':
                self.cache_note(item)

    def sync_items(self):
        dirty_items = [deepcopy(item) for _, item in self.items.items() if item['dirty']]

        # remove keys
        for item in dirty_items:
            item.pop('dirty', None)
            item.pop('updated_at', None)

        response = self.sn_api.sync(dirty_items)
        self.map_items(response['response_items'])
        self.map_items(response['saved_items'], metadata_only=True)

    def get_updated(self, item):
        try:
            return item['content']['appData']['org.standardnotes.sn']['client_updated_at']
        except KeyError:
            return item.get('updated_at', item['created_at'])

    def get_note(self, title):
        item = self.items[self.note_uuids[title]]
        note = item['content']
        text = note['text']

        # Add a new line so it outputs pretty
        if not text.endswith('\n'):
            text += '\n';

        text = text.encode() # convert to binary data

        return dict(note_name=title, text=text, uuid=item['uuid'],
                created=item['created_at'],
                modified=self.get_updated(item))

    def get_notes(self):
        return self.note_uuids

    def set_dirty(self, item):
        item['dirty'] = True

        ref = item['content']
        ref = ref.setdefault('appData', {})
        ref = ref.setdefault('org.standardnotes.sn', {})
        ref['client_updated_at'] = datetime.utcnow().isoformat() + 'Z'

    def touch_note(self, uuid):
        item = self.items[uuid]
        self.set_dirty(item)

    def write_note(self, uuid, text):
        item = self.items[uuid]
        item['content']['text'] = text.decode() # convert back to string
        self.set_dirty(item)

    def create_note(self, name):
        uuid = str(uuid1())
        content = dict(title=name, text='', references=[])
        creation_time = datetime.utcnow().isoformat() + 'Z'
        self.items[uuid] = dict(content_type='Note', auth_hash=None,
                                uuid=uuid, created_at=creation_time,
                                enc_item_key='', content=content)
        item = self.items[uuid]
        self.set_dirty(item)

    def rename_note(self, uuid, new_note_name):
        item = self.items[uuid]
        item['content']['title'] = new_note_name
        self.set_dirty(item)

    def delete_note(self, uuid):
        item = self.items[uuid]
        item['deleted'] = True
        self.set_dirty(item)

    def get_tags(self):
        tags = {}
        tag_items = [item for uuid, item in self.items.items()
                if item['content_type'] == 'Tag']
        sorted_tag_items = sorted(tag_items, key=lambda x: x['created_at'])

        for item in sorted_tag_items:
            tag = item['content']
            references = tag['references']

            notes = [r['uuid'] for r in references if r['content_type'] == 'Note']

            # remove title duplicates by adding a number to the end
            count = 0
            while True:
                title = tag['title'] + ('' if not count else str(count + 1))

                # clean up filenames
                title = title.replace('/', '-').replace(' ', '_')

                if title in tags:
                    count += 1
                else:
                    break

            tags[title] = dict(tag_name=title, notes=notes, uuid=item['uuid'],
                    created=item['created_at'],
                    modified=item.get('updated_at', item['created_at']))

        return tags

    def __init__(self, sn_api, ext):
        self.sn_api = sn_api
        self.ext = ext
        self.sync_items()
